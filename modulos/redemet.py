"""Conversa com a API da REDEMET.

Regra de ouro: NUNCA falhar em silêncio. Cada função devolve (dados, erro).
Se deu errado, 'erro' traz um texto curto que o site mostra na tela
(ex.: "SIGMET indisponível às 17:05Z"), para ninguém confundir
"não há SIGMET" com "não consegui consultar".
"""
import re
from concurrent.futures import ThreadPoolExecutor
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


def _pedir_paginas(caminho, api_key, extras=None, max_paginas=6):
    """Igual ao _pedir, mas segue as PÁGINAS da resposta. A API divide o resultado em
    páginas ('last_page' diz quantas); ler só a primeira esconde as mensagens do resto."""
    todas, anterior = [], None
    for pagina in range(1, max_paginas + 1):
        params = {"api_key": api_key, "page_tam": 150, "page": pagina, **(extras or {})}
        r = requests.get(f"{URL}/{caminho}", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        js = r.json()
        if js.get("status") is False:
            raise RecusaAPI(str(js.get("message", "recusado pela API"))[:120])
        dados = js.get("data") or {}
        itens = dados.get("data") or []
        primeiro = itens[0].get("mens") if itens else None
        if pagina > 1 and primeiro == anterior:
            break                              # a API ignorou o pedido de outra página: não repete
        anterior = primeiro
        todas += itens
        if pagina >= (dados.get("last_page") or 1):
            break
    return todas


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


def ultima_awc(tipo, icaos):
    """RESERVA para aeródromos do EXTERIOR: busca METAR/TAF no Aviation Weather Center
    (NOAA, EUA), serviço público e sem chave. Usado só para o que a REDEMET não devolver.
    Devolve no MESMO formato do ultima_por_localidade: ({"SCEL": {"mens": ...}}, erro)."""
    if not icaos:
        return {}, None
    url = f"https://aviationweather.gov/api/data/{tipo}"
    try:
        r = requests.get(url, params={"ids": ",".join(icaos), "format": "json"}, timeout=TIMEOUT,
                         headers={"User-Agent": "meteorologia-hiremar (site de instrucao)"})
        r.raise_for_status()
        itens = r.json() if r.text.strip() else []      # sem nenhuma mensagem: resposta vazia
    except Exception as e:
        return {}, f"{tipo.upper()} do exterior indisponível às {_agora_z()} ({_motivo(e)})"
    ultimas = {}
    for item in itens:
        icao = (item.get("icaoId") or "").upper()
        texto = (item.get("rawOb") if tipo == "metar" else item.get("rawTAF")) or ""
        texto = texto.strip()
        if not icao or not texto:
            continue
        # Deixa igual ao padrão da REDEMET: "METAR SCEL ...=" (o AWC manda sem o "METAR" e sem "=")
        if tipo == "metar" and not texto.startswith(("METAR", "SPECI")):
            texto = "METAR " + texto
        if not texto.endswith("="):
            texto += "="
        chave = str(item.get("obsTime") or item.get("issueTime") or "")
        if icao not in ultimas or chave > ultimas[icao]["_chave"]:
            ultimas[icao] = {"mens": texto, "_chave": chave, "fonte": "AWC/NOAA"}
    return ultimas, None


def mensagens_periodo(tipo, icaos, inicio, fim, api_key, max_paginas=40):
    """Consulta de mensagens PASSADAS, igual à tela "Consulta Mensagens" da REDEMET.

    tipo   : "metar" (traz METAR e SPECI) ou "taf"
    icaos  : lista de localidades, ex.: ["SBGR", "SBSP"]
    inicio, fim : datetime em UTC. A API só aceita hora cheia (AAAAMMDDHH), então
             pedimos as horas que cobrem o período e cortamos os minutos aqui no código.
    Retorna (lista de dicts {localidade, tipo, validade, recebimento, mens}, erro).

    Atenção: quando a EMS manda um COR, a REDEMET guarda só a mensagem corrigida."""
    extras = {"data_ini": inicio.strftime("%Y%m%d%H"), "data_fim": fim.strftime("%Y%m%d%H")}
    try:
        itens = _pedir_paginas(f"{tipo}/{','.join(icaos)}", api_key, extras, max_paginas)
    except Exception as e:
        return [], f"{tipo.upper()} indisponível às {_agora_z()} ({_motivo(e)})"

    saida, vistos = [], set()
    for i in itens:
        texto = " ".join((i.get("mens") or "").split())
        validade = i.get("validade_inicial") or ""
        try:
            instante = datetime.strptime(validade[:16], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            instante = None
        # corta o que ficou fora dos minutos pedidos (a API trabalha com hora cheia)
        if instante and not (inicio <= instante <= fim):
            continue
        if not texto or texto in vistos:           # a mesma mensagem pode vir repetida entre páginas
            continue
        vistos.add(texto)
        primeira = texto.split()[0]
        saida.append({"localidade": (i.get("id_localidade") or "").upper(),
                      "tipo": primeira if primeira in ("METAR", "SPECI", "TAF") else tipo.upper(),
                      "validade": instante, "recebimento": i.get("recebimento") or "",
                      "mens": texto})
    saida.sort(key=lambda d: (d["localidade"], d["validade"] or datetime.min.replace(tzinfo=timezone.utc)))
    return saida, None


def sigwx(api_key):
    """Endereço da carta SIGWX mais recente (SFC/FL250) da REDEMET.
    A API devolve só o link da imagem (não aceita pedir cartas antigas).
    Retorna (url, erro)."""
    try:
        r = requests.get("https://api-redemet.decea.mil.br/produtos/sigwx",
                         params={"api_key": api_key}, timeout=TIMEOUT)
        r.raise_for_status()
        # Às vezes vem só o texto do link; às vezes um JSON com o link dentro.
        # Procuramos o primeiro endereço de imagem no texto da resposta, seja qual for o formato.
        m = re.search(r"https?://[^\s\"'\\]+\.(?:png|gif|jpg|jpeg)", r.text.replace("\\/", "/"), re.I)
        if not m:
            raise RecusaAPI("resposta sem link de imagem")
        return m.group(0), None
    except Exception as e:
        return None, f"Carta SIGWX indisponível às {_agora_z()} ({_motivo(e)})"


URL_CARTAS_SIGWX = "https://api-redemet.decea.mil.br/produtos/cartas/sigwx/"
URL_ESTATICO_SIGWX = "https://estatico-redemet.decea.mil.br/sigwx"


def cartas_sigwx(api_key):
    """LISTA de todas as cartas SIGWX que a REDEMET tem agora (é a mesma lista que aparece
    no site da REDEMET em Produtos > Cartas > SIGWX), já com a VALIDADE e a marca de EMENDA.

    Por que isto existe: o nome do arquivo não diz a validade (siginf00.gif do dia 10 vale
    para 11/10 00Z) e a carta emendada tem outro nome (siginf-amd-00.gif). Esta lista diz
    as duas coisas direto, sem precisar "ler" a imagem.

    Retorna (lista, erro). Cada item é um dicionário:
      {"arquivo": "siginf-amd-00.gif", "validade": datetime UTC, "url": endereço da imagem,
       "amd": True/False, "emitida": datetime UTC (quando a REDEMET publicou) ou None}"""
    try:
        r = requests.get(URL_CARTAS_SIGWX, params={"api_key": api_key}, timeout=TIMEOUT)
        r.raise_for_status()
        js = r.json()
        if js.get("status") is False:
            raise RecusaAPI(str(js.get("message", "recusado pela API"))[:120])
        lista = []
        # A resposta é: data -> {nome do produto: {"dados": {"00z": [cartas], "06z": [...]}}}
        for produto in (js.get("data") or {}).values():
            for cartas_do_horario in ((produto or {}).get("dados") or {}).values():
                for c in cartas_do_horario or []:
                    if not c.get("disponivel", True) or not c.get("path_arquivo"):
                        continue
                    # validade = data ("2026-10-11") + hora ("00z")
                    hora = int(re.sub(r"\D", "", c.get("horario_zulu", "")) or 0)
                    dia = datetime.strptime(c["validade_utc"], "%Y-%m-%d")
                    validade = dia.replace(hour=hora, tzinfo=timezone.utc)
                    emitida = None
                    if c.get("criado_em"):
                        emitida = datetime.strptime(c["criado_em"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
                    lista.append({"arquivo": c["path_arquivo"].rsplit("/", 1)[-1],
                                  "validade": validade,
                                  "url": URL_ESTATICO_SIGWX + c["path_arquivo"],
                                  "amd": bool(c.get("is_amd")),
                                  "emitida": emitida})
        if not lista:
            raise RecusaAPI("lista de cartas vazia")
        return lista, None
    except Exception as e:
        return [], f"Lista de cartas SIGWX indisponível às {_agora_z()} ({_motivo(e)})"


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


# A mensagem pode começar com o órgão que EMITIU o aviso, antes do grupo de aeródromos:
#   'SBGR SBRP/SBSP/SBSR/SBUL/SBUR AD WRNG 11 VALID ...'  (SBGR emitiu; vale para SBRP, SBSP...)
# Por isso usamos re.search (procura em qualquer ponto) e \b (começo de palavra),
# e o grupo capturado é só o que vem IMEDIATAMENTE antes de 'AD WRNG'.
PADRAO_AVISO = r"\b((?:[A-Z]{4}/)*[A-Z]{4}) AD WRNG (\w+) VALID (\d{6})/(\d{6})"


def avisos_aerodromo(icaos, api_key):
    """AD WRNG vigentes agora. Retorna ({"SBGR": [texto, ...], ...}, erro, diagnostico).
    Um aviso pode valer para vários aeródromos (ex.: 'SBST/SBTA AD WRNG 20 ...').
    'diagnostico' lista TODA mensagem recebida e o que fizemos com ela (para conferência)."""
    # Sem datas, a API só olha a HORA ATUAL e perde avisos emitidos antes (ex.: o das 19:30Z
    # consultado às 21Z). Pedimos as últimas 12 h; os vencidos o código descarta mais abaixo.
    agora = datetime.now(timezone.utc)
    janela = {"data_ini": (agora - timedelta(hours=12)).strftime("%Y%m%d%H"),
              "data_fim": agora.strftime("%Y%m%d%H")}

    # UM AERÓDROMO POR CONSULTA. Pedindo vários de uma vez, a API devolve só um aviso por
    # órgão emissor e horário (ex.: SBGR emitiu os nº 9, 10, 11 e 20 às 19:30Z e só um voltava).
    def consultar(icao):
        try:
            return _pedir_paginas(f"aviso/{icao}", api_key, janela), None
        except Exception as e:
            return [], _motivo(e)

    # ThreadPoolExecutor faz até 8 consultas AO MESMO TEMPO (em vez de uma esperando a outra),
    # então 30 aeródromos levam o tempo de poucas consultas.
    with ThreadPoolExecutor(max_workers=8) as executor:
        resultados = list(executor.map(consultar, icaos))

    itens = [item for lista, _ in resultados for item in lista]
    falhas = [erro for _, erro in resultados if erro]
    if falhas and len(falhas) == len(icaos):      # todas falharam: aí sim avisamos o erro
        return {}, f"Aviso de aeródromo indisponível às {_agora_z()} ({falhas[0]})", []

    agora = datetime.now(timezone.utc)
    # Junta pelo texto: o mesmo aviso pode vir uma vez para cada aeródromo consultado.
    # setdefault(chave, valor_inicial) cria a entrada se ela ainda não existe.
    por_texto = {}
    for i in itens:
        t = " ".join((i.get("mens") or "").upper().split())
        if t:
            por_texto.setdefault(t, set()).add((i.get("id_localidade") or i.get("id_fir") or "?").upper())

    # Avisos cancelados: '... CNL AD WRNG 2 ...' cancela o aviso nº 2 daquele grupo
    cancelados = set()
    for t in por_texto:
        m = re.search(PADRAO_AVISO, t)
        for numero in re.findall(r"\bCNL AD WRNG (\w+)", t):
            if m:
                cancelados.add((m.group(1), numero))

    vigentes, diagnostico = {}, []
    for t, ids in por_texto.items():
        m = re.search(PADRAO_AVISO, t)
        if not m:
            situacao = "ignorado (não é AD WRNG no formato esperado)"
        elif re.search(r"\bCNL\b", t):
            situacao = "ignorado (mensagem de cancelamento)"
        else:
            grupo, numero, ini, fim = m.groups()
            if (grupo, numero) in cancelados:
                situacao = "cancelado"
            elif not (_instante_ddhhmm(ini, agora) <= agora <= _instante_ddhhmm(fim, agora)):
                situacao = "fora da validade"
            else:
                situacao = "VIGENTE"
                for icao in grupo.split("/"):
                    vigentes.setdefault(icao, []).append(t)
        diagnostico.append((situacao, sorted(ids), t))
    return vigentes, None, diagnostico


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
