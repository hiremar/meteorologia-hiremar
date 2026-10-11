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
from modulos import tracklog as tl
from modulos.aerodromos import COORDS

AEROPORTOS = [
    "SBGR", "SBSP", "SBKP",            # São Paulo
    # aviação geral / voos curtos na TMA São Paulo (Cessna 172, instrução...)
    "SBMT", "SBJD", "SBBP", "SBJH", "SDCO", "SBSJ",
    "SBRJ", "SBGL",                    # Rio de Janeiro
    "SBPA", "SBCT", "SBFL",            # Sul
    "SBBR", "SBGO", "SBCG", "SBCY",    # Centro-Oeste
    "SBCF", "SBSV", "SBRF", "SBFZ",    # Sudeste / Nordeste
    "SBBE", "SBEG",                    # Norte
]
MAX_POR_PAR = 4          # voos guardados por par e por dia (economiza créditos e espaço)
DIAS_GUARDADOS = 30      # a OpenSky só tem trajetórias dos últimos 30 dias mesmo
PAUSA_S = 0.5            # respiro entre pedidos (educação com o servidor deles)
MAX_SEM_DESTINO = 300    # trajetórias extras por dia para deduzir o destino (~1.200 créditos)
RAIO_POUSO_NM = 12       # o último sinal precisa estar a até 12 NM de um aeródromo...
TETO_POUSO_FT = 5000     # ...e abaixo de 5.000 ft para contar como pouso ali


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


def destino_pela_trajetoria(pontos, origem):
    """A OpenSky às vezes não sabe o destino (os receptores dela não viram o avião pousar).
    Deduzimos pelo ÚLTIMO ponto: se o avião sumiu baixo e perto de um aeródromo da lista, é ele."""
    fim = pontos[-1]
    if fim["alt_ft"] > TETO_POUSO_FT:
        return None
    perto = [(tl._distancia_nm(fim["lat"], fim["lon"], *COORDS[a]), a) for a in AEROPORTOS
             if a != origem and a in COORDS]
    dist, aeroporto = min(perto)
    return aeroporto if dist <= RAIO_POUSO_NM else None


def _trajetoria(v, cred):
    """Pontos da trajetória, ou None se não houver (ErroOpenSky de créditos sobe)."""
    try:
        pontos = osk.trajetoria(v["icao24"], v["meio"], cred)
    except osk.ErroOpenSky as e:
        if "esgotados" in str(e):
            raise
        return None
    except Exception:
        return None
    time.sleep(PAUSA_S)
    return pontos if len(pontos) >= 10 else None


def _guardar(resultado, par, v, pontos):
    resultado.setdefault(par, []).append({
        "indicativo": v["indicativo"], "icao24": v["icao24"],
        "decolagem": v["decolagem"], "pouso": v["pouso"], "pontos": compactar(pontos)})


def coletar_dia(dia, cred):
    """{"SBGR-SBRJ": [voo, voo...], ...} para o dia. Cada voo: indicativo, decolagem, pouso, pontos."""
    lista = set(AEROPORTOS)
    pares, sem_destino = {}, {}
    for origem in AEROPORTOS:
        try:
            voos = osk.voos_do_dia(origem, None, dia, cred)
        except osk.ErroOpenSky as e:
            print(f"::warning::[{origem}] {e}")
            if "esgotados" in str(e) or "credenciais" in str(e):
                break                                   # sem créditos ou senha errada: para por hoje
            continue
        except Exception as e:
            print(f"[{origem}] falhou ({type(e).__name__})")
            continue
        com, sem = 0, 0
        for v in voos:
            if v["destino"] in lista and v["destino"] != origem:
                pares.setdefault(f"{origem}-{v['destino']}", []).append(v)
                com += 1
            elif not v["destino"]:
                sem_destino.setdefault(origem, []).append(v)
                sem += 1
        print(f"[{origem}] {len(voos)} decolagens · {com} com destino na lista · {sem} sem destino")
        time.sleep(PAUSA_S)

    resultado = {}
    try:
        # 1) Voos com destino conhecido: até MAX_POR_PAR por par, espalhados pelo dia
        for par, voos in sorted(pares.items()):
            for v in espalhados(voos, MAX_POR_PAR):
                pontos = _trajetoria(v, cred)
                if pontos:
                    _guardar(resultado, par, v, pontos)

        # 2) Voos SEM destino: baixa a trajetória e deduz pelo último ponto.
        #    Revezando entre as origens, para nenhum aeroporto gastar o limite sozinho.
        filas = {o: list(reversed(espalhados(vs, len(vs)))) for o, vs in sem_destino.items()}
        gastos, deduzidos = 0, 0
        while gastos < MAX_SEM_DESTINO and any(filas.values()):
            for origem, fila in filas.items():
                if not fila or gastos >= MAX_SEM_DESTINO:
                    continue
                v = fila.pop()
                gastos += 1
                pontos = _trajetoria(v, cred)
                destino = destino_pela_trajetoria(pontos, origem) if pontos else None
                par = f"{origem}-{destino}"
                if destino and len(resultado.get(par, [])) < MAX_POR_PAR:
                    _guardar(resultado, par, v, pontos)
                    deduzidos += 1
        print(f"Destino deduzido pela trajetória: {deduzidos} de {gastos} voos sem destino")
    except osk.ErroOpenSky:
        print("::warning::Créditos da OpenSky esgotados: salvando o que já baixei.")
    print(f"{sum(len(v) for v in resultado.values())} trajetórias em {len(resultado)} pares")
    return resultado


def main():
    pasta = Path(sys.argv[1])
    dia = (date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2
           else (datetime.now(timezone.utc) - timedelta(days=1)).date())
    cred = (os.environ.get("OPENSKY_CLIENT_ID"), os.environ.get("OPENSKY_CLIENT_SECRET"))
    if not all(cred):
        # "::error::" faz a mensagem aparecer em vermelho no resumo do GitHub Actions
        print("::error::Faltam OPENSKY_CLIENT_ID e/ou OPENSKY_CLIENT_SECRET em Settings > Secrets and "
              "variables > Actions.")
        sys.exit(1)

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
    total = sum(len(v) for v in voos.values())
    if not voos:
        print(f"::error::Nenhum voo coletado para {dia} (OpenSky fora do ar, sem créditos ou sem "
              "trajetórias). O acervo antigo foi mantido.")
        sys.exit(1)
    # "::notice::" aparece no resumo do GitHub Actions: dá para ver o resultado sem abrir o registro
    print(f"::notice::{dia}: {total} voos em {len(voos)} pares. Acervo com {len(indice['dias'])} dia(s).")


if __name__ == "__main__":
    main()
