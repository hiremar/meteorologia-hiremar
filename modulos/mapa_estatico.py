"""Mapa em IMAGEM (PNG) para o PDF do briefing — o mesmo visual do mapa do site,
mas "fotografado": fundo escuro da Esri, satélite IR, SIGMET, raios, aeródromos
com a categoria de voo e a rota.

Como funciona: o mapa do site (Leaflet) usa a projeção Web Mercator, dividida em
"azulejos" (tiles) de 256 x 256 pixels. Aqui baixamos os mesmos azulejos, colamos
lado a lado com a PIL (biblioteca de imagens) e desenhamos o resto por cima.
Se os azulejos não vierem (internet fora), o fundo fica liso e o resto aparece igual.
"""
import base64
import io
import math
from concurrent.futures import ThreadPoolExecutor

import requests
from PIL import Image, ImageDraw, ImageFont

from . import metar as mt
from . import redemet as rd
from .aerodromos import AERODROMOS

ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/{}/MapServer/tile/{}/{}/{}"
FUNDO = "Canvas/World_Dark_Gray_Base"
ROTULOS = "Reference/World_Boundaries_and_Places"
COR_FUNDO = (32, 36, 40)


# ---------------------------------------------------------------------------
# Projeção: lat/lon <-> pixel do "mundo inteiro" no zoom z
# ---------------------------------------------------------------------------
def _merc_y(lat):
    """'Altura' Mercator de uma latitude (0 no equador, cresce para o norte)."""
    return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def _px(lat, lon, z):
    """Pixel (x, y) no mapa-múndi de 256·2^z pixels de lado."""
    tam = 256 * 2 ** z
    return (lon + 180) / 360 * tam, (1 - _merc_y(lat) / math.pi) / 2 * tam


