import streamlit as st
import folium
import requests
import re
from streamlit_folium import st_folium
from folium import plugins

# --- CONFIGURAÇÃO ---
st.set_page_config(layout="wide", page_title="Portal Prof. Hiremar")

# --- ESTILO MATRIX ---
st.markdown("""
    <style>
        .stApp { background-color: #0b1a27; }
        h1, h2, h3, p, label { color: #f1c40f !important; }
        [data-testid="stSidebar"] { background-color: #1e1e1e; border-right: 2px solid #00f2ff; }
        code { color: #00ff00 !important; background-color: #000000 !important; }
    </style>
""", unsafe_allow_html=True)

# --- API KEY ---
if "REDEMET_KEY" in st.secrets:
    api_key = st.secrets["REDEMET_KEY"]
else:
    api_key = st.sidebar.text_input("REDEMET API KEY", type="password")

if not api_key:
    st.warning("Insira a API KEY para carregar dados meteorológicos.")
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

# --- INTERFACE ---
aba = st.sidebar.radio("Navegação", ["🛰️ Briefing em Tempo Real", "📺 Aulas"])

if aba == "🛰️ Briefing em Tempo Real":
    st.sidebar.subheader("📍 Rota e Planeamento")
    lista_ads = ["SBGR", "SBSP", "SBKP", "SBGL", "SBRJ", "SBRF", "SBPA", "SBCT", "SBBR", "SBBH"]
    origem = st.sidebar.selectbox("Origem", lista_ads, index=0)
    destino = st.sidebar.selectbox("Destino", lista_ads, index=8)
    alternativa = st.sidebar.selectbox("Alternativa", lista_ads, index=9)
    
    st.sidebar.subheader("📡 Meteorologia")
    show_sat = st.sidebar.checkbox("Exibir Satélite", value=False)
    show_sigmet = st.sidebar.checkbox("Exibir SIGMETs", value=True)

    COORDS = {
        "SBGR": [-23.432, -46.470], "SBGL": [-22.810, -43.250], "SBSP": [-23.626, -46.656],
        "SBRJ": [-22.910, -43.162], "SBRF": [-8.126, -34.923],  "SBKP": [-23.007, -47.134],
        "SBPA": [-29.994, -51.171], "SBCT": [-25.531, -49.175], "SBBR": [-15.869, -47.917],
        "SBBH": [-19.624, -43.898]
    }

    # 1. INICIAR MAPA
    m = folium.Map(location=[-15.0, -48.0], zoom_start=5, tiles=None)

    # 2. CAMADAS DE FUNDO (BASE)
    folium.TileLayer(tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                     attr='Esri Satellite', name='Satélite (Google Earth)', overlay=False).add_to(m)
    folium.TileLayer('CartoDB dark_matter', name="Mapa Escuro", overlay=False).add_to(m)

    # 3. CAMADAS DE CARTAS BAIXA (L1 a L9)
    for i in range(1, 10):
        folium.WmsTileLayer(
            url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
            layers=f"ICA:ENRC_L{i}",
            fmt="image/png", transparent=True, name=f"Carta L{i} (Baixa)",
            overlay=True, show=(i==1), attr="DECEA"
        ).add_to(m)

    # 4. CAMADAS DE CARTAS ALTA (H1 a H9)
    for i in range(1, 10):
        folium.WmsTileLayer(
            url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
            layers=f"ICA:ENRC_H{i}",
            fmt="image/png", transparent=True, name=f"Carta H{i} (Alta)",
            overlay=True, show=False, attr="DECEA"
        ).add_to(m)

    # 5. SATÉLITE REDEMET
    if show_sat:
        folium.WmsTileLayer(
            url="https://redemet.decea.mil.br/geoserver/wms",
            layers="satelite:goes16_ch13_realce",
            fmt="image/png", transparent=True, name="Satélite GOES-16",
            overlay=True, opacity=0.5
        ).add_to(m)

    # 6. SIGMETs
    if show_sigmet:
        try:
            s_res = requests.get(f"https://api-redemet.decea.mil.br/mensagens/sigmet?api_key={api_key}").json()
            for s in s_res.get('data', {}).get('data', []):
                pts = sigmet_to_decimal(s['mens'])
                if len(pts) >= 3:
                    folium.Polygon(
                        locations=pts, color=get_sigmet_color(s['mens']),
                        fill=True, fill_opacity=0.3, popup=s['mens']
                    ).add_to(m)
        except: pass

    # 7. AERÓDROMOS (ORIGEM, DESTINO, ALTERNATIVA)
    dados_missao = []
    # Lista única para evitar duplicados se a alternativa for igual ao destino, por exemplo
    ad_para_plotar = list(dict.fromkeys([origem, destino, alternativa]))

    for icao in ad_para_plotar:
        try:
            m_res = requests.get(f"https://api-redemet.decea.mil.br/mensagens/metar/{icao}?api_key={api_key}").json()
            t_res = requests.get(f"https://api-redemet.decea.mil.br/mensagens/taf/{icao}?api_key={api_key}").json()
            metar = m_res['data']['data'][0]['mens'] if m_res.get('data') and m_res['data']['data'] else "N/D"
            taf = t_res['data']['data'][0]['mens'] if t_res.get('data') and t_res['data']['data'] else "N/D"
            
            dados_missao.append({"ICAO": icao, "METAR": metar, "TAF": taf})
            
            # Cor do ícone: Azul para rota principal, Roxo para alternativa
            cor_icone = 'purple' if icao == alternativa else 'blue'
            
            folium.Marker(
                COORDS[icao], 
                popup=folium.Popup(f"<b>{icao}</b><br><small>{metar}</small>", max_width=300),
                icon=folium.Icon(color=cor_icone, icon='plane', prefix='fa')
            ).add_to(m)
        except: continue

    # Linha da Rota Principal
    folium.PolyLine([COORDS[origem], COORDS[destino]], color="#00f2ff", weight=4, opacity=0.8, tooltip="Rota Principal").add_to(m)

    # Controles
    folium.LayerControl(position='topright', collapsed=True).add_to(m)
    plugins.Fullscreen().add_to(m)

    st.title(f"🛰️ Briefing: {origem} ✈️ {destino} (ALTN: {alternativa})")
    st_folium(m, width="100%", height=700)

    # Exibição dos códigos METAR/TAF (Cards)
    if dados_missao:
        st.divider()
        cols = st.columns(len(dados_missao))
        for idx, dado in enumerate(dados_missao):
            with cols[idx]:
                st.subheader(f"📍 {dado['ICAO']}")
                st.markdown("**METAR**")
                st.code(dado['METAR'], language="fix")
                st.markdown("**TAF**")
                st.code(dado['TAF'], language="fix")

