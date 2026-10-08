"""Planejamento de voo: as abas que ficam embaixo do mapa.

  🕓 Consultar mensagens  -> METAR/SPECI/TAF passados, por período (igual à REDEMET)
  🗺️ SIGWX               -> cartas SIGWX que cobrem o horário do voo
  🌬️ Vento na rota       -> vento e temperatura do GFS no FL de cruzeiro e nos vizinhos
  📄 Gerar voo           -> junta o que o piloto escolher num PDF colorido

A aba "Dados da rota" (METAR/TAF de origem, destino e alternativa) continua no app.py.

HORÁRIOS (Doc 8896 da OACI, item 5.3.3.4): o piloto informa a decolagem (ETD) e o tempo
de voo (EET). Cada ponto da rota ganha uma hora estimada, e para cada hora usamos:
  - vento/temperatura: a validade mais próxima na grade de 3 h (vale ±1,5 h);
  - SIGWX: a validade mais próxima na grade de 6 h (vale ±3 h).

As funções do app.py que BAIXAM dados com cache (satélite, METAR, raios) chegam aqui no
dicionário 'fontes', para o PDF reaproveitar o que o mapa já baixou.
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

# Níveis de cruzeiro: de FL030 a FL450, de 10 em 10. O vento sai do GFS interpolado.
NIVEIS_CRUZEIRO = list(range(30, 460, 10))
CORREDORES = [25, 50, 100]          # NM para cada lado da rota
URL_SIGWX = "https://estatico-redemet.decea.mil.br/sigwx/{t:%Y/%m/%d}/{nome}{t:%H}.gif"
# O nome do arquivo NÃO diz a validade com segurança. Em 08/10/2026 vimos:
#   2026/10/08/siginf06.gif -> "VALID 12 UTC 09-OCT-2026"  (30 h depois do nome)
#   2026/10/07/siginf18.gif -> "VALID 18 UTC 08-OCT-2026"  (24 h depois do nome)
# Por isso o site LÊ a validade impressa no quadro da carta (reconhecimento de texto,
# programa Tesseract) e só usa a carta cuja validade bate com a do voo.
# Ordem em que procuramos os arquivos (horas ANTES da validade): os mais prováveis primeiro.
DESLOCAMENTOS_SIGWX_H = [24, 30, 18, 36, 12, 42, 6, 48, 0]
MESES_EN = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}
# Cartas SIGWX da REDEMET por validade. 'siginf' = SFC/FL250 (CIMAER).
# Quando soubermos o nome do arquivo da carta ALTA (FL250-630), é só acrescentar aqui,
# ex.: ("sigsup", "FL250-FL630").
CARTAS_SIGWX = [("siginf", "SFC/FL250 (CIMAER)")]


def fl_txt(fl):
    return f"FL{fl:03d}"


def voo_padrao():
    """Decolagem nos próximos ~30 min (arredondada a 5 min) e 1 h de voo."""
    agora = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    etd = agora + timedelta(minutes=30 - agora.minute % 5)
    return {"etd": etd, "eet_min": 60}


def horarios(voo):
    """(etd, eta, eet_min) a partir do que está guardado na sessão."""
    voo = voo or voo_padrao()
    return voo["etd"], voo["etd"] + timedelta(minutes=voo["eet_min"]), voo["eet_min"]


def txt_horarios(voo):
    etd, eta, eet = horarios(voo)
    return f"ETD {etd:%d/%m %H:%M}Z · EET {eet // 60:02d}:{eet % 60:02d} · ETA {eta:%d/%m %H:%M}Z"


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
def _imagem_png(url):
    """Baixa uma imagem e devolve como PNG (a REDEMET manda GIF). Levanta exceção se não existir."""
    from PIL import Image
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    buf = io.BytesIO()
    Image.open(io.BytesIO(r.content)).convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


@st.cache_data(ttl=3 * 3600, show_spinner=False, max_entries=6)
def _gfs_validade(validade):
    """GFS válido no instante 'validade' (hora cheia). Fica 3 h no cache."""
    conteudo, info = gfs.baixar(alvo=validade)
    return gfs.ler_grib(conteudo), info


def gfs_do_voo(voo):
    """Baixa o GFS de todas as validades que o voo precisa. Devolve ({validade: dados}, infos, erros)."""
    etd, eta, _ = horarios(voo)
    dados, infos, erros = {}, [], []
    for v in rt.validades_do_voo(etd, eta, 3):
        try:
            d, info = _gfs_validade(v)
            dados[v] = d
            infos.append(info)
        except Exception as e:
            erros.append(f"GFS válido {v:%d/%m %H}Z indisponível ({e})")
    return dados, infos, erros


def validade_impressa(png):
    """Lê o quadro "VALID: 18 UTC 08 - OCT - 2026" da carta (canto inferior direito).
    Usa o Tesseract (programa de reconhecimento de texto, instalado pelo packages.txt).
    Devolve datetime em UTC, ou None se não conseguir ler."""
    import shutil
    import subprocess
    import tempfile
    from PIL import Image
    if not shutil.which("tesseract"):
        return None
    im = Image.open(io.BytesIO(png)).convert("L")
    w, h = im.size
    canto = im.crop((int(w * .55), int(h * .5), w, h))
    canto = canto.resize((canto.width * 2, canto.height * 2))     # ampliar ajuda a leitura
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        canto.save(f.name)
        texto = subprocess.run(["tesseract", f.name, "-", "--psm", "6"], capture_output=True,
                               text=True, timeout=30).stdout.upper()
    m = re.search(r"VALID\W*(\d{2})\s*UTC\W*(\d{1,2})\W*([A-Z0]{3})\W*(\d{4})", texto)
    if not m:
        return None
    hora, dia, mes, ano = m.groups()
    mes = MESES_EN.get(mes.replace("0", "O"))
    try:
        return datetime(int(ano), mes, int(dia), int(hora), tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


@st.cache_data(ttl=6 * 3600, show_spinner=False, max_entries=200)
def _validade_do_arquivo(url):
    """(png, validade lida na carta) de um arquivo da REDEMET. Exceção se o arquivo não existir."""
    png = _imagem_png(url)
    return png, validade_impressa(png)


def sigwx_do_voo(voo, api_key):
    """Cartas SIGWX que cobrem o voo (validade ±3 h, Doc 8896). Devolve lista de dicts
    {validade, titulo, url, png (ou None), nota}.

    Para cada validade necessária, abrimos os arquivos candidatos da REDEMET e LEMOS a
    validade impressa; só fica a carta que bate. Sem o leitor de texto, usamos o padrão
    mais comum (24 h) e avisamos para conferir."""
    etd, eta, _ = horarios(voo)
    cartas = []
    for v in rt.validades_do_voo(etd, eta, 6):
        for nome, faixa in CARTAS_SIGWX:
            uso = f"usar de {v - timedelta(hours=3):%d/%m %H}Z a {v + timedelta(hours=3):%d/%m %H}Z"
            carta = {"validade": v, "titulo": f"SIGWX {faixa} válida {v:%d/%m %H}Z", "url": None, "png": None,
                     "nota": f"carta desta validade ainda não está na REDEMET ({uso})."}
            sem_leitura = None
            for horas in DESLOCAMENTOS_SIGWX_H:
                url = URL_SIGWX.format(t=v - timedelta(hours=horas), nome=nome)
                try:
                    png, lida = _validade_do_arquivo(url)
                except Exception:
                    continue                          # arquivo não existe: tenta o próximo
                if lida == v:
                    carta.update(url=url, png=png, nota=f"Doc 8896: {uso}. Validade conferida na carta "
                                                        f"(arquivo {url.rsplit('/sigwx/', 1)[-1]}).")
                    break
                if lida is None and sem_leitura is None and horas == 24:
                    sem_leitura = (url, png)           # leitor indisponível: guarda o palpite mais provável
            if not carta["png"] and sem_leitura:
                url, png = sem_leitura
                carta.update(url=url, png=png, nota=f"Doc 8896: {uso}. ATENÇÃO: não foi possível ler a validade "
                                                    "na carta; confira o quadro VALID antes de usar.")
            cartas.append(carta)
    if not any(c["png"] for c in cartas):          # nenhuma por validade: mostra a mais recente da API
        url, erro = _sigwx_url(api_key)
        if url:
            try:
                png, lida = _validade_do_arquivo(url)
                quando = f" (válida {lida:%d/%m %H}Z)" if lida else ""
                cartas.append({"validade": None, "titulo": f"SIGWX SFC/FL250 mais recente{quando}",
                               "url": url, "png": png,
                               "nota": "A carta da validade do voo ainda não saiu; esta é a mais recente e NÃO "
                                       "vale para o horário do voo. Use só como referência."})
            except Exception:
                pass
    return cartas


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
def aba_sigwx(api_key, plano=None, voo=None):
    if plano:
        st.markdown(f"Cartas **SIGWX** para o voo ({txt_horarios(voo)}). Pelo **Doc 8896 (OACI), "
                    "item 5.3.3.4**, cada SIGWX pode ser usada de **3 h antes até 3 h depois** da validade; "
                    "voos longos precisam de mais de uma carta.")
        with st.spinner("Buscando as cartas na REDEMET..."):
            cartas = sigwx_do_voo(voo, api_key)
        for c in cartas:
            st.markdown(f"**{c['titulo']}** · {c['nota']}")
            if c["png"]:
                st.image(c["png"], use_container_width=True)
                st.caption(f"[Abrir a imagem original]({c['url']})")
        if not any(c["png"] for c in cartas):
            st.warning("A REDEMET não entregou nenhuma carta SIGWX agora (pode estar em manutenção).", icon="⚠️")
        st.caption("A carta de nível alto (FL250-FL630) ainda não está disponível por aqui.")
        return
    url, erro = _sigwx_url(api_key)
    if erro:
        st.warning(erro, icon="⚠️")
        return
    m = re.search(r"/(\d{4})/(\d{2})/(\d{2})/[a-z]*?(\d{2})\.\w+$", url)
    quando = f" · {m.group(3)}/{m.group(2)}/{m.group(1)} {m.group(4)}Z" if m else ""
    st.markdown(f"Carta **SIGWX SFC/FL250** mais recente da REDEMET{quando}. "
                f"[Abrir a imagem em tamanho real]({url})  \nPlaneje um voo para ver as cartas "
                "das validades do seu horário (Doc 8896: ±3 h).")
    st.image(url, use_container_width=True)


# ============================================================================
# 3) Vento na rota
# ============================================================================
def _pernas(plano):
    return [ad.COORDS[plano[0]], ad.COORDS[plano[1]]]


def _posicao(l):
    return f"{abs(l['lat']):.1f}{'S' if l['lat'] < 0 else 'N'} {abs(l['lon']):.1f}{'W' if l['lon'] < 0 else 'E'}"


def calcular_ventos(dados_val, fl, plano, voo):
    """Vento no FL escolhido e nos vizinhos (±2.000 ft). Devolve {fl: (linhas, resumo)}."""
    etd, _, eet = horarios(voo)
    return {n: rt.vento_na_rota(dados_val, n, _pernas(plano), etd, eet) for n in rt.niveis_vizinhos(fl)}


def tabela_comparacao(ventos, fl):
    return [{"Nível": fl_txt(n) + (" (escolhido)" if n == fl else ""),
             "Componente média": rt.texto_componente(r["componente_media"]),
             "Vento máximo": f"{r['vento_max']} kt",
             "Temperatura": f"{r['temp_min']} a {r['temp_max']} °C",
             "Desvio ISA": f"ISA{r['isa_desvio_medio']:+d}"} for n, (_, r) in ventos.items()]


def _tabela_vento(linhas):
    return [{"Nº": l["n"], "Distância": f"{l['dist_nm']} NM", "Hora": f"{l['hora']:%H:%M}Z",
             "Posição": _posicao(l), "Vento": l["vento"], "Temperatura": f"{l['temp_c']} °C",
             "Desvio ISA": f"ISA{l['isa_desvio']:+d}", "Componente": rt.texto_componente(l["componente"]),
             "GFS válido": f"{l['validade']:%d/%m %H}Z"} for l in linhas]


def resumo_vento_txt(res):
    return (f"Componente média na rota: {rt.texto_componente(res['componente_media'])}. "
            f"Vento máximo no nível: {res['vento_max']} kt. Temperatura de {res['temp_min']} a "
            f"{res['temp_max']} °C (ISA{res['isa_desvio_medio']:+d} em média).")


def _mapa_vento(dados_val, fl, plano, linhas):
    """Mapa de barbelas no FL, com a validade do MEIO do voo, e os pontos numerados da tabela."""
    from . import mapa_estatico as me
    validades = sorted({l["validade"] for l in linhas})
    meio = validades[len(validades) // 2]
    pontos = [ad.COORDS[i] for i in plano if i]
    return me.mapa_vento(rt.limites(pontos, margem_graus=1.2, minimo_graus=5), dados_val[meio], fl,
                         _pernas(plano), ad.COORDS[plano[2]] if plano[2] else None,
                         f"Vento {fl_txt(fl)} · GFS válido {meio:%d/%m %H}Z",
                         numerados=[(l["n"], l["lat"], l["lon"]) for l in linhas])


def aba_vento(plano, fl, voo):
    if not plano:
        st.info("Planeje um voo na barra lateral (origem, destino, nível e horário) para ver o vento na rota.",
                icon="🧭")
        return
    # O GFS pesa alguns MB por validade: só baixa quando o usuário pedir (depois fica no cache)
    if not st.session_state.get("vento_ligado"):
        st.caption(f"Vento e temperatura do modelo GFS no {fl_txt(fl)} e nos níveis vizinhos (±2.000 ft), "
                   f"ponto a ponto, na hora em que você passa por cada ponto ({txt_horarios(voo)}).")
        if st.button("🌬️ Calcular vento na rota", type="primary"):
            st.session_state["vento_ligado"] = True
            st.rerun()
        return
    with st.spinner("Baixando o modelo GFS das validades do voo (a primeira vez demora um pouco)..."):
        dados_val, infos, erros = gfs_do_voo(voo)
    for e in erros:
        st.warning(e, icon="⚠️")
    if not dados_val:
        return
    ventos = calcular_ventos(dados_val, fl, plano, voo)
    linhas, res = ventos[fl]
    validades = ", ".join(f"{v:%d/%m %H}Z" for v in res["validades"])
    st.markdown(f"**{txt_horarios(voo)}** · {res['distancia_nm']} NM · GFS válido {validades} "
                f"(Doc 8896: cada validade vale ±1,5 h)")
    st.markdown("**Comparação de níveis** (vizinhos no mesmo sentido de voo, ±2.000 ft)")
    st.dataframe(tabela_comparacao(ventos, fl), hide_index=True, use_container_width=True)
    escolha = st.radio("Detalhar o nível", list(ventos), index=list(ventos).index(fl), horizontal=True,
                       format_func=fl_txt)
    linhas, res = ventos[escolha]
    c = res["componente_media"]
    cor = "#d7263d" if c <= -15 else "#2e9e44" if c >= 15 else "#c9d3dc"
    st.markdown(f"<div style='font-size:1.05rem'>{fl_txt(escolha)} · componente média: "
                f"<b style='color:{cor}'>{rt.texto_componente(c)}</b></div>", unsafe_allow_html=True)
    st.dataframe(_tabela_vento(linhas), hide_index=True, use_container_width=True)
    try:
        st.image(_mapa_vento(dados_val, escolha, plano, linhas), use_container_width=True,
                 caption="Os números no mapa são os pontos da tabela.")
    except Exception as e:
        st.caption(f"Mapa de barbelas indisponível ({type(e).__name__}).")


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


def montar_briefing(plano, fl, voo, opcoes, corredor_nm, metars, tafs, avisos_ad, sigmets_txt,
                    pontos_raios, satelite=None, gfs_val=None, sigwx=None, agora=None):
    """Junta tudo num dicionário para o relatorio_pdf.gerar(). Não usa nada do Streamlit
    (assim dá para testar fora do site).
    opcoes  : conjunto com "mapa", "aerodromos", "em_rota", "sigmet", "raios", "vento", "sigwx"
    satelite: (data_url, limites, instante) ou None
    gfs_val : {validade: dados do GFS} ou None
    sigwx   : lista de cartas de sigwx_do_voo() ou None"""
    from . import mapa_estatico as me
    agora = agora or datetime.now(timezone.utc)
    origem, destino, altn = plano
    etd, eta, eet = horarios(voo)
    pernas = _pernas(plano)
    amostras = rt.pontos_da_rota(pernas, 10)
    b = {"origem": origem, "destino": destino, "altn": altn, "nivel": fl_txt(fl),
         "horarios": txt_horarios(voo),
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
        b["em_rota"] = [_cartao(f"Em rota ({d} NM da rota)", icao, metars, tafs, avisos_ad, agora)
                        for icao, d in em_rota]
    if "sigmet" in opcoes:
        b["sigmets"] = [(rd.decodificar_sigmet(t), t, no_nivel) for t, no_nivel in na_rota]
    if "raios" in opcoes:
        if n_raios:
            b["raios_txt"] = (f"{n_raios} descarga(s) na última hora a até {corredor_nm} NM da rota "
                              f"(as mais recentes: {rd.FAIXAS_RAIOS[faixa][2]}).")
        elif raio_perto is not None:
            b["raios_txt"] = (f"Nenhuma descarga no corredor de {corredor_nm} NM. "
                              f"A mais próxima está a cerca de {raio_perto} NM da rota.")
        else:
            b["raios_txt"] = "Nenhuma descarga atmosférica informada perto da rota na última hora."
        b["raios_txt"] += " (Raios são observação dos últimos 60 min, não previsão para a hora do voo.)"

    # ---------- resumo da primeira página ----------
    cats = [_cartao("", i, metars, tafs, avisos_ad, agora)["cat"] for i in plano if i]
    ordem = ["LIFR", "IFR", "MVFR", "VFR", "ND"]
    pior = min(cats, key=ordem.index) if cats else "ND"
    com_aviso = [i for i in [*plano, *(i for i, _ in em_rota)] if i and avisos_ad.get(i)]
    no_nivel = [t for t, n in na_rota if n]
    b["resumo"] = [
        ("Horários", txt_horarios(voo)),
        ("Categorias agora (FAA)", " · ".join(f"{i} {c}" for i, c in zip([i for i in plano if i], cats)) +
         f"  (pior: {pior})"),
        ("SIGMET perto da rota", f"{len(na_rota)}" + (f", {len(no_nivel)} no seu nível" if na_rota else "")),
        ("Raios no corredor", f"{n_raios} na última hora" if n_raios else "nenhum"),
        ("Aviso de aeródromo", ", ".join(com_aviso) if com_aviso else "nenhum vigente"),
        ("Aeródromos em rota", ", ".join(i for i, _ in em_rota) if em_rota else "nenhum no corredor"),
    ]

    # ---------- vento ----------
    if "vento" in opcoes:
        if gfs_val:
            ventos = calcular_ventos(gfs_val, fl, plano, voo)
            linhas, res = ventos[fl]
            validades = ", ".join(f"{v:%d/%m %H}Z" for v in res["validades"])
            try:
                png_v = _mapa_vento(gfs_val, fl, plano, linhas)
            except Exception:
                png_v = None
            b["vento"] = {
                "nivel": fl_txt(fl), "niveis": [fl_txt(n) for n in ventos], "fl": fl,
                "comparacao": tabela_comparacao(ventos, fl),
                "linhas": [{**l, "por_nivel": {fl_txt(n): ventos[n][0][i] for n in ventos}}
                           for i, l in enumerate(linhas)],
                "fonte": (f"Modelo GFS válido {validades}. Doc 8896 (OACI) 5.3.3.4: cada validade de vento/"
                          "temperatura vale de 1,5 h antes a 1,5 h depois; cada ponto usa a validade da hora "
                          "estimada de passagem. Níveis vizinhos = mesmo sentido de voo (±2.000 ft)."),
                "resumo_txt": resumo_vento_txt(res), "mapa_png": png_v}
            b["resumo"].insert(1, (f"Vento no {fl_txt(fl)}",
                                   f"{rt.texto_componente(res['componente_media'])} em média, "
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
        folha.titulo(f"{origem} -> {destino}" + (f" (altn {altn})" if altn else "") + f" · {fl_txt(fl)}")
        folha.legenda(me.legenda_padrao(bool(pontos_raios), bool(sigmets_txt), bool(altn)))
        b["mapa_png"] = folha.png()
        partes = []
        if satelite:
            partes.append(f"Situação ATUAL: satélite GOES-19 IR de {satelite[2]:%d/%m %H:%M}Z")
        partes.append(f"Etiquetas: categoria de voo FAA pelo METAR. Corredor da rota: {corredor_nm} NM.")
        if folha.avisos:
            partes.append("Mapa de fundo indisponível no momento.")
        b["mapa_legenda"] = ". ".join(partes)

    if "sigwx" in opcoes:
        b["sigwx"] = [c for c in (sigwx or []) if c["png"]]
        faltando = [c for c in (sigwx or []) if not c["png"] and c["validade"]]
        if not b["sigwx"]:
            b["indisponiveis"].append("carta SIGWX indisponível na REDEMET: o PDF saiu sem ela.")
        elif faltando:
            b["indisponiveis"].append("SIGWX não encontrada para: " +
                                      ", ".join(f"{c['validade']:%d/%m %H}Z" for c in faltando) + ".")
    return b


ITENS_PDF = {   # chave: (texto da caixa de seleção, marcada por padrão?)
    "mapa": ("🗺️ Mapa da rota (satélite IR, SIGMET, raios, aeródromos)", True),
    "aerodromos": ("📋 METAR / TAF de origem, destino e alternativa", True),
    "em_rota": ("🛬 METAR / TAF dos aeródromos no meio da rota", True),
    "sigmet": ("⚡ SIGMET que afetam a rota (decodificados)", True),
    "raios": ("🌩️ Raios perto da rota", True),
    "vento": ("🌬️ Vento e temperatura no nível e vizinhos (GFS)", True),
    "sigwx": ("🗺️ Cartas SIGWX das validades do voo", True),
}


def aba_gerar_voo(plano, fl, voo, api_key, fontes):
    """fontes = {"goes", "metars_e_tafs", "sigmets", "raios"} (funções com cache do app.py)"""
    if not plano:
        st.info("Planeje um voo na barra lateral (origem, destino, alternativa, nível e horário) "
                "para gerar o pacote de briefing em PDF.", icon="🧭")
        return
    st.markdown(f"Pacote de briefing do voo **{plano[0]} → {plano[1]}**"
                + (f" (altn {plano[2]})" if plano[2] else "") + f" no **{fl_txt(fl)}** · {txt_horarios(voo)}")
    with st.form("gerar_voo"):
        st.markdown("**O que entra no PDF**")
        c1, c2 = st.columns(2)
        marcados = set()
        for i, (k, (texto, padrao)) in enumerate(ITENS_PDF.items()):
            if (c1 if i % 2 == 0 else c2).checkbox(texto, value=padrao, key=f"pdf_{k}"):
                marcados.add(k)
        corredor = st.radio("Largura do corredor da rota (para cada lado)", CORREDORES, index=1, horizontal=True,
                            format_func=lambda n: f"{n} NM")
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
            gfs_val = None
            if "vento" in marcados:
                st.write("Modelo GFS das validades do voo")
                gfs_val, _, erros = gfs_do_voo(voo)
                for e in erros:
                    st.write(f"⚠️ {e}")
            sigwx = None
            if "sigwx" in marcados:
                st.write("Cartas SIGWX")
                sigwx = sigwx_do_voo(voo, api_key)
            st.write("Desenhando o mapa e o PDF")
            b = montar_briefing(plano, fl, voo, marcados, corredor, metars, tafs, avisos_ad, textos, pontos,
                                satelite, gfs_val, sigwx)
            pdf = relatorio_pdf.gerar(b)
            st.session_state["pdf_voo"] = {
                "bytes": pdf, "mapa": b.get("mapa_png"), "avisos": b["indisponiveis"],
                "nome": f"briefing_{plano[0]}_{plano[1]}_{horarios(voo)[0]:%d%m_%H%MZ}_{corredor}NM.pdf",
                "resumo": f"gerado às {datetime.now(timezone.utc):%H:%M}Z · corredor de {corredor} NM · "
                          f"{len(marcados)} item(ns)"}
            status.update(label="Briefing pronto!", state="complete", expanded=False)

    pronto = st.session_state.get("pdf_voo")
    if pronto:
        for a in pronto["avisos"]:
            st.warning(a, icon="⚠️")
        st.download_button("⬇️ Baixar o PDF do briefing", pronto["bytes"], pronto["nome"], "application/pdf",
                           type="primary")
        # O botão entrega SEMPRE o último PDF gerado: mudou as opções, tem que gerar de novo
        st.caption(f"PDF {pronto.get('resumo', '')}. Mudou alguma opção acima? Clique em "
                   "**Gerar voo (PDF)** de novo antes de baixar.")
        if pronto.get("mapa"):
            st.image(pronto["mapa"], caption="Prévia do mapa que está no PDF", use_container_width=True)
