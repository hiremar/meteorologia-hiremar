"""Carta SIGWX (CIMAER, SFC/FL250) como CAMADA do mapa, encaixada nas coordenadas.

A carta é desenhada em projeção Mercator (o quadro diz "TRUE AT 16.06S"), a mesma do
mapa do site (Leaflet). Então basta saber onde ficam as latitudes e longitudes na
imagem e "esticar" a carta sobre o mapa: ela encaixa sem deformar.

Medimos na carta de 08/10/2026 (imagem de ~948 x 762 pixels), pelas linhas pontilhadas
da grade de 5 em 5 graus:
  - longitude: a moldura interna vai de W80° (esquerda) a W10° (direita), em linha reta;
  - latitude : y = topo_da_moldura + 159,94 - 726,2 · merc(lat)   (erro máximo de 2 px)
    onde merc(lat) = ln(tan(45° + lat/2)) é a "altura" Mercator da latitude.
Como cada carta pode vir deslocada 1 pixel, achamos a moldura em cada imagem.

A carta é traço preto em fundo branco: sobre o nosso mapa escuro o preto sumiria.
Por isso o traço vira claro com um contorno escuro fino, e o branco, as fronteiras
azuis e a grade pontilhada da carta ficam transparentes (o mapa já tem os dele).
O quadro de legenda do canto (CIMAER - BRASIL / VALID...) sai; a validade vai para o site.
"""
import base64
import io
import math

import numpy as np
from PIL import Image, ImageFilter

LON_ESQ, LON_DIR = -80.0, -10.0     # longitudes das bordas esquerda e direita da moldura
DESLOC_LAT = 159.94                 # pixels entre o topo da moldura e o equador (merc = 0)
ESCALA_LAT = 726.2                  # pixels por "radiano Mercator"
COR_TRACO = (255, 246, 213)         # creme claro: lê bem sobre mapa escuro e satélite
COR_CONTORNO = (8, 16, 24)


def _merc_inv(m):
    return math.degrees(2 * math.atan(math.exp(m)) - math.pi / 2)


def achar_moldura(a):
    """Moldura interna do mapa (retângulo preto). Devolve (x0, x1, y0, y1).
    São as linhas/colunas quase todas pretas, tirando a borda externa da imagem."""
    preto = a.sum(2) < 150
    h, w = preto.shape
    cols = [x for x in range(w) if preto[:, x].sum() > 0.8 * h]
    lins = [y for y in range(h) if preto[y, :].sum() > 0.8 * w]
    # a borda externa fica a menos de ~6 px da beira; a moldura interna é a seguinte
    x0 = min(x for x in cols if x > 10)
    x1 = max(x for x in cols if x < w - 10)
    y0 = min(y for y in lins if y > 10)
    y1 = max(y for y in lins if y < h - 10)
    return x0, x1, y0, y1


def achar_quadro_legenda(a, x0, x1, y0, y1):
    """Quadro "CIMAER - BRASIL" no canto inferior direito: procura a linha horizontal
    preta longa (topo do quadro) e a vertical (lado esquerdo). Devolve (x, y) do canto."""
    preto = a.sum(2) < 150
    topo = None
    for y in range(y1 - 40, (y0 + y1) // 2, -1):            # de baixo para cima
        if preto[y, x1 - 230:x1 - 5].sum() > 210:
            topo = y
    if topo is None:
        return None
    esq = None
    for x in range(x1 - 5, x0 + (x1 - x0) // 2, -1):         # da direita para a esquerda
        if preto[topo:y1, x].sum() > 0.9 * (y1 - topo):
            esq = x
            break
    return (esq, topo) if esq else None


def preparar_camada(png):
    """Imagem da carta (bytes) -> (data_url da camada transparente, limites [[s, o], [n, l]])."""
    img = Image.open(io.BytesIO(png)).convert("RGB")
    a = np.asarray(img).astype(int)
    x0, x1, y0, y1 = achar_moldura(a)
    quadro = achar_quadro_legenda(a, x0, x1, y0, y1)

    # recorte: só o miolo do mapa (sem a moldura)
    miolo = a[y0 + 1:y1, x0 + 1:x1]
    lum = 0.3 * miolo[..., 0] + 0.59 * miolo[..., 1] + 0.11 * miolo[..., 2]
    traco = lum < 110                                    # o que é escuro é desenho da carta
    if quadro:                                           # some com o quadro de legenda
        qx, qy = quadro
        traco[qy - y0 - 1:, qx - x0 - 1:] = False

    # contorno escuro de 1 px em volta do traço (MaxFilter = "engordar" a máscara)
    m = Image.fromarray((traco * 255).astype(np.uint8), "L")
    contorno = np.asarray(m.filter(ImageFilter.MaxFilter(3))) > 0
    rgba = np.zeros(traco.shape + (4,), dtype=np.uint8)
    rgba[contorno] = COR_CONTORNO + (190,)
    rgba[traco] = COR_TRACO + (255,)

    # coordenadas das bordas do recorte
    largura = x1 - x0
    lon = lambda x: LON_ESQ + (x - x0) / largura * (LON_DIR - LON_ESQ)
    lat = lambda y: _merc_inv((DESLOC_LAT - (y - y0)) / ESCALA_LAT)
    limites = [[lat(y1 - 0.5), lon(x0 + 0.5)], [lat(y0 + 0.5), lon(x1 - 0.5)]]

    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode(), limites
