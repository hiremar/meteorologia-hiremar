"""Planejamento de voo: as abas que ficam embaixo do mapa.

  🕓 Consultar mensagens  -> METAR/SPECI/TAF passados, por período (igual à REDEMET)
  🗺️ SIGWX               -> carta de tempo significativo da REDEMET
  🌬️ Vento na rota       -> vento e temperatura do GFS no nível de cruzeiro
  📄 Gerar voo           -> junta o que o piloto escolher num PDF colorido

A aba "Dados da rota" (METAR/TAF de origem, destino e alternativa) continua no app.py.

As funções que BAIXAM dados com cache (satélite, METAR, raios, GFS) ficam no app.py;
ele as entrega aqui no dicionário 'fontes', para o cache ser o mesmo do mapa
(o que o mapa já baixou, o PDF reaproveita sem baixar de novo).
"""
import csv
import io
import re
from datetime import datetime, timedelta, timezone

import requests
import streamlit as st

from . import aerodromos as ad
from . import metar as mt
from . import modelo_gfs as gfs
from . import redemet as rd
from . import rota as rt

# Níveis de cruzeiro oferecidos = os níveis de pressão do GFS (só eles têm vento E temperatura)
NIVEIS_CRUZEIRO = [r for r, (tipo, _) in gfs.NIVEIS.items() if tipo == "iso"]
CORREDORES = [25, 50, 100]          # NM para cada lado da rota


# ============================================================================
# Downloads com cache (só os que são exclusivos destas abas)
# ============================================================================
@st.cache_data(ttl=300, show_spinner=False)
def _consultar(tipo, icaos, inicio, fim, chave):
    return rd.mensagens_periodo(tipo, list(icaos), inicio, fim, chave)


@st.cache_data(ttl=300, show_spinner=False)
def _mais_recente(tipo, icaos, chave):
    return rd.ultima_por_localidade(tipo, list(icaos), chave)


@st.cache_data(ttl=1800, show_spinner=False)        # a SIGWX muda poucas vezes por dia
def _sigwx_url(chave):
    return rd.sigwx(chave)


@st.cache_data(ttl=1800, show_spinner=False)
def _sigwx_png(url):
    """Baixa a imagem da SIGWX e devolve como PNG (a REDEMET às vezes manda GIF)."""
    from PIL import Image
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    buf = io.BytesIO()
    Image.open(io.BytesIO(r.content)).convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


# ============================================================================
# 1) Consulta de mensagens por período
# ============================================================================
def _ler_icaos(texto):
    """'sbgr, sbsp  SBKP' -> ['SBGR', 'SBSP', 'SBKP']  (sem repetir, na ordem digitada)"""
    vistos = []
    for p in re.split(r"[\s,;/]+", texto.upper()):
        if p and p not in vistos:
            vistos.append(p)
    return vistos


