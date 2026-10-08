"""Contas da ROTA: distância, rumo, pontos ao longo do caminho, o que fica perto
dela (aeródromos, SIGMET, raios) e o vento do GFS no nível de cruzeiro.

Tudo em graus decimais (sul e oeste negativos) e milhas náuticas (NM).
A rota é a ortodrômica (o "caminho mais curto" sobre a Terra) entre dois pontos.
"""
import math
from datetime import timedelta

import numpy as np

R_NM = 3440.065          # raio médio da Terra em milhas náuticas


# ---------------------------------------------------------------------------
# Geometria básica
# ---------------------------------------------------------------------------
def distancia_nm(a, b):
    """Distância entre dois pontos [lat, lon] (fórmula de haversine)."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * R_NM * math.asin(math.sqrt(h))


def rumo_verdadeiro(a, b):
    """Rumo verdadeiro inicial de a para b, em graus (0 = norte, 90 = leste)."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def ponto_intermediario(a, b, f):
    """Ponto na fração f (0 = a, 1 = b) da ortodrômica entre a e b."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = distancia_nm(a, b) / R_NM
    if d == 0:
        return list(a)
    k1, k2 = math.sin((1 - f) * d) / math.sin(d), math.sin(f * d) / math.sin(d)
    x = k1 * math.cos(la1) * math.cos(lo1) + k2 * math.cos(la2) * math.cos(lo2)
    y = k1 * math.cos(la1) * math.sin(lo1) + k2 * math.cos(la2) * math.sin(lo2)
    z = k1 * math.sin(la1) + k2 * math.sin(la2)
    return [math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))]


def pontos_da_rota(pernas, passo_nm=10):
    """pernas = [[lat, lon], [lat, lon], ...]  (ex.: origem, destino).
    Devolve [(lat, lon, distância acumulada em NM, rumo da perna), ...] a cada ~passo_nm."""
    saida, acumulado = [], 0.0
    for a, b in zip(pernas, pernas[1:]):
        d = distancia_nm(a, b)
        n = max(1, int(math.ceil(d / passo_nm)))
        for i in range(n + (1 if b is pernas[-1] else 0)):
            f = i / n
            p = ponto_intermediario(a, b, f)
            rumo = rumo_verdadeiro(p, b) if f < 1 else rumo_verdadeiro(a, b)
            saida.append((p[0], p[1], acumulado + f * d, rumo))
        acumulado += d
    return saida


def dist_ao_caminho_nm(p, amostras):
    """Distância de p até a rota (aproximada pela amostra mais próxima, a cada ~10 NM)."""
    return min(distancia_nm(p, (la, lo)) for la, lo, *_ in amostras)


def ponto_no_poligono(p, poligono):
    """Teste do "raio": conta quantas vezes uma linha saindo do ponto cruza as bordas.
    Número ímpar = dentro. poligono = [[lat, lon], ...]."""
    y, x = p
    dentro = False
    for (y1, x1), (y2, x2) in zip(poligono, poligono[1:] + poligono[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            dentro = not dentro
    return dentro


def limites(pontos, margem_graus=1.5, minimo_graus=4.0):
    """Caixa [lat_min, lat_max, lon_min, lon_max] em volta dos pontos, com margem
    e um tamanho mínimo (para rotas curtas como SBSP-SBKP não virarem um zoom absurdo)."""
    lats = [p[0] for p in pontos]
    lons = [p[1] for p in pontos]
    la0, la1 = min(lats) - margem_graus, max(lats) + margem_graus
    lo0, lo1 = min(lons) - margem_graus, max(lons) + margem_graus
    for ini, fim, idx in ((la0, la1, 0), (lo0, lo1, 1)):
        falta = minimo_graus - (fim - ini)
        if falta > 0:
            if idx == 0:
                la0, la1 = la0 - falta / 2, la1 + falta / 2
            else:
                lo0, lo1 = lo0 - falta / 2, lo1 + falta / 2
    return [la0, la1, lo0, lo1]


# ---------------------------------------------------------------------------
# O que está perto da rota
# ---------------------------------------------------------------------------
def aerodromos_no_corredor(amostras, aerodromos, corredor_nm, excluir=(), longe_de=(), raio_terminal_nm=40):
    """Aeródromos a até 'corredor_nm' da rota, na ordem em que aparecem no caminho.
    aerodromos = lista (icao, cidade, uf, lat, lon) de modulos/aerodromos.py
    longe_de   = pontos [lat, lon] (origem, destino, alternativa): quem estiver a menos de
                 'raio_terminal_nm' deles fica de fora (é área terminal, não "em rota";
                 senão um voo saindo de SBGR lista meia dúzia de aeródromos de São Paulo)."""
    achados = []
    for icao, _, _, lat, lon in aerodromos:
        if icao in excluir:
            continue
        if any(distancia_nm((lat, lon), p) < raio_terminal_nm for p in longe_de):
            continue
        dists = [(distancia_nm((lat, lon), (la, lo)), acum) for la, lo, acum, _ in amostras]
        d, acum = min(dists)
        if d <= corredor_nm:
            achados.append((acum, icao, round(d)))
    return [(icao, d) for _, icao, d in sorted(achados)]


def nivel_fl(rotulo):
    """'FL180 · 500 hPa' -> 180"""
    return int(rotulo[2:5])


def faixa_sigmet(texto):
    """Base e topo do SIGMET em FL (None quando não informado). SFC = 0."""
    import re
    t = texto.upper()
    m = re.search(r"\b(SFC|FL(\d{3}))/(?:FL)?(\d{3})\b", t)
    if m:
        return (0 if m.group(1) == "SFC" else int(m.group(2))), int(m.group(3))
    m = re.search(r"\bTOPS? (?:ABV )?FL(\d{3})", t)
    if m:
        return 0, int(m.group(1))
    m = re.search(r"\bABV FL(\d{3})", t)
    if m:
        return int(m.group(1)), 999
    m = re.search(r"\bBLW FL(\d{3})", t)
    if m:
        return 0, int(m.group(1))
    return None, None


def sigmets_na_rota(textos, amostras, corredor_nm, coordenadas, fl=None):
    """SIGMETs cujo polígono cruza a rota ou fica a até 'corredor_nm' dela.
    'coordenadas' é a função que tira o polígono do texto (redemet.coordenadas_sigmet).
    Devolve [(texto, no_nivel), ...]; no_nivel = True/False/None (None = sem níveis no texto)."""
    saida = []
    for txt in textos:
        pol = coordenadas(txt)
        if len(pol) < 3:
            continue
        cruza = any(ponto_no_poligono((la, lo), pol) for la, lo, *_ in amostras)
        perto = cruza or any(dist_ao_caminho_nm(v, amostras) <= corredor_nm for v in pol)
        if not perto:
            continue
        base, topo = faixa_sigmet(txt)
        no_nivel = None if (fl is None or base is None) else (base <= fl <= topo)
        saida.append((txt, no_nivel))
    return saida


def raios_no_corredor(pontos, amostras, corredor_nm):
    """pontos = [[lat, lon, faixa], ...]. Devolve (quantidade no corredor,
    distância do raio mais próximo em NM ou None, faixa de idade mais recente)."""
    if not pontos:
        return 0, None, None
    # filtro rápido pela caixa da rota antes da conta exata (pode haver milhares de raios)
    caixa = limites([(la, lo) for la, lo, *_ in amostras], margem_graus=corredor_nm / 60 + 0.2, minimo_graus=0)
    n, mais_perto, faixa_min = 0, None, None
    for la, lo, faixa in pontos:
        if not (caixa[0] <= la <= caixa[1] and caixa[2] <= lo <= caixa[3]):
            continue
        d = dist_ao_caminho_nm((la, lo), amostras)
        mais_perto = d if mais_perto is None else min(mais_perto, d)
        if d <= corredor_nm:
            n += 1
            faixa_min = faixa if faixa_min is None else min(faixa_min, faixa)
    return n, (round(mais_perto) if mais_perto is not None else None), faixa_min


# ---------------------------------------------------------------------------
# Vento e temperatura do GFS ao longo da rota
# ---------------------------------------------------------------------------
def _interpolar(campo, lats, lons, lat, lon):
    """Interpolação bilinear: média ponderada dos 4 pontos de grade em volta.
    lats crescente (sul -> norte), lons crescente (oeste -> leste)."""
    i = int(np.clip(np.searchsorted(lats, lat) - 1, 0, len(lats) - 2))
    j = int(np.clip(np.searchsorted(lons, lon) - 1, 0, len(lons) - 2))
    fy = (lat - lats[i]) / (lats[i + 1] - lats[i])
    fx = (lon - lons[j]) / (lons[j + 1] - lons[j])
    fy, fx = min(max(fy, 0), 1), min(max(fx, 0), 1)
    return float((1 - fy) * (1 - fx) * campo[i, j] + (1 - fy) * fx * campo[i, j + 1]
                 + fy * (1 - fx) * campo[i + 1, j] + fy * fx * campo[i + 1, j + 1])


def vento_de(u, v):
    """Componentes (u para leste, v para norte), em kt -> (direção DE ONDE vem, velocidade).
    Convenção meteorológica: vento 270/20 sopra DO oeste."""
    vel = math.hypot(u, v)
    direcao = (270 - math.degrees(math.atan2(v, u))) % 360
    return (360 if round(direcao) == 0 else round(direcao)), round(vel)


def isa_c(fl):
    """Temperatura da atmosfera padrão no FL: 15 °C ao nível do mar, -1,98 °C a cada 1000 ft,
    constante em -56,5 °C acima de 36.089 ft (tropopausa ISA)."""
    return max(15 - 1.98 * fl / 10, -56.5)


# ---------------------------------------------------------------------------
# Horários do voo e validades (Doc 8896 da OACI, item 5.3.3.4)
# ---------------------------------------------------------------------------
# As cartas de vento/temperatura WAFS valem de 3 em 3 h e podem ser usadas de 1,5 h antes
# até 1,5 h depois da validade. A SIGWX vale de 6 em 6 h, usada de 3 h antes a 3 h depois.
# Na prática: para cada instante do voo, usa-se a validade MAIS PRÓXIMA na grade de 3 h
# (vento) ou de 6 h (SIGWX). Voo longo -> mais de uma validade.
def validade_mais_proxima(instante, passo_h):
    """Arredonda para a validade mais próxima da grade (00Z, 03Z, 06Z... para passo 3)."""
    base = instante.replace(hour=0, minute=0, second=0, microsecond=0)
    horas = (instante - base).total_seconds() / 3600
    return base + timedelta(hours=round(horas / passo_h) * passo_h)


def validades_do_voo(etd, eta, passo_h):
    """Todas as validades necessárias para cobrir o voo de etd a eta (olhando a cada 15 min).
    Ex. do Doc 8896: voo 12-19Z -> vento 12, 15 e 18Z ; SIGWX 12 e 18Z."""
    achadas, t = [], etd
    while t <= eta:
        v = validade_mais_proxima(t, passo_h)
        if v not in achadas:
            achadas.append(v)
        t += timedelta(minutes=15)
    v = validade_mais_proxima(eta, passo_h)
    if v not in achadas:
        achadas.append(v)
    return achadas


def hora_no_ponto(etd, eet_min, dist_nm, total_nm):
    """Hora estimada sobre um ponto, supondo velocidade constante (regra de três)."""
    frac = dist_nm / total_nm if total_nm else 0
    return etd + timedelta(minutes=eet_min * frac)


# ---------------------------------------------------------------------------
# Qualquer FL: interpolação entre os níveis de pressão do modelo
# ---------------------------------------------------------------------------
def pressao_isa_hpa(fl):
    """Pressão da atmosfera padrão no FL (FL = altitude-pressão em centenas de pés)."""
    h = fl * 100 * 0.3048                                  # pés -> metros
    if h <= 11000:
        return 1013.25 * (1 - 2.25577e-5 * h) ** 5.25588
    return 226.32 * math.exp(-(h - 11000) / 6341.6)        # acima da tropopausa ISA


def niveis_iso(dados_gfs):
    """[(hPa, rótulo), ...] dos níveis de pressão presentes nos dados, do mais baixo ao mais alto."""
    from .modelo_gfs import NIVEIS
    return sorted(((hpa, r) for r, (tipo, hpa) in NIVEIS.items()
                   if tipo == "iso" and r in dados_gfs["niveis"]), reverse=True)


def no_ponto(dados_gfs, fl, lat, lon):
    """(u kt, v kt, T °C) no FL e no ponto. O FL vira pressão (ISA) e interpolamos entre os dois
    níveis do modelo em volta, em ln(p) — a altura varia quase em linha reta com ln(p)."""
    p = pressao_isa_hpa(fl)
    niv = niveis_iso(dados_gfs)
    lats, lons = dados_gfs["lat"], dados_gfs["lon"]
    # acha os dois níveis vizinhos (fora da faixa do modelo, usa o mais próximo)
    if p >= niv[0][0]:
        pares, f = (niv[0], niv[0]), 0.0
    elif p <= niv[-1][0]:
        pares, f = (niv[-1], niv[-1]), 0.0
    else:
        k = next(i for i in range(len(niv) - 1) if niv[i][0] >= p >= niv[i + 1][0])
        (p1, r1), (p2, r2) = niv[k], niv[k + 1]
        pares, f = (niv[k], niv[k + 1]), (math.log(p1) - math.log(p)) / (math.log(p1) - math.log(p2))
    vals = []
    for _, r in pares:
        d = dados_gfs["niveis"][r]
        vals.append([_interpolar(d[c], lats, lons, lat, lon) for c in ("u", "v", "t")])
    u, v, t = [(1 - f) * a + f * b for a, b in zip(*vals)]
    return u * 1.943844, v * 1.943844, t - 273.15


def vento_na_rota(dados_por_validade, fl, pernas, etd, eet_min, passo_nm=None):
    """Tabela do vento no FL ao longo da rota, cada ponto com a validade do GFS da hora
    em que o avião passa por ali (regra de 1,5 h do Doc 8896).

    dados_por_validade = {datetime da validade: dados do GFS}
    Componente na rota = projeção do vento sobre o rumo:  u·sen(rumo) + v·cos(rumo).
    Positivo = vento de cauda (ajuda); negativo = vento de proa (atrapalha).
    Devolve (linhas, resumo)."""
    total = sum(distancia_nm(a, b) for a, b in zip(pernas, pernas[1:]))
    passo = passo_nm or max(25, min(100, round(total / 8 / 25) * 25))   # ~8 a 12 linhas
    linhas = []
    for n, (lat, lon, acum, rumo) in enumerate(pontos_da_rota(pernas, passo), start=1):
        hora = hora_no_ponto(etd, eet_min, acum, total)
        validade = validade_mais_proxima(hora, 3)
        dados = dados_por_validade.get(validade)
        if dados is None:                     # validade que não baixou: usa a mais próxima que houver
            validade = min(dados_por_validade, key=lambda v: abs(v - hora))
            dados = dados_por_validade[validade]
        u, v, t = no_ponto(dados, fl, lat, lon)
        rad = math.radians(rumo)
        comp = u * math.sin(rad) + v * math.cos(rad)
        direcao, vel = vento_de(u, v)
        linhas.append({"n": n, "lat": lat, "lon": lon, "dist_nm": round(acum), "rumo": round(rumo),
                       "hora": hora, "validade": validade,
                       "vento": f"{direcao:03d}/{vel:02d} kt", "dir": direcao, "vel": vel,
                       "temp_c": round(t), "isa_desvio": round(t - isa_c(fl)), "componente": round(comp)})
    comps = [l["componente"] for l in linhas]
    temps = [l["temp_c"] for l in linhas]
    resumo = {"componente_media": round(sum(comps) / len(comps)) if comps else 0,
              "vento_max": max((l["vel"] for l in linhas), default=0),
              "temp_min": min(temps) if temps else None, "temp_max": max(temps) if temps else None,
              "isa_desvio_medio": round(sum(l["isa_desvio"] for l in linhas) / len(linhas)) if linhas else None,
              "distancia_nm": round(total), "fl": fl,
              "validades": sorted({l["validade"] for l in linhas})}
    return linhas, resumo


def niveis_vizinhos(fl, minimo=30, maximo=450):
    """Nível de cruzeiro e os vizinhos no MESMO sentido de voo (±2.000 ft): FL340 -> 320, 340, 360."""
    return [n for n in (fl - 20, fl, fl + 20) if minimo <= n <= maximo]


def texto_componente(c):
    """+12 -> 'cauda 12 kt' ; -20 -> 'proa 20 kt'"""
    if abs(c) < 1:
        return "nulo"
    return f"{'cauda' if c > 0 else 'proa'} {abs(c)} kt"
