"""Conversa com a API da REDEMET.

Regra de ouro: NUNCA falhar em silêncio. Cada função devolve (dados, erro).
Se deu errado, 'erro' traz um texto curto que o site mostra na tela
(ex.: "SIGMET indisponível às 17:05Z"), para ninguém confundir
"não há SIGMET" com "não consegui consultar".
"""
import re
from datetime import datetime, timedelta, timezone

import requests

URL = "https://api-redemet.decea.mil.br/mensagens"
TIMEOUT = 15  # segundos: se a API não responder nisso, desistimos (a página não trava)


def _agora_z():
    return datetime.now(timezone.utc).strftime("%H:%MZ")


class RecusaAPI(Exception):
    """A REDEMET respondeu, mas recusou o pedido (status false)."""


def _motivo(e):
    """Texto seguro para mostrar na tela. Erros de conexão do 'requests' trazem
    o endereço completo, COM a chave dentro: por isso mostramos só o tipo do erro."""
    if isinstance(e, RecusaAPI):
        return str(e)
    if isinstance(e, requests.HTTPError) and e.response is not None:
        return f"HTTP {e.response.status_code}"
    return type(e).__name__


def _pedir(caminho, api_key, extras=None):
    """Faz o pedido e devolve a lista de mensagens (o 'data' de dentro do 'data')."""
    params = {"api_key": api_key, **(extras or {})}
    r = requests.get(f"{URL}/{caminho}", params=params, timeout=TIMEOUT)
    r.raise_for_status()                      # erro HTTP (401, 500...) vira exceção
    js = r.json()
    # A REDEMET às vezes responde "HTTP 200" mas com status false e um recado
    # (ex.: "Tamanho da página maior que a permitida!!!"). Isso também é erro.
    if js.get("status") is False:
        raise RecusaAPI(str(js.get("message", "recusado pela API"))[:120])
    return (js.get("data") or {}).get("data") or []


def ultima_por_localidade(tipo, icaos, api_key):
    """Busca METAR ou TAF de várias localidades numa chamada só
    (a REDEMET aceita 'SBGR,SBBR,SBPA' separado por vírgula).
    Sem datas no pedido, a API já devolve a mensagem mais recente de cada uma.
    (Não use page_tam acima de 150: a API recusa.)

    tipo: "metar" ou "taf".   Retorna ({"SBGR": {...}, ...}, erro)."""
    try:
        itens = _pedir(f"{tipo}/{','.join(icaos)}", api_key)
    except Exception as e:
        return {}, f"{tipo.upper()} indisponível às {_agora_z()} ({_motivo(e)})"

    ultimas = {}
    for item in itens:
        icao = (item.get("id_localidade") or "").upper()
        # ordem: validade_inicial e, em empate, recebimento (formato 'AAAA-MM-DD HH:MM:SS')
        chave = (item.get("validade_inicial") or "", item.get("recebimento") or "")
        if icao and (icao not in ultimas or chave > ultimas[icao]["_chave"]):
            ultimas[icao] = {"mens": (item.get("mens") or "").strip(), "_chave": chave}
    return ultimas, None


def sigmets(api_key):
    """SIGMETs vigentes. Retorna (lista de textos, erro)."""
    try:
        itens = _pedir("sigmet", api_key)
        return [i.get("mens", "") for i in itens if i.get("mens")], None
    except Exception as e:
        return [], f"SIGMET indisponível às {_agora_z()} ({_motivo(e)})"


# ----------------------------------------------------------------------------
# SIGMET -> polígono
# ----------------------------------------------------------------------------
def coordenadas_sigmet(texto):
    """'S2015 W04530' -> [-20.25, -45.5]. Devolve a lista de pontos na ordem do texto."""
    padrao = r"([NS])(\d{2})(\d{2})\s*([WE])(\d{3})(\d{2})"
    pontos = []
    for ns, lat_g, lat_m, we, lon_g, lon_m in re.findall(padrao, texto):
        lat = int(lat_g) + int(lat_m) / 60
        lon = int(lon_g) + int(lon_m) / 60
        pontos.append([-lat if ns == "S" else lat, -lon if we == "W" else lon])
    return pontos


def fenomeno_sigmet(texto):
    """Classifica pelo fenômeno, procurando a PALAVRA inteira (\\b = borda de palavra).
    Antes o código usava  "TS" in msg,  que também achava 'TS' dentro de 'INTSF'
    (intensificando) e pintava turbulência de vermelho."""
    t = texto.upper()
    if re.search(r"\bTSGR\b|\bTS\b", t):
        return "TS", "#e0202b"
    if re.search(r"\bICE\b", t):
        return "ICE", "#5ec8f2"
    if re.search(r"\bTURB\b", t):
        return "TURB", "#f2d024"
    if re.search(r"\bVA\b|\bVA CLD\b", t):
        return "VA", "#9b9b9b"
    return "OUTRO", "#f28c28"


