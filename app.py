import base64
import io
import os
import re
from datetime import datetime, timedelta, timezone
import folium
from folium import plugins
import numpy as np
from PIL import Image
import requests
import s3fs
import streamlit as st
from streamlit_folium import st_folium
import xarray as xr

# Garante pasta do Herbie se necessário
os.environ["HERBIE_SAVE_DIR"] = "/tmp/herbie_data"

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(layout="wide", page_title="Portal de Meteorologia Prof. Hiremar")

# --- ESTILO VISUAL (MATRIX / AERONÁUTICO) ---
st.markdown(
    """
    <style>
        .stApp { background-color: #0b1a27; }
        h1, h2, h3, h4, p, li, label, div, span { color: #f1c40f !important; font-family: 'Segoe UI', sans-serif; }
        [data-testid="stSidebar"] { background-color: #1e1e1e; border-right: 2px solid #00f2ff; }
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] p, [data-testid="stSidebar"] span { color: #00f2ff !important; }
        code { color: #00ff00 !important; background-color: #000000 !important; font-size: 1.1em !important; border: 1px solid #00ff00; }
        .streamlit-expanderHeader { background-color: #1e1e1e !important; border: 1px solid #00f2ff !important; color: #ffffff !important; }
        a { color: #00f2ff !important; text-decoration: none; font-weight: bold; }
        a:hover { color: #f1c40f !important; }
    </style>
""",
    unsafe_allow_html=True,
)

# --- SEGURANÇA DA API ---
if "REDEMET_KEY" in st.secrets:
    api_key = st.secrets["REDEMET_KEY"]
else:
    api_key = st.sidebar.text_input("REDEMET API KEY", type="password")

if not api_key:
    st.error("⚠️ API KEY necessária para carregar os dados.")
    st.stop()


# --- Região do mapa e resolução ---------------------------------------
LAT_MIN, LAT_MAX = -58.0, 16.0
LON_MIN, LON_MAX = -95.0, -25.0
RES_GRAUS = 0.05          # 0.05° ≈ 5 km. Menor = mais nítido, porém mais pesado


def _reprojetar_geos_para_latlon(x, y, lon0_deg, H, r_eq, r_pol):
    """O satélite enxerga o planeta 'de longe' (projeção geostacionária).
    O Folium espera lat/lon. Aqui, para CADA pixel do mapa final, calculamos
    de qual pixel do satélite ele vem (fórmulas do manual GOES-R PUG)."""
    lons = np.arange(LON_MIN, LON_MAX, RES_GRAUS)

    # Linhas espaçadas em Mercator, que é como o Leaflet desenha o mapa.
    # (Se fossem espaçadas em latitude pura, a imagem ficaria deslocada.)
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

    # ângulo de varredura -> número da linha/coluna na matriz do arquivo
    col = np.rint((x_ang - x[0]) / (x[1] - x[0])).astype(int)
    lin = np.rint((y_ang - y[0]) / (y[1] - y[0])).astype(int)
    ok = visivel & (col >= 0) & (col < len(x)) & (lin >= 0) & (lin < len(y))
    return lin, col, ok


def _colorir_ir(tc):
    """Temperatura de brilho (°C) -> cor RGBA. Quanto mais frio, mais alto o topo
    da nuvem (CBs em amarelo/laranja/vermelho). Solo quente fica transparente."""
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
    t = pts[:, 0][::-1]          # np.interp exige eixo crescente, então invertemos
    rgba = np.zeros(tc.shape + (4,), dtype=np.uint8)
    for i in range(4):
        rgba[..., i] = np.interp(tc, t, pts[:, i + 1][::-1]).astype(np.uint8)
    return rgba


