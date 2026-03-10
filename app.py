import streamlit as st
import folium
import requests
import re
import pandas as pd
from streamlit_folium import st_folium
from datetime import datetime

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(layout="wide", page_title="Portal Prof. Hiremar - Master Met")

# --- INJEÇÃO DE ESTILO (CSS BASEADO NO SEU SIMULADOR) ---
st.markdown(f"""
    <style>
        /* Fundo principal e containers */
        .stApp {{
            background-color: #0b1a27;
            color: #ffffff;
        }}
        
        /* Sidebar customizada */
        [data-testid="stSidebar"] {{
            background-color: #1e1e1e;
            border-right: 2px solid #00f2ff;
        }}

        /* Títulos e Subtítulos */
        h1, h2, h3, .stMarkdown p {{
            color: #ffffff;
            font-family: 'Segoe UI', sans-serif;
        }}

        /* Estilização de Expander e Cards */
        .streamlit-expanderHeader {{
            background-color: #1e1e1e !important;
            border: 1px solid #00f2ff !important;
            color: #00f2ff !important;
            border-radius: 8px;
        }}

        /* Botões */
        .stButton>button {{
            width: 100%;
            background-color: #00f2ff;
            color: #0b1a27;
            font-weight: bold;
            border-radius: 8px;
            border: none;
            transition: 0.3s;
        }}
        .stButton>button:hover {{
            background-color: #f1c40f;
            transform: scale(1.02);
        }}

        /* Input de Texto (API Key) */
        input {{
            background-color: #1e1e1e !important;
            color: #00f2ff !important;
            border: 1px solid #00f2ff !important;
        }}
    </style>
""", unsafe_allow_html=True)

# --- SEGURANÇA DA API ---
if "REDEMET_KEY" in st.secrets:
    api_key = st.secrets["REDEMET_KEY"]
else:
    api_key = st.sidebar.text_input("REDEMET API KEY", type="password", help="Insira sua chave da REDEMET")

if not api_key:
    st.warning("⚠️ Aguardando API KEY para carregar dados operacionais...")
    # st.stop() # Comentei o stop para você conseguir ver o layout mesmo sem a chave agora

# --- MENU LATERAL ---
with st.sidebar:
    st.image("https://raw.githubusercontent.com/hiremar/meteorologia/main/logohiremar.jpg", width=150) # Link exemplo para sua logo
    st.title("🚀 Master Met")
    aba = st.radio("Módulos:", ["🛰️ Briefing Real-Time", "🎮 Simulador & Quiz", "📺 Videoaulas", "📚 Biblioteca"])
    st.divider()
    st.info("Instrutor: Prof. Me. Hiremar Soares")

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
if aba == "🛰️ Briefing Real-Time":
    st.title("🛰️ Centro de Operações Meteorológicas")
    
    col_map, col_info = st.columns([3, 1])
    
    with col_info:
        st.subheader("📍 Rota")
        lista_ads = ["SBGR", "SBSP", "SBKP", "SBGL", "SBRJ", "SBRF", "SBPA", "SBCT", "SBBR", "SBBH"]
        origem = st.selectbox("Origem", lista_ads, index=0)
        destino = st.selectbox("Destino", lista_ads, index=8)
        
        st.subheader("📡 Camadas")
        show_tsc = st.checkbox("Satélite (GOES-16)", value=True)
        show_sigmet = st.checkbox("Avisos SIGMET", value=True)

    with col_map:
        m = folium.Map(location=[-15.0, -48.0], zoom_start=4, tiles='CartoDB dark_matter')
        
        if show_tsc:
            folium.WmsTileLayer(
                url="https://redemet.decea.mil.br/geoserver/wms",
                layers="satelite:goes16_ch13_realce",
                fmt="image/png", transparent=True, name="Nuvens", overlay=True
            ).add_to(m)

        # Logica de marcadores (Simplificada para o exemplo)
        COORDS = {"SBGR": [-23.432, -46.470], "SBBR": [-15.869, -47.917]}
        if origem in COORDS and destino in COORDS:
            folium.Marker(COORDS[origem], popup=origem, icon=folium.Icon(color='blue')).add_to(m)
            folium.Marker(COORDS[destino], popup=destino, icon=folium.Icon(color='green')).add_to(m)
            folium.PolyLine([COORDS[origem], COORDS[destino]], color="#00f2ff", weight=3).add_to(m)

        st_folium(m, width="100%", height=500)

# --- SEÇÃO 2: SIMULADOR & QUIZ ---
elif aba == "🎮 Simulador & Quiz":
    st.title("🎮 Avaliação Técnica: Massas de Ar & Frentes")
    
    # Simulação do Quiz do seu HTML
    questions = [
        {"q": "Qual o símbolo de uma frente oclusa?", "options": ["Triângulos azuis", "Semicírculos vermelhos", "Triângulos e Semicírculos roxos", "Linha alternada"], "correct": 2},
        {"q": "Ciclones Tropicais possuem núcleo de qual tipo?", "options": ["Núcleo Frio", "Núcleo Quente", "Núcleo Estacionário", "Núcleo Ocluso"], "correct": 1}
    ]
    
    score = 0
    for i, item in enumerate(questions):
        st.subheader(f"Questão {i+1}: {item['q']}")
        res = st.radio(f"Selecione a opção para a Q{i+1}:", item['options'], key=f"q{i}")
        if res == item['options'][item['correct']]:
            score += 1
            
    if st.button("Finalizar Avaliação"):
        st.balloons()
        nota = (score / len(questions)) * 100
        st.success(f"Avaliação Concluída! Nota: {nota}%")

# --- SEÇÃO 3: VÍDEOS ---
elif aba == "📺 Videoaulas":
    st.title("📺 MasterClass Meteorologia")
    c1, c2 = st.columns(2)
    with c1:
        st.video("https://www.youtube.com/watch?v=dQw4w9WgXcQ") # Substitua pelos seus
        st.caption("Aula 01 - Circulação Geral da Atmosfera")
    with c2:
        st.video("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        st.caption("Aula 02 - Termodinâmica e Estabilidade")

# --- SEÇÃO 4: MATERIAIS ---
elif aba == "📚 Biblioteca":
    st.title("📚 Materiais de Apoio")
    st.markdown("""
    * [📘] **Manual de Meteorologia do Comando da Aeronáutica**
    * [📗] **Slides: Interpretação de Cartas SIGWX**
    * [📂] **Pasta de Exercícios - Anhembi Morumbi**
    """)


