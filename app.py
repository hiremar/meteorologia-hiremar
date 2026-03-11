import streamlit as st
import folium
import requests
import re
from streamlit_folium import st_folium
from folium import plugins

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(layout="wide", page_title="Portal de Meteorologia Prof. Hiremar")

# --- ESTILO MATRIX ---
st.markdown("""
    <style>
        .stApp { background-color: #0b1a27; }
        h1, h2, h3, h4, p, li, label, div, span { color: #f1c40f !important; }
        [data-testid="stSidebar"] { background-color: #1e1e1e; border-right: 2px solid #00f2ff; }
        code { color: #00ff00 !important; background-color: #000000 !important; }
    </style>
""", unsafe_allow_html=True)

# --- API KEY ---
api_key = st.sidebar.text_input("REDEMET API KEY", value="tyZcJePk7Y5v7QZGbqXiDQwHaGQFli9J5HfQh15f", type="password")

# --- FUNÇÕES ---
def plot_tsc(mapa, api_key):
    try:
        url_tsc = f"https://api-redemet.decea.mil.br/produtos/raios?api_key={api_key}"
        res = requests.get(url_tsc).json()
        if res.get('status') and res.get('data'):
            fg_raios = folium.FeatureGroup(name="⚡ Descargas Atmosféricas (TSC)").add_to(mapa)
            for raio in res['data']:
                minutos = int(raio['minutos'])
                # Cores padrão REDEMET
                cor = 'red' if minutos <= 15 else ('yellow' if minutos <= 30 else ('green' if minutos <= 45 else 'blue'))
                folium.CircleMarker(
                    location=[float(raio['lat']), float(raio['lon'])],
                    radius=6, # Tamanho do ponto
                    color=cor,
                    fill=True,
                    fill_opacity=1,
                    popup=f"Raio há {minutos} min",
                    z_index=1000 # Garante que fique em cima da nuvem
                ).add_to(fg_raios)
    except: pass

# --- MENU ---
aba = st.sidebar.radio("Ir para:", ["🛰️ Briefing em Tempo Real", "📺 Aulas", "📚 Materiais"])

if aba == "🛰️ Briefing em Tempo Real":
    # Inputs da Sidebar
    st.sidebar.subheader("📡 Camadas")
    show_tsc = st.sidebar.checkbox("Exibir Satélite / TSC", value=True)
    show_sigmet = st.sidebar.checkbox("Exibir SIGMETs", value=True)
    
    # Criando o Mapa com os Fundos Legais
    m = folium.Map(location=[-15.0, -48.0], zoom_start=5, tiles=None)

    # 1. Mapa Estilo Google Earth
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri Satellite', name='Satélite (Google Earth)', overlay=False
    ).add_to(m)

    # 2. Mapa Escuro (Dark Matter)
    folium.TileLayer('CartoDB dark_matter', name="Mapa Escuro", overlay=False).add_to(m)

    # --- CAMADAS METEOROLÓGICAS ---
    if show_tsc:
        # Nuvens GOES-16
        folium.WmsTileLayer(
            url="https://redemet.decea.mil.br/geoserver/wms",
            layers="satelite:goes16_ch13_realce",
            fmt="image/png", transparent=True, name="Nuvens (Satélite)", overlay=True, opacity=0.5
        ).add_to(m)
        # Plota os Raios por cima de tudo
        plot_tsc(m, api_key)

    # --- CARTAS AIS (CORREÇÃO L1 DEFINITIVA) ---
    LINKS_BAIXA = {f"L{i}": f"ICA:ENRC_L{i}" for i in range(1, 10)}
    lista_baixa = []
    for label, layer_id in LINKS_BAIXA.items():
        lyr = folium.WmsTileLayer(
            url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
            layers=layer_id,
            fmt="image/png",
            transparent=True,
            name=f"Carta {label}",
            overlay=True,
            show=False,
            attr="DECEA",
            version="1.1.1"
        ).add_to(m)
        lista_baixa.append(lyr)

    # Adiciona Controle de Camadas (O menu que você gosta no topo direito)
    folium.LayerControl(position='topright', collapsed=True).add_to(m)
    plugins.Fullscreen().add_to(m)

    st.title("🛰️ Briefing Operacional")
    st_folium(m, width="100%", height=700)
