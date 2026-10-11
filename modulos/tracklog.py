"""Track log de um voo REAL (FlightAware) para comparar com o perfil simulado.

Aceita três formatos:
  1. Texto copiado da tabela "Track log" do FlightAware (Ctrl+A / Ctrl+C na página e colar).
     Em português vem assim (colunas separadas por TAB):
        Sáb 11:33:35  -23.4381  -46.4976  ← 254°  153  283  1.029  771  FlightAware ADS-B (CGH / SBSP)
        hora          latitude  longitude rota    nós  km/h metros taxa centro
     Em inglês a altitude vem em "feet" (pés) com vírgula de milhar: 2,650.
  2. CSV com cabeçalho (Latitude, Longitude e metros/feet/altitude).
  3. KML do botão "Google Earth" do FlightAware (coordenadas lon,lat,altitude em METROS).

Devolve uma lista de pontos {"min": minutos desde o 1º ponto, "lat", "lon", "alt_ft"}.
"""
import csv
import io
import math
import re

M_PARA_FT = 3.28084


def _distancia_nm(lat1, lon1, lat2, lon2):
    """Distância de círculo máximo (fórmula de haversine). Raio da Terra = 3.440 NM."""
    la1, lo1, la2, lo2 = map(math.radians, (lat1, lon1, lat2, lon2))
    a = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(a))


def _inteiro(txt):
    """'1.029' (pt-BR) ou '2,650' (inglês) -> 1029 / 2650. Altitude e velocidade não têm decimais."""
    txt = re.sub(r"[^\d-]", "", txt)
    return int(txt) if txt not in ("", "-") else None


def _minutos(txt):
    """'11:33:35' ou '11:33:35 AM' -> minutos do dia (com segundos em fração)."""
    m = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?\s*([AP]M)?", txt, re.I)
    if not m:
        return None
    h, mi, s, ampm = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), (m.group(4) or "").upper()
    if ampm == "PM" and h < 12:
        h += 12
    if ampm == "AM" and h == 12:
        h = 0
    return h * 60 + mi + s / 60


# ---------------------------------------------------------------------------
# Leitores
# ---------------------------------------------------------------------------
def _ler_kml(conteudo):
    """KML: pega todas as coordenadas 'lon,lat,alt' (alt em metros) em ordem.
    O KML do FlightAware não traz a hora de cada ponto de forma simples; o tempo fica sem medir."""
    texto = conteudo.decode("utf-8", "ignore") if isinstance(conteudo, bytes) else conteudo
    pontos = []
    # <gx:coord>lon lat alt</gx:coord>  ou  <coordinates>lon,lat,alt lon,lat,alt ...</coordinates>
    for lon, lat, alt in re.findall(r"(-?\d+\.\d+)[ ,](-?\d+\.\d+)[ ,](-?\d+(?:\.\d+)?)", texto):
        pontos.append({"min": None, "lat": float(lat), "lon": float(lon), "alt_ft": float(alt) * M_PARA_FT})
    return pontos


def _colunas(cabecalho):
    """Descobre em que coluna está cada coisa a partir dos nomes do cabeçalho."""
    nomes = [c.strip().lower() for c in cabecalho]
    def achar(*chaves):
        return next((i for i, n in enumerate(nomes) if any(k in n for k in chaves)), None)
    col = {"hora": achar("hor", "time"), "lat": achar("lat"), "lon": achar("lon"),
           "metros": achar("metro", "meter"), "pes": achar("feet", "pés", "pes", "ft", "altitude")}
    return col if col["lat"] is not None and col["lon"] is not None else None


def _ler_tabela(texto):
    """Texto colado ou CSV. Separador: TAB, ponto e vírgula ou vírgula (o que aparecer)."""
    linhas = [l for l in texto.splitlines() if l.strip()]
    if not linhas:
        return []
    amostra = "\n".join(linhas[:5])
    sep = "\t" if "\t" in amostra else ";" if ";" in amostra else ","
    tabela = list(csv.reader(io.StringIO("\n".join(linhas)), delimiter=sep))

    # Cabeçalho: a primeira linha que fala em latitude
    col, inicio = None, 0
    for i, cel in enumerate(tabela[:10]):
        if any("lat" in c.lower() for c in cel):
            col, inicio = _colunas(cel), i + 1
            break
    if col is None:
        # Sem cabeçalho: assume a ordem do FlightAware em português (hora, lat, lon, rota, nós, km/h, metros)
        col = {"hora": 0, "lat": 1, "lon": 2, "metros": 6, "pes": None}

    pontos = []
    for cel in tabela[inicio:]:
        try:
            lat = float(cel[col["lat"]].replace(",", "."))
            lon = float(cel[col["lon"]].replace(",", "."))
        except (IndexError, ValueError):
            continue                         # linha de "Partida", "Chegada", "Tempo de taxiamento"...
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        if col["metros"] is not None and col["metros"] < len(cel):
            alt = _inteiro(cel[col["metros"]])
            alt_ft = alt * M_PARA_FT if alt is not None else None
        elif col["pes"] is not None and col["pes"] < len(cel):
            alt_ft = _inteiro(cel[col["pes"]])
        else:
            alt_ft = None
        if alt_ft is None:
            continue
        hora = _minutos(cel[col["hora"]]) if col["hora"] is not None and col["hora"] < len(cel) else None
        pontos.append({"min": hora, "lat": lat, "lon": lon, "alt_ft": alt_ft})
    return pontos


