import streamlit as st
import folium
import requests
import re
import os
from streamlit_folium import st_folium
from datetime import datetime
from folium import plugins

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(layout="wide", page_title="Portal de Meteorologia Prof. Hiremar")

# --- INJEÇÃO DE ESTILO (VISUAL MATRIX / SIMULADOR) ---
st.markdown("""
    <style>
        .stApp { background-color: #0b1a27; }
        
        /* Letras Amareladas/Creme */
        h1, h2, h3, h4, p, li, label, div, span {
            color: #f1c40f !important;
            font-family: 'Segoe UI', sans-serif;
        }

        /* Sidebar Customizada */
        [data-testid="stSidebar"] {
            background-color: #1e1e1e;
            border-right: 2px solid #00f2ff;
        }
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] p, [data-testid="stSidebar"] span {
            color: #00f2ff !important;
        }

        /* METAR/TAF Code Block - Verde Matrix */
        code {
            color: #00ff00 !important;
            background-color: #000000 !important;
            font-size: 1.1em !important;
            border: 1px solid #00ff00;
        }

        /* Estilo dos Expanders */
        .streamlit-expanderHeader {
            background-color: #1e1e1e !important;
            border: 1px solid #00f2ff !important;
            color: #ffffff !important;
        }
    </style>
""", unsafe_allow_html=True)

# --- SEGURANÇA DA API (SECRETS) ---
# Prioriza o st.secrets para não mostrar o input na tela se já estiver configurado
if "REDEMET_KEY" in st.secrets:
    api_key = st.secrets["REDEMET_KEY"]
else:
    api_key = st.sidebar.text_input("REDEMET API KEY", type="password", help="Insira sua chave API da Redemet")

if not api_key:
    st.error("⚠️ API KEY não detectada. Configure o 'Secret' no Streamlit Cloud ou insira manualmente na barra lateral.")
    st.stop()

# --- CONFIGURAÇÕES DE CARTAS ENRC ---
LINKS_BAIXA = {
    "L1": "ICA%3AENRC_L1", "L2": "ICA%3AENRC_L2", "L3": "ICA%3AENRC_L3",
    "L4": "ICA%3AENRC_L4", "L5": "ICA%3AENRC_L5", "L6": "ICA%3AENRC_L6",
    "L7": "ICA%3AENRC_L7", "L8": "ICA%3AENRC_L8", "L9": "ICA%3AENRC_L9"
}

LINKS_ALTA = {
    "H1": "ICA%3AENRC_H1", "H2": "ICA%3AENRC_H2", "H3": "ICA%3AENRC_H3",
    "H4": "ICA%3AENRC_H4", "H5": "ICA%3AENRC_H5", "H6": "ICA%3AENRC_H6",
    "H7": "ICA%3AENRC_H7", "H8": "ICA%3AENRC_H8", "H9": "ICA%3AENRC_H9"
}

# --- MENU LATERAL ---
st.sidebar.title("✈️ Menu de Navegação")
aba = st.sidebar.radio("Ir para:", ["🛰️ Briefing em Tempo Real", "📺 Aulas em Vídeo", "📚 Materiais e Links"])

# --- FUNÇÕES DE APOIO ---
def get_sigmet_color(msg):
    msg = msg.upper()
    if "TS" in msg: return "red"
    if "ICE" in msg: return "skyblue"
    if "TURB" in msg: return "yellow"
    return "orange"

def sigmet_to_decimal(texto):
    padrao = r'([NS])(\d{2})(\d{2})\s([WE])(\d{3})(\d{2})'
    matches = re.findall(padrao, texto)
    return [[-(int(m[1]) + int(m[2])/60) if m[0] == 'S' else (int(m[1]) + int(m[2])/60),
             -(int(m[4]) + int(m[5])/60) if m[3] == 'W' else (int(m[4]) + int(m[5])/60)] for m in matches]

