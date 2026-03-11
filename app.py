import streamlit as st
import folium
import requests
import re
from streamlit_folium import st_folium
from datetime import datetime
from folium import plugins

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(layout="wide", page_title="Portal de Meteorologia Prof. Hiremar")

# --- INJEÇÃO DE ESTILO MATRIX ---
st.markdown("""
    <style>
        .stApp { background-color: #0b1a27; }
        h1, h2, h3, h4, p, li, label, div, span { color: #f1c40f !important; font-family: 'Segoe UI', sans-serif; }
        [data-testid="stSidebar"] { background-color: #1e1e1e; border-right: 2px solid #00f2ff; }
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] p, [data-testid="stSidebar"] span { color: #00f2ff !important; }
        code { color: #00ff00 !important; background-color: #000000 !important; font-size: 1.1em !important; border: 1px solid #00ff00; }
        .streamlit-expanderHeader { background-color: #1e1e1e !important; border: 1px solid #00f2ff !important; color: #ffffff !important; }
    </style>
""", unsafe_allow_html=True)

# --- SEGURANÇA DA API ---
# Se não houver segredo configurado, pede o input mas não deixa o valor exposto no código
if "REDEMET_KEY" in st.secrets:
    api_key = st.secrets["REDEMET_KEY"]
else:
    api_key = st.sidebar.text_input("REDEMET API KEY", type="password", help="Insira sua chave API")

if not api_key:
    st.info("💡 Por favor, insira sua REDEMET API KEY na barra lateral para carregar os dados meteorológicos.")
    st.stop()

# --- CONFIGURAÇÕES DE CARTAS ENRC ---
LINKS_BAIXA = {f"L{i}": f"ICA:ENRC_L{i}" for i in range(1, 10)}
LINKS_ALTA = {f"H{i}": f"ICA:ENRC_H{i}" for i in range(1, 10)}

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

# --- MENU LATERAL ---
st.sidebar.title("✈️ Menu de Navegação")
aba = st.sidebar.radio("Ir para:", ["🛰️ Briefing em Tempo Real", "📺 Aulas em Vídeo", "📚 Materiais e Links"])

