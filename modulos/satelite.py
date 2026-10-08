"""GOES-19: do arquivo NetCDF da NOAA até uma imagem pronta para o mapa.

Dois produtos:
  - IR  (canal 13, 10,3 µm): temperatura do topo das nuvens -> cores, com um
        sombreamento de "relevo" (o topo das nuvens frias vira montanha) que dá o ar 3D.
        Também sai uma grade de temperatura para o site mostrar °C e K ao passar o mouse.
  - VIS (visível em CORES REAIS): canais 1 (azul, 0,47 µm), 2 (vermelho, 0,64 µm) e
        3 (infravermelho próximo, 0,86 µm, usado para fabricar o verde, que o GOES não tem).
        É a receita "true color" da NOAA/CIMSS. À noite a imagem fica transparente.

Os dois vêm em 2 km. Antes de colocar na grade do mapa (~5 km) tiramos a média dos
vizinhos (suavização): sem isso, sortear 1 pixel a cada 5 km deixa a imagem serrilhada.
O visível vem do produto MCMIPF, que traz os 16 canais já na mesma grade de 2 km do IR.
"""
import base64
import io
import math
import re
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image

# --- Região do mapa e resolução ---------------------------------------------
LAT_MIN, LAT_MAX = -58.0, 16.0
LON_MIN, LON_MAX = -95.0, -25.0
RES_GRAUS = 0.05          # 0.05° ≈ 5 km. Menor = mais nítido, porém mais pesado
PASSO_TEMP = 2            # grade de temperatura do mouse: 1 a cada 2 pixels (~10 km)
K_BASE = 170              # temperatura (K) guardada como (K - 170) em 1 byte: 170 a 424 K
REGIAO_PADRAO = (LAT_MIN, LAT_MAX, LON_MIN, LON_MAX, RES_GRAUS)   # América do Sul inteira, ~5 km
RES_DETALHE = 0.02        # recorte da rota: ~2 km, a resolução nativa do GOES (o máximo que existe)
LARG_MAX_DETALHE = 1800   # pixels: rota muito longa -> resolução um pouco menor, para não pesar

# Qual arquivo e quais variáveis usar para cada canal
CANAIS = {
    "IR":  {"produto": "ABI-L2-CMIPF",  "filtro": "M6C13", "variaveis": ["CMI"]},
    "VIS": {"produto": "ABI-L2-MCMIPF", "filtro": "MCMIPF-M6", "variaveis": ["CMI_C01", "CMI_C02", "CMI_C03"]},
}

# Escala do IR: (°C, R, G, B, A). Quanto mais frio, mais alto o topo da nuvem.
ESCALA_IR = [
    [10, 255, 255, 255, 0],
    [-5, 235, 235, 235, 90],
    [-20, 200, 210, 230, 170],
    [-30, 90, 150, 255, 220],
    [-40, 0, 220, 220, 235],
    [-50, 60, 220, 60, 245],
    [-58, 255, 240, 0, 250],
    [-65, 255, 130, 0, 255],
    [-72, 220, 0, 0, 255],
    [-80, 255, 0, 200, 255],
]


def eixos(regiao=None):
    """Longitudes (oeste -> leste) e latitudes (norte -> sul) dos pixels do mapa.
    As linhas são espaçadas em Mercator, que é como o Leaflet desenha o mapa.
    regiao = (lat_min, lat_max, lon_min, lon_max, resolução em graus); padrão = América do Sul."""
    la0, la1, lo0, lo1, res = regiao or REGIAO_PADRAO
    lons = np.arange(lo0, lo1, res)
    merc = lambda lat: np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
    n_lin = int(round((la1 - la0) / res * 1.15))
    ys = np.linspace(merc(la1), merc(la0), n_lin)
    lats = np.degrees(2 * np.arctan(np.exp(ys)) - np.pi / 2)
    return lons, lats


