import streamlit as st
import folium
import requests
import re
from streamlit_folium import st_folium
from folium import plugins
from herbie import Herbie
import xarray as xr
import numpy as np

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(layout="wide", page_title="Portal de Meteorologia Prof. Hiremar")

# --- ESTILO VISUAL (MATRIX / AERONÁUTICO) ---
st.markdown("""
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
""", unsafe_allow_html=True)

# --- SEGURANÇA DA API ---
if "REDEMET_KEY" in st.secrets:
    api_key = st.secrets["REDEMET_KEY"]
else:
    api_key = st.sidebar.text_input("REDEMET API KEY", type="password")

if not api_key:
    st.error("⚠️ API KEY necessária para carregar os dados.")
    st.stop()

# --- FUNÇÕES DE APOIO ---
def sigmet_to_decimal(texto):
    padrao = r'([NS])(\d{2})(\d{2})\s([WE])(\d{3})(\d{2})'
    matches = re.findall(padrao, texto)
    return [[-(int(m[1]) + int(m[2])/60) if m[0] == 'S' else (int(m[1]) + int(m[2])/60),
             -(int(m[4]) + int(m[5])/60) if m[3] == 'W' else (int(m[4]) + int(m[5])/60)] for m in matches]

def get_sigmet_color(msg):
    msg = msg.upper()
    if "TS" in msg: return "red"
    if "ICE" in msg: return "skyblue"
    if "TURB" in msg: return "yellow"
    return "orange"

# --- FUNÇÃO PARA O MODELO GFS (VERSÃO AWS - MAIS ESTÁVEL) ---
@st.cache_data(ttl=3600)
def carregar_dados_gfs():
    try:
        # Usando AWS para evitar quedas de conexão
        H = Herbie(model="gfs", product="pgrb2.0p25", fxx=0, source="aws", overwrite=False)
        ds = H.xarray(":(UGRD|VGRD|TMP|RH):", engine="cfgrib")
        return ds
    except Exception as e:
        st.sidebar.error(f"Erro na conexão AWS: {e}")
        return None

# --- TABELA DE NÍVEIS ---
NIVEIS_MAP = {
    "SFC": 1013, "FL050": 850, "FL080": 750, "FL100": 700, 
    "FL120": 650, "FL140": 600, "FL180": 500, "FL220": 450, 
    "FL240": 400, "FL260": 350, "FL300": 300, "FL340": 250, 
    "FL360": 225, "FL410": 200
}

# --- FUNÇÃO DE MAPA UNIFICADO ---
def gerar_mapa_base(cartas_L=[], cartas_H=[], mostrar_sat=True):
    m = folium.Map(location=[-15.0, -48.0], zoom_start=5, tiles=None)
    folium.TileLayer('CartoDB dark_matter', name="Mapa Escuro (Matrix)", overlay=False).add_to(m)
    if mostrar_sat:
        folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 
                         attr='Esri Satellite', name='Satélite', overlay=False).add_to(m)
    for carta in cartas_L:
        folium.WmsTileLayer(url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms", layers=f"ICA:ENRC_{carta}",
                            fmt="image/png", transparent=True, name=f"Carta {carta}", overlay=True).add_to(m)
    for carta in cartas_H:
        folium.WmsTileLayer(url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms", layers=f"ICA:ENRC_{carta}",
                            fmt="image/png", transparent=True, name=f"Carta {carta}", overlay=True).add_to(m)
    return m

# --- MENU LATERAL ---
st.sidebar.title("✈️ Menu de Navegação")
aba = st.sidebar.radio("Ir para:", ["🛰️ Briefing em Tempo Real", "🚀 Modelo GFS (Vento/Gelo)", "📺 Aulas em Vídeo", "📚 Materiais e Links"])