def aba_consulta(api_key, plano=None):
    st.markdown("Consulte METAR, SPECI e TAF **de qualquer localidade e período**, "
                "como na tela *Consulta Mensagens* da REDEMET. Não precisa ter rota planejada.")
    agora = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    # Período padrão: das últimas 6 horas cheias até a PRÓXIMA hora cheia (pega a mensagem mais nova)
    ini_padrao = agora.replace(minute=0) - timedelta(hours=6)
    fim_padrao = agora.replace(minute=0) + timedelta(hours=1)
    padrao = ", ".join(i for i in (plano or []) if i) or "SBGR"

    # st.form: nada é consultado enquanto o usuário preenche; só quando clicar no botão
    with st.form("consulta_mensagens"):
        icaos_txt = st.text_input("Localidades (indicativo ICAO, separadas por vírgula)", padrao,
                                  help="Qualquer localidade com METAR na REDEMET, não só as do mapa. Até 6.")
        recente = st.checkbox("Mostrar só a mensagem mais recente", value=False)
        c1, c2, c3, c4 = st.columns(4)
        d_ini = c1.date_input("Data inicial (UTC)", ini_padrao.date(), format="DD/MM/YYYY")
        h_ini = c2.time_input("Hora inicial (UTC)", ini_padrao.time(), step=1800)
        d_fim = c3.date_input("Data final (UTC)", fim_padrao.date(), format="DD/MM/YYYY")
        h_fim = c4.time_input("Hora final (UTC)", fim_padrao.time(), step=1800)
        t1, t2, _ = st.columns([1, 1, 2])
        q_metar = t1.checkbox("METAR / SPECI", value=True)
        q_taf = t2.checkbox("TAF", value=False)
        enviar = st.form_submit_button("🔎 Consultar", type="primary")

    if enviar:
        icaos = _ler_icaos(icaos_txt)
        inicio = datetime.combine(d_ini, h_ini, tzinfo=timezone.utc)
        fim = datetime.combine(d_fim, h_fim, tzinfo=timezone.utc)
        erro = None
        if not icaos or any(not re.fullmatch(r"[A-Z]{4}", i) for i in icaos):
            erro = "Indicativos inválidos: use 4 letras, ex.: SBGR, SBSP."
        elif len(icaos) > 6:
            erro = "No máximo 6 localidades por consulta."
        elif not (q_metar or q_taf):
            erro = "Marque METAR/SPECI e/ou TAF."
        elif not recente and fim <= inicio:
            erro = "A data/hora final precisa ser depois da inicial."
        elif not recente and fim - inicio > timedelta(days=31):
            erro = "Período máximo: 31 dias por consulta."
        if erro:
            st.warning(erro)
        else:
            resultado, falhas = [], []
            with st.spinner("Consultando a REDEMET..."):
                for tipo, ligado in (("metar", q_metar), ("taf", q_taf)):
                    if not ligado:
                        continue
                    if recente:
                        ultimas, e = _mais_recente(tipo, tuple(icaos), api_key)
                        for icao, item in ultimas.items():
                            txt = item["mens"]
                            resultado.append({"localidade": icao, "tipo": txt.split()[0] if txt else tipo.upper(),
                                              "validade": mt.horario_metar(txt), "mens": " ".join(txt.split())})
                    else:
                        itens, e = _consultar(tipo, tuple(icaos), inicio, fim, api_key)
                        resultado += itens
                    if e:
                        falhas.append(e)
            # guardado na "memória da sessão": continua na tela quando o usuário mexe em outra coisa
            st.session_state["consulta"] = {"itens": resultado, "falhas": falhas,
                                            "titulo": f"{', '.join(icaos)} · " + (
                                                "mais recente" if recente else
                                                f"{inicio:%d/%m %H:%M}Z a {fim:%d/%m %H:%M}Z")}

    res = st.session_state.get("consulta")
    if not res:
        return
    for f in res["falhas"]:
        st.warning(f, icon="⚠️")
    itens = res["itens"]
    st.markdown(f"**Resultados** · {res['titulo']} · {len(itens)} mensagem(ns)")
    if not itens:
        st.info("Nenhuma mensagem encontrada nesse período.")
        return
    filtro = st.text_input("Filtrar por texto", placeholder="ex.: TS, SPECI, BKN004, COR...")
    if filtro:
        itens = [i for i in itens if filtro.upper() in i["mens"].upper()]
    linhas = [{"Localidade": i["localidade"], "Tipo": i["tipo"],
               "Data/Hora (UTC)": i["validade"].strftime("%d/%m/%Y %H:%M") if i["validade"] else "",
               "Mensagem": i["mens"]} for i in itens]
    st.dataframe(linhas, hide_index=True, use_container_width=True,
                 column_config={"Mensagem": st.column_config.TextColumn(width="large")})

    # Arquivos para baixar (iguais aos botões TXT e CSV da REDEMET)
    txt = "\n".join(i["mens"] for i in itens)
    csv_buf = io.StringIO()
    escritor = csv.DictWriter(csv_buf, fieldnames=list(linhas[0]), delimiter=";")
    escritor.writeheader()
    escritor.writerows(linhas)
    b1, b2, _ = st.columns([1, 1, 4])
    b1.download_button("⬇️ TXT", txt, "mensagens.txt", "text/plain")
    b2.download_button("⬇️ CSV", csv_buf.getvalue().encode("utf-8-sig"), "mensagens.csv", "text/csv",
                       help="Abre direto no Excel (separador ponto e vírgula).")