def reprojetar_geos_para_latlon(x, y, lon0_deg, H, r_eq, r_pol, regiao=None):
    """O satélite enxerga o planeta 'de longe' (projeção geoestacionária).
    O mapa espera lat/lon. Para CADA pixel do mapa final, calculamos
    de qual pixel do satélite ele vem (fórmulas do manual GOES-R PUG)."""
    lons, lats = eixos(regiao)
    lon_g, lat_g = np.meshgrid(np.radians(lons), np.radians(lats))
    lon0 = np.radians(lon0_deg)
    e2 = 1 - (r_pol / r_eq) ** 2

    phi_c = np.arctan((r_pol ** 2 / r_eq ** 2) * np.tan(lat_g))
    r_c = r_pol / np.sqrt(1 - e2 * np.cos(phi_c) ** 2)
    s_x = H - r_c * np.cos(phi_c) * np.cos(lon_g - lon0)
    s_y = -r_c * np.cos(phi_c) * np.sin(lon_g - lon0)
    s_z = r_c * np.sin(phi_c)

    visivel = H * (H - s_x) >= s_y ** 2 + (r_eq ** 2 / r_pol ** 2) * s_z ** 2
    y_ang = np.arctan(s_z / s_x)
    x_ang = np.arcsin(-s_y / np.sqrt(s_x ** 2 + s_y ** 2 + s_z ** 2))

    col = np.rint((x_ang - x[0]) / (x[1] - x[0])).astype(int)
    lin = np.rint((y_ang - y[0]) / (y[1] - y[0])).astype(int)
    ok = visivel & (col >= 0) & (col < len(x)) & (lin >= 0) & (lin < len(y))
    return lin, col, ok


# ---------------------------------------------------------------------------
# Suavização e ângulo do Sol
# ---------------------------------------------------------------------------
def suavizar(a, raio=1):
    """Média dos vizinhos (janela de (2·raio+1)² pixels), ignorando os sem dado (NaN).
    Feita em duas passadas (linhas, depois colunas): gasta bem menos memória."""
    a = np.asarray(a, dtype="float32")
    valido = np.isfinite(a)
    soma = np.where(valido, a, 0).astype("float32")
    peso = valido.astype("float32")
    for eixo in (0, 1):
        s2, p2 = soma.copy(), peso.copy()
        for d in range(1, raio + 1):
            for desloc in (d, -d):
                s2 += np.roll(soma, desloc, axis=eixo)
                p2 += np.roll(peso, desloc, axis=eixo)
        soma, peso = s2, p2
    with np.errstate(invalid="ignore", divide="ignore"):
        saida = soma / peso
    saida[~valido] = np.nan
    return saida


def cos_zenite_solar(instante, lats, lons):
    """Cosseno do ângulo zenital do Sol em cada pixel (1 = Sol a pino, 0 = horizonte,
    negativo = noite). Fórmulas astronômicas simples (precisão de ~0,5°, suficiente aqui)."""
    dia = instante.timetuple().tm_yday
    g = 2 * math.pi / 365 * (dia - 1 + (instante.hour - 12) / 24)
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g) - 0.006758 * math.cos(2 * g)
            + 0.000907 * math.sin(2 * g) - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    eq_tempo = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                         - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))   # minutos
    minutos = instante.hour * 60 + instante.minute + instante.second / 60
    ang_horario = np.radians((minutos + eq_tempo + 4 * lons[None, :]) / 4 - 180)      # graus -> rad
    lat = np.radians(lats)[:, None]
    return np.sin(lat) * math.sin(decl) + np.cos(lat) * math.cos(decl) * np.cos(ang_horario)


# ---------------------------------------------------------------------------
# Cores
# ---------------------------------------------------------------------------
def colorir_ir(tc):
    """Temperatura de brilho (°C) -> cor RGBA. Quanto mais frio, mais alto o topo."""
    pts = np.array(ESCALA_IR, dtype=float)
    t = pts[:, 0][::-1]
    rgba = np.zeros(tc.shape + (4,), dtype=np.uint8)
    for i in range(4):
        rgba[..., i] = np.interp(tc, t, pts[:, i + 1][::-1]).astype(np.uint8)
    return rgba


