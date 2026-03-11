import streamlit as st
import folium
import requests
import re
import os
from streamlit_folium import st_folium
from datetime import datetime
from folium import plugins

# --- CONFIGURAÇÃO DA PÁGINA ---
st.set_page_config(layout="wide", page_title="Briefing Meteorológico Prof. Hiremar")

# --- ESTILO CSS PARA O MAPA ---
st.markdown("""
    <style>
    .main .block-container { padding-top: 1rem; }
    iframe { border-radius: 10px; }
    </style>
    """, unsafe_allow_name_allowed=True)

# --- BARRA LATERAL (PAINEL DE CONTROLE) ---
st.sidebar.title("🛠️ Painel de Controle")
api_key = st.sidebar.text_input("REDEMET API KEY", value="tyZcJePk7Y5v7QZGbqXiDQwHaGQFli9J5HfQh15f", type="password")

st.sidebar.subheader("📍 Planejamento de Voo")
lista_ads = ["SBGR", "SBSP", "SBKP", "SBGL", "SBRJ", "SBRF", "SBPA", "SBCT", "SBBR", "SBBH"]
origem = st.sidebar.selectbox("Origem", lista_ads, index=0)
destino = st.sidebar.selectbox("Destino", lista_ads, index=8)
alternativa = st.sidebar.selectbox("Alternativa", lista_ads, index=9)

st.sidebar.subheader("📡 Camadas Meteorológicas")
show_tsc = st.sidebar.checkbox("Exibir Satélite / TSC", value=True)
show_sigmet = st.sidebar.checkbox("Exibir SIGMETs", value=True)

# --- CONFIGURAÇÕES DE CARTAS ENRC ---
# Links extraídos do arquivo Cartas AIS.txt 
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

COORDS = {
    "SBGR": [-23.432, -46.470], "SBGL": [-22.810, -43.250], "SBSP": [-23.626, -46.656],
    "SBRJ": [-22.910, -43.162], "SBRF": [-8.126, -34.923],  "SBKP": [-23.007, -47.134],
    "SBPA": [-29.994, -51.171], "SBCT": [-25.531, -49.175], "SBBR": [-15.869, -47.917],
    "SBBH": [-19.624, -43.898]
}
OUTROS_ADS = ["SBGL", "SBRJ", "SBRF", "SBKP", "SBPA", "SBCT"]

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

# --- TÍTULO PRINCIPAL ---
st.title(f"🛰️ Briefing Operacional: {origem} ✈️ {destino}")

# --- CONSTRUÇÃO DO MAPA ---
m = folium.Map(location=[-15.0, -48.0], zoom_start=5, tiles=None)

# 1. Mapas de Fundo
folium.TileLayer('CartoDB dark_matter', name="Mapa Escuro (Noite)", control=True).add_to(m)
folium.TileLayer('OpenStreetMap', name="Mapa Geográfico", control=True).add_to(m)
folium.TileLayer(
    tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attr='Esri Satellite', name='Satélite (Google Earth)', control=True
).add_to(m)

# 2. Satélite / TSC (Camada Dinâmica REDEMET)
if show_tsc:
    folium.WmsTileLayer(
        url="https://redemet.decea.mil.br/geoserver/wms",
        layers="satelite:goes16_ch13_realce",
        fmt="image/png", transparent=True, name="Nuvens / TSC",
        overlay=True, control=True
    ).add_to(m)

# 3. SIGMETs
if show_sigmet:
    try:
        s_res = requests.get(f"https://api-redemet.decea.mil.br/mensagens/sigmet?api_key={api_key}").json()
        for s in s_res.get('data', {}).get('data', []):
            pts = sigmet_to_decimal(s['mens'])
            if len(pts) >= 3:
                folium.Polygon(
                    locations=pts, color=get_sigmet_color(s['mens']),
                    fill=True, fill_opacity=0.3, popup=s['mens'], name="⚠️ SIGMET"
                ).add_to(m)
    except: pass

# 4. Agrupamento de Cartas ENRC (L e H) 
lista_baixa = []
for label, layer_id in LINKS_BAIXA.items():
    lyr = folium.WmsTileLayer(
        url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
        layers=layer_id.replace("%3A", ":"),
        fmt="image/png", transparent=True, name=f"Carta {label}",
        overlay=True, control=True, show=False, attr="DECEA"
    ).add_to(m)
    lista_baixa.append(lyr)

lista_alta = []
for label, layer_id in LINKS_ALTA.items():
    lyr = folium.WmsTileLayer(
        url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms",
        layers=layer_id.replace("%3A", ":"),
        fmt="image/png", transparent=True, name=f"Carta {label}",
        overlay=True, control=True, show=False, attr="DECEA"
    ).add_to(m)
    lista_alta.append(lyr)

# 5. Adicionando o Controle de Grupos Colapsáveis
plugins.GroupedLayerControl(
    groups={
        "📉 CARTAS BAIXA (ENRC L)": lista_baixa,
        "📈 CARTAS ALTA (ENRC H)": lista_alta
    },
    exclusive_groups=False,
    collapsed=True,
    position='topright'
).add_to(m)

# 6. Aeródromos e Rota
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
        folium.Marker(COORDS[icao], popup=f"<b>{icao}</b><br>{metar}", 
                      icon=folium.Icon(color=cor, icon='plane', prefix='fa')).add_to(m)
    except: continue

folium.PolyLine([COORDS[origem], COORDS[destino]], color="cyan", weight=4, opacity=0.8, dash_array='10').add_to(m)

# 7. Extras do Mapa
plugins.Fullscreen().add_to(m)
plugins.MeasureControl(position='topleft', primary_length_unit='nm').add_to(m)
folium.LayerControl(position='topright', collapsed=True).add_to(m)

# Renderização do Mapa no Streamlit
st_folium(m, width=1400, height=650)

# --- CARDS DE DETALHAMENTO ---
st.divider()
st.subheader("🔍 Detalhamento Meteorológico (METAR/TAF)")
if dados_missao:
    ordem = {origem: 0, destino: 1, alternativa: 2}
    dados_ordenados = sorted(dados_missao, key=lambda x: ordem.get(x['ICAO'], 99))
    cols = st.columns(3)
    for idx, dado in enumerate(dados_ordenados):
        tipo = "SAÍDA" if dado['ICAO'] == origem else ("DESTINO" if dado['ICAO'] == destino else "ALTERNATIVA")
        with cols[idx].expander(f"✈️ {dado['ICAO']} - {tipo}", expanded=True):
            st.write("**METAR:**")
            st.code(dado['METAR'], language="fix")
            st.write("**TAF:**")
            st.code(dado['TAF'], language="fix")



