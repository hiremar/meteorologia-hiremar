"""Portal de Meteorologia Aeronáutica — Prof. Hiremar.

Este arquivo só monta a TELA. O trabalho pesado está na pasta "modulos":
cada assunto num arquivo (satélite, REDEMET, modelo GFS, desenho do mapa...).
"""
import html
from datetime import datetime, timezone
from pathlib import Path

import folium
from folium import plugins
import streamlit as st
import streamlit.components.v1 as components

from modulos import aerodromos as ad
from modulos import camadas_mapa as cm
from modulos import metar as mt
from modulos import modelo_gfs as gfs
from modulos import redemet as rd
from modulos import satelite as sat

st.set_page_config(layout="wide", page_title="Meteorologia Aeronáutica · Prof. Hiremar", page_icon="🛰️")

# Cores gerais ficam em .streamlit/config.toml. Aqui só os detalhes.
st.markdown("""
<style>
  h1, h2, h3 { color: #f1c40f !important; }
  h1 { font-size: 2rem !important; }            /* título da página menor (antes ~2.75rem) */
  .aviso { display:flex; align-items:center; gap:10px; margin:2px 0 12px;
           color:#ffb347; font-size:.85rem; line-height:1.35; }
  .aviso svg { flex:none; }
  .block-container { padding-top: 2.2rem; }
  .chips { display:flex; flex-wrap:wrap; gap:6px; margin:-4px 0 10px; }
  .chip { background:#13263a; border:1px solid #24445f; color:#c9d3dc; border-radius:999px;
          padding:2px 10px; font-size:.8rem; }
  .chip.alerta { border-color:#d99a00; color:#ffd666; }
  .msg { font-family: Consolas, 'Courier New', monospace; font-size:.9rem; line-height:1.45;
         white-space: pre-wrap; word-break: break-word;       /* quebra a linha: nada escondido */
         background:#06131e; color:#bdf5c4; border-left:3px solid #2e9e44;
         border-radius:4px; padding:8px 10px; margin:2px 0 10px; }
  .msg.taf { color:#cfe3ff; border-left-color:#3f6fd8; }
  .cartao-titulo { display:flex; align-items:center; gap:8px; font-weight:700; color:#f1c40f; }
  .cat-chip { font:700 11px/16px 'Segoe UI',Arial; padding:0 6px; border-radius:3px; }
  .rotulo { color:#9fb3c4; font-size:.8rem; margin-top:4px; }
</style>
""", unsafe_allow_html=True)

# Aviso fixo de "material de instrução": triângulo laranja com bordas arredondadas.
# É um desenho SVG: stroke-linejoin="round" é o que arredonda as pontas do triângulo.
def aviso_instrucao():
    st.markdown(
        '<div class="aviso">'
        '<svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="#ff9800" '
        'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>'
        '<line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>'
        '<span><b>Material de instrução.</b> Não substitui as fontes oficiais '
        '(REDEMET, AISWEB, NOTAM) nem o briefing meteorológico oficial. '
        'Não utilizar para planejamento ou decisão operacional real.</span>'
        '</div>', unsafe_allow_html=True)


# --- Chave da REDEMET (fica nos "Secrets" do Streamlit, nunca no código) ---
try:
    api_key = st.secrets["REDEMET_KEY"]
except Exception:            # sem arquivo de secrets (ex.: rodando no seu computador)
    api_key = None
if not api_key:
    api_key = st.sidebar.text_input("REDEMET API KEY", type="password")
if not api_key:
    st.error("⚠️ Informe a chave da API REDEMET para carregar os dados.")
    st.stop()


# ============================================================================
# CACHE: guarda o resultado por um tempo, para não refazer a cada clique
# ============================================================================
@st.cache_data(ttl=600, show_spinner=False)          # 10 min = intervalo de varredura do GOES
def goes(canal):
    return sat.carregar_overlay(canal)


@st.cache_data(ttl=300, show_spinner=False)          # 5 min
def metars_e_tafs(chave):
    metars, e1 = rd.ultima_por_localidade("metar", ad.LISTA_ICAO, chave)
    tafs, e2 = rd.ultima_por_localidade("taf", ad.LISTA_ICAO, chave)
    avisos, e3, diag = rd.avisos_aerodromo(ad.LISTA_ICAO, chave)
    return metars, tafs, avisos, diag, [e for e in (e1, e2, e3) if e]