# ============================================================================
# 2) SIGWX
# ============================================================================
def aba_sigwx(api_key):
    url, erro = _sigwx_url(api_key)
    if erro:
        st.warning(erro, icon="⚠️")
        return
    m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/[a-z]*?(\d{2})\.\w+$", url)
    quando = f" · {m.group(3)}/{m.group(2)}/{m.group(1)} {m.group(4)}Z" if m else ""
    st.markdown(f"Carta de **tempo significativo (SIGWX) SFC/FL250** mais recente da REDEMET{quando}. "
                f"[Abrir a imagem em tamanho real]({url})")
    st.image(url, use_container_width=True)
    st.caption("A API da REDEMET entrega só a carta mais recente (não permite consultar cartas antigas).")


# ============================================================================
# 3) Vento na rota
# ============================================================================
def _carregar_gfs(modelo, horas):
    hora_cheia = datetime.now(timezone.utc).strftime("%Y%m%d%H")
    return modelo(horas, hora_cheia)


def _pernas(plano):
    return [ad.COORDS[plano[0]], ad.COORDS[plano[1]]]


def _tabela_vento(linhas):
    return [{"Distância": f"{l['dist_nm']} NM",
             "Posição": f"{abs(l['lat']):.1f}{'S' if l['lat'] < 0 else 'N'} {abs(l['lon']):.1f}{'W' if l['lon'] < 0 else 'E'}",
             "Rumo V": f"{l['rumo']:03d}°", "Vento": l["vento"],
             "Temperatura": "-" if l["temp_c"] is None else f"{l['temp_c']} °C",
             "Componente": rt.texto_componente(l["componente"]),
             "Desvio ISA": "-" if l["isa_desvio"] is None else f"ISA{l['isa_desvio']:+d}"} for l in linhas]


def resumo_vento_txt(res):
    t = (f"Componente média na rota: {rt.texto_componente(res['componente_media'])}. "
         f"Vento máximo no nível: {res['vento_max']} kt.")
    if res["temp_min"] is not None:
        t += (f" Temperatura de {res['temp_min']} a {res['temp_max']} °C "
              f"(ISA{res['isa_desvio_medio']:+d} em média).")
    return t


def aba_vento(plano, nivel, modelo):
    if not plano:
        st.info("Planeje um voo na barra lateral (origem, destino e nível) para ver o vento na rota.", icon="🧭")
        return
    c1, c2 = st.columns([2, 3])
    horas = c1.select_slider("Validade do modelo", options=[0, 3, 6, 9, 12, 18, 24], key="vento_horas",
                             format_func=lambda h: "agora" if h == 0 else f"+{h} h")
    # O GFS pesa alguns MB: só baixa quando o usuário pedir (depois fica no cache por 1 h)
    if not st.session_state.get("vento_ligado"):
        if c2.button("🌬️ Calcular vento na rota", type="primary"):
            st.session_state["vento_ligado"] = True
            st.rerun()
        st.caption(f"Vento e temperatura do modelo GFS no {nivel.split(' · ')[0]}, ponto a ponto ao longo da rota.")
        return
    try:
        with st.spinner("Baixando o modelo GFS (a primeira vez demora um pouco)..."):
            dados, info = _carregar_gfs(modelo, horas)
    except Exception as e:
        st.warning(f"Modelo GFS indisponível agora ({e}).", icon="⚠️")
        return
    linhas, res = rt.vento_na_rota(dados, nivel, _pernas(plano))
    st.markdown(f"**{nivel.split(' · ')[0]}** · GFS {info['run']:%d/%H}Z +{info['fhora']}h, "
                f"válido {info['valido']:%d/%m %H:%M}Z · {res['distancia_nm']} NM")
    c = res["componente_media"]
    cor = "#d7263d" if c <= -15 else "#2e9e44" if c >= 15 else "#c9d3dc"
    st.markdown(f"<div style='font-size:1.05rem'>Componente média: "
                f"<b style='color:{cor}'>{rt.texto_componente(c)}</b></div>", unsafe_allow_html=True)
    st.caption(resumo_vento_txt(res))
    st.dataframe(_tabela_vento(linhas), hide_index=True, use_container_width=True)
    try:
        png = _mapa_vento(dados, nivel, plano, info)
        st.image(png, use_container_width=True)
    except Exception as e:
        st.caption(f"Mapa de barbelas indisponível ({type(e).__name__}).")


