"""Voos REAIS pela OpenSky Network (rede de receptores ADS-B para pesquisa).

O que dá para fazer:
  - voos_do_dia(): lista os voos de um aeródromo para outro num dia (precisa de conta).
    A OpenSky monta essa lista num processamento NOTURNO: só existem voos de ontem para trás.
  - no_ar_perto(): aviões no ar agora numa região (funciona até sem conta).
  - trajetoria(): os pontos (hora, lat, lon, altitude) de um voo, no MESMO formato do
    modulos/tracklog.py, para usar a mesma comparação do "colar track log".
    Só existe para os últimos 30 dias, e a própria OpenSky diz que é "experimental".

Credenciais: conta gratuita em opensky-network.org > Account > API Client.
No Streamlit (Settings > Secrets):
    OPENSKY_CLIENT_ID = "..."
    OPENSKY_CLIENT_SECRET = "..."
Cada pedido gasta "créditos" (conta Standard = 4.000 por dia; um voo ou trajetória ≈ 4).
"""
import time
from datetime import datetime, timedelta, timezone

import requests

API = "https://opensky-network.org/api"
URL_TOKEN = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"
TIMEOUT = 20
M_PARA_FT = 3.28084

_token = {"valor": None, "expira": 0}       # guardado na memória do servidor (vale 30 min)


class ErroOpenSky(Exception):
    """Erro com texto pronto para mostrar ao usuário."""


def _cabecalho(client_id, client_secret):
    """Pede um 'token' de acesso (OAuth2) e reaproveita até perto de expirar.
    Sem credenciais: pedido anônimo (sem token)."""
    if not (client_id and client_secret):
        return {}
    if _token["valor"] and time.time() < _token["expira"] - 60:
        return {"Authorization": f"Bearer {_token['valor']}"}
    r = requests.post(URL_TOKEN, data={"grant_type": "client_credentials", "client_id": client_id,
                                       "client_secret": client_secret}, timeout=TIMEOUT)
    if r.status_code != 200:
        raise ErroOpenSky("A OpenSky recusou as credenciais (confira OPENSKY_CLIENT_ID e "
                          "OPENSKY_CLIENT_SECRET nos Secrets do Streamlit).")
    js = r.json()
    _token.update(valor=js["access_token"], expira=time.time() + js.get("expires_in", 1800))
    return {"Authorization": f"Bearer {_token['valor']}"}


def _pedir(caminho, params, cred):
    r = requests.get(f"{API}/{caminho}", params=params, headers=_cabecalho(*cred), timeout=TIMEOUT)
    if r.status_code == 401:                 # token venceu no meio do caminho: pede outro e tenta de novo
        _token["valor"] = None
        r = requests.get(f"{API}/{caminho}", params=params, headers=_cabecalho(*cred), timeout=TIMEOUT)
    if r.status_code == 404:
        return None                          # a OpenSky responde 404 quando não acha nada
    if r.status_code == 429:
        raise ErroOpenSky("Créditos diários da OpenSky esgotados. Tente de novo mais tarde.")
    if r.status_code == 403 or "cannot access" in r.text.lower():
        raise ErroOpenSky("Sem conta, a OpenSky não libera voos passados. Cadastre as credenciais "
                          "(OPENSKY_CLIENT_ID e OPENSKY_CLIENT_SECRET) nos Secrets do Streamlit.")
    r.raise_for_status()
    return r.json()


def _hhmm(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%H:%MZ") if epoch else "--:--"


def voos_do_dia(origem, destino, dia, cred=(None, None)):
    """Voos que decolaram de 'origem' no dia (UTC) com destino estimado 'destino'
    (destino=None: TODOS os voos que saíram de 'origem', para qualquer lugar).
    Devolve lista de dicts {icao24, indicativo, destino, decolagem, pouso, rotulo, meio}.
    O destino da OpenSky é ESTIMADO (aeroporto mais perto de onde o sinal sumiu)."""
    inicio = datetime(dia.year, dia.month, dia.day, tzinfo=timezone.utc)
    dados = _pedir("flights/departure", {"airport": origem, "begin": int(inicio.timestamp()),
                                         "end": int((inicio + timedelta(days=1)).timestamp()) - 1}, cred) or []
    voos = []
    for f in dados:
        if destino and f.get("estArrivalAirport") != destino:
            continue
        ind = (f.get("callsign") or "").strip() or f["icao24"]
        voos.append({"icao24": f["icao24"], "indicativo": ind, "destino": f.get("estArrivalAirport"),
                     "decolagem": f.get("firstSeen"), "pouso": f.get("lastSeen"),
                     # 'meio' = um instante no meio do voo: a trajetória é pedida por instante
                     "meio": (f["firstSeen"] + f["lastSeen"]) // 2 if f.get("lastSeen") else f.get("firstSeen"),
                     "rotulo": f"{ind} · decolou {_hhmm(f.get('firstSeen'))} · "
                               f"último sinal {_hhmm(f.get('lastSeen'))} · {f.get('estArrivalAirport') or '?'}"})
    return sorted(voos, key=lambda v: v["decolagem"] or 0)


def no_ar_perto(limites, cred=(None, None)):
    """Aviões no ar AGORA dentro de limites = (lat_min, lon_min, lat_max, lon_max)."""
    lamin, lomin, lamax, lomax = limites
    js = _pedir("states/all", {"lamin": lamin, "lomin": lomin, "lamax": lamax, "lomax": lomax}, cred) or {}
    voos = []
    for s in js.get("states") or []:
        # s = [icao24, indicativo, país, ..., lon(5), lat(6), alt baro m(7), no chão(8), velocidade m/s(9), rumo(10)...]
        if s[8] or s[7] is None:
            continue
        ind = (s[1] or "").strip() or s[0]
        fl = round(s[7] * M_PARA_FT / 100)
        voos.append({"icao24": s[0], "indicativo": ind, "meio": 0, "fl": fl,
                     "rotulo": f"{ind} · FL{fl:03d} · rumo {round(s[10] or 0):03d}° · "
                               f"{round((s[9] or 0) * 1.944)} kt"})
    return sorted(voos, key=lambda v: v["indicativo"])


def trajetoria(icao24, instante, cred=(None, None)):
    """Pontos do voo no formato do tracklog: [{"min", "lat", "lon", "alt_ft"}].
    instante = qualquer momento do voo (epoch); 0 = voo em andamento agora."""
    js = _pedir("tracks/all", {"icao24": icao24, "time": int(instante)}, cred)
    if not js or not js.get("path"):
        raise ErroOpenSky("A OpenSky não tem a trajetória deste voo (só guarda os últimos 30 dias, "
                          "e às vezes falha). Tente outro voo ou cole o track log do FlightAware.")
    caminho = [p for p in js["path"] if p[3] is not None]     # p = [hora, lat, lon, alt baro m, rumo, no chão]
    t0 = caminho[0][0]
    return [{"min": (p[0] - t0) / 60, "lat": p[1], "lon": p[2], "alt_ft": p[3] * M_PARA_FT} for p in caminho]
