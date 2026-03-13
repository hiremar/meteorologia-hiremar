import streamlit as st
import folium
import requests
import re
import xarray as xr
import numpy as np
import pandas as pd
from datetime import datetime
from streamlit_folium import st_folium
from folium import plugins
from herbie import Herbie
import os
# Garante que o Herbie tenha onde salvar os arquivos temporários no servidor
os.environ["HERBIE_SAVE_DIR"] = "/tmp/herbie_data"

# Estas duas são essenciais para ler o arquivo .grib2 do GFS
import cfgrib
import eccodes

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
# --- FUNÇÕES PARA O MODELO GFS (PROVISÓRIO PARA TESTE) ---

# Tabela de níveis que você pediu
NIVEIS_MAP = {
    "SFC": 1000, "FL050": 850, "FL080": 750, "FL100": 700, 
    "FL120": 600, "FL140": 600, "FL180": 500, "FL220": 400, 
    "FL240": 400, "FL260": 350, "FL300": 300, "FL340": 250, 
    "FL360": 225, "FL410": 200
}

@st.cache_resource(ttl=3600)
def carregar_dados_gfs(fl_alvo):
    try:
        pressao = NIVEIS_MAP[fl_alvo]
        # Pegamos os dados de um ponto central (Brasília) para referência de temperatura do nível
        url = f"https://api.open-meteo.com/v1/gfs?latitude=-15.78&longitude=-47.93&hourly=temperature_{pressao}hPa&forecast_days=1"
        response = requests.get(url).json()
        
        # Calculamos a média das temperaturas previstas para as próximas 24h no nível escolhido
        temps = response['hourly'][f'temperature_{pressao}hPa']
        temp_media_c = sum(temps) / len(temps)
        
        # Criamos um dicionário simples com os resultados
        dados_processados = {
            'temp_media_c': temp_media_c,
            'rodada': "GFS via Open-Meteo (Atualizado)"
        }
        return dados_processados, dados_processados['rodada']
    except Exception as e:
        return None, None