# --- SEÇÃO 1: BRIEFING OPERACIONAL ---
if aba == "🛰️ Briefing em Tempo Real":
    st.sidebar.subheader("📍 Planejamento de Voo")
    lista_ads = ["SBGR", "SBSP", "SBKP", "SBGL", "SBRJ", "SBRF", "SBPA", "SBCT", "SBBR", "SBBH"]
    origem = st.sidebar.selectbox("Origem", lista_ads, index=0)
    destino = st.sidebar.selectbox("Destino", lista_ads, index=8)
    alternativa = st.sidebar.selectbox("Alternativa", lista_ads, index=9)

    st.sidebar.subheader("📡 Camadas Meteorológicas")
    show_tsc = st.sidebar.checkbox("Exibir Satélite / TSC", value=True)
    show_sigmet = st.sidebar.checkbox("Exibir SIGMETs", value=True)
    show_vias = st.sidebar.checkbox("Exibir Aerovias", value=False)

    COORDS = {
        "SBGR": [-23.432, -46.470], "SBGL": [-22.810, -43.250], "SBSP": [-23.626, -46.656],
        "SBRJ": [-22.910, -43.162], "SBRF": [-8.126, -34.923],  "SBKP": [-23.007, -47.134],
        "SBPA": [-29.994, -51.171], "SBCT": [-25.531, -49.175], "SBBR": [-15.869, -47.917],
        "SBBH": [-19.624, -43.898]
    }
    OUTROS_ADS = ["SBGL", "SBRJ", "SBRF", "SBKP", "SBPA", "SBCT"]

    st.title(f"🛰️ Briefing Operacional: {origem} ✈️ {destino}")

    # --- MAPA ---
    m = folium.Map(location=[-15.0, -48.0], zoom_start=5, tiles=None)

    # Camadas Base
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri Satellite', name='Satélite (Google Earth)', overlay=False
    ).add_to(m)
    folium.TileLayer('CartoDB dark_matter', name="Mapa Escuro", control=True).add_to(m)

    # Camadas Meteorológicas Dinâmicas
    if show_tsc:
        folium.WmsTileLayer(
            url="https://redemet.decea.mil.br/geoserver/wms",
            layers="satelite:goes16_ch13_realce",
            fmt="image/png", transparent=True, name="Nuvens / TSC", overlay=True, opacity=0.6
        ).add_to(m)

    if show_sigmet:
        try:
            s_res = requests.get(f"https://api-redemet.decea.mil.br/mensagens/sigmet?api_key={api_key}").json()
            for s in s_res.get('data', {}).get('data', []):
                pts = sigmet_to_decimal(s['mens'])
                if len(pts) >= 3:
                    folium.Polygon(locations=pts, color=get_sigmet_color(s['mens']), fill=True, fill_opacity=0.3, popup=s['mens'], name="⚠️ SIGMET").add_to(m)
        except: pass

    if show_vias:
        folium.TileLayer(tiles='https://tile.wayfinding.pro/v1/enroute/{z}/{x}/{y}.png', attr='Wayfinding Pro', name='Aerovias', overlay=True).add_to(m)

    # --- INCLUSÃO DAS CARTAS AIS (ESTILO COLAB - FUNCIONA TUDO) ---
    lista_baixa = []
    for label, layer_id in LINKS_BAIXA.items():
        lyr = folium.WmsTileLayer(
            url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
            layers=layer_id.replace("%3A", ":"),
            fmt="image/png",
            transparent=True,
            name=f"Carta {label}",
            overlay=True,
            control=True,
            show=False,
            attr="DECEA",
            # Removidos: crs e version (deixa o Folium usar o padrão dele igual no Colab)
        ).add_to(m)
        lista_baixa.append(lyr)

    lista_alta = []
    for label, layer_id in LINKS_ALTA.items():
        lyr = folium.WmsTileLayer(
            url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
            layers=layer_id.replace("%3A", ":"),
            fmt="image/png",
            transparent=True,
            name=f"Carta {label}",
            overlay=True,
            control=True,
            show=False,
            attr="DECEA"
        ).add_to(m)
        lista_alta.append(lyr)

    # Agrupamento Sanfona para Cartas
    plugins.GroupedLayerControl(
        groups={
            "📉 CARTAS BAIXA (ENRC L)": lista_baixa,
            "📈 CARTAS ALTA (ENRC H)": lista_alta
        },
        exclusive_groups=False,
        collapsed=True,
        position='topright'
    ).add_to(m)

    # Marcadores de Aeródromos
    dados_missao = []
    todos_para_mapa = list(set([origem, destino, alternativa] + OUTROS_ADS))

    for icao in todos_para_mapa:
        try:
            m_data = requests.get(f"https://api-redemet.decea.mil.br/mensagens/metar/{icao}?api_key={api_key}").json()
            t_data = requests.get(f"https://api-redemet.decea.mil.br/mensagens/taf/{icao}?api_key={api_key}").json()
            metar = m_data['data']['data'][0]['mens'] if m_data.get('data') and m_data['data']['data'] else "N/D"
            taf = t_data['data']['data'][0]['mens'] if t_data.get('data') and t_data['data']['data'] else "N/D"

            if icao in [origem, destino, alternativa]:
                dados_missao.append({"ICAO": icao, "METAR": metar, "TAF": taf})

            cor = 'blue' if icao in [origem, destino] else ('purple' if icao == alternativa else 'green')
            folium.Marker(COORDS[icao], popup=f"<b>{icao}</b><br>{metar}", icon=folium.Icon(color=cor, icon='plane', prefix='fa')).add_to(m)
        except: continue

    folium.PolyLine([COORDS[origem], COORDS[destino]], color="#00f2ff", weight=5, opacity=0.8).add_to(m)
    
    # Controles extras
    plugins.Fullscreen().add_to(m)
    folium.LayerControl(position='topright', collapsed=True).add_to(m)
    
    st_folium(m, width="100%", height=650)

    # Detalhamento METAR/TAF (Cards)
    st.divider()
    st.subheader("🔍 Detalhamento da Missão (METAR/TAF)")
    if dados_missao:
        ordem = {origem: 0, destino: 1, alternativa: 2}
        dados_ordenados = sorted(dados_missao, key=lambda x: ordem.get(x['ICAO'], 99))
        cols = st.columns(3)
        for idx, dado in enumerate(dados_ordenados):
            with cols[idx].expander(f"✈️ {dado['ICAO']}", expanded=True):
                st.markdown("**METAR:**")
                st.code(dado['METAR'], language="fix")
                st.markdown("**TAF:**")
                st.code(dado['TAF'], language="fix")

# --- SEÇÃO 2: VÍDEOS ---
elif aba == "📺 Aulas em Vídeo":
    st.title("📺 Aulas de Meteorologia")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Aula 1: Introdução")
        st.video("https://www.youtube.com/watch?v=Y_91K9CBaRg&t=4s") 
    with col2:
        st.subheader("Aula 2: Interpretação de Cartas")
        st.write("Vídeo em breve...")

# --- SEÇÃO 3: MATERIAIS ---
elif aba == "📚 Materiais e Links":
    st.title("📚 Biblioteca e Links Úteis")
    st.markdown("""
    ### 🔗 Links Oficiais
    * [Portal REDEMET](https://www.redemet.decea.mil.br/)
    * [AISWEB - Informações Aeronáuticas](https://aisweb.decea.mil.br/)
    """)