def niveis_sigmet(texto):
    """Extrai a faixa de níveis, ex.: 'FL250/380', 'SFC/FL100', 'TOP FL400'."""
    m = re.search(r"\b((?:SFC|FL\d{3})/(?:FL)?\d{3}|TOP (?:ABV )?FL\d{3}|ABV FL\d{3}|BLW FL\d{3})\b", texto)
    return m.group(1) if m else ""


# ----------------------------------------------------------------------------
# SIGMET -> decodificação em português (mesma lógica da Aula 9 do professor)
# ----------------------------------------------------------------------------
FIRS = {"SBAZ": "FIR Amazônica", "SBBS": "FIR Brasília", "SBCW": "FIR Curitiba",
        "SBRE": "FIR Recife", "SBAO": "FIR Atlântico"}

NOMES_FENOMENO = {"TS": "Trovoada", "ICE": "Gelo severo", "TURB": "Turbulência severa",
                  "VA": "Cinzas vulcânicas", "OUTRO": "Outro fenômeno"}

# Como a trovoada aparece (vêm antes de TS na mensagem)
TIPOS_TS = {"OBSC": "obscurecida", "EMBD": "embutida", "FRQ": "frequente", "SQL": "em linha (SQL)"}

DIRECOES = {"N": "norte", "NE": "nordeste", "E": "leste", "SE": "sudeste",
            "S": "sul", "SW": "sudoeste", "W": "oeste", "NW": "noroeste"}


def _validade(ddhhmm):
    """'041933' -> 'dia 04 às 19:33Z'."""
    return f"dia {ddhhmm[:2]} às {ddhhmm[2:4]}:{ddhhmm[4:]}Z"


def decodificar_sigmet(texto):
    """Transforma o SIGMET num dicionário com os campos em português.
    As coordenadas ficam de fora de propósito: o polígono já está no mapa."""
    t = " ".join(texto.upper().split())          # junta tudo numa linha, sem espaços duplos
    d = {}

    m = re.search(r"\bSIGMET\s+(\w+)", t)
    d["titulo"] = f"SIGMET {m.group(1)}" if m else "SIGMET"

    m = re.match(r"([A-Z]{4})\b", t)             # 1ª palavra = órgão / FIR
    if m:
        d["fir"] = f"{m.group(1)} – {FIRS.get(m.group(1), 'FIR')}"

    m = re.search(r"\bVALID\s+(\d{6})/(\d{6})", t)
    if m:
        d["validade"] = f"de {_validade(m.group(1))} até {_validade(m.group(2))}"

    fen, cor = fenomeno_sigmet(t)
    nome = NOMES_FENOMENO[fen]
    if fen == "TS":
        tipo = re.search(r"\b(OBSC|EMBD|FRQ|SQL)\b", t)
        if tipo:
            nome += " " + TIPOS_TS[tipo.group(1)]
        if re.search(r"\bTSGR\b", t):
            nome += ", com granizo"
    d["fenomeno"], d["cor"] = nome, cor
    if re.search(r"\bOBS\b", t):
        d["situacao"] = "Observado"
    elif re.search(r"\bFCST\b", t):
        d["situacao"] = "Previsto"

    m = re.search(r"\b(?:SFC|FL(\d{3}))/(?:FL)?(\d{3})\b", t)
    if m:
        base = f"FL{m.group(1)}" if m.group(1) else "a superfície"
        d["niveis"] = f"Entre {base} e FL{m.group(2)}"
    else:
        m = re.search(r"\bTOPS? (ABV )?FL(\d{3})", t)
        if m:
            d["niveis"] = f"Topo {'acima do' if m.group(1) else 'no'} FL{m.group(2)}"
        else:
            m = re.search(r"\b(ABV|BLW) FL(\d{3})", t)
            if m:
                d["niveis"] = f"{'Acima' if m.group(1) == 'ABV' else 'Abaixo'} do FL{m.group(2)}"

    if re.search(r"\bSTNR\b", t):
        mov = "Estacionário"
    else:
        m = re.search(r"\bMOV ([NSEW]{1,2}) (\d+)(KT|KMH)", t)
        mov = (f"Deslocando-se para {DIRECOES.get(m.group(1), m.group(1))} a {int(m.group(2))} "
               f"{'kt' if m.group(3) == 'KT' else 'km/h'}") if m else "Não informado"
    if re.search(r"\bINTSF\b", t):
        mov += " · intensificando"
    elif re.search(r"\bWKN\b", t):
        mov += " · enfraquecendo"
    elif re.search(r"\bNC\b", t):
        mov += " · sem mudança de intensidade"
    d["movimento"] = mov
    return d