def sombrear_relevo(rgba, tc, intensidade=0.22):
    """Dá o ar 3D: trata o topo das nuvens como um relevo (nuvem mais fria = mais alta)
    e ilumina com um 'sol' vindo do noroeste, como num mapa topográfico sombreado.
    Lado virado para a luz fica mais claro; o lado oposto, mais escuro."""
    altura = np.clip(-np.nan_to_num(tc, nan=10.0), -10, 90)        # °C negativos viram "altura"
    altura = suavizar(altura, 1)                   # tira só o "chiado" de cada pixel; mantém a textura
    d_lin, d_col = np.gradient(altura)                             # variação por pixel
    # normal da superfície (x = leste, y = norte; as linhas crescem para o SUL)
    nx, ny, nz = -d_col * 0.6, d_lin * 0.6, np.ones_like(altura)
    norma = np.sqrt(nx ** 2 + ny ** 2 + nz ** 2)
    alt, az = math.radians(45), math.radians(315)                  # luz a 45°, vindo do noroeste
    lx, ly, lz = math.cos(alt) * math.sin(az), math.cos(alt) * math.cos(az), math.sin(alt)
    luz = (nx * lx + ny * ly + nz * lz) / norma                    # 1 = de frente para a luz
    fator = np.clip(1 + intensidade * (luz - math.sin(alt)) / (1 - math.sin(alt)), 0.55, 1.35)
    saida = rgba.copy()
    for i in range(3):
        saida[..., i] = np.clip(rgba[..., i] * fator, 0, 255).astype(np.uint8)
    return saida


def colorir_cor_real(c01, c02, c03, cos_sol):
    """Visível em CORES REAIS (receita "true color" da NOAA/CIMSS):
       vermelho = canal 2 ; azul = canal 1 ;
       verde    = 0,45·vermelho + 0,10·canal 3 + 0,45·azul  (o GOES não tem canal verde);
       depois correção de gama (1/2,2) e um pouco mais de contraste: nuvem bem branca.
    O Sol baixo escurece a imagem; compensamos em parte. À noite (Sol abaixo do
    horizonte) a imagem vai ficando transparente e o mapa de fundo aparece."""
    sol = np.clip(cos_sol, 0.05, 1)
    compensa = 1 / sol ** 0.35                       # clareia o fim de tarde sem estourar
    r = np.clip(np.nan_to_num(c02) * compensa, 0, 1)
    b = np.clip(np.nan_to_num(c01) * compensa, 0, 1)
    nir = np.clip(np.nan_to_num(c03) * compensa, 0, 1)
    g = np.clip(0.45 * r + 0.1 * nir + 0.45 * b, 0, 1)
    rgb = np.stack([r, g, b], axis=-1) ** (1 / 2.2)                 # gama
    contraste = 105                                   # o mesmo do exemplo da NOAA/Unidata
    f = 259 * (contraste + 255) / (255 * (259 - contraste))
    rgb = np.clip(f * (rgb - 0.5) + 0.5, 0, 1)
    # dia -> opaco ; Sol entre 3° acima e 6° abaixo do horizonte -> vai sumindo ; noite -> transparente
    alfa = np.clip((cos_sol + 0.10) / 0.15, 0, 1)
    alfa[~np.isfinite(c02)] = 0
    return np.dstack([(rgb * 255).astype(np.uint8), (alfa * 255).astype(np.uint8)])


def legenda_ir_css():
    """Gradiente CSS com as mesmas cores do IR (para a barra da legenda)."""
    pts = [p for p in ESCALA_IR if p[0] <= -5]
    t0, t1 = pts[0][0], pts[-1][0]
    paradas = ", ".join(f"rgb({r},{g},{b}) {round((t0 - t) / (t0 - t1) * 100)}%" for t, r, g, b, _ in pts)
    return f"linear-gradient(to right, {paradas})", t0, t1


