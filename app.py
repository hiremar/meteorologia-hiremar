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

# --- BLOCO GFS (NOVO) ---
NIVEIS_MAP = {
    "SFC": 1013, "FL050": 850, "FL080": 750, "FL100": 700, 
    "FL120": 650, "FL140": 600, "FL180": 500, "FL220": 450, 
    "FL240": 400, "FL260": 350, "FL300": 300, "FL340": 250, 
    "FL360": 225, "FL410": 200
}

@st.cache_data(ttl=43200)
def carregar_dados_gfs():
    try:
        # Busca a análise mais recente disponível
        H = Herbie(model="gfs", product="pgrb2.0p25", fxx=0)
        ds = H.xarray(":(UGRD|VGRD|TMP|RH):")
        return ds
    except Exception as e:
        return None

# --- MENU LATERAL ---
st.sidebar.title("✈️ Menu de Navegação")
# Adicionada a aba do GFS aqui:
aba = st.sidebar.radio("Ir para:", ["🛰️ Briefing em Tempo Real", "🚀 Previsão GFS & Gelo", "📺 Aulas em Vídeo", "📚 Materiais e Links"])

if aba == "🛰️ Briefing em Tempo Real":
    # (Mantém todo o seu código original de briefing aqui...)
    st.sidebar.subheader("📍 Planejamento de Voo")
    lista_ads = ["SBGR", "SBSP", "SBKP", "SBGL", "SBRJ", "SBRF", "SBPA", "SBCT", "SBBR", "SBBH"]
    origem = st.sidebar.selectbox("Origem", lista_ads, index=0)
    destino = st.sidebar.selectbox("Destino", lista_ads, index=8)
    alternativa = st.sidebar.selectbox("Alternativa", lista_ads, index=9)
    # ... Restante do código do Briefing ...
    st.title(f"🛰️ Briefing Operacional: {origem} ✈️ {destino}")
    m = folium.Map(location=[-15.0, -48.0], zoom_start=5, tiles='CartoDB dark_matter')
    st_folium(m, width="100%", height=600)

elif aba == "🚀 Previsão GFS & Gelo":
    st.title("🚀 Previsão Numérica GFS e Análise de Gelo")
    st.write("Processando dados do modelo global da NOAA (Ciclo 12h) para análise de vento e gelo (AC 91-74B).")
    
    fl_alvo = st.sidebar.selectbox("Selecione o Nível de Voo (FL):", list(NIVEIS_MAP.keys()))
    pressao = NIVEIS_MAP[fl_alvo]

    with st.spinner("Buscando dados no servidor da NOAA..."):
        ds = carregar_dados_gfs()
        if ds:
            st.success(f"Dados do GFS carregados com sucesso para o {fl_alvo}!")
            # Aqui no futuro desenharemos as camadas de vento e gelo
            m_gfs = folium.Map(location=[-15.0, -48.0], zoom_start=4, tiles='CartoDB dark_matter')
            
            if fl_alvo in ["FL120", "FL140", "FL180", "FL220", "FL240"]:
                st.warning("⚠️ Atenção: Nível selecionado dentro da faixa crítica de gelo severo no Brasil.")
            
            st_folium(m_gfs, width="100%", height=600)
        else:
            st.error("Servidor NOAA temporariamente indisponível.")

elif aba == "📺 Aulas em Vídeo":
    # (Seu código original de aulas...)
    st.title("📺 Centro de Treinamento")
    st.video("https://www.youtube.com/watch?v=Y_91K9CBaRg")

elif aba == "📚 Materiais e Links":
    # (Seu código original de links...)
    st.title("📚 Biblioteca Digital")
    st.markdown("- [ICA 105-15/2025](https://publicacoes.decea.mil.br/publicacao/ica-105-15)")
