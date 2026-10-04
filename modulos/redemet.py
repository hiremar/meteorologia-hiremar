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
