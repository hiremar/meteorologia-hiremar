"""Portal de Meteorologia Aeronáutica — Prof. Hiremar.

Este arquivo só monta a TELA. O trabalho pesado está na pasta "modulos":
cada assunto num arquivo (satélite, REDEMET, modelo GFS, desenho do mapa...).
"""
import html
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import folium
from folium import plugins
import streamlit as st
import streamlit.components.v1 as components

from modulos import aerodromos as ad
from modulos import camadas_mapa as cm
from modulos import metar as mt
from modulos import modelo_gfs as gfs
from modulos import planejamento as pl
from modulos import redemet as rd
from modulos import rota as rt_mod
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


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def camada_sigwx(png):
    """Carta SIGWX (imagem) -> camada transparente encaixada no mapa (modulos/sigwx_mapa.py)."""
    from modulos import sigwx_mapa
    return sigwx_mapa.preparar_camada(png)


@st.cache_data(ttl=600, show_spinner=False, max_entries=6)
def goes_rota(canal, regiao, arquivo):
    """Recorte em alta resolução (~2 km) em volta da rota, do MESMO arquivo da imagem geral."""
    return sat.carregar_overlay(canal, regiao, arquivo)


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


@st.cache_data(ttl=86400, show_spinner=False)        # 1 dia: aerovia só muda na emenda AIRAC
def segmentos_aerovias(nivel):
    """Todos os segmentos de aerovia de 'alta' ou 'baixa' (GEOAISWEB, modulos/aerovias.py).
    Se o download falhar, o erro "sobe" e o Streamlit NÃO guarda no cache (tenta de novo depois)."""
    from modulos import aerovias as av
    return av.baixar(nivel)


def rede_aerovias():
    """Junta alta + baixa numa rede só: (fixos, aerovias, erros)."""
    from modulos import aerovias as av
    segs, erros = [], []
    for nivel in ("alta", "baixa"):
        try:
            segs += segmentos_aerovias(nivel)
        except Exception as e:
            erros.append(f"aerovias de {nivel} indisponíveis no GEOAISWEB agora ({type(e).__name__})")
    fixos, aerovias = av.montar_rede(segs)
    return fixos, aerovias, erros


# Cartas do GeoAISWEB: { nome da camada no servidor: texto no menu }.
# Para acrescentar uma WAC, copie o nome exato da lista do GeoAISWEB (ex.: WAC_3262_SAO_PAULO).
WACS = ["WAC_3140_BRASILIA", "WAC_3141_SALVADOR", "WAC_3189_BELO_HORIZONTE", "WAC_3190_GOIANIA",
        "WAC_3191_RONDONOPOLIS", "WAC_3192_CORUMBA", "WAC_3260_BELA_VISTA", "WAC_3261_CAMPO_GRANDE",
        "WAC_3262_SAO_PAULO", "WAC_3263_RIO_DE_JANEIRO", "WAC_3313_CURITIBA", "WAC_3314_FOZ_DO_IGUACU",
        "WAC_3383_URUGUAIANA", "WAC_3384_PORTO_ALEGRE", "WAC_3434_RIO_DA_PRATA"]


# Guia em PDF de como usar o planejamento de voo (fica na pasta "materiais" do repositório)
GUIA_PLANEJAMENTO = Path(__file__).parent / "materiais" / "Guia_Planejamento_de_Voo.pdf"


def botao_guia(onde, rotulo="📘 Como planejar (guia em PDF)"):
    """Botão discreto para baixar o guia. 'onde' = a barra lateral, uma aba, a página..."""
    if GUIA_PLANEJAMENTO.exists():
        onde.download_button(rotulo, GUIA_PLANEJAMENTO.read_bytes(), GUIA_PLANEJAMENTO.name,
                             "application/pdf", use_container_width=True)