@st.cache_data(ttl=600, show_spinner=False)   # 10 min = intervalo de varredura do GOES
def carregar_goes19_overlay():
    try:
        fs = s3fs.S3FileSystem(anon=True)
        agora = datetime.now(timezone.utc)

        # Procura o arquivo C13 mais recente na hora atual; se não houver, na anterior.
        # (timedelta evita o erro de virada de dia que o "hour-1" tinha)
        arquivos = []
        for delta in (0, 1):
            t = agora - timedelta(hours=delta)
            pasta = f"noaa-goes19/ABI-L2-CMIPF/{t:%Y}/{t:%j}/{t:%H}/"
            try:
                arquivos = [f for f in fs.ls(pasta) if "M6C13" in f and f.endswith(".nc")]
            except FileNotFoundError:
                arquivos = []
            if arquivos:
                break
        if not arquivos:
            return None, None, None
        ultimo = sorted(arquivos)[-1]

        with fs.open(ultimo, "rb") as f:
            ds = xr.open_dataset(f, engine="h5netcdf")
            p = ds["goes_imager_projection"].attrs
            r_eq, r_pol = float(p["semi_major_axis"]), float(p["semi_minor_axis"])
            H = float(p["perspective_point_height"]) + r_eq
            lon0 = float(p["longitude_of_projection_origin"])
            x = ds["x"].values.astype("float64")
            y = ds["y"].values.astype("float64")

            lin, col, ok = _reprojetar_geos_para_latlon(x, y, lon0, H, r_eq, r_pol)

            # Lê só o "retângulo" do disco que interessa (bem menos dados do S3)
            r0, r1 = lin[ok].min(), lin[ok].max() + 1
            c0, c1 = col[ok].min(), col[ok].max() + 1
            pedaco = ds["CMI"].isel(y=slice(r0, r1), x=slice(c0, c1)).values

        tc = np.full(lin.shape, np.nan)
        tc[ok] = pedaco[lin[ok] - r0, col[ok] - c0] - 273.15   # Kelvin -> °C
        rgba = _colorir_ir(np.nan_to_num(tc, nan=99.0))
        rgba[np.isnan(tc), 3] = 0

        buf = io.BytesIO()
        Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        bounds = [[LAT_MIN, LON_MIN], [LAT_MAX, LON_MAX]]
        # hora da imagem, tirada do nome do arquivo: ..._s20262711820...
        hora = re.search(r"_s(\d{4})(\d{3})(\d{2})(\d{2})", ultimo)
        carimbo = f"{hora[1]} dia {hora[2]} {hora[3]}:{hora[4]}Z" if hora else "?"
        return f"data:image/png;base64,{img_b64}", bounds, carimbo

    except Exception as e:
        st.sidebar.error(f"Erro no processamento GOES-19: {e}")
        return None, None, None

# --- FUNÇÕES DE APOIO ---
def sigmet_to_decimal(texto):
    padrao = r"([NS])(\d{2})(\d{2})\s([WE])(\d{3})(\d{2})"
    matches = re.findall(padrao, texto)
    return [
        [
            -(int(m[1]) + int(m[2]) / 60) if m[0] == "S" else (int(m[1]) + int(m[2]) / 60),
            -(int(m[4]) + int(m[5]) / 60) if m[3] == "W" else (int(m[4]) + int(m[5]) / 60),
        ]
        for m in matches
    ]


def get_sigmet_color(msg):
    msg = msg.upper()
    if "TS" in msg:
        return "red"
    if "ICE" in msg:
        return "skyblue"
    if "TURB" in msg:
        return "yellow"
    return "orange"


NIVEIS_MAP = {
    "SFC": 1000,
    "FL050": 850,
    "FL080": 750,
    "FL100": 700,
    "FL120": 600,
    "FL140": 600,
    "FL180": 500,
    "FL220": 400,
    "FL240": 400,
    "FL260": 350,
    "FL300": 300,
    "FL340": 250,
    "FL360": 225,
    "FL410": 200,
}


@st.cache_resource(ttl=3600)
def carregar_dados_gfs(fl_alvo):
    try:
        pressao = NIVEIS_MAP.get(fl_alvo, 500)
        url = f"https://api.open-meteo.com/v1/gfs?latitude=-15.78&longitude=-47.93&hourly=temperature_{pressao}hPa,windspeed_{pressao}hPa,winddirection_{pressao}hPa&forecast_days=1"
        r = requests.get(url)
        if r.status_code != 200:
            return None, "Erro na API"

        response = r.json()
        dados_processados = {
            "temp_media_c": response["hourly"][f"temperature_{pressao}hPa"][0],
            "wind_spd": response["hourly"][f"windspeed_{pressao}hPa"][0],
            "wind_dir": response["hourly"][f"winddirection_{pressao}hPa"][0],
            "rodada": "GFS via Open-Meteo (Real-time)",
        }
        return dados_processados, dados_processados["rodada"]
    except Exception as e:
        return None, str(e)