def ler(texto=None, arquivo=None, nome_arquivo=""):
    """Ponto de entrada: texto colado OU arquivo enviado (CSV/TXT/KML). Devolve (pontos, erro)."""
    try:
        if arquivo is not None:
            if nome_arquivo.lower().endswith((".kml", ".kmz")):
                if nome_arquivo.lower().endswith(".kmz"):
                    import zipfile
                    with zipfile.ZipFile(io.BytesIO(arquivo)) as z:
                        arquivo = z.read(next(n for n in z.namelist() if n.endswith(".kml")))
                pontos = _ler_kml(arquivo)
            else:
                pontos = _ler_tabela(arquivo.decode("utf-8", "ignore"))
        else:
            pontos = _ler_tabela(texto or "")
    except Exception as e:
        return [], f"Não consegui ler o track log ({type(e).__name__})."
    if len(pontos) < 5:
        return [], ("Não encontrei pontos suficientes. Copie a tabela inteira do track log do FlightAware "
                    "(com latitude, longitude e altitude) ou envie o CSV/KML.")
    # Horários: se o voo passou da meia-noite, os minutos "voltam"; somamos 24 h.
    base = pontos[0]["min"]
    if base is not None:
        dia = 0
        anterior = base
        for p in pontos:
            if p["min"] is None:
                continue
            if p["min"] + dia < anterior - 600:     # caiu mais de 10 h: virou o dia
                dia += 24 * 60
            p["min"] = p["min"] + dia - base
            anterior = p["min"] + base
    return pontos, None


# ---------------------------------------------------------------------------
# Perfil do voo real
# ---------------------------------------------------------------------------
def perfil_real(pontos, margem_ft=300):
    """Distância percorrida (NM) × altitude, e o TOC/TOD REAIS.
    Nível de cruzeiro = a MAIOR altitude que aparece pelo menos 2 vezes (arredondada a 500 ft).
    Assim um pico isolado não conta, e na OpenSky (que alterna FL350/FL360 por arredondamento)
    o nível fica o certo, FL360.
    TOC real = primeiro ponto a menos de 'margem_ft' desse nível; TOD real = último ponto assim.
    FlightAware: 300 ft. OpenSky (altitude em degraus de 1.000 ft): use 1.000 ft."""
    from collections import Counter
    dist = [0.0]
    for a, b in zip(pontos, pontos[1:]):
        dist.append(dist[-1] + _distancia_nm(a["lat"], a["lon"], b["lat"], b["lon"]))
    alts = [p["alt_ft"] for p in pontos]
    contagem = Counter(round(h / 500) * 500 for h in alts)
    repetidas = [h for h, n in contagem.items() if n >= 2]
    topo = max(repetidas) if repetidas else max(alts)
    no_topo = [i for i, h in enumerate(alts) if h >= topo - margem_ft]
    i_toc, i_tod = no_topo[0], no_topo[-1]
    tem_hora = all(p["min"] is not None for p in pontos)
    total = dist[-1]

    def razao_media(i, j):
        if not tem_hora or pontos[j]["min"] == pontos[i]["min"]:
            return None
        return abs(alts[j] - alts[i]) / (pontos[j]["min"] - pontos[i]["min"])

    return {"perfil": list(zip(dist, alts)), "total_nm": total,
            "nivel_fl": round(topo / 1000) * 10,
            "toc_nm": dist[i_toc], "tod_nm": total - dist[i_tod],          # TOD contado a partir do destino
            "toc_min": pontos[i_toc]["min"] if tem_hora else None,
            "tod_min": (pontos[-1]["min"] - pontos[i_tod]["min"]) if tem_hora else None,
            "total_min": pontos[-1]["min"] if tem_hora else None,
            "roc_medio": razao_media(0, i_toc), "rod_medio": razao_media(i_tod, len(pontos) - 1),
            # quantos NM por 1.000 ft a descida real usou (compare com a regra 3:1)
            "nm_por_1000ft": (total - dist[i_tod]) / max((alts[i_tod] - alts[-1]) / 1000, 0.1)}