@st.cache_data(ttl=300, show_spinner=False)
def lista_sigmets(chave):
    return rd.sigmets(chave)


@st.cache_data(ttl=300, show_spinner=False)          # 5 min: no máximo 1 consulta à REDEMET a cada 5 min
def raios(chave):
    return rd.descargas(chave)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=4)   # 1 h
def modelo(horas_a_frente, hora_cheia_utc):
    # 'hora_cheia_utc' só serve para renovar o cache quando muda a hora
    conteudo, info = gfs.baixar(horas_a_frente)
    return gfs.ler_grib(conteudo), info


def fmt_z(dt):
    return dt.strftime("%d/%m %H:%MZ") if dt else "?"


def mostrar_mapa(m, altura):
    """O mapa vai para a página como HTML pronto: arrastar e dar zoom NÃO
    recarregam o site (antes, cada interação podia reexecutar o script).
    Se um dia o Streamlit mudar esse recurso, cai no streamlit-folium."""
    try:
        components.html(m.get_root().render(), height=altura)
    except Exception:
        from streamlit_folium import st_folium
        st_folium(m, height=altura, use_container_width=True, returned_objects=[])


# ============================================================================
# MENU
# ============================================================================
st.sidebar.title("✈️ Meteorologia Aeronáutica")
aba = st.sidebar.radio("Ir para:", ["🛰️ Briefing em tempo real", "📺 Aulas e simuladores", "📚 Materiais e links", "👤 Sobre o professor"],
                       label_visibility="collapsed")

