"""Leitura da BIBLIOTECA DE VOOS REAIS que o robô (coletar_voos.py) grava no ramo dados-voos.

O servidor do Streamlit não consegue falar com a OpenSky, mas consegue ler arquivos do GitHub.
Então o site lê daqui:
  index.json            -> que dias e que pares (origem-destino) existem
  voos/AAAA-MM-DD.json  -> {"SBGR-SBRJ": [ {indicativo, icao24, decolagem, pouso, pontos}, ...], ...}
"""
from datetime import datetime, timezone

import requests

BASE = "https://raw.githubusercontent.com/hiremar/meteorologia-hiremar/dados-voos"
TIMEOUT = 20


def indice():
    """Conteúdo do index.json, ou None se a biblioteca ainda não existe."""
    r = requests.get(f"{BASE}/index.json", timeout=TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def dias_com_par(ind, origem, destino):
    """Dias (mais recente primeiro) que têm pelo menos um voo origem -> destino."""
    par = f"{origem}-{destino}"
    return sorted((d for d, pares in (ind or {}).get("dias", {}).items() if par in pares), reverse=True)


def voos_do_par(dia, origem, destino):
    """Voos guardados de origem -> destino num dia, com rótulo pronto para a caixa de seleção."""
    r = requests.get(f"{BASE}/voos/{dia}.json", timeout=TIMEOUT)
    r.raise_for_status()
    voos = r.json().get(f"{origem}-{destino}", [])
    for v in voos:
        dec = datetime.fromtimestamp(v["decolagem"], timezone.utc) if v.get("decolagem") else None
        pou = datetime.fromtimestamp(v["pouso"], timezone.utc) if v.get("pouso") else None
        v["rotulo"] = (f"{v['indicativo']} · decolou {dec:%H:%MZ}" if dec else v["indicativo"]) + \
                      (f" · último sinal {pou:%H:%MZ}" if pou else "")
    return voos


def pontos_do_voo(voo):
    """Pontos no formato do modulos/tracklog.py: [{"min", "lat", "lon", "alt_ft"}]."""
    return [{"min": s / 60, "lat": la, "lon": lo, "alt_ft": alt} for s, la, lo, alt in voo["pontos"]]