# ----------------------------------------------------------------------------
# Aviso de aeródromo (AD WRNG)
# ----------------------------------------------------------------------------
def _instante_ddhhmm(s, agora):
    """'041930' -> datetime. A mensagem só traz dia/hora/minuto; o mês é o mais
    próximo de hoje (resolve a virada do mês, ex.: dia 31 lido no dia 1º)."""
    dd, hh, mm = int(s[:2]), int(s[2:4]), int(s[4:])
    candidatos = []
    for desloc in (-1, 0, 1):                 # mês passado, este mês, próximo mês
        ano, mes = agora.year, agora.month + desloc
        if mes == 0:
            ano, mes = ano - 1, 12
        elif mes == 13:
            ano, mes = ano + 1, 1
        try:
            candidatos.append(datetime(ano, mes, dd, tzinfo=timezone.utc) + timedelta(hours=hh, minutes=mm))
        except ValueError:                    # ex.: dia 31 num mês de 30 dias
            pass
    return min(candidatos, key=lambda c: abs(c - agora))


PADRAO_AVISO = r"((?:[A-Z]{4}/)*[A-Z]{4}) AD WRNG (\w+) VALID (\d{6})/(\d{6})"


def avisos_aerodromo(icaos, api_key):
    """AD WRNG vigentes agora. Retorna ({"SBGR": [texto, ...], ...}, erro).
    Um aviso pode valer para vários aeródromos (ex.: 'SBST/SBTA AD WRNG 20 ...')."""
    try:
        itens = _pedir(f"aviso/{','.join(icaos)}", api_key)
    except Exception as e:
        return {}, f"Aviso de aeródromo indisponível às {_agora_z()} ({_motivo(e)})"

    agora = datetime.now(timezone.utc)
    # { ... } com 'for' dentro cria um CONJUNTO (set): textos repetidos ficam só uma vez
    textos = {" ".join((i.get("mens") or "").upper().split()) for i in itens}

    # Avisos cancelados: '... CNL AD WRNG 2 ...' cancela o aviso nº 2 daquele aeródromo
    cancelados = set()
    for t in textos:
        m = re.match(PADRAO_AVISO, t)
        for numero in re.findall(r"\bCNL AD WRNG (\w+)", t):
            if m:
                cancelados.add((m.group(1), numero))

    vigentes = {}
    for t in textos:
        m = re.match(PADRAO_AVISO, t)
        if not m or re.search(r"\bCNL\b", t):
            continue                          # não é aviso, ou é a própria mensagem de cancelamento
        grupo, numero, ini, fim = m.groups()
        if (grupo, numero) in cancelados:
            continue
        if not (_instante_ddhhmm(ini, agora) <= agora <= _instante_ddhhmm(fim, agora)):
            continue                          # fora da validade
        for icao in grupo.split("/"):
            vigentes.setdefault(icao, []).append(t)
    return vigentes, None


FENOMENOS_AVISO = [   # (código, descrição) — na ordem em que vão aparecer
    (r"\bTSGR\b", "trovoada com granizo"), (r"\bTS\b", "trovoada"), (r"\bGR\b", "granizo"),
    (r"\bSQ\b", "tempestade (SQ)"), (r"\bTC\b", "ciclone tropical"),
    (r"\bFZRA\b", "chuva congelante"), (r"\bFRST\b", "geada"), (r"\bHVY SN\b", "neve forte"),
    (r"\bSN\b", "neve"), (r"\bSS\b", "tempestade de areia"), (r"\bDS\b", "tempestade de poeira"),
    (r"\bVA\b", "cinzas vulcânicas"), (r"\bTOX CHEM\b", "produtos químicos tóxicos"),
    (r"\bTSUNAMI\b", "tsunami"),
]


