"""Robô da BIBLIOTECA DE VOOS REAIS (roda toda madrugada pelo .github/workflows/voos-reais.yml).

Por que existe: a OpenSky recusa conexões do servidor do Streamlit, mas aceita as do GitHub.
Então o robô busca os voos aqui e guarda numa pasta; o site só LÊ essa pasta.

O que faz, para o dia de ONTEM (UTC):
  1. Para cada aeroporto da lista, pede à OpenSky todas as decolagens do dia.
  2. Fica só com os voos cujo destino também está na lista (ex.: SBGR -> SBRJ).
  3. Para cada par (origem-destino), escolhe até MAX_POR_PAR voos espalhados pelo dia.
  4. Baixa a trajetória de cada um e grava em <pasta>/voos/AAAA-MM-DD.json
  5. Apaga os dias com mais de DIAS_GUARDADOS e atualiza <pasta>/index.json

Uso:  python coletar_voos.py <pasta do acervo> [AAAA-MM-DD]
Credenciais: variáveis de ambiente OPENSKY_CLIENT_ID e OPENSKY_CLIENT_SECRET (Secrets do GitHub).
"""
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from modulos import opensky as osk

AEROPORTOS = [
    "SBGR", "SBSP", "SBKP",            # São Paulo
    "SBRJ", "SBGL",                    # Rio de Janeiro
    "SBPA", "SBCT", "SBFL",            # Sul
    "SBBR", "SBGO", "SBCG", "SBCY",    # Centro-Oeste
    "SBCF", "SBSV", "SBRF", "SBFZ",    # Sudeste / Nordeste
    "SBBE", "SBEG",                    # Norte
]
MAX_POR_PAR = 4          # voos guardados por par e por dia (economiza créditos e espaço)
DIAS_GUARDADOS = 30      # a OpenSky só tem trajetórias dos últimos 30 dias mesmo
PAUSA_S = 0.5            # respiro entre pedidos (educação com o servidor deles)


def espalhados(voos, n):
    """Escolhe n voos espalhados ao longo do dia (madrugada, manhã, tarde, noite),
    em vez de pegar só os n primeiros."""
    if len(voos) <= n:
        return voos
    passo = (len(voos) - 1) / (n - 1)
    return [voos[round(i * passo)] for i in range(n)]


def compactar(pontos):
    """Trajetória em formato enxuto: [segundos desde o 1º ponto, lat, lon, altitude em pés].
    4 casas decimais em lat/lon = ~10 m, mais que suficiente para o perfil."""
    return [[round(p["min"] * 60), round(p["lat"], 4), round(p["lon"], 4), round(p["alt_ft"])]
            for p in pontos]


def coletar_dia(dia, cred):
    """{"SBGR-SBRJ": [voo, voo...], ...} para o dia. Cada voo: indicativo, decolagem, pouso, pontos."""
    lista = set(AEROPORTOS)
    pares = {}
    for origem in AEROPORTOS:
        try:
            voos = osk.voos_do_dia(origem, None, dia, cred)
        except osk.ErroOpenSky as e:
            print(f"[{origem}] {e}")
            if "esgotados" in str(e):
                break                                   # sem créditos: para por hoje
            continue
        except Exception as e:
            print(f"[{origem}] falhou ({type(e).__name__})")
            continue
        for v in voos:
            if v["destino"] in lista and v["destino"] != origem:
                pares.setdefault(f"{origem}-{v['destino']}", []).append(v)
        print(f"[{origem}] {len(voos)} decolagens")
        time.sleep(PAUSA_S)

    resultado, baixados = {}, 0
    for par, voos in sorted(pares.items()):
        for v in espalhados(voos, MAX_POR_PAR):
            try:
                pontos = osk.trajetoria(v["icao24"], v["meio"], cred)
            except osk.ErroOpenSky as e:
                if "esgotados" in str(e):
                    print("Créditos esgotados: salvando o que já baixei.")
                    return resultado
                continue                                # esse voo não tem trajetória: pula
            except Exception:
                continue
            if len(pontos) < 10:
                continue                                # trajetória curta demais para comparar
            resultado.setdefault(par, []).append({
                "indicativo": v["indicativo"], "icao24": v["icao24"],
                "decolagem": v["decolagem"], "pouso": v["pouso"], "pontos": compactar(pontos)})
            baixados += 1
            time.sleep(PAUSA_S)
    print(f"{baixados} trajetórias em {len(resultado)} pares")
    return resultado


def main():
    pasta = Path(sys.argv[1])
    dia = (date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2
           else (datetime.now(timezone.utc) - timedelta(days=1)).date())
    cred = (os.environ.get("OPENSKY_CLIENT_ID"), os.environ.get("OPENSKY_CLIENT_SECRET"))
    if not all(cred):
        sys.exit("Faltam OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET nos Secrets do GitHub.")

    (pasta / "voos").mkdir(parents=True, exist_ok=True)
    voos = coletar_dia(dia, cred)
    if voos:
        (pasta / "voos" / f"{dia}.json").write_text(
            json.dumps(voos, separators=(",", ":")), encoding="utf-8")

    # Faxina: apaga os dias velhos
    limite = dia - timedelta(days=DIAS_GUARDADOS)
    for arq in (pasta / "voos").glob("*.json"):
        if date.fromisoformat(arq.stem) < limite:
            arq.unlink()

    # Índice: que dias e pares existem (o site lê só isto para montar a busca)
    indice = {"atualizado": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ"),
              "aeroportos": AEROPORTOS, "dias": {}}
    for arq in sorted((pasta / "voos").glob("*.json")):
        conteudo = json.loads(arq.read_text(encoding="utf-8"))
        indice["dias"][arq.stem] = {par: len(lista) for par, lista in conteudo.items()}
    (pasta / "index.json").write_text(json.dumps(indice, separators=(",", ":")), encoding="utf-8")
    print(f"Índice: {len(indice['dias'])} dia(s)")
    if not voos:
        sys.exit(1)        # nada coletado: o workflow mostra falha (mas o acervo antigo fica)


if __name__ == "__main__":
    main()