# --- MENU LATERAL ---
st.sidebar.title("✈️ Menu de Navegação")
aba = st.sidebar.radio(
    "Ir para:",
    [
        "🛰️ Briefing em Tempo Real",
        "🚀 Modelo GFS (Vento/Gelo)",
        "📺 Aulas em Vídeo",
        "📚 Materiais e Links",
    ],
)

if aba == "🛰️ Briefing em Tempo Real":
    st.sidebar.subheader("📍 Planejamento de Voo")
    lista_ads = [
        "SBGR",
        "SBSP",
        "SBKP",
        "SBGL",
        "SBRJ",
        "SBRF",
        "SBPA",
        "SBCT",
        "SBBR",
        "SBBH",
    ]
    origem = st.sidebar.selectbox("Origem", lista_ads, index=0)
    destino = st.sidebar.selectbox("Destino", lista_ads, index=8)
    alternativa = st.sidebar.selectbox("Alternativa", lista_ads, index=9)

    st.sidebar.subheader("📡 Camadas Ativas")
    show_goes_ir = st.sidebar.checkbox("Exibir Satélite GOES-19 (NetCDF NOAA)", value=True)
    show_sigmet = st.sidebar.checkbox("Exibir SIGMETs", value=True)

    st.sidebar.markdown("---")
    st.sidebar.subheader("🗺️ Seleção de Cartas ENRC")
    cartas_baixa_sel = st.sidebar.multiselect("Cartas de Baixa (L)", [f"L{i}" for i in range(1, 10)])
    cartas_alta_sel = st.sidebar.multiselect("Cartas de Alta (H)", [f"H{i}" for i in range(1, 10)])

    st.title(f"🛰️ Briefing Operacional: {origem} ✈️ {destino}")

    # 1. Inicialização do Mapa
    m = folium.Map(location=[-15.0, -58.0], zoom_start=4, tiles=None)

    # Camadas de Fundo Cartográfico
    folium.TileLayer("CartoDB dark_matter", name="Mapa Escuro (Matrix)", overlay=False).add_to(m)
    folium.TileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri Satellite",
        name="Satélite (Google Earth)",
        overlay=False,
    ).add_to(m)

    # 2. Cartas ENRC Selecionadas
    for carta in cartas_baixa_sel:
        folium.WmsTileLayer(
            url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
            layers=f"ICA:ENRC_{carta}",
            fmt="image/png",
            transparent=True,
            name=f"Carta {carta}",
            overlay=True,
            show=True,
        ).add_to(m)

    for carta in cartas_alta_sel:
        folium.WmsTileLayer(
            url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
            layers=f"ICA:ENRC_{carta}",
            fmt="image/png",
            transparent=True,
            name=f"Carta {carta}",
            overlay=True,
            show=True,
        ).add_to(m)

    # 3. CAMADA OVERLAY GOES-19 (NETCDF4 REAL-TIME S3)
    if show_goes_ir:
        with st.spinner("Conectando ao S3 da NOAA e extraindo NetCDF do GOES-19..."):
            img_url, img_bounds, carimbo = carregar_goes19_overlay()
            if img_url and img_bounds:
                folium.raster_layers.ImageOverlay(
                    image=img_url,
                    bounds=img_bounds,
                    opacity=0.85,
                    name=f"GOES-19 IR C13 ({carimbo})",
                    interactive=False,
                ).add_to(m)
                st.caption(f"🛰️ GOES-19 Canal 13 (IR) — imagem das {carimbo}")
            else:
                st.warning("Não foi possível obter a imagem GOES-19 agora.")

    # 4. SIGMETs
    if show_sigmet:
        try:
            s_res = requests.get(f"https://api-redemet.decea.mil.br/mensagens/sigmet?api_key={api_key}").json()
            for s in s_res.get("data", {}).get("data", []):
                pts = sigmet_to_decimal(s["mens"])
                if len(pts) >= 3:
                    folium.Polygon(
                        locations=pts,
                        color=get_sigmet_color(s["mens"]),
                        fill=True,
                        fill_opacity=0.3,
                        popup=s["mens"],
                    ).add_to(m)
        except Exception:
            pass

    # 5. Marcadores e Rota
    COORDS = {
        "SBGR": [-23.432, -46.470],
        "SBGL": [-22.810, -43.250],
        "SBSP": [-23.626, -46.656],
        "SBRJ": [-22.910, -43.162],
        "SBRF": [-8.126, -34.923],
        "SBKP": [-23.007, -47.134],
        "SBPA": [-29.994, -51.171],
        "SBCT": [-25.531, -49.175],
        "SBBR": [-15.869, -47.917],
        "SBBH": [-19.624, -43.898],
    }

    dados_missao = []
    for icao in list(dict.fromkeys([origem, destino, alternativa])):
        try:
            m_dat = requests.get(f"https://api-redemet.decea.mil.br/mensagens/metar/{icao}?api_key={api_key}").json()
            t_dat = requests.get(f"https://api-redemet.decea.mil.br/mensagens/taf/{icao}?api_key={api_key}").json()
            metar = m_dat["data"]["data"][0]["mens"]
            taf = t_dat["data"]["data"][0]["mens"]
            dados_missao.append({"ICAO": icao, "METAR": metar, "TAF": taf})

            cor = "blue" if icao in [origem, destino] else "purple"
            folium.Marker(
                COORDS[icao],
                popup=f"<b>{icao}</b>",
                icon=folium.Icon(color=cor, icon="plane", prefix="fa"),
            ).add_to(m)
        except Exception:
            continue

    folium.PolyLine([COORDS[origem], COORDS[destino]], color="#00f2ff", weight=5).add_to(m)

    # Controles
    plugins.Fullscreen().add_to(m)
    folium.LayerControl(position="topright").add_to(m)

    st_folium(m, width="100%", height=600)

    # Detalhamento METAR/TAF
    st.subheader("🔍 Dados Meteorológicos da Rota")
    cols = st.columns(3)
    for i, dado in enumerate(dados_missao):
        if i < 3:
            with cols[i].expander(f"📍 {dado['ICAO']}", expanded=True):
                st.markdown("**METAR:**")
                st.code(dado["METAR"], language="fix")
                st.markdown("**TAF:**")
                st.code(dado["TAF"], language="fix")

