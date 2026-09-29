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


def _pedir(caminho, api_key, extras=None):
    """Faz o pedido e devolve a lista de mensagens (o 'data' de dentro do 'data')."""
    params = {"api_key": api_key, **(extras or {})}
    r = requests.get(f"{URL}/{caminho}", params=params, timeout=TIMEOUT)
    r.raise_for_status()                      # erro HTTP (401, 500...) vira exceção
    return (r.json().get("data") or {}).get("data") or []


def ultima_por_localidade(tipo, icaos, api_key, horas_atras=None):
    """Busca METAR ou TAF de várias localidades numa chamada só
    (a REDEMET aceita 'SBGR,SBBR,SBPA' separado por vírgula)
    e fica com a mensagem mais recente de cada uma.

    tipo: "metar" ou "taf".   Retorna ({"SBGR": {...}, ...}, erro)."""
    extras = {"page_tam": 500}
    if horas_atras:
        agora = datetime.now(timezone.utc)
        extras["data_ini"] = (agora - timedelta(hours=horas_atras)).strftime("%Y%m%d%H")
        extras["data_fim"] = agora.strftime("%Y%m%d%H")
    try:
        itens = _pedir(f"{tipo}/{','.join(icaos)}", api_key, extras)
    except Exception as e:
        return {}, f"{tipo.upper()} indisponível às {_agora_z()} ({type(e).__name__})"

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
        return [], f"SIGMET indisponível às {_agora_z()} ({type(e).__name__})"


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