# --- MENU LATERAL ---
st.sidebar.title("✈️ Menu de Navegação")
aba = st.sidebar.radio("Ir para:", ["🛰️ Briefing em Tempo Real", "🚀 Modelo GFS (Vento/Gelo)", "📺 Aulas em Vídeo", "📚 Materiais e Links"])
if aba == "🛰️ Briefing em Tempo Real":
    st.sidebar.subheader("📍 Planejamento de Voo")
    lista_ads = ["SBGR", "SBSP", "SBKP", "SBGL", "SBRJ", "SBRF", "SBPA", "SBCT", "SBBR", "SBBH"]
    origem = st.sidebar.selectbox("Origem", lista_ads, index=0)
    destino = st.sidebar.selectbox("Destino", lista_ads, index=8)
    alternativa = st.sidebar.selectbox("Alternativa", lista_ads, index=9)

    st.sidebar.subheader("📡 Camadas Ativas")
    show_tsc = st.sidebar.checkbox("Exibir Satélite / TSC", value=True)
    show_sigmet = st.sidebar.checkbox("Exibir SIGMETs", value=True)
    
    # Nova subjanela na sidebar para as Cartas (Substituindo Aerovias)
    st.sidebar.markdown("---")
    st.sidebar.subheader("🗺️ Seleção de Cartas ENRC")
    cartas_baixa_sel = st.sidebar.multiselect("Cartas de Baixa (L)", [f"L{i}" for i in range(1, 10)])
    cartas_alta_sel = st.sidebar.multiselect("Cartas de Alta (H)", [f"H{i}" for i in range(1, 10)])

    st.title(f"🛰️ Briefing Operacional: {origem} ✈️ {destino}")

    # 1. Inicialização do Mapa (Ordem de pintura importa)
    m = folium.Map(location=[-15.0, -48.0], zoom_start=5, tiles=None)
    
    # Camadas de Fundo
    folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', 
                     attr='Esri Satellite', name='Satélite (Google Earth)', overlay=False).add_to(m)
    folium.TileLayer('CartoDB dark_matter', name="Mapa Escuro (Matrix)", overlay=False).add_to(m)

    # 2. Cartas ENRC Selecionadas (Renderizadas antes dos marcadores)
    for carta in cartas_baixa_sel:
        folium.WmsTileLayer(
            url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
            layers=f"ICA:ENRC_{carta}",
            fmt="image/png", transparent=True, name=f"Carta {carta}", overlay=True, show=True
        ).add_to(m)

    for carta in cartas_alta_sel:
        folium.WmsTileLayer(
            url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
            layers=f"ICA:ENRC_{carta}",
            fmt="image/png", transparent=True, name=f"Carta {carta}", overlay=True, show=True
        ).add_to(m)

    # 3. Camadas Meteorológicas
    if show_tsc:
        folium.WmsTileLayer(url="https://redemet.decea.mil.br/geoserver/wms", layers="satelite:goes16_ch13_realce",
                            fmt="image/png", transparent=True, name="Nuvens / TSC", overlay=True, opacity=0.6).add_to(m)

    if show_sigmet:
        try:
            s_res = requests.get(f"https://api-redemet.decea.mil.br/mensagens/sigmet?api_key={api_key}").json()
            for s in s_res.get('data', {}).get('data', []):
                pts = sigmet_to_decimal(s['mens'])
                if len(pts) >= 3:
                    folium.Polygon(locations=pts, color=get_sigmet_color(s['mens']), fill=True, fill_opacity=0.3, popup=s['mens']).add_to(m)
        except: pass

    # 4. Marcadores e Rota (No topo de tudo)
    COORDS = {"SBGR": [-23.432, -46.470], "SBGL": [-22.810, -43.250], "SBSP": [-23.626, -46.656],
              "SBRJ": [-22.910, -43.162], "SBRF": [-8.126, -34.923],  "SBKP": [-23.007, -47.134],
              "SBPA": [-29.994, -51.171], "SBCT": [-25.531, -49.175], "SBBR": [-15.869, -47.917], "SBBH": [-19.624, -43.898]}
    
    dados_missao = []
    for icao in list(dict.fromkeys([origem, destino, alternativa])):
        try:
            m_dat = requests.get(f"https://api-redemet.decea.mil.br/mensagens/metar/{icao}?api_key={api_key}").json()
            t_dat = requests.get(f"https://api-redemet.decea.mil.br/mensagens/taf/{icao}?api_key={api_key}").json()
            metar = m_dat['data']['data'][0]['mens']
            taf = t_dat['data']['data'][0]['mens']
            dados_missao.append({"ICAO": icao, "METAR": metar, "TAF": taf})
            
            cor = 'blue' if icao in [origem, destino] else 'purple'
            folium.Marker(COORDS[icao], popup=f"<b>{icao}</b>", icon=folium.Icon(color=cor, icon='plane', prefix='fa')).add_to(m)
        except: continue

    folium.PolyLine([COORDS[origem], COORDS[destino]], color="#00f2ff", weight=5).add_to(m)
    
    # Controles
    plugins.Fullscreen().add_to(m)
    folium.LayerControl(position='topright').add_to(m)

    st_folium(m, width="100%", height=600)

    # Detalhamento METAR/TAF
    st.subheader("🔍 Dados Meteorológicos da Rota")
    cols = st.columns(3)
    for i, dado in enumerate(dados_missao):
        if i < 3:
            with cols[i].expander(f"📍 {dado['ICAO']}", expanded=True):
                st.markdown("**METAR:**")
                st.code(dado['METAR'], language="fix")
                st.markdown("**TAF:**")
                st.code(dado['TAF'], language="fix")

@st.cache_resource(ttl=3600)
def carregar_dados_gfs(fl_alvo):
    try:
        pressao = NIVEIS_MAP.get(fl_alvo, 500)
        
        # URL atualizada com Vento e Temperatura
        url = f"https://api.open-meteo.com/v1/gfs?latitude=-15.78&longitude=-47.93&hourly=temperature_{pressao}hPa,windspeed_{pressao}hPa,winddirection_{pressao}hPa&forecast_days=1"
        
        r = requests.get(url)
        if r.status_code != 200:
            return None, "Erro na API"
            
        response = r.json()
        
        # Pegamos o primeiro índice da previsão (tempo atual)
        temp_atual = response['hourly'][f'temperature_{pressao}hPa'][0]
        wind_spd = response['hourly'][f'windspeed_{pressao}hPa'][0]
        wind_dir = response['hourly'][f'winddirection_{pressao}hPa'][0]
        
        dados_processados = {
            'temp_media_c': temp_atual,
            'wind_spd': wind_spd,
            'wind_dir': wind_dir,
            'rodada': "GFS via Open-Meteo (Real-time)"
        }
        return dados_processados, dados_processados['rodada']
    except Exception as e:
        return None, str(e)
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