# ---------------------------------------------------------------------------
# Arquivos
# ---------------------------------------------------------------------------
def achar_arquivo(fs, canal, horas_atras=3):
    """Arquivo mais recente do canal pedido (procura até 3 horas para trás)."""
    cfg = CANAIS[canal]
    agora = datetime.now(timezone.utc)
    for delta in range(horas_atras):
        t = agora - timedelta(hours=delta)
        pasta = f"noaa-goes19/{cfg['produto']}/{t:%Y}/{t:%j}/{t:%H}/"
        try:
            # refresh=True: lista a pasta DE NOVO na NOAA. Sem isso, o s3fs reaproveita uma lista
            # antiga guardada na memória e o site fica preso numa imagem de 40-60 min atrás.
            achados = [f for f in fs.ls(pasta, refresh=True) if cfg["filtro"] in f and f.endswith(".nc")]
        except FileNotFoundError:
            achados = []
        if achados:
            return sorted(achados)[-1]
    return None


def instante_arquivo(nome):
    """..._s20262712110207_... -> datetime 2026-09-28 21:10 UTC"""
    m = re.search(r"_s(\d{4})(\d{3})(\d{2})(\d{2})", nome)
    if not m:
        return None
    return datetime.strptime("".join(m.groups()), "%Y%j%H%M").replace(tzinfo=timezone.utc)


def regiao_da_rota(pontos, margem=3.0, minimo=8.0):
    """Recorte em alta resolução em volta da rota: pontos = [[lat, lon], ...].
    Devolve (lat_min, lat_max, lon_min, lon_max, resolução), arredondado para o cache funcionar."""
    lats = [p[0] for p in pontos]
    lons = [p[1] for p in pontos]
    la0, la1 = min(lats) - margem, max(lats) + margem
    lo0, lo1 = min(lons) - margem, max(lons) + margem
    if la1 - la0 < minimo:
        c = (la0 + la1) / 2
        la0, la1 = c - minimo / 2, c + minimo / 2
    if lo1 - lo0 < minimo:
        c = (lo0 + lo1) / 2
        lo0, lo1 = c - minimo / 2, c + minimo / 2
    la0, la1 = max(la0, LAT_MIN), min(la1, LAT_MAX)
    lo0, lo1 = max(lo0, LON_MIN), min(lo1, LON_MAX)
    res = max(RES_DETALHE, (lo1 - lo0) / LARG_MAX_DETALHE, (la1 - la0) * 1.15 / LARG_MAX_DETALHE)
    return (round(la0, 1), round(la1, 1), round(lo0, 1), round(lo1, 1), round(res, 3))


def processar_dataset(ds, canal, instante=None, regiao=None):
    """Dataset aberto -> (matriz RGBA reprojetada, extras).
    extras["temp_k"] (só no IR) = grade de temperatura em Kelvin para o mouse.
    extras["rgba_relevo"] (só no IR) = a mesma imagem com o sombreamento de relevo (ar 3D)."""
    p = ds["goes_imager_projection"].attrs
    r_eq, r_pol = float(p["semi_major_axis"]), float(p["semi_minor_axis"])
    H = float(p["perspective_point_height"]) + r_eq
    lon0 = float(p["longitude_of_projection_origin"])
    x = ds["x"].values.astype("float64")
    y = ds["y"].values.astype("float64")

    lin, col, ok = reprojetar_geos_para_latlon(x, y, lon0, H, r_eq, r_pol, regiao)
    if not ok.any():
        raise RuntimeError("região fora da visão do satélite")
    r0, r1 = lin[ok].min(), lin[ok].max() + 1
    c0, c1 = col[ok].min(), col[ok].max() + 1

    def campo(variavel, suave):
        """Lê só o pedaço da América do Sul e coloca na grade do mapa.
        suave=True: média dos vizinhos antes (tira o serrilhado do visível).
        No IR fica False: lá a suavização deixava as nuvens com cara de "borrado"."""
        pedaco = ds[variavel].isel(y=slice(r0, r1), x=slice(c0, c1)).values
        if suave:
            pedaco = suavizar(pedaco, 1)
        saida = np.full(lin.shape, np.nan, dtype="float32")
        saida[ok] = pedaco[lin[ok] - r0, col[ok] - c0]
        return saida

    extras = {}
    if canal == "IR":
        kelvin = campo("CMI", suave=False)
        tc = kelvin - 273.15
        rgba = colorir_ir(np.nan_to_num(tc, nan=99.0))
        rgba[np.isnan(kelvin), 3] = 0                                  # sem dado = transparente
        # as duas versões saem do mesmo download: plana e com relevo (o site deixa escolher)
        extras["rgba_relevo"] = sombrear_relevo(rgba, tc)
        extras["temp_k"] = kelvin[::PASSO_TEMP, ::PASSO_TEMP]
    else:
        lons, lats = eixos(regiao)
        cos_sol = cos_zenite_solar(instante or datetime.now(timezone.utc), lats, lons)
        rgba = colorir_cor_real(campo("CMI_C01", True), campo("CMI_C02", True), campo("CMI_C03", True), cos_sol)
    return rgba, extras