def decodificar_aviso(texto):
    """'SBST/SBTA AD WRNG 20 VALID 041930/042330 TS SFC WSPD 15KT MAX 40 FCST NC='
    -> ['Trovoada · vento à superfície 15 kt, rajadas até 40 kt',
        'Previsto · sem mudança de intensidade', 'Válido de 04 19:30Z a 04 23:30Z']"""
    t = " ".join(texto.upper().split())
    itens = []
    for padrao, nome in FENOMENOS_AVISO:
        if re.search(padrao, t):
            if nome == "trovoada" and "trovoada com granizo" in itens:
                continue                      # TSGR já disse tudo
            itens.append(nome)

    m = re.search(r"\bSFC (?:WSPD |WIND (\d{3})/)(\d+)(KT|KMH)(?: MAX (\d+))?", t)
    if m:
        dirc, vel, uni, maxi = m.groups()
        u = "kt" if uni == "KT" else "km/h"
        vento = "vento à superfície" + (f" de {dirc}°" if dirc else "") + f" {int(vel)} {u}"
        if maxi:
            vento += f", rajadas até {int(maxi)} {u}"
        itens.append(vento)

    linhas = [(" · ".join(itens) or "fenômeno não identificado").capitalize()]

    estado = "Observado" if re.search(r"\bOBS\b", t) else "Previsto" if re.search(r"\bFCST\b", t) else ""
    tendencia = ("intensificando" if re.search(r"\bINTSF\b", t) else
                 "enfraquecendo" if re.search(r"\bWKN\b", t) else
                 "sem mudança de intensidade" if re.search(r"\bNC\b", t) else "")
    if estado or tendencia:
        linhas.append(" · ".join(x for x in (estado, tendencia) if x))

    m = re.search(PADRAO_AVISO, t)
    if m:
        ini, fim = m.group(3), m.group(4)
        linhas.append(f"Válido de {ini[:2]} {ini[2:4]}:{ini[4:]}Z a {fim[:2]} {fim[2:4]}:{fim[4:]}Z")
    return linhas

# ----------------------------------------------------------------------------
# Descargas atmosféricas (raios) — produto STSC da REDEMET
# ----------------------------------------------------------------------------
URL_STSC = "https://api-redemet.decea.mil.br/produtos/stsc"

# Faixas de idade iguais às da aba TSC da REDEMET: (idade máxima em min, cor, texto)
FAIXAS_RAIOS = [(15, "#ff1a1a", "0 a 15 min"),
                (30, "#ffe600", "15 a 30 min"),
                (45, "#1db31d", "30 a 45 min"),
                (60, "#1f4dff", "45 a 60 min")]


def _instante(hhmm, agora):
    """A API só manda a hora ('19:41'). Junta com a data de hoje (UTC).
    Se a hora ficou "no futuro" (ex.: '23:58' lido às 00:03Z), era de ontem."""
    h, m = re.search(r"(\d{1,2}):(\d{2})", hhmm).groups()
    inst = agora.replace(hour=int(h), minute=int(m), second=0, microsecond=0)
    if inst > agora + timedelta(minutes=5):
        inst -= timedelta(days=1)
    return inst


def _pedir_stsc(api_key, quadros):
    """Pede as últimas 'quadros' fotografias de raios.
    Devolve [(instante, [[lat, lon], ...]), ...]."""
    r = requests.get(URL_STSC, params={"api_key": api_key, "anima": quadros}, timeout=TIMEOUT)
    r.raise_for_status()
    js = r.json()
    if js.get("status") is False:
        raise RecusaAPI(str(js.get("message", "recusado pela API"))[:120])
    dados = js.get("data") or {}
    agora = datetime.now(timezone.utc)
    resultado = []
    # zip junta as duas listas lado a lado: 1º horário com a 1ª lista de pontos, e assim por diante
    for hhmm, lista in zip(dados.get("anima") or [], dados.get("stsc") or []):
        pontos = []
        for p in lista or []:
            try:
                pontos.append([round(float(p["la"]), 2), round(float(p["lo"]), 2)])
            except (KeyError, TypeError, ValueError):
                continue                      # ponto com defeito: ignora só ele
        resultado.append((_instante(hhmm, agora), pontos))
    return resultado


def descargas(api_key):
    """Raios da última hora. Retorna ([(instante, pontos), ...], erro).

    Não sabemos de antemão de quantos em quantos minutos a REDEMET gera cada
    fotografia. Então pedimos 4, medimos o intervalo entre elas e, se for menor
    que 15 min, pedimos de novo a quantidade que cobre 60 min."""
    try:
        quadros = _pedir_stsc(api_key, 4)
        if len(quadros) >= 2:
            instantes = sorted(q[0] for q in quadros)
            passo = (instantes[1] - instantes[0]).total_seconds() / 60    # em minutos
            if 0 < passo < 15:
                quadros = _pedir_stsc(api_key, min(60, int(60 // passo) + 1))
        return quadros, None
    except Exception as e:
        return [], f"Descargas atmosféricas indisponíveis às {_agora_z()} ({_motivo(e)})"


def pontos_por_idade(quadros, agora):
    """Transforma as fotografias em [[lat, lon, faixa], ...], com faixa 0 = vermelho
    (até 15 min) ... 3 = azul (até 60 min). Mais de 60 min fica de fora.
    A idade é calculada AGORA (e não quando os dados foram baixados): assim,
    mesmo com o cache, a cor mostra a idade real do raio."""
    saida = []
    for instante, pontos in quadros:
        idade = (agora - instante).total_seconds() / 60
        if idade > 60:
            continue
        faixa = min(int(max(idade, 0) // 15), 3)
        saida += [[lat, lon, faixa] for lat, lon in pontos]
    return saida
