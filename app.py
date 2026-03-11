import streamlit as st
import folium
import requests
import re
from streamlit_folium import st_folium
from folium import plugins

# --- CONFIGURAÇÃO ---
st.set_page_config(layout="wide", page_title="Portal Prof. Hiremar")

# --- ESTILO ---
st.markdown("""
    <style>
        .stApp { background-color: #0b1a27; }
        h1, h2, h3, p, label { color: #f1c40f !important; }
        [data-testid="stSidebar"] { background-color: #1e1e1e; border-right: 2px solid #00f2ff; }
    </style>
""", unsafe_allow_html=True)

# --- API KEY ---
if "REDEMET_KEY" in st.secrets:
    api_key = st.secrets["REDEMET_KEY"]
else:
    api_key = st.sidebar.text_input("REDEMET API KEY", type="password")

if not api_key:
    st.warning("Insira a API KEY para prosseguir.")
    st.stop()

# --- MENU ---
aba = st.sidebar.radio("Navegação", ["🛰️ Briefing em Tempo Real", "📺 Aulas"])

if aba == "🛰️ Briefing em Tempo Real":
    st.title("🛰️ Briefing Operacional")
    
    # Checkbox para o Satélite
    show_sat = st.sidebar.checkbox("Exibir Satélite GOES-16", value=False)

    # 1. Mapa Base (Iniciando Vazio)
    m = folium.Map(location=[-15.0, -48.0], zoom_start=5, tiles=None)

    # 2. Adicionando os Fundos (Base Layers) - overlay=False é a chave
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri Satellite', name='Satélite (Google Earth)', overlay=False
    ).add_to(m)

    folium.TileLayer('CartoDB dark_matter', name="Mapa Escuro (Matrix)", overlay=False).add_to(m)
    
    folium.TileLayer('OpenStreetMap', name="Mapa Rodoviário", overlay=False).add_to(m)

    # 3. Adicionando a Carta L1 (Destaque)
    # Colocamos ela direto no mapa para não ter erro de 'plano'
    folium.WmsTileLayer(
        url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
        layers="ICA:ENRC_L1",
        fmt="image/png",
        transparent=True,
        name="Carta L1 (Baixa)",
        overlay=True,
        show=True, # Já começa ligada
        attr="DECEA"
    ).add_to(m)

    # 4. Outras Cartas (L2 a L9) - Opcionais no menu
    for i in range(2, 10):
        folium.WmsTileLayer(
            url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
            layers=f"ICA:ENRC_L{i}",
            fmt="image/png",
            transparent=True,
            name=f"Carta L{i}",
            overlay=True,
            show=False,
            attr="DECEA"
        ).add_to(m)

    # 5. Camada de Satélite REDEMET (Se marcado)
    if show_sat:
        folium.WmsTileLayer(
            url="https://redemet.decea.mil.br/geoserver/wms",
            layers="satelite:goes16_ch13_realce",
            fmt="image/png",
            transparent=True,
            name="Satélite GOES-16",
            overlay=True,
            opacity=0.5
        ).add_to(m)

    # 6. Controles
    folium.LayerControl(position='topright', collapsed=False).add_to(m)
    plugins.Fullscreen().add_to(m)

    st_folium(m, width="100%", height=700)

# --- CRÉDITOS ---
st.sidebar.markdown("---")
st.sidebar.write("Desenvolvido para fins de instrução meteorológica.")