def _fonte(tamanho, negrito=False):
    """Fonte com acentos. No Streamlit Cloud (Linux) costuma existir a DejaVu;
    se não houver, a PIL usa a fonte própria dela (Pillow 10.1 ou mais nova)."""
    nomes = (["DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if negrito
             else ["DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"])
    for n in nomes:
        try:
            return ImageFont.truetype(n, tamanho)
        except OSError:
            pass
    try:
        return ImageFont.load_default(size=tamanho)
    except TypeError:                       # Pillow antiga
        return ImageFont.load_default()


class MapaEstatico:
    """Uma "folha" de mapa cobrindo a caixa [lat_min, lat_max, lon_min, lon_max]."""

    def __init__(self, caixa, largura=1400, altura_max=1100):
        la0, la1, lo0, lo1 = caixa
        # Escolhe o maior zoom em que a caixa ainda cabe na largura/altura pedidas
        for z in range(10, 1, -1):
            x0, y1 = _px(la0, lo0, z)
            x1, y0 = _px(la1, lo1, z)
            if x1 - x0 <= largura and y1 - y0 <= altura_max:
                break
        self.z = z
        # centraliza a caixa numa imagem do tamanho final
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.w, self.h = largura, int(min(altura_max, max(y1 - y0, largura * 0.62)))
        self.ox, self.oy = cx - self.w / 2, cy - self.h / 2        # canto superior esquerdo no "mundo"
        self.img = Image.new("RGBA", (self.w, self.h), COR_FUNDO + (255,))
        self.avisos = []

    def xy(self, lat, lon):
        """lat/lon -> pixel nesta imagem."""
        x, y = _px(lat, lon, self.z)
        return x - self.ox, y - self.oy

    def latlon(self, x, y):
        """Pixel nesta imagem -> lat/lon (o caminho inverso, usado pelo mapa de vento)."""
        tam = 256 * 2 ** self.z
        lon = (x + self.ox) / tam * 360 - 180
        lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + self.oy) / tam))))
        return lat, lon

    # ---------------------------------------------------------------------
    def _azulejos(self, servico):
        """Baixa os azulejos que cobrem a imagem e devolve uma camada RGBA."""
        camada = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        tx0, ty0 = int(self.ox // 256), int(self.oy // 256)
        tx1, ty1 = int((self.ox + self.w) // 256), int((self.oy + self.h) // 256)
        pedidos = [(tx, ty) for tx in range(tx0, tx1 + 1) for ty in range(ty0, ty1 + 1)]

        def baixar(t):
            tx, ty = t
            r = requests.get(ESRI.format(servico, self.z, ty, tx % (2 ** self.z)), timeout=10,
                             headers={"User-Agent": "meteorologia-hiremar (instrucao)"})
            r.raise_for_status()
            return t, Image.open(io.BytesIO(r.content)).convert("RGBA")

        falhas = 0
        with ThreadPoolExecutor(max_workers=8) as ex:          # 8 downloads ao mesmo tempo
            for fut in [ex.submit(baixar, t) for t in pedidos]:
                try:
                    (tx, ty), azulejo = fut.result()
                    camada.alpha_composite(azulejo, (int(tx * 256 - self.ox), int(ty * 256 - self.oy)))
                except Exception:
                    falhas += 1
        if falhas == len(pedidos):
            self.avisos.append("mapa de fundo indisponível")
        return camada

    def fundo(self):
        self.img.alpha_composite(self._azulejos(FUNDO))

    def rotulos(self):
        """Fronteiras e nomes de cidades (por cima do satélite, como no site)."""
        self.img.alpha_composite(self._azulejos(ROTULOS))

    # ---------------------------------------------------------------------
    def satelite(self, data_url, limites, opacidade=0.85):
        """Recorta a imagem do GOES que o site já fez (data URL) e encaixa no mapa.
        As linhas daquela imagem já são espaçadas em Mercator (ver satelite.py),
        então basta uma regra de três em x (longitude) e em y (Mercator)."""
        bruta = Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))).convert("RGBA")
        (la_min, lo_min), (la_max, lo_max) = limites
        W, H = bruta.size
        # canto superior esquerdo e inferior direito DESTA folha, em lat/lon
        n_lat, o_lon = self.latlon(0, 0)
        s_lat, l_lon = self.latlon(self.w, self.h)
        fx = lambda lon: (lon - lo_min) / (lo_max - lo_min) * W
        fy = lambda lat: (_merc_y(la_max) - _merc_y(lat)) / (_merc_y(la_max) - _merc_y(la_min)) * H
        recorte = bruta.transform((self.w, self.h), Image.EXTENT,
                                  (fx(o_lon), fy(n_lat), fx(l_lon), fy(s_lat)), Image.BILINEAR)
        if opacidade < 1:
            a = recorte.getchannel("A").point(lambda v: int(v * opacidade))
            recorte.putalpha(a)
        self.img.alpha_composite(recorte)

    def sigmets(self, textos):
        camada = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        d = ImageDraw.Draw(camada)
        f = _fonte(15, True)
        for txt in textos:
            pol = rd.coordenadas_sigmet(txt)
            if len(pol) < 3:
                continue
            fen, cor = rd.fenomeno_sigmet(txt)
            rgb = tuple(int(cor[i:i + 2], 16) for i in (1, 3, 5))
            pts = [self.xy(la, lo) for la, lo in pol]
            d.polygon(pts, fill=rgb + (55,))
            d.line(pts + [pts[0]], fill=rgb + (255,), width=3)
            cx = sum(p[0] for p in pts) / len(pts)
            cy = sum(p[1] for p in pts) / len(pts)
            rotulo = f"SIGMET {fen} {rd.niveis_sigmet(txt)}".strip()
            d.text((cx, cy), rotulo, font=f, fill=(255, 255, 255, 255), anchor="mm",
                   stroke_width=3, stroke_fill=(0, 0, 0, 255))
        self.img.alpha_composite(camada)

    def raios(self, pontos):
        """pontos = [[lat, lon, faixa], ...] — o mesmo "raiozinho" do site, por idade."""
        d = ImageDraw.Draw(self.img)
        forma = [(.1, -.5), (-.3, .05), (0, .05), (-.15, .5), (.3, -.1), (.02, -.1), (.22, -.5)]
        cores = [tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for _, c, _ in rd.FAIXAS_RAIOS]
        s = 13
        # os mais antigos primeiro: os recentes (vermelhos) ficam por cima
        for la, lo, faixa in sorted(pontos, key=lambda p: -p[2]):
            x, y = self.xy(la, lo)
            if -s < x < self.w + s and -s < y < self.h + s:
                d.polygon([(x + a * s, y + b * s) for a, b in forma], fill=cores[faixa], outline=(0, 0, 0))

    def rota(self, pernas, alternativa=None):
        d = ImageDraw.Draw(self.img)
        pts = [self.xy(*p) for p in pernas]
        d.line(pts, fill=(0, 0, 0, 255), width=9)
        d.line(pts, fill=(0, 242, 255, 255), width=5)
        if alternativa:
            a, b = self.xy(*pernas[-1]), self.xy(*alternativa)
            n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) // 14))
            for i in range(0, n, 2):                 # tracejado: desenha um pedaço sim, outro não
                p0 = (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
                p1 = (a[0] + (b[0] - a[0]) * (i + 1) / n, a[1] + (b[1] - a[1]) * (i + 1) / n)
                d.line([p0, p1], fill=(199, 125, 255, 255), width=4)

    def aerodromos(self, metars, icaos, avisos=None):
        """Etiqueta VFR/MVFR/IFR/LIFR (critério FAA, igual ao site) + o código ICAO.
        Só os aeródromos da lista 'icaos' (os da rota): na região de SP há tantos
        que, todos juntos, as etiquetas se escondem umas atrás das outras.
        Desenhamos na ordem inversa: o primeiro da lista (origem) fica por cima."""
        d = ImageDraw.Draw(self.img)
        f_cat, f_icao = _fonte(13, True), _fonte(14, True)
        ordem = {icao: i for i, icao in enumerate(icaos)}
        lista = sorted((a for a in AERODROMOS if a[0] in ordem), key=lambda a: -ordem[a[0]])
        for icao, _, _, lat, lon in lista:
            x, y = self.xy(lat, lon)
            if not (0 <= x <= self.w and 0 <= y <= self.h):
                continue
            metar = (metars.get(icao) or {}).get("mens", "")
            info = mt.analisar(metar) if metar else None
            texto, fundo, cor = mt.CATEGORIAS_FAA[info["faa"] if info else "ND"]
            caixa = d.textbbox((x, y), texto, font=f_cat, anchor="mm")
            caixa = (caixa[0] - 5, caixa[1] - 3, caixa[2] + 5, caixa[3] + 3)
            if (avisos or {}).get(icao):              # aviso de aeródromo: anel branco e preto
                d.rounded_rectangle((caixa[0] - 5, caixa[1] - 5, caixa[2] + 5, caixa[3] + 5), 5, outline=(0, 0, 0), width=2)
                d.rounded_rectangle((caixa[0] - 3, caixa[1] - 3, caixa[2] + 3, caixa[3] + 3), 4, outline=(255, 255, 255), width=2)
            d.rounded_rectangle(caixa, 3, fill=fundo, outline=(0, 0, 0))
            d.text((x, y), texto, font=f_cat, fill=cor, anchor="mm")
            d.text((x, caixa[1] - 4), icao, font=f_icao, fill=(241, 196, 15), anchor="md",
                   stroke_width=3, stroke_fill=(0, 0, 0))

    def legenda(self, linhas, canto="baixo-esquerda"):
        """Caixinha escura com texto, no canto do mapa. linhas = [(texto, cor RGB ou None), ...]"""
        d = ImageDraw.Draw(self.img)
        f = _fonte(14)
        alt = 20 * len(linhas) + 12
        larg = max(d.textlength(t, font=f) for t, _ in linhas) + (34 if any(c for _, c in linhas) else 16)
        x0 = 10 if "esquerda" in canto else self.w - larg - 10
        y0 = self.h - alt - 10 if "baixo" in canto else 10
        d.rounded_rectangle((x0, y0, x0 + larg, y0 + alt), 6, fill=(13, 27, 40, 230))
        for i, (t, cor) in enumerate(linhas):
            yy = y0 + 8 + 20 * i
            xx = x0 + 8
            if cor:
                d.rectangle((xx, yy + 3, xx + 14, yy + 15), fill=cor, outline=(0, 0, 0))
                xx += 22
            d.text((xx, yy), t, font=f, fill=(232, 238, 243))

    def titulo(self, texto):
        d = ImageDraw.Draw(self.img)
        f = _fonte(18, True)
        larg = d.textlength(texto, font=f) + 20
        d.rounded_rectangle((10, 10, 10 + larg, 40), 6, fill=(13, 27, 40, 230))
        d.text((20, 15), texto, font=f, fill=(241, 196, 15))

    def png(self):
        buf = io.BytesIO()
        self.img.convert("RGB").save(buf, format="PNG", optimize=True)
        return buf.getvalue()


def legenda_padrao(com_raios=True, com_sigmet=True, com_altn=True):
    linhas = [("Rota", (0, 242, 255))] + ([("Para a alternativa", (199, 125, 255))] if com_altn else [])
    if com_sigmet:
        linhas += [("SIGMET TS", (224, 32, 43)), ("SIGMET TURB", (242, 208, 36)), ("SIGMET ICE", (94, 200, 242))]
    if com_raios:
        linhas += [(f"Raios {t}", tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))) for _, c, t in rd.FAIXAS_RAIOS]
    return linhas