# ============================================================================
# ABA 1 — BRIEFING
# ============================================================================
if aba.startswith("🛰️"):
    # ---------------- barra lateral ----------------
    st.sidebar.subheader("📡 Camadas")
    ver_ir = st.sidebar.checkbox("Satélite infravermelho (GOES-19 canal 13)", value=True)
    ver_vis = st.sidebar.checkbox("Satélite visível (GOES-19 canal 2)", value=False,
                                  help="Só mostra nuvens durante o dia.")
    ver_sigmet = st.sidebar.checkbox("SIGMET", value=True)
    periodo_raios = st.sidebar.radio("Descargas atmosféricas (raios)",
                                     ["Só a última informação", "Últimos 60 min", "Não mostrar"])
    ver_raios = periodo_raios != "Não mostrar"      # True ou False, conforme a escolha
    ver_ads = st.sidebar.checkbox("Aeródromos das capitais", value=True)
    estilo = st.sidebar.radio("Mostrar aeródromos como", ["Etiquetas VFR/IFR (FAA)", "Bolinhas (cores REDEMET)"],
                              disabled=not ver_ads)
    estilo = "FAA" if estilo.startswith("Etiquetas") else "REDEMET"

    ver_modelo = st.sidebar.checkbox("Modelo GFS (vento, temperatura)", value=False)
    if ver_modelo:
        chave_var = st.sidebar.selectbox("Variável", list(gfs.VARIAVEIS),
                                         format_func=lambda k: gfs.VARIAVEIS[k]["nome"])
        # temperatura só existe nos níveis de pressão (a de superfície fica para depois)
        niveis = [r for r, (tipo, _) in gfs.NIVEIS.items()
                  if tipo == "iso" or gfs.VARIAVEIS[chave_var]["tipo"] == "vetor"]
        rotulo_nivel = st.sidebar.selectbox("Nível", niveis, index=niveis.index("FL180 · 500 hPa"))
        horas = st.sidebar.select_slider("Validade", options=[0, 3, 6, 9, 12, 18, 24],
                                         format_func=lambda h: "agora" if h == 0 else f"+{h} h")

    with st.sidebar.expander("🗺️ Cartas ENRC (DECEA)"):
        cartas = (st.multiselect("Cartas de baixa (L)", [f"L{i}" for i in range(1, 10)]) +
                  st.multiselect("Cartas de alta (H)", [f"H{i}" for i in range(1, 10)]))

    # Planejamento: só aparece quando o usuário clicar em "Planejar voo"
    st.sidebar.subheader("📍 Planejamento de voo")
    with st.sidebar.form("planejamento"):
        opcoes = ad.LISTA_ICAO
        origem = st.selectbox("Origem", opcoes, index=None, placeholder="Escolha...", format_func=ad.rotulo)
        destino = st.selectbox("Destino", opcoes, index=None, placeholder="Escolha...", format_func=ad.rotulo)
        altn = st.selectbox("Alternativa (opcional)", opcoes, index=None, placeholder="Escolha...",
                            format_func=ad.rotulo)
        planejar = st.form_submit_button("✈️ Planejar voo", type="primary")
    if planejar:
        if origem and destino:
            st.session_state["plano"] = [origem, destino, altn]
        else:
            st.sidebar.warning("Escolha pelo menos origem e destino.")
    if st.session_state.get("plano") and st.sidebar.button("Limpar planejamento"):
        del st.session_state["plano"]
        st.rerun()
    plano = st.session_state.get("plano")

    # ---------------- título ----------------
    if plano:
        st.title(f"🛰️ Briefing: {plano[0]} ✈️ {plano[1]}" + (f"  (altn {plano[2]})" if plano[2] else ""))
    else:
        st.title("🛰️ Briefing operacional")
    aviso_instrucao()

    avisos, chips = [], []

    # ---------------- mapa ----------------
    m = folium.Map(location=[-15.0, -55.0], zoom_start=4, tiles=None, control_scale=True)
    m.get_root().header.add_child(folium.Element(cm.CSS_MAPA))
    cm.adicionar_mapas_fundo(m)

    for carta in cartas:
        folium.WmsTileLayer(url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms", layers=f"ICA:ENRC_{carta}",
                            fmt="image/png", transparent=True, name=f"Carta {carta}", overlay=True).add_to(m)

    with st.spinner("Carregando satélite, mensagens e modelo..."):
        for canal, ligado, nome in (("IR", ver_ir, "GOES-19 IR (canal 13)"), ("VIS", ver_vis, "GOES-19 visível (canal 2)")):
            if not ligado:
                continue
            try:
                url_img, limites, instante = goes(canal)
                folium.raster_layers.ImageOverlay(url_img, bounds=limites, opacity=0.85 if canal == "IR" else 0.95,
                                                  name=f"{nome} {fmt_z(instante)}", interactive=False,
                                                  pixelated=False).add_to(m)   # False = navegador suaviza no zoom
                idade = int((datetime.now(timezone.utc) - instante).total_seconds() // 60)
                chips.append((f"{nome}: {fmt_z(instante)} (há {idade} min)", idade > 30))
            except Exception as e:
                avisos.append(f"{nome} indisponível agora ({e}).")

        if ver_modelo:
            try:
                hora_cheia = datetime.now(timezone.utc).strftime("%Y%m%d%H")
                dados, info = modelo(horas, hora_cheia)
                var = gfs.VARIAVEIS[chave_var]
                grade = gfs.grade_para_mapa(dados, rotulo_nivel, chave_var)
                titulo = f"{var['nome'].split(' (')[0]} {rotulo_nivel.split(' · ')[0]}"
                cm.CamadaModelo(grade, chave_var, var["tipo"], var["unidade"], titulo,
                                name=f"GFS {titulo}").add_to(m)
                chips.append((f"GFS {info['run']:%d/%H}Z +{info['fhora']}h → válido {fmt_z(info['valido'])}", False))
            except Exception as e:
                avisos.append(f"Modelo GFS indisponível agora ({e}).")

        nao_desenhados = []
        if ver_sigmet:
            textos, erro = lista_sigmets(api_key)
            if erro:
                avisos.append(erro)
            else:
                nao_desenhados = cm.adicionar_sigmets(m, textos)
                chips.append((f"{len(textos)} SIGMET vigente(s)", False))

        if ver_raios:
            quadros, erro = raios(api_key)
            if erro:
                avisos.append(erro)
            else:
                if periodo_raios.startswith("Só") and quadros:
                    mais_novo = max(inst for inst, _ in quadros)
                    quadros = [(inst, pts) for inst, pts in quadros if inst == mais_novo]
                agora = datetime.now(timezone.utc)
                pontos = rd.pontos_por_idade(quadros, agora)
                cm.CamadaRaios(pontos).add_to(m)
                cm.Legenda(cm.legenda_raios(), "bottomleft").add_to(m)
                if quadros:
                    ultimo = max(inst for inst, _ in quadros)
                    idade = int((agora - ultimo).total_seconds() // 60)
                    chips.append((f"Raios: {len(pontos)} ponto(s), último {fmt_z(ultimo)} (há {idade} min)",
                                  idade > 20))
                else:
                    chips.append(("Raios: nenhuma descarga informada", False))

        metars, tafs, avisos_ad, diag_ad, erros = metars_e_tafs(api_key)
        avisos += erros
        if ver_ads:
            cm.adicionar_aerodromos(m, metars, tafs, estilo, avisos_ad)
            no_mapa = sorted(i for i in avisos_ad if i in ad.LISTA_ICAO)   # só os que aparecem no mapa
            if no_mapa:
                chips.append((f"⚠ Aviso de aeródromo: {', '.join(no_mapa)}", True))
            cm.Legenda(cm.legenda_categorias(estilo), "bottomright").add_to(m)

    if plano:
        pts = [ad.COORDS[plano[0]], ad.COORDS[plano[1]]]
        folium.PolyLine(pts, color="#00f2ff", weight=4, opacity=0.9, tooltip="Rota").add_to(m)
        if plano[2]:
            folium.PolyLine([ad.COORDS[plano[1]], ad.COORDS[plano[2]]], color="#c77dff", weight=3,
                            dash_array="6 6", tooltip="Para a alternativa").add_to(m)
        m.fit_bounds([ad.COORDS[i] for i in plano if i], padding=(60, 60))

    plugins.Fullscreen().add_to(m)
    folium.LayerControl(position="topright", collapsed=True).add_to(m)

    # Linha de "chips" com a situação de cada fonte + avisos visíveis
    st.markdown("<div class='chips'>" + "".join(
        f"<span class='chip{' alerta' if alerta else ''}'>{html.escape(t)}</span>" for t, alerta in chips) +
        "</div>", unsafe_allow_html=True)
    for a in avisos:
        st.warning(a, icon="⚠️")

    mostrar_mapa(m, altura=640)
    st.caption("Passe o mouse sobre um aeródromo para ver METAR e TAF. Use o botão de camadas "
               "(canto superior direito) para ligar e desligar camadas e trocar o mapa de fundo.")

    # Diagnóstico (só aparece se o endereço terminar com ?diag=1): mostra tudo que a REDEMET
    # devolveu nos avisos de aeródromo e o que o site fez com cada mensagem.
    if st.query_params.get("diag"):
        with st.expander(f"🔧 Diagnóstico · avisos de aeródromo ({len(diag_ad)} mensagem(ns) recebida(s))"):
            if not diag_ad:
                st.write("A REDEMET não devolveu nenhuma mensagem de aviso de aeródromo.")
            for situacao, ids, texto in sorted(diag_ad, key=lambda x: x[0]):
                st.markdown(f"<div class='msg'><b>{html.escape(situacao)}</b> · localidade(s) na resposta: "
                            f"{html.escape(', '.join(ids))}<br>{html.escape(texto)}</div>", unsafe_allow_html=True)

    if nao_desenhados:
        with st.expander(f"SIGMET sem polígono desenhável ({len(nao_desenhados)})"):
            for t in nao_desenhados:
                st.markdown(f"<div class='msg'>{html.escape(t)}</div>", unsafe_allow_html=True)

    # ---------------- METAR / TAF da rota ----------------
    if plano:
        st.subheader("🔍 Dados meteorológicos da rota")
        papeis = ["Origem", "Destino", "Alternativa"]
        cols = st.columns(3)
        for col, papel, icao in zip(cols, papeis, plano):
            if not icao:
                continue
            metar = (metars.get(icao) or {}).get("mens", "")
            taf = (tafs.get(icao) or {}).get("mens", "")
            info = mt.analisar(metar) if metar else None
            cat = info["faa"] if info else "ND"
            texto, fundo, cor = mt.CATEGORIAS_FAA[cat]
            idade = f" · há {info['idade_min']} min" if info and info["idade_min"] is not None else ""
            with col:
                st.markdown(
                    f"<div class='cartao-titulo'>{papel}: {icao}"
                    f"<span class='cat-chip' style='background:{fundo};color:{cor}'>{texto}</span></div>"
                    f"<div class='rotulo'>{html.escape(ad.NOMES.get(icao, ''))}{idade}</div>"
                    + "".join(f"<div class='rotulo' style='color:#ffd666'>⚠ AVISO DE AERÓDROMO</div>"
                              f"<div class='msg' style='border-left-color:#ffbe00;color:#ffe9a8'>"
                              f"{html.escape(' · '.join(rd.decodificar_aviso(a)))}</div>"
                              for a in avisos_ad.get(icao, [])) +
                    f"<div class='rotulo'>METAR</div><div class='msg'>{html.escape(metar or 'não disponível')}</div>"
                    f"<div class='rotulo'>TAF</div><div class='msg taf'>"
                    f"{html.escape(mt.formatar_taf(taf) if taf else 'não disponível')}</div>",
                    unsafe_allow_html=True)
    else:
        st.info("Escolha origem, destino e alternativa na barra lateral e clique em **Planejar voo** "
                "para ver a rota e os METAR/TAF completos aqui embaixo.", icon="🧭")

# ============================================================================
# ABA 2 — AULAS E SIMULADORES
# ============================================================================
elif aba.startswith("📺"):
    st.title("📺 Centro de treinamento")
    aviso_instrucao()
    st.subheader("Aulas em vídeo")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Aula 1: Altimetria — ajustes QNH / QNE**")
        st.video("https://www.youtube.com/watch?v=Y_91K9CBaRg")
    with c2:
        st.markdown("**Aula 2: Satélite, SIGMET e gelo**")
        st.video("https://www.youtube.com/watch?v=KoyZS3iCeM0")

    st.subheader("Simuladores interativos")
    pasta = Path(__file__).parent / "simuladores"
    arquivos = sorted(pasta.glob("*.html"))
    if arquivos:
        escolhido = st.selectbox("Escolha o simulador", arquivos, format_func=lambda p: p.stem.replace("_", " "))
        components.html(escolhido.read_text(encoding="utf-8"), height=820, scrolling=True)
    else:
        st.info("Em breve. Para publicar um simulador, coloque o arquivo .html na pasta "
                "'simuladores' do repositório: ele aparece aqui automaticamente.", icon="🧪")

# ============================================================================
# ABA 4 — SOBRE O PROFESSOR (currículo em formato de perfil; texto em modulos/sobre.py)
# ============================================================================
elif aba.startswith("👤"):
    from modulos.sobre import mostrar_sobre
    mostrar_sobre()

# ============================================================================
# ABA 3 — MATERIAIS
# ============================================================================
else:
    st.title("📚 Biblioteca digital")
    aviso_instrucao()
    st.markdown("""
### 📖 Manuais oficiais
- [ICA 105-15/2025 (Manual de Estação Meteorológica de Superfície)](https://publicacoes.decea.mil.br/publicacao/ica-105-15)
- [ICA 105-16/2025 (Códigos Meteorológicos)](https://publicacoes.decea.mil.br/publicacao/ica-105-16)
- [ICA 105-17/2025 (Manual de Centros Meteorológicos)](https://publicacoes.decea.mil.br/publicacao/ica-105-17)
### 🔗 Links úteis
- [REDEMET](https://redemet.decea.mil.br/)
- [AISWEB](https://aisweb.decea.mil.br/)
- [Aviation Weather Center](https://aviationweather.gov/)
### 🛰️ Fontes de dados deste site
- Satélite: NOAA GOES-19 (canais 13 e 2), processado por este site
- Modelo: NOAA GFS 0,25° (servidor NOMADS)
- METAR, TAF e SIGMET: API REDEMET (DECEA)
- Mapas de fundo: Esri, OpenStreetMap, OpenTopoMap
""")