def rgba_para_data_url(rgba):
    """Matriz RGBA -> 'data:image/webp;base64,...' (a imagem vai embutida na página).
    WebP fica várias vezes menor que PNG (o site carrega mais rápido); se a PIL não
    tiver suporte a WebP, cai para PNG."""
    img = Image.fromarray(rgba, "RGBA")
    buf = io.BytesIO()
    try:
        img.save(buf, format="WEBP", quality=85, method=4)
        tipo = "webp"
    except (OSError, KeyError, ValueError):
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        tipo = "png"
    return f"data:image/{tipo};base64," + base64.b64encode(buf.getvalue()).decode()


def temperatura_para_data_url(kelvin):
    """Grade de temperatura -> PNG em tons de cinza: cada pixel guarda (K - 170).
    255 = sem dado. O navegador lê esse PNG e mostra °C e K onde o mouse está."""
    v = np.where(np.isfinite(kelvin), np.clip(np.round(kelvin - K_BASE), 0, 254), 255).astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(v, "L").save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def carregar_overlay(canal, regiao=None, arquivo=None):
    """Faz tudo: acha o arquivo, lê só o pedaço necessário, reprojeta e colore.
    Retorna (data_url, limites, instante_utc, extras) ou levanta exceção com a explicação.
    regiao : recorte e resolução (padrão: América do Sul a ~5 km; ver regiao_da_rota)
    arquivo: usar exatamente este arquivo do GOES (o recorte da rota usa o MESMO horário
             da imagem geral, para não aparecer "emenda" entre as duas)
    extras: "canal", "arquivo", "url_relevo" (IR com relevo), "temp_url" (IR, só na imagem geral)."""
    import s3fs          # importados aqui para o site abrir mesmo se faltarem
    import xarray as xr

    # skip_instance_cache / use_listings_cache=False: nada de reaproveitar listas de arquivos antigas
    fs = s3fs.S3FileSystem(anon=True, skip_instance_cache=True, use_listings_cache=False)
    arquivo = arquivo or achar_arquivo(fs, canal)
    if arquivo is None:
        raise RuntimeError("nenhum arquivo GOES-19 encontrado nas últimas 3 horas")
    instante = instante_arquivo(arquivo)
    with fs.open(arquivo, "rb") as f:
        ds = xr.open_dataset(f, engine="h5netcdf")
        rgba, extras = processar_dataset(ds, canal, instante, regiao)
    la0, la1, lo0, lo1, _ = regiao or REGIAO_PADRAO
    limites = [[la0, lo0], [la1, lo1]]
    saida = {"canal": canal, "arquivo": arquivo}
    if "rgba_relevo" in extras:
        saida["url_relevo"] = rgba_para_data_url(extras["rgba_relevo"])
    if "temp_k" in extras and regiao is None:
        saida["temp_url"] = temperatura_para_data_url(extras["temp_k"])
    return rgba_para_data_url(rgba), limites, instante, saida