def _mapa_vento(dados, nivel, plano, info):
    from . import mapa_estatico as me
    pontos = [ad.COORDS[i] for i in plano if i]
    return me.mapa_vento(rt.limites(pontos, margem_graus=2.5, minimo_graus=8), dados, nivel, _pernas(plano),
                         ad.COORDS[plano[2]] if plano[2] else None,
                         f"Vento {nivel.split(' · ')[0]} · GFS válido {info['valido']:%d/%m %H}Z")


# ============================================================================
# 4) Gerar voo (PDF)
# ============================================================================
def _cartao(papel, icao, metars, tafs, avisos_ad, agora):
    metar = (metars.get(icao) or {}).get("mens", "")
    info = mt.analisar(metar, agora) if metar else None
    return {"papel": papel, "icao": icao, "nome": ad.NOMES.get(icao, ""), "metar": metar,
            "taf": (tafs.get(icao) or {}).get("mens", ""), "cat": info["faa"] if info else "ND",
            "idade": info["idade_min"] if info else None,
            "avisos": [(rd.decodificar_aviso(a), a) for a in avisos_ad.get(icao, [])]}


def montar_briefing(plano, nivel, opcoes, corredor_nm, metars, tafs, avisos_ad, sigmets_txt,
                    pontos_raios, satelite=None, gfs_dados=None, sigwx=None, agora=None):
    """Junta tudo num dicionário para o relatorio_pdf.gerar(). Não usa nada do Streamlit
    (assim dá para testar fora do site).
    opcoes  : conjunto com "mapa", "aerodromos", "em_rota", "sigmet", "raios", "vento", "sigwx"
    satelite: (data_url, limites, instante) ou None ; gfs_dados: (dados, info) ou None
    sigwx   : (png_bytes, texto) ou None"""
    from . import mapa_estatico as me
    agora = agora or datetime.now(timezone.utc)
    origem, destino, altn = plano
    pernas = _pernas(plano)
    amostras = rt.pontos_da_rota(pernas, 10)
    fl = rt.nivel_fl(nivel)
    b = {"origem": origem, "destino": destino, "altn": altn, "nivel": nivel.replace(" · ", " / "),
         "distancia_nm": round(rt.distancia_nm(*pernas)), "rumo": round(rt.rumo_verdadeiro(*pernas)),
         "corredor_nm": corredor_nm, "gerado_em": agora, "indisponiveis": []}

    em_rota = rt.aerodromos_no_corredor(amostras, ad.AERODROMOS, corredor_nm, excluir=plano,
                                        longe_de=[ad.COORDS[i] for i in plano if i])
    na_rota = rt.sigmets_na_rota(sigmets_txt, amostras, corredor_nm, rd.coordenadas_sigmet, fl)
    n_raios, raio_perto, faixa = rt.raios_no_corredor(pontos_raios, amostras, corredor_nm)

    if "aerodromos" in opcoes:
        b["aerodromos"] = [_cartao(p, i, metars, tafs, avisos_ad, agora)
                           for p, i in zip(("Origem", "Destino", "Alternativa"), plano) if i]
    if "em_rota" in opcoes:
        b["em_rota"] = []
        for icao, d in em_rota:
            c = _cartao(f"Em rota ({d} NM da rota)", icao, metars, tafs, avisos_ad, agora)
            b["em_rota"].append(c)
    if "sigmet" in opcoes:
        b["sigmets"] = [(rd.decodificar_sigmet(t), t, no_nivel) for t, no_nivel in na_rota]
    if "raios" in opcoes:
        if n_raios:
            idade = rd.FAIXAS_RAIOS[faixa][2]
            b["raios_txt"] = (f"{n_raios} descarga(s) na última hora a até {corredor_nm} NM da rota "
                              f"(as mais recentes: {idade}).")
        elif raio_perto is not None:
            b["raios_txt"] = (f"Nenhuma descarga no corredor de {corredor_nm} NM. "
                              f"A mais próxima está a cerca de {raio_perto} NM da rota.")
        else:
            b["raios_txt"] = "Nenhuma descarga atmosférica informada perto da rota na última hora."

    # ---------- resumo da primeira página ----------
    cats = [_cartao("", i, metars, tafs, avisos_ad, agora)["cat"] for i in plano if i]
    ordem = ["LIFR", "IFR", "MVFR", "VFR", "ND"]
    pior = min(cats, key=ordem.index) if cats else "ND"
    com_aviso = [i for i in [*plano, *(i for i, _ in em_rota)] if i and avisos_ad.get(i)]
    no_nivel = [t for t, n in na_rota if n]
    b["resumo"] = [
        ("Categorias (FAA)", " · ".join(f"{i} {c}" for i, c in zip([i for i in plano if i], cats)) +
         f"  (pior: {pior})"),
        ("SIGMET perto da rota", f"{len(na_rota)}" + (f", {len(no_nivel)} no seu nível" if na_rota else "")),
        ("Raios no corredor", f"{n_raios} na última hora" if n_raios else "nenhum"),
        ("Aviso de aeródromo", ", ".join(com_aviso) if com_aviso else "nenhum vigente"),
        ("Aeródromos em rota", ", ".join(i for i, _ in em_rota) if em_rota else "nenhum no corredor"),
    ]

    # ---------- vento ----------
    if "vento" in opcoes:
        if gfs_dados:
            dados, info = gfs_dados
            linhas, res = rt.vento_na_rota(dados, nivel, pernas)
            for l in linhas:
                l["comp_txt"] = rt.texto_componente(l["componente"])
            fonte = (f"GFS rodada {info['run']:%d/%m %H}Z +{info['fhora']}h, válido {info['valido']:%d/%m %H:%M}Z. "
                     f"Componente: positivo = cauda (verde), negativo = proa (vermelho).")
            try:
                png_v = _mapa_vento(dados, nivel, plano, info)
            except Exception:
                png_v = None
            b["vento"] = {"nivel": nivel.split(" · ")[0], "linhas": linhas, "fonte": fonte,
                          "resumo_txt": resumo_vento_txt(res), "mapa_png": png_v}
            b["resumo"].insert(0, ("Vento no nível", f"{rt.texto_componente(res['componente_media'])} em média, "
                                                     f"máx. {res['vento_max']} kt"))
        else:
            b["indisponiveis"].append("modelo GFS indisponível: o PDF saiu sem a parte de vento.")

    # ---------- mapa ----------
    if "mapa" in opcoes:
        pts = [ad.COORDS[i] for i in plano if i]
        folha = me.MapaEstatico(rt.limites(pts, margem_graus=1.5, minimo_graus=5))
        folha.fundo()
        if satelite:
            try:
                folha.satelite(satelite[0], satelite[1])
            except Exception:
                b["indisponiveis"].append("imagem de satélite não pôde ser colocada no mapa.")
        folha.rotulos()
        folha.sigmets(sigmets_txt)
        folha.raios(pontos_raios)
        folha.rota(pernas, ad.COORDS[altn] if altn else None)
        folha.aerodromos(metars, [i for i in plano if i] + [i for i, _ in em_rota], avisos_ad)
        folha.titulo(f"{origem} -> {destino}" + (f" (altn {altn})" if altn else "") + f" · {nivel.split(' · ')[0]}")
        folha.legenda(me.legenda_padrao(bool(pontos_raios), bool(sigmets_txt), bool(altn)))
        b["mapa_png"] = folha.png()
        partes = []
        if satelite:
            partes.append(f"Satélite GOES-19 IR de {satelite[2]:%d/%m %H:%M}Z")
        partes.append(f"Etiquetas: categoria de voo FAA pelo METAR. Corredor da rota: {corredor_nm} NM.")
        if folha.avisos:
            partes.append("Mapa de fundo indisponível no momento.")
        b["mapa_legenda"] = ". ".join(partes)

    if "sigwx" in opcoes:
        if sigwx:
            b["sigwx_png"], b["sigwx_txt"] = sigwx
        else:
            b["indisponiveis"].append("carta SIGWX indisponível: o PDF saiu sem ela.")
    return b