elif aba == "🚀 Modelo GFS (Vento/Gelo)":
    st.title("🚀 Análise de Previsão Numérica - GFS")
    fl_alvo = st.sidebar.selectbox("Selecione o FL para Análise:", list(NIVEIS_MAP.keys()))

    with st.spinner(f"Buscando dados do {fl_alvo}..."):
        ds, rodada_info = carregar_dados_gfs(fl_alvo)
        if ds:
            st.success(f"Dados carregados para o {fl_alvo}")
            c1, c2, c3 = st.columns(3)
            c1.metric("Temperatura", f"{ds['temp_media_c']:.1f} °C")
            c2.metric("Vento (Velocidade)", f"{ds['wind_spd']:.0f} km/h")
            c3.metric("Vento (Direção)", f"{ds['wind_dir']:.0f}°")

            if ds["temp_media_c"] < 0 and fl_alvo != "SFC":
                st.warning("❄️ Risco de Gelo: Nível acima da Isoterma de 0°C.")

            m_gfs = folium.Map(location=[-15.0, -58.0], zoom_start=4, tiles="CartoDB dark_matter")
            st_folium(m_gfs, width="100%", height=600)
        else:
            st.error("Falha na comunicação com o provedor GFS. Tente outro FL.")

elif aba == "📺 Aulas em Vídeo":
    st.title("📺 Centro de Treinamento")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("🎥 Aula 1: Altimetria - Ajuste: QNH / QNE")
        st.video("https://www.youtube.com/watch?v=Y_91K9CBaRg")
    with col2:
        st.subheader("🎥 Aula 2: Satélite, SIGMET e GELO")
        st.video("https://www.youtube.com/watch?v=KoyZS3iCeM0")

elif aba == "📚 Materiais e Links":
    st.title("📚 Biblioteca Digital")
    st.markdown(
        """
    ### 📖 Manuais Oficiais
    - [ICA 105-15/2025 (Manual de Estação Meteorológica de Superfície)](https://publicacoes.decea.mil.br/publicacao/ica-105-15)
    - [ICA 105-16/2025 (Códigos Meteorológicos)](https://publicacoes.decea.mil.br/publicacao/ica-105-16)
    - [ICA 105-17/2025 (Manual de Centros Meteorológicos)](https://publicacoes.decea.mil.br/publicacao/ica-105-17)
    ### 🔗 Links Úteis
    - [REDEMET](https://redemet.decea.mil.br/)
    - [AISWEB](https://aisweb.decea.mil.br/)
    - [AVIATION WEATHER CENTER](https://aviationweather.gov/)
    """
    )