# ---------------------------------------------------------------------------
# Mapa de vento: barbelas (o símbolo de vento das cartas aeronáuticas)
# ---------------------------------------------------------------------------
def mapa_vento(caixa, dados_gfs, rotulo_nivel, pernas, alternativa=None, titulo="", largura=1400):
    """Fundo do mapa + barbelas de vento coloridas pela velocidade + a rota.
    Usa o matplotlib só para desenhar as barbelas (ele já sabe desenhar o símbolo
    certo: cada traço longo = 10 kt, traço curto = 5 kt, bandeira = 50 kt)."""
    import matplotlib
    matplotlib.use("Agg")                          # desenha sem janela (servidor)
    import matplotlib.pyplot as plt
    import numpy as np

    folha = MapaEstatico(caixa, largura=largura)
    folha.fundo()
    folha.rotulos()
    folha.rota(pernas, alternativa)

    d = dados_gfs["niveis"][rotulo_nivel]
    lats, lons = dados_gfs["lat"], dados_gfs["lon"]
    # uma barbela a cada ~75 pixels, em grade regular NA IMAGEM
    xs, ys, us, vs = [], [], [], []
    passo = 75
    for py in range(passo // 2, folha.h, passo):
        for px in range(passo // 2, folha.w, passo):
            la, lo = folha.latlon(px, py)
            if not (lats[0] <= la <= lats[-1] and lons[0] <= lo <= lons[-1]):
                continue
            i = int(np.argmin(np.abs(lats - la)))
            j = int(np.argmin(np.abs(lons - lo)))
            xs.append(px)
            ys.append(folha.h - py)               # no matplotlib o y cresce para CIMA
            us.append(float(d["u"][i, j]) * 1.943844)
            vs.append(float(d["v"][i, j]) * 1.943844)

    dpi = 100
    fig = plt.figure(figsize=(folha.w / dpi, folha.h / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.imshow(folha.img, extent=[0, folha.w, 0, folha.h])
    vel = np.hypot(us, vs)
    # Escala de cores CLARA (o fundo é escuro): azul-claro (fraco) -> amarelo -> vermelho -> magenta (jato)
    from matplotlib.colors import LinearSegmentedColormap
    cores = LinearSegmentedColormap.from_list("vento", ["#9be7ff", "#2ee6a6", "#c6f000", "#ffd000",
                                                        "#ff7a00", "#ff2a2a", "#ff3df2"])
    b = ax.barbs(xs, ys, us, vs, vel, cmap=cores, clim=(0, 120), length=7.5, linewidth=1.6,
                 sizes={"emptybarb": 0.15})
    ax.set_xlim(0, folha.w)
    ax.set_ylim(0, folha.h)
    ax.axis("off")
    cax = fig.add_axes([0.62, 0.07, 0.34, 0.022])
    cb = fig.colorbar(b, cax=cax, orientation="horizontal")
    cb.set_label("velocidade do vento (kt)", color="white", fontsize=10)
    cb.ax.tick_params(colors="white", labelsize=9)
    if titulo:
        ax.text(14, folha.h - 16, titulo, color="#f1c40f", fontsize=14, fontweight="bold", va="top",
                bbox=dict(facecolor="#0d1b28", edgecolor="none", alpha=0.9, boxstyle="round,pad=0.4"))
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, facecolor="#202428")
    plt.close(fig)
    return buf.getvalue()