def nome_wac(w):
    """'WAC_3262_SAO_PAULO' -> 'WAC 3262 · Sao Paulo'  (texto mostrado no menu e no mapa)"""
    return "WAC " + w[4:8] + " · " + w[9:].replace("_", " ").title()


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
    # Cada grupo fica numa "aba" que abre e fecha (st.sidebar.expander). Tudo que está
    # dentro do "with" vai para dentro da aba; fechada, a barra lateral fica limpa.
    # (os valores marcados continuam valendo mesmo com a aba fechada)
    st.sidebar.subheader("📡 Camadas")
    with st.sidebar.expander("🛰️ Satélite"):
        ver_ir = st.checkbox("Infravermelho (GOES-19 canal 13)", value=True)
        relevo_ir = st.checkbox("Relevo 3D no infravermelho", value=False, disabled=not ver_ir,
                                help="Sombreia os topos das nuvens como um relevo (nuvem mais fria = mais alta). "
                                     "Bom para comparar com a versão plana em aula.")
        ver_vis = st.checkbox("Visível em cores reais (GOES-19 canais 1, 2 e 3)", value=False,
                              help="Como o olho veria do espaço. Só de dia: à noite fica transparente.")

    with st.sidebar.expander("⚡ SIGMET e raios"):
        ver_sigmet = st.checkbox("SIGMET", value=True)
        periodo_raios = st.radio("Descargas atmosféricas (raios)",
                                 ["Só a última informação", "Últimos 60 min", "Não mostrar"])
        ver_raios = periodo_raios != "Não mostrar"      # True ou False, conforme a escolha

    with st.sidebar.expander("✈️ Aeródromos"):
        ver_ads = st.checkbox("Mostrar aeródromos", value=True)
        estilo = st.radio("Mostrar como", ["Etiquetas VFR/IFR (FAA)", "Bolinhas (cores REDEMET)"],
                          disabled=not ver_ads)
        estilo = "FAA" if estilo.startswith("Etiquetas") else "REDEMET"

    # Cartas METEOROLÓGICAS: SIGWX no mapa + vento/temperatura do modelo GFS
    with st.sidebar.expander("🌦️ Cartas meteorológicas"):
        ver_sigwx = st.checkbox("SIGWX SFC/FL250 (CIMAER)", value=False,
                                help="A carta de tempo significativo encaixada no mapa. Com voo planejado, "
                                     "vem a da validade do voo (Doc 8896: ±3 h); sem voo, a mais próxima de agora.")
        st.markdown("**Vento e temperatura (modelo GFS)**")
        ver_modelo = st.checkbox("Mostrar no mapa", value=False)
        if ver_modelo:
            chave_var = st.selectbox("Variável", list(gfs.VARIAVEIS),
                                     format_func=lambda k: gfs.VARIAVEIS[k]["nome"])
            # temperatura só existe nos níveis de pressão (a de superfície fica para depois)
            niveis = [r for r, (tipo, _) in gfs.NIVEIS.items()
                      if tipo == "iso" or gfs.VARIAVEIS[chave_var]["tipo"] == "vetor"]
            rotulo_nivel = st.selectbox("Nível", niveis, index=niveis.index("FL180 · 500 hPa"))
            horas = st.select_slider("Validade", options=[0, 3, 6, 9, 12, 18, 24],
                                     format_func=lambda h: "agora" if h == 0 else f"+{h} h")

    # Cartas AERONÁUTICAS do GeoAISWEB (DECEA). Aqui entram depois SID, STAR, IAC...
    with st.sidebar.expander("🗺️ Cartas aeronáuticas (DECEA)"):
        # Baixa e alta cobrem a MESMA área, então é uma OU outra (radio = escolha única).
        enrc = st.radio("Cartas de rota ENRC", ["Nenhuma", "Todas de baixa (L1–L9)", "Todas de alta (H1–H9)"])
        # WACs vizinhas não se sobrepõem: pode escolher várias (ex.: São Paulo + Rio).
        wacs = st.multiselect("Cartas visuais WAC", WACS, format_func=nome_wac,
                              help="A WAC fica por cima da ENRC na área dela.")
        ver_aerovias = st.checkbox("Aerovias perto da rota (traço do DECEA)", value=True,
                                   help="Com voo planejado: as aerovias em volta da rota, desenhadas a partir "
                                        "dos dados do GEOAISWEB. Alta (FL245 ou acima) ou baixa, conforme o "
                                        "nível de cruzeiro. Passe o mouse para ver o nome e os limites.")

    # Planejamento: só aparece quando o usuário clicar em "Planejar voo"
    # A aba do planejamento já vem ABERTA quando há um plano ativo (expanded=...).
    if not isinstance(st.session_state.get("nivel", 100), int):   # sessão aberta na versão antiga do site
        st.session_state["nivel"] = 100
    aba_plano = st.sidebar.expander("📍 Planejamento de voo", expanded=bool(st.session_state.get("plano")))
    with aba_plano.form("planejamento"):
        opcoes = ad.LISTA_ICAO
        origem = st.selectbox("Origem", opcoes, index=None, placeholder="Escolha...", format_func=ad.rotulo)
        destino = st.selectbox("Destino", opcoes, index=None, placeholder="Escolha...", format_func=ad.rotulo)
        altn = st.selectbox("Alternativa (opcional)", opcoes, index=None, placeholder="Escolha...",
                            format_func=ad.rotulo)
        # Rota por aerovias (opcional). Vazia = linha reta, como antes.
        rota_txt = st.text_area("Rota (opcional)", (st.session_state.get("rota") or {}).get("original", ""),
                                height=68, placeholder="Ex.: UKBEV UZ26 SAMGA VUKEP",
                                help="Como no plano de voo: FIXO AEROVIA FIXO... Fixo solto = direto (DCT). "
                                     "SID/STAR e velocidade/nível (N0452F360) são ignorados. "
                                     "Deixe vazio para linha reta.")
        nivel_escolhido = st.selectbox("Nível de cruzeiro", pl.NIVEIS_CRUZEIRO, format_func=pl.fl_txt,
                                       index=pl.NIVEIS_CRUZEIRO.index(st.session_state.get("nivel", 100)))
        # Horário do voo (UTC). Padrão: decolagem daqui a ~30 min e 1 h de voo.
        voo_atual = st.session_state.get("voo") or pl.voo_padrao()
        # A barra lateral é estreita: um campo por linha (lado a lado os rótulos quebravam e ficava torto)
        data_etd = st.date_input("Data da decolagem (UTC)", voo_atual["etd"].date(), format="DD/MM/YYYY")
        hora_etd = st.time_input("Hora da decolagem (UTC)", voo_atual["etd"].time(), step=300)
        eet_txt = st.text_input("Tempo de voo · EET (hh:mm)", f"{voo_atual['eet_min'] // 60:02d}:"
                                f"{voo_atual['eet_min'] % 60:02d}", help="Ex.: 01:15 = 1 h e 15 min.")
        planejar = st.form_submit_button("✈️ Planejar voo", type="primary")
    if planejar:
        etd = datetime.combine(data_etd, hora_etd, tzinfo=timezone.utc)
        m_eet = re.fullmatch(r"\s*(\d{1,2})[:h]?(\d{2})\s*", eet_txt or "")
        agora_z = datetime.now(timezone.utc)
        if not (origem and destino):
            aba_plano.warning("Escolha pelo menos origem e destino.")
        elif not m_eet or not (5 <= int(m_eet.group(1)) * 60 + int(m_eet.group(2)) <= 18 * 60):
            aba_plano.warning("Tempo de voo inválido: use hh:mm (ex.: 01:15), entre 00:05 e 18:00.")
        elif not (agora_z - timedelta(hours=1) <= etd <= agora_z + timedelta(hours=24)):
            aba_plano.warning("A decolagem deve ser entre 1 h atrás e 24 h à frente (UTC).")
        else:
            st.session_state["plano"] = [origem, destino, altn]
            st.session_state["nivel"] = nivel_escolhido
            st.session_state["voo"] = {"etd": etd, "eet_min": int(m_eet.group(1)) * 60 + int(m_eet.group(2))}
            st.session_state.pop("pdf_voo", None)       # PDF de um plano anterior não vale mais
            # ---- rota por aerovias ----
            st.session_state.pop("rota", None)          # começa do zero: sem rota = linha reta
            st.session_state.pop("rota_erro", None)
            if rota_txt and rota_txt.strip():
                from modulos import aerovias as av
                with st.spinner("Lendo as aerovias do GEOAISWEB..."):
                    fixos, vias, erros_av = rede_aerovias()
                if not vias:
                    st.session_state["rota_erro"] = ("Não consegui baixar as aerovias agora ("
                                                     + "; ".join(erros_av) + "). Desenhei em linha reta.")
                else:
                    r = av.ler_rota(rota_txt, fixos, vias, origem, destino)
                    if r["ok"]:
                        st.session_state["rota"] = {"od": (origem, destino), "original": rota_txt.strip(),
                                                    "texto": av.texto_expandido(r["pontos"]),
                                                    "pontos": r["pontos"], "avisos": r["avisos"] + erros_av}
                    else:
                        st.session_state["rota_erro"] = r["erro"] + " Desenhei em linha reta."
    if st.session_state.get("plano") and aba_plano.button("Limpar planejamento"):
        del st.session_state["plano"]
        st.session_state.pop("rota", None)
        st.session_state.pop("rota_erro", None)
        st.rerun()
    botao_guia(aba_plano)
    plano = st.session_state.get("plano")
    nivel = st.session_state.get("nivel", 100)          # FL de cruzeiro (número: 100 = FL100)
    voo = st.session_state.get("voo") or pl.voo_padrao()

    # ---------------- título ----------------
    if plano:
        st.title(f"🛰️ Briefing: {plano[0]} ✈️ {plano[1]}" + (f"  (altn {plano[2]})" if plano[2] else "")
                 + f" · {pl.fl_txt(nivel)}")
        st.caption(pl.txt_horarios(voo))
        rota = pl.rota_ativa(plano)
        if rota:
            dist = pl.distancia_total(pl._pernas(plano))
            reta = rt_mod.distancia_nm(ad.COORDS[plano[0]], ad.COORDS[plano[1]])
            st.markdown(f"<div class='msg' style='border-left-color:#00f2ff;color:#cff9ff'>🛣️ ROTA: "
                        f"{html.escape(rota['texto'])}<br>{dist:.0f} NM pela rota · {reta:.0f} NM em linha reta "
                        f"(+{(dist / reta - 1) * 100:.0f}%)</div>", unsafe_allow_html=True)
            for a in rota["avisos"]:
                st.caption(f"ℹ️ {a}")
        if st.session_state.get("rota_erro"):
            st.warning("Rota: " + st.session_state["rota_erro"], icon="🛣️")
    else:
        st.title("🛰️ Briefing operacional")
    aviso_instrucao()

    avisos, chips = [], []

    # ---------------- mapa ----------------
    m = folium.Map(location=[-15.0, -55.0], zoom_start=4, tiles=None, control_scale=True)
    m.get_root().header.add_child(folium.Element(cm.CSS_MAPA))
    # Etiqueta com o nome do fixo da rota: texto pequeno, fundo escuro, ao lado da bolinha
    m.get_root().header.add_child(folium.Element(
        "<style>.fixo-rota{font:700 10px/1 'Segoe UI',Arial;color:#cff9ff;background:rgba(6,19,30,.85);"
        "border:1px solid #00f2ff;border-radius:3px;padding:1px 3px;white-space:nowrap;"
        "transform:translate(7px,-16px);display:inline-block;pointer-events:none}</style>"))
    # Com carta ENRC/WAC na tela, as linhas de estados/países do mapa ficam desligadas
    cm.adicionar_mapas_fundo(m, rotulos=(enrc == "Nenhuma" and not wacs))     # (a SIGWX não tem fronteiras)

    # Primeiro as ENRC, depois as WAC: no mapa, o que é adicionado por último fica por cima.
    camadas = []
    if enrc != "Nenhuma":
        letra = "L" if "baixa" in enrc else "H"
        camadas += [(f"ICA:ENRC_{letra}{i}", f"ENRC {letra}{i}") for i in range(1, 10)]
    camadas += [(f"ICA:{w}", nome_wac(w)) for w in wacs]
    for camada, nome in camadas:
        folium.WmsTileLayer(url="https://geoaisweb.decea.mil.br/geoserver/ICA/wms", layers=camada,
                            fmt="image/png", transparent=True, name=nome, overlay=True).add_to(m)

    with st.spinner("Carregando satélite, mensagens e modelo..."):
        # o visível primeiro (fica embaixo); o IR por cima: nuvens frias coloridas sobre a imagem real
        for canal, ligado, nome in (("VIS", ver_vis, "GOES-19 visível (cores reais)"), ("IR", ver_ir, "GOES-19 IR (canal 13)")):
            if not ligado:
                continue
            try:
                url_img, limites, instante, extras = goes(canal)
                if canal == "IR" and relevo_ir:
                    url_img = extras.get("url_relevo", url_img)
                if canal == "IR" and extras.get("temp_url"):
                    # legenda com a barra de cores e a temperatura onde o mouse está
                    cm.LeituraTemperatura(extras["temp_url"], limites, sat.K_BASE).add_to(m)
                opac = 0.85 if canal == "IR" else 1.0
                folium.raster_layers.ImageOverlay(url_img, bounds=limites, opacity=opac,
                                                  name=f"{nome} {fmt_z(instante)}", interactive=False,
                                                  pixelated=False).add_to(m)   # False = navegador suaviza no zoom
                # Com voo planejado: por cima, um recorte em ~2 km só na região da rota (nítido no zoom)
                if plano:
                    try:
                        regiao = sat.regiao_da_rota([ad.COORDS[i] for i in plano if i])
                        url_hd, lim_hd, _, ext_hd = goes_rota(canal, regiao, extras["arquivo"])
                        if canal == "IR" and relevo_ir:
                            url_hd = ext_hd.get("url_relevo", url_hd)
                        folium.raster_layers.ImageOverlay(url_hd, bounds=lim_hd, opacity=opac,
                                                          name=f"{nome} detalhado na rota", interactive=False,
                                                          pixelated=False).add_to(m)
                    except Exception as e:
                        avisos.append(f"{nome}: recorte detalhado da rota indisponível ({type(e).__name__}).")
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

        # SIGWX por cima do satélite e do modelo (o traço claro com contorno lê bem sobre os dois)
        if ver_sigwx:
            voo_sigwx = voo if plano else {
                "etd": datetime.now(timezone.utc), "eet_min": 0}       # sem voo: a validade mais próxima de agora
            cartas = [c for c in pl.sigwx_do_voo(voo_sigwx, api_key) if c["png"]]
            if not cartas:
                avisos.append("Carta SIGWX indisponível na REDEMET agora.")
            for i, c in enumerate(cartas):
                try:
                    url_sig, lim_sig = camada_sigwx(c["png"])
                    folium.raster_layers.ImageOverlay(url_sig, bounds=lim_sig, name=c["titulo"], show=(i == 0),
                                                      interactive=False, pixelated=False).add_to(m)
                    chips.append((c["titulo"] + (" (as outras validades: botão de camadas)"
                                                 if i == 0 and len(cartas) > 1 else ""), c["validade"] is None))
                except Exception as e:
                    avisos.append(f"Não consegui encaixar a SIGWX no mapa ({type(e).__name__}).")

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
        pts = pl._pernas(plano)                  # origem, fixos da rota (se houver) e destino
        rota = pl.rota_ativa(plano)

        # 1) Aerovias em volta da rota (referência). Desenhadas ANTES = ficam embaixo da rota.
        if ver_aerovias:
            from modulos import aerovias as av
            nivel_av = "alta" if nivel >= 245 else "baixa"
            try:
                caixa = rt_mod.limites(pts, margem_graus=1.0, minimo_graus=3)
                grupo = folium.FeatureGroup(name=f"Aerovias de {nivel_av} (DECEA)")
                for s in av.segmentos_na_caixa(segmentos_aerovias(nivel_av), caixa):
                    folium.PolyLine(s["pts"], color="#5b7cfa", weight=2, opacity=0.75,
                                    tooltip=f"{s['aerovia']} · {s['de']}→{s['para']} · "
                                            f"{s['base']} a {s['topo']}"
                                            + (" · mão única" if s["direcao"] != "BOTH" else "")).add_to(grupo)
                grupo.add_to(m)
                chips.append((f"Aerovias de {nivel_av}: GEOAISWEB", False))
            except Exception as e:
                avisos.append(f"Aerovias indisponíveis no GEOAISWEB agora ({type(e).__name__}).")

        # 2) A rota: linha preta por baixo + ciano por cima (contorno, lê bem sobre o satélite)
        dica = f"Rota: {rota['texto']}" if rota else "Rota direta (linha reta)"
        folium.PolyLine(pts, color="#000000", weight=7, opacity=0.6).add_to(m)
        folium.PolyLine(pts, color="#00f2ff", weight=4, opacity=0.95, tooltip=dica).add_to(m)
        if rota:                                  # bolinha + nome em cada fixo
            fixos_grupo = folium.FeatureGroup(name="Fixos da rota")
            for p in rota["pontos"]:
                folium.CircleMarker([p["lat"], p["lon"]], radius=4, color="#000", weight=1, fill=True,
                                    fill_color="#00f2ff", fill_opacity=1,
                                    tooltip=f"{p['ident']} (via {p['via']})").add_to(fixos_grupo)
                folium.Marker([p["lat"], p["lon"]], icon=folium.DivIcon(
                    html=f"<div class='fixo-rota'>{p['ident']}</div>", icon_size=(0, 0))).add_to(fixos_grupo)
            fixos_grupo.add_to(m)
        if plano[2]:
            folium.PolyLine([ad.COORDS[plano[1]], ad.COORDS[plano[2]]], color="#c77dff", weight=3,
                            dash_array="6 6", tooltip="Para a alternativa").add_to(m)
        m.fit_bounds([ad.COORDS[i] for i in plano if i] + pts, padding=(60, 60))

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

    # ---------------- BRIEFING DO VOO (abas embaixo do mapa; o plano é preenchido na barra lateral) ----------------
    st.subheader("🧭 Briefing do voo")
    abas = st.tabs(["🔍 Dados da rota", "🕓 Consultar mensagens", "🗺️ SIGWX", "🌬️ Vento na rota",
                    "📄 Gerar voo (PDF)"])
    with abas[0]:
        if plano:
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
            st.info("Escolha origem, destino, alternativa e nível na barra lateral e clique em **Planejar voo** "
                    "para ver a rota e os METAR/TAF completos aqui.", icon="🧭")
    with abas[1]:
        pl.aba_consulta(api_key, plano)
    with abas[2]:
        pl.aba_sigwx(api_key, plano, voo)
    with abas[3]:
        pl.aba_vento(plano, nivel, voo)
    with abas[4]:
        pl.aba_gerar_voo(plano, nivel, voo, api_key, {"goes": goes, "goes_rota": goes_rota, "metars_e_tafs": metars_e_tafs,
                                                      "sigmets": lista_sigmets, "raios": raios})

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
    st.markdown("### 📘 Guias do site")
    st.markdown("Passo a passo de como montar o briefing meteorológico do seu voo no site: "
                "plano, mapa, abas do Briefing do voo, PDF, validades (Doc 8896) e checklist.")
    botao_guia(st, "📘 Guia do Planejamento de Voo (PDF)")
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