# Variáveis globais de seleção para persistência entre abas
st.sidebar.markdown("---")
st.sidebar.subheader("🗺️ Seleção de Cartas ENRC")
cartas_baixa_sel = st.sidebar.multiselect("Cartas de Baixa (L)", [f"L{i}" for i in range(1, 10)])
cartas_alta_sel = st.sidebar.multiselect("Cartas de Alta (H)", [f"H{i}" for i in range(1, 10)])

if aba == "🛰️ Briefing em Tempo Real":
    st.sidebar.subheader("📍 Planejamento de Voo")
    origem = st.sidebar.selectbox("Origem", ["SBGR", "SBSP", "SBKP", "SBGL", "SBRJ", "SBPA", "SBCT", "SBBR"], index=0)
    destino = st.sidebar.selectbox("Destino", ["SBGR", "SBSP", "SBKP", "SBGL", "SBRJ", "SBPA", "SBCT", "SBBR"], index=6)
    
    show_tsc = st.sidebar.checkbox("Exibir Satélite / TSC", value=True)
    show_sigmet = st.sidebar.checkbox("Exibir SIGMETs", value=True)

    st.title(f"🛰️ Briefing Operacional: {origem} ✈️ {destino}")
    m = gerar_mapa_base(cartas_baixa_sel, cartas_alta_sel, mostrar_sat=show_tsc)

    # Camadas REDEMET
    if show_tsc:
        folium.WmsTileLayer(url="https://redemet.decea.mil.br/geoserver/wms", layers="satelite:goes16_ch13_realce",
                            fmt="image/png", transparent=True, name="Nuvens / TSC", overlay=True, opacity=0.6).add_to(m)

    # Rota e Sigmets (Lógica simplificada para o exemplo)
    plugins.Fullscreen().add_to(m)
    st_folium(m, width="100%", height=600)

elif aba == "🚀 Modelo GFS (Vento/Gelo)":
    st.title("🚀 Análise GFS (AWS Mirror)")
    fl_alvo = st.sidebar.selectbox("Selecione o FL:", list(NIVEIS_MAP.keys()))
    pressao_hpa = NIVEIS_MAP[fl_alvo]

    with st.spinner(f"Sincronizando com AWS para o {fl_alvo}..."):
        ds = carregar_dados_gfs()
        
        # Mapa Unificado (Mesmas cartas do briefing)
        m_gfs = gerar_mapa_base(cartas_baixa_sel, cartas_alta_sel)

        if ds:
            st.success(f"Dados do modelo carregados com sucesso!")
            
            # Filtro de dados
            data_nivel = ds.sel(isobaricInhPa=pressao_hpa, method="nearest")
            temp_c = data_nivel.t.values - 273.15
            umidade = data_nivel.r.values

            # Alerta de Gelo (Lógica Prof. Hiremar)
            if fl_alvo in ["FL120", "FL140", "FL180", "FL220", "FL240"]:
                st.warning(f"⚠️ Nível {fl_alvo}: Faixa crítica de gelo severo (AC 91-74B).")
            
            # Exemplo de Detecção de Umidade
            if umidade.max() > 75:
                st.info(f"Umidade elevada detectada no nível ({umidade.max():.1f}%). Risco de IMC.")

        plugins.Fullscreen().add_to(m_gfs)
        st_folium(m_gfs, width="100%", height=600)
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
    st.markdown("""
    ### 📖 Manuais Oficiais
    - [ICA 105-15/2025 (Manual de Estação Meteorológica de Superfície)](https://publicacoes.decea.mil.br/publicacao/ica-105-15)
    - [ICA 105-16/2025 (Códigos Meteorológicos)](https://publicacoes.decea.mil.br/publicacao/ica-105-16)
    - [ICA 105-17/2025 (Manual de Centros Meteorológicos)](https://publicacoes.decea.mil.br/publicacao/ica-105-17)
    ### 🔗 Links Úteis
    - [REDEMET](https://redemet.decea.mil.br/)
    - [AISWEB](https://aisweb.decea.mil.br/)
    - [AVIATION WEATHER CENTER](https://aviationweather.gov/)
    """)







