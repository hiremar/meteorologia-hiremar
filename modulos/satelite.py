"""GOES-19: do arquivo NetCDF da NOAA até uma imagem PNG pronta para o mapa.

É o mesmo processo que já funcionava no seu app, agora servindo dois canais:
  - IR  (canal 13, 10,3 µm): temperatura do topo das nuvens -> cores
  - VIS (canal 2, 0,64 µm): reflectância (luz do Sol refletida) -> tons de cinza

O canal 2 "puro" tem 0,5 km de resolução e o arquivo é enorme. Por isso o visível
vem do produto MCMIPF, que traz os 16 canais já em 2 km (a mesma grade do canal 13).
Assim a reprojeção é idêntica e o custo de download fica parecido com o do IR.
"""
import base64
import io
import re
from datetime import datetime, timedelta, timezone

import numpy as np
from PIL import Image

# --- Região do mapa e resolução ---------------------------------------------
LAT_MIN, LAT_MAX = -58.0, 16.0
LON_MIN, LON_MAX = -95.0, -25.0
RES_GRAUS = 0.05          # 0.05° ≈ 5 km. Menor = mais nítido, porém mais pesado

# Qual arquivo e qual variável usar para cada canal
CANAIS = {
    "IR":  {"produto": "ABI-L2-CMIPF",  "filtro": "M6C13", "variavel": "CMI"},
    "VIS": {"produto": "ABI-L2-MCMIPF", "filtro": "MCMIPF-M6", "variavel": "CMI_C02"},
}


def reprojetar_geos_para_latlon(x, y, lon0_deg, H, r_eq, r_pol):
    """O satélite enxerga o planeta 'de longe' (projeção geoestacionária).
    O mapa espera lat/lon. Para CADA pixel do mapa final, calculamos
    de qual pixel do satélite ele vem (fórmulas do manual GOES-R PUG)."""
    lons = np.arange(LON_MIN, LON_MAX, RES_GRAUS)

    # Linhas espaçadas em Mercator, que é como o Leaflet desenha o mapa.
    merc = lambda lat: np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))
    n_lin = int(round((LAT_MAX - LAT_MIN) / RES_GRAUS * 1.15))
    ys = np.linspace(merc(LAT_MAX), merc(LAT_MIN), n_lin)
    lats = np.degrees(2 * np.arctan(np.exp(ys)) - np.pi / 2)

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


def colorir_ir(tc):
    """Temperatura de brilho (°C) -> cor RGBA. Quanto mais frio, mais alto o topo."""
    #        °C    R    G    B    A
    pts = np.array([
        [ 10, 255, 255, 255,   0],
        [ -5, 235, 235, 235,  90],
        [-20, 200, 210, 230, 170],
        [-30,  90, 150, 255, 220],
        [-40,   0, 220, 220, 235],
        [-50,  60, 220,  60, 245],
        [-58, 255, 240,   0, 250],
        [-65, 255, 130,   0, 255],
        [-72, 220,   0,   0, 255],
        [-80, 255,   0, 200, 255],
    ], dtype=float)
    t = pts[:, 0][::-1]
    rgba = np.zeros(tc.shape + (4,), dtype=np.uint8)
    for i in range(4):
        rgba[..., i] = np.interp(tc, t, pts[:, i + 1][::-1]).astype(np.uint8)
    return rgba


def colorir_vis(refl):
    """Reflectância (0 = escuro, 1 = muito brilhante) -> cinza RGBA.
    - raiz quadrada (correção gama) realça nuvens finas e fica mais natural;
    - superfícies escuras (mar, floresta) ficam quase transparentes, então o
      mapa de fundo aparece e as nuvens se destacam.
    À noite a reflectância é ~0: a imagem fica praticamente transparente."""
    g = np.sqrt(np.clip(refl, 0, 1))
    cinza = (g * 255).astype(np.uint8)
    alfa = (np.clip((g - 0.22) / 0.38, 0, 1) * 240).astype(np.uint8)
    return np.dstack([cinza, cinza, cinza, alfa])


def achar_arquivo(fs, canal, horas_atras=3):
    """Arquivo mais recente do canal pedido (procura até 3 horas para trás)."""
    cfg = CANAIS[canal]
    agora = datetime.now(timezone.utc)
    for delta in range(horas_atras):
        t = agora - timedelta(hours=delta)
        pasta = f"noaa-goes19/{cfg['produto']}/{t:%Y}/{t:%j}/{t:%H}/"
        try:
            achados = [f for f in fs.ls(pasta) if cfg["filtro"] in f and f.endswith(".nc")]
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


def processar_dataset(ds, canal):
    """Dataset aberto -> matriz RGBA já reprojetada."""
    p = ds["goes_imager_projection"].attrs
    r_eq, r_pol = float(p["semi_major_axis"]), float(p["semi_minor_axis"])
    H = float(p["perspective_point_height"]) + r_eq
    lon0 = float(p["longitude_of_projection_origin"])
    x = ds["x"].values.astype("float64")
    y = ds["y"].values.astype("float64")

    lin, col, ok = reprojetar_geos_para_latlon(x, y, lon0, H, r_eq, r_pol)
    r0, r1 = lin[ok].min(), lin[ok].max() + 1
    c0, c1 = col[ok].min(), col[ok].max() + 1
    pedaco = ds[CANAIS[canal]["variavel"]].isel(y=slice(r0, r1), x=slice(c0, c1)).values

    campo = np.full(lin.shape, np.nan)
    campo[ok] = pedaco[lin[ok] - r0, col[ok] - c0]

    if canal == "IR":
        rgba = colorir_ir(np.nan_to_num(campo - 273.15, nan=99.0))   # Kelvin -> °C
    else:
        rgba = colorir_vis(np.nan_to_num(campo, nan=0.0))
    rgba[np.isnan(campo), 3] = 0                                     # sem dado = transparente
    return rgba


def rgba_para_data_url(rgba):
    """Matriz RGBA -> 'data:image/png;base64,...' (a imagem vai embutida na página)."""
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def carregar_overlay(canal):
    """Faz tudo: acha o arquivo, lê só o pedaço necessário, reprojeta e colore.
    Retorna (data_url, limites, instante_utc) ou levanta exceção com a explicação."""
    import s3fs          # importados aqui para o site abrir mesmo se faltarem
    import xarray as xr

    fs = s3fs.S3FileSystem(anon=True)
    arquivo = achar_arquivo(fs, canal)
    if arquivo is None:
        raise RuntimeError("nenhum arquivo GOES-19 encontrado nas últimas 3 horas")
    with fs.open(arquivo, "rb") as f:
        ds = xr.open_dataset(f, engine="h5netcdf")
        rgba = processar_dataset(ds, canal)
    limites = [[LAT_MIN, LON_MIN], [LAT_MAX, LON_MAX]]
    return rgba_para_data_url(rgba), limites, instante_arquivo(arquivo)
