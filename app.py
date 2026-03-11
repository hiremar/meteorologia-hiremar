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

# --- API KEY (SEGURA) ---
if "REDEMET_KEY" in st.secrets:
    api_key = st.secrets["REDEMET_KEY"]
else:
    api_key = st.sidebar.text_input("REDEMET API KEY", type="password")

if not api_key:
    st.stop()

# --- FUNÇÕES ---
def sigmet_to_decimal(texto):
    padrao = r'([NS])(\d{2})(\d{2})\s([WE])(\d{3})(\d{2})'
    matches = re.findall(padrao, texto)
    return [[-(int(m[1]) + int(m[2])/60) if m[0] == 'S' else (int(m[1]) + int(m[2])/60),
             -(int(m[4]) + int(m[5])/60) if m[3] == 'W' else (int(m[4]) + int(m[5])/60)] for m in matches]

# --- SEÇÃO PRINCIPAL ---
st.sidebar.title("✈️ Navegação")
aba = st.sidebar.radio("Ir para:", ["🛰️ Briefing em Tempo Real", "📺 Aulas", "📚 Materiais"])

if aba == "🛰️ Briefing em Tempo Real":
    st.sidebar.subheader("📡 Camadas")
    show_satelite = st.sidebar.checkbox("Exibir Satélite", value=False)
    show_sigmet = st.sidebar.checkbox("Exibir SIGMETs", value=True)

    # 1. CRIAR O MAPA BASE (Sem tiles padrão aqui)
    m = folium.Map(location=[-15.0, -48.0], zoom_start=5, tiles=None)

    # 2. ADICIONAR OS MAPAS DE FUNDO (BASE LAYERS)
    folium.TileLayer(
        tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        attr='Esri Satellite', name='Satélite (Google Earth)', overlay=False, control=True
    ).add_to(m)

    folium.TileLayer('CartoDB dark_matter', name="Mapa Escuro (Matrix)", overlay=False, control=True).add_to(m)

    # 3. CRIAR GRUPOS PARA AS CARTAS (OVERLAYS)
    group_baixa = folium.FeatureGroup(name="📉 CARTAS BAIXA (ENRC L)", overlay=True, control=False).add_to(m)
    group_alta = folium.FeatureGroup(name="📈 CARTAS ALTA (ENRC H)", overlay=True, control=False).add_to(m)

    # 4. ADICIONAR CARTAS AOS GRUPOS COM Z-INDEX ALTO
    # Criamos a L1 separada para garantir que ela receba atenção total
    for i in range(1, 10):
        layer_id = f"ICA:ENRC_L{i}"
        lyr = folium.WmsTileLayer(
            url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
            layers=layer_id,
            fmt="image/png",
            transparent=True,
            name=f"L{i}",
            overlay=True,
            show=False,
            attr="DECEA",
            version="1.1.1",
            zindex=100 # Isso garante que ela fique por cima do mapa base
        )
        lyr.add_to(group_baixa)

    # 5. SATÉLITE (Como Overlay)
    if show_satelite:
        folium.WmsTileLayer(
            url="https://redemet.decea.mil.br/geoserver/wms",
            layers="satelite:goes16_ch13_realce",
            fmt="image/png", transparent=True, name="Nuvens", overlay=True, opacity=0.5, zindex=50
        ).add_to(m)

    # 6. SIGMET
    if show_sigmet:
        try:
            s_res = requests.get(f"https://api-redemet.decea.mil.br/mensagens/sigmet?api_key={api_key}").json()
            for s in s_res.get('data', {}).get('data', []):
                pts = sigmet_to_decimal(s['mens'])
                if len(pts) >= 3:
                    folium.Polygon(locations=pts, color="red", fill=True, fill_opacity=0.2, popup=s['mens']).add_to(m)
        except: pass

    # 7. CONTROLES FINAIS
    folium.LayerControl(position='topright', collapsed=True).add_to(m)
    
    # Adicionamos o agrupador sanfona para facilitar a vida do usuário
    plugins.GroupedLayerControl(
        groups={
            "Cartas de Rota": [group_baixa, group_alta]
        },
        collapsed=True
    ).add_to(m)

    st.title("🛰️ Briefing Operacional")
    st_folium(m, width="100%", height=700)