if aba == "🛰️ Briefing em Tempo Real":
    st.sidebar.subheader("📍 Planejamento de Voo")
    lista_ads = ["SBGR", "SBSP", "SBKP", "SBGL", "SBRJ", "SBRF", "SBPA", "SBCT", "SBBR", "SBBH"]
    origem = st.sidebar.selectbox("Origem", lista_ads, index=0)
    destino = st.sidebar.selectbox("Destino", lista_ads, index=8)
    alternativa = st.sidebar.selectbox("Alternativa", lista_ads, index=9)

    st.sidebar.subheader("📡 Camadas Visuais")
    show_satelite = st.sidebar.checkbox("Exibir Satélite GOES-16", value=True)
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

    # --- INICIALIZAÇÃO DO MAPA COM CAMADAS DE FUNDO ---
    m = folium.Map(location=[-15.0, -48.0], zoom_start=5, tiles=None)

    # Adicionando os mapas base que você gosta
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri Satellite', name='Satélite (Google Earth)', overlay=False
    ).add_to(m)
    
    folium.TileLayer('CartoDB dark_matter', name="Mapa Escuro (Matrix)", overlay=False).add_to(m)
    
    folium.TileLayer('OpenStreetMap', name="Mapa Padrão", overlay=False).add_to(m)

    # --- CAMADAS METEOROLÓGICAS ---
    if show_satelite:
        folium.WmsTileLayer(
            url="https://redemet.decea.mil.br/geoserver/wms",
            layers="satelite:goes16_ch13_realce",
            fmt="image/png", transparent=True, name="Nuvens (Satélite)", overlay=True, opacity=0.5
        ).add_to(m)

    if show_sigmet:
        try:
            s_res = requests.get(f"https://api-redemet.decea.mil.br/mensagens/sigmet?api_key={api_key}").json()
            for s in s_res.get('data', {}).get('data', []):
                pts = sigmet_to_decimal(s['mens'])
                if len(pts) >= 3:
                    folium.Polygon(locations=pts, color=get_sigmet_color(s['mens']), fill=True, fill_opacity=0.3, popup=s['mens']).add_to(m)
        except: pass

    if show_vias:
         folium.TileLayer(tiles='https://tile.wayfinding.pro/v1/enroute/{z}/{x}/{y}.png', attr='Wayfinding Pro', name='Aerovias', overlay=True).add_to(m)

    # --- CARTAS AIS (L1, L2... H1, H2...) ---
    lista_baixa = []
    for label, layer_id in LINKS_BAIXA.items():
        lyr = folium.WmsTileLayer(
            url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
            layers=layer_id,
            fmt="image/png",
            transparent=True,
            name=f"Carta {label}",
            overlay=True,
            show=False, # Começam desligadas para não poluir
            attr="DECEA",
            version="1.1.1"
        ).add_to(m)
        lista_baixa.append(lyr)

    lista_alta = []
    for label, layer_id in LINKS_ALTA.items():
        lyr = folium.WmsTileLayer(url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms", layers=layer_id, fmt="image/png", transparent=True, name=f"Carta {label}", overlay=True, show=False, attr="DECEA", version="1.1.1").add_to(m)
        lista_alta.append(lyr)

    # Organiza as cartas em grupos no menu
    plugins.GroupedLayerControl(
        groups={"📉 CARTAS BAIXA": lista_baixa, "📈 CARTAS ALTA": lista_alta},
        exclusive_groups=False, collapsed=True, position='topright'
    ).add_to(m)

    # --- AERÓDROMOS E ROTA ---
    dados_missao = []
    for icao in list(set([origem, destino, alternativa] + OUTROS_ADS)):
        try:
            m_res = requests.get(f"https://api-redemet.decea.mil.br/mensagens/metar/{icao}?api_key={api_key}").json()
            t_res = requests.get(f"https://api-redemet.decea.mil.br/mensagens/taf/{icao}?api_key={api_key}").json()
            metar = m_res['data']['data'][0]['mens'] if m_res.get('data') and m_res['data']['data'] else "N/D"
            taf = t_res['data']['data'][0]['mens'] if t_res.get('data') and t_res['data']['data'] else "N/D"
            if icao in [origem, destino, alternativa]:
                dados_missao.append({"ICAO": icao, "METAR": metar, "TAF": taf})
            cor = 'blue' if icao in [origem, destino] else ('purple' if icao == alternativa else 'green')
            folium.Marker(COORDS[icao], popup=f"<b>{icao}</b><br>{metar}", icon=folium.Icon(color=cor, icon='plane', prefix='fa')).add_to(m)
        except: continue

    folium.PolyLine([COORDS[origem], COORDS[destino]], color="#00f2ff", weight=5, opacity=0.8).add_to(m)
    
    # Controles de tela cheia e camadas
    plugins.Fullscreen().add_to(m)
    folium.LayerControl(position='topright', collapsed=True).add_to(m)

    st_folium(m, width="100%", height=650)

    # --- CARDS METAR/TAF ---
    st.divider()
    if dados_missao:
        cols = st.columns(3)
        for idx, dado in enumerate(dados_missao):
            with cols[idx].expander(f"✈️ {dado['ICAO']}", expanded=True):
                st.markdown("**METAR:**")
                st.code(dado['METAR'], language="fix")
                st.markdown("**TAF:**")
                st.code(dado['TAF'], language="fix")

# --- ABAS DE VÍDEO E MATERIAIS ---
elif aba == "📺 Aulas em Vídeo":
    st.title("📺 Aulas de Meteorologia")
    st.video("https://www.youtube.com/watch?v=Y_91K9CBaRg&t=4s")

elif aba == "📚 Materiais e Links":
    st.title("📚 Biblioteca")
    st.write("Links Oficiais: [REDEMET](https://www.redemet.decea.mil.br/) | [AISWEB](https://aisweb.decea.mil.br/)")