ITENS_PDF = {   # chave: (texto da caixa de seleção, marcada por padrão?)
    "mapa": ("🗺️ Mapa da rota (satélite IR, SIGMET, raios, aeródromos)", True),
    "aerodromos": ("📋 METAR / TAF de origem, destino e alternativa", True),
    "em_rota": ("🛬 METAR / TAF dos aeródromos no meio da rota", True),
    "sigmet": ("⚡ SIGMET que afetam a rota (decodificados)", True),
    "raios": ("🌩️ Raios perto da rota", True),
    "vento": ("🌬️ Vento e temperatura no nível de cruzeiro (GFS)", True),
    "sigwx": ("🗺️ Carta SIGWX", True),
}


def aba_gerar_voo(plano, nivel, api_key, fontes):
    """fontes = {"goes", "metars_e_tafs", "sigmets", "raios", "modelo"} (funções com cache do app.py)"""
    if not plano:
        st.info("Planeje um voo na barra lateral (origem, destino, alternativa e nível de cruzeiro) "
                "para gerar o pacote de briefing em PDF.", icon="🧭")
        return
    st.markdown(f"Monte o **pacote de briefing** do voo {plano[0]} → {plano[1]}"
                + (f" (altn {plano[2]})" if plano[2] else "") + f" no **{nivel.split(' · ')[0]}** "
                "e baixe em PDF.")
    with st.form("gerar_voo"):
        st.markdown("**O que entra no PDF**")
        c1, c2 = st.columns(2)
        marcados = set()
        for k, (texto, padrao) in ITENS_PDF.items():
            col = c1 if list(ITENS_PDF).index(k) % 2 == 0 else c2
            if col.checkbox(texto, value=padrao, key=f"pdf_{k}"):
                marcados.add(k)
        c3, c4 = st.columns(2)
        corredor = c3.select_slider("Largura do corredor da rota (para cada lado)", CORREDORES, value=50,
                                    format_func=lambda n: f"{n} NM")
        horas = c4.select_slider("Validade do vento (GFS)", options=[0, 3, 6, 9, 12, 18, 24],
                                 format_func=lambda h: "agora" if h == 0 else f"+{h} h")
        gerar = st.form_submit_button("✈️ Gerar voo (PDF)", type="primary")

    if gerar:
        from . import relatorio_pdf
        with st.status("Montando o briefing...", expanded=True) as status:
            st.write("METAR, TAF e avisos de aeródromo")
            metars, tafs, avisos_ad, _, _ = fontes["metars_e_tafs"](api_key)
            st.write("SIGMET e raios")
            textos, _ = fontes["sigmets"](api_key)
            quadros, _ = fontes["raios"](api_key)
            pontos = rd.pontos_por_idade(quadros, datetime.now(timezone.utc))
            satelite = None
            if "mapa" in marcados:
                st.write("Satélite GOES-19")
                try:
                    satelite = fontes["goes"]("IR")
                except Exception:
                    satelite = None
            gfs_dados = None
            if "vento" in marcados:
                st.write("Modelo GFS (vento e temperatura)")
                try:
                    gfs_dados = _carregar_gfs(fontes["modelo"], horas)
                except Exception:
                    gfs_dados = None
            sigwx = None
            if "sigwx" in marcados:
                st.write("Carta SIGWX")
                url, _ = _sigwx_url(api_key)
                if url:
                    try:
                        sigwx = (_sigwx_png(url), f"Imagem: {url}")
                    except Exception:
                        sigwx = None
            st.write("Desenhando o mapa e o PDF")
            b = montar_briefing(plano, nivel, marcados, corredor, metars, tafs, avisos_ad, textos, pontos,
                                satelite, gfs_dados, sigwx)
            pdf = relatorio_pdf.gerar(b)
            st.session_state["pdf_voo"] = {"bytes": pdf, "mapa": b.get("mapa_png"),
                                           "nome": f"briefing_{plano[0]}_{plano[1]}_{datetime.now(timezone.utc):%d%m_%H%MZ}.pdf",
                                           "avisos": b["indisponiveis"]}
            status.update(label="Briefing pronto!", state="complete", expanded=False)

    pronto = st.session_state.get("pdf_voo")
    if pronto:
        for a in pronto["avisos"]:
            st.warning(a, icon="⚠️")
        st.download_button("⬇️ Baixar o PDF do briefing", pronto["bytes"], pronto["nome"], "application/pdf",
                           type="primary")
        if pronto.get("mapa"):
            st.image(pronto["mapa"], caption="Prévia do mapa que está no PDF", use_container_width=True)
