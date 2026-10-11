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
from . import perfil_voo as pv
from . import opensky as osk
from . import tracklog as tl
from . import redemet as rd
from . import rota as rt

# Níveis de cruzeiro: de FL030 a FL450, de 10 em 10. O vento sai do GFS interpolado.
NIVEIS_CRUZEIRO = list(range(30, 460, 10))
CORREDORES = [25, 50, 100]          # NM para cada lado da rota
URL_SIGWX = "https://estatico-redemet.decea.mil.br/sigwx/{t:%Y/%m/%d}/{nome}{t:%H}.gif"
# Carta EMENDADA (AMD): mesmo lugar, outro nome. Visto em 10/10/2026: siginf-amd-00.gif
URL_SIGWX_AMD = "https://estatico-redemet.decea.mil.br/sigwx/{t:%Y/%m/%d}/{nome}-amd-{t:%H}.gif"
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


@st.cache_data(ttl=600, show_spinner=False)         # 10 min: uma emenda (AMD) pode sair a qualquer hora
def _lista_sigwx(chave):
    return rd.cartas_sigwx(chave)


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


def _mesma_validade(lida, v):
    """A validade lida na imagem bate com a do voo? Comparamos dia, mês e hora e IGNORAMOS o
    ano: em 10/10/2026 o leitor de texto leu "11-OCT-2025" numa carta de 2026 (o 6 virou 5)
    e o site descartou a carta certa."""
    return lida is not None and (lida.month, lida.day, lida.hour) == (v.month, v.day, v.hour)


def _nota_amd(c):
    quando = f" em {c['emitida']:%d/%m %H:%M}Z" if c.get("emitida") else ""
    return (f"⚠️ CARTA EMENDADA (AMD), publicada{quando}: substitui a versão original desta validade. "
            "Confira se não saiu outra emenda depois. ")


def sigwx_do_voo(voo, api_key):
    """Cartas SIGWX que cobrem o voo (validade ±3 h, Doc 8896). Devolve lista de dicts
    {validade, titulo, url, png (ou None), nota, amd}.

    1º caminho: a LISTA de cartas da REDEMET (rd.cartas_sigwx), que já diz a validade e se a
       carta foi EMENDADA (AMD). Havendo AMD para a validade, ela é a escolhida.
    2º caminho (reserva, se a lista falhar): abrir os arquivos candidatos e LER a validade
       impressa na carta (Tesseract), como era antes."""
    etd, eta, _ = horarios(voo)
    lista, erro_lista = _lista_sigwx(api_key)
    cartas = []
    for v in rt.validades_do_voo(etd, eta, 6):
        for nome, faixa in CARTAS_SIGWX:
            uso = f"usar de {v - timedelta(hours=3):%d/%m %H}Z a {v + timedelta(hours=3):%d/%m %H}Z"
            carta = {"validade": v, "titulo": f"SIGWX {faixa} válida {v:%d/%m %H}Z", "url": None, "png": None,
                     "amd": False, "nota": f"carta desta validade ainda não está na REDEMET ({uso})."}

            # --- 1º caminho: a lista da REDEMET ---------------------------------------
            candidatas = [c for c in lista if c["validade"] == v and c["arquivo"].startswith(nome)]
            # ordem de preferência: AMD antes da original; entre iguais, a publicada por último
            candidatas.sort(key=lambda c: (c["amd"], c["emitida"] or v), reverse=True)
            for c in candidatas:
                try:
                    png = _imagem_png(c["url"])
                except Exception:
                    continue                          # imagem não abriu: tenta a próxima
                carta.update(url=c["url"], png=png, amd=c["amd"],
                             nota=(_nota_amd(c) if c["amd"] else "") +
                                  f"Doc 8896: {uso}. Validade informada pela REDEMET (arquivo {c['arquivo']}).")
                if c["amd"]:
                    carta["titulo"] += " — EMENDADA (AMD)"
                break

            # --- 2º caminho (reserva): ler a validade impressa na imagem ----------------
            if not carta["png"] and erro_lista:
                sem_leitura = None
                for horas in DESLOCAMENTOS_SIGWX_H:
                    t = v - timedelta(hours=horas)
                    # a emenda primeiro (siginf-amd-00.gif), depois a original (siginf00.gif)
                    for amd, url in ((True, URL_SIGWX_AMD.format(t=t, nome=nome)),
                                     (False, URL_SIGWX.format(t=t, nome=nome))):
                        try:
                            png, lida = _validade_do_arquivo(url)
                        except Exception:
                            continue                  # arquivo não existe: tenta o próximo
                        if _mesma_validade(lida, v):
                            arq = url.rsplit('/sigwx/', 1)[-1]
                            carta.update(url=url, png=png, amd=amd,
                                         nota=(_nota_amd({}) if amd else "") +
                                              f"Doc 8896: {uso}. Validade conferida na carta (arquivo {arq}).")
                            if amd:
                                carta["titulo"] += " — EMENDADA (AMD)"
                            break
                        if lida is None and sem_leitura is None and horas == 24 and not amd:
                            sem_leitura = (url, png)   # leitor indisponível: guarda o palpite mais provável
                    if carta["png"]:
                        break
                if not carta["png"] and sem_leitura:
                    url, png = sem_leitura
                    carta.update(url=url, png=png, nota=f"Doc 8896: {uso}. ATENÇÃO: não foi possível ler a "
                                                        "validade na carta; confira o quadro VALID antes de usar.")
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
            if c.get("amd"):
                st.warning(f"**{c['titulo']}**: a CIMAER emendou esta carta. O site mostra a versão "
                           "emendada (AMD), que substitui a original.", icon="⚠️")
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
def rota_ativa(plano):
    """A rota por aerovias (lida em modulos/aerovias.py e guardada na sessão pelo app.py),
    se ela pertencer a ESTE plano (mesma origem e destino). Senão None = linha reta.
    O try/except deixa a função funcionar também fora do site (testes, sem Streamlit)."""
    try:
        r = st.session_state.get("rota")
    except Exception:
        return None
    if r and plano and r.get("od") == (plano[0], plano[1]):
        return r
    return None


def _pernas(plano):
    """Pontos [lat, lon] por onde o voo passa: origem, fixos da rota (se houver) e destino.
    TUDO que segue a rota (vento, SIGMET e raios no corredor, aeródromos em rota, mapa do PDF)
    usa esta lista, então mudar só aqui já faz o resto seguir a aerovia."""
    r = rota_ativa(plano)
    meio = [[p["lat"], p["lon"]] for p in r["pontos"]] if r else []
    return [ad.COORDS[plano[0]], *meio, ad.COORDS[plano[1]]]


def distancia_total(pernas):
    """Soma das pernas (com rota por aerovia a distância é maior que a linha reta)."""
    return sum(rt.distancia_nm(a, b) for a, b in zip(pernas, pernas[1:]))


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


def _tabela_vento(linhas, perfil=None):
    """perfil (opcional) = resultado de pv.calcular(): acrescenta a coluna Fase (subida/cruzeiro/descida)."""
    return [{"Nº": l["n"], "Distância": f"{l['dist_nm']} NM",
             **({"Fase": pv.texto_fase(perfil, l["dist_nm"])} if perfil else {}),
             "Hora": f"{l['hora']:%H:%M}Z",
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
    pontos = [ad.COORDS[i] for i in plano if i] + _pernas(plano)
    return me.mapa_vento(rt.limites(pontos, margem_graus=1.2, minimo_graus=5), dados_val[meio], fl,
                         _pernas(plano), ad.COORDS[plano[2]] if plano[2] else None,
                         f"Vento {fl_txt(fl)} · GFS válido {meio:%d/%m %H}Z",
                         numerados=[(l["n"], l["lat"], l["lon"]) for l in linhas])


# ----------------------------------------------------------------------------
# Perfil vertical (TOC/TOD) - SIMULADO. A conta está em modulos/perfil_voo.py
# ----------------------------------------------------------------------------
def aeronave_escolhida():
    """Tipo escolhido no formulário (guardado na sessão). Fora do site: o padrão (A320)."""
    try:
        return st.session_state.get("aeronave") or pv.PADRAO
    except Exception:
        return pv.PADRAO


def perfil_do_voo(plano, fl, aeronave=None, vento_kt=0):
    """Calcula o perfil com a distância REAL da rota (aerovias, se houver) e a elevação dos aeródromos."""
    return pv.calcular(aeronave or aeronave_escolhida(), fl, distancia_total(_pernas(plano)),
                       pv.ELEVACAO_FT.get(plano[0], 0), pv.ELEVACAO_FT.get(plano[1], 0), vento_kt)


def _avisos_elevacao(plano):
    faltam = [i for i in plano[:2] if i not in pv.ELEVACAO_FT]
    return (f"Elevação não cadastrada para {', '.join(faltam)}: considerada 0 ft." if faltam else "")


def bloco_perfil(plano, fl, voo, vento_kt=None):
    """Quadro do perfil vertical na aba de vento. vento_kt = componente média no nível (None = sem GFS)."""
    p = perfil_do_voo(plano, fl, vento_kt=vento_kt or 0)
    etd, _, eet = horarios(voo)
    st.markdown(f"**📈 Perfil vertical simulado · {p['nome']} · {fl_txt(fl)}**")
    for a in p["avisos"]:
        st.warning(a, icon="⚠️")
    if p["atinge_nivel"]:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("TOC (topo da subida)", f"{p['toc_nm']:.0f} NM",
                  f"{p['toc_min']:.0f} min · {etd + timedelta(minutes=p['toc_min']):%H:%M}Z", delta_color="off")
        c2.metric("TOD (início da descida)", f"{p['tod_nm']:.0f} NM antes",
                  f"descida de ~{p['tod_min']:.0f} min", delta_color="off")
        c3.metric("Regra prática 3:1", f"{p['regra_3x1_nm']:.0f} NM antes",
                  "3 NM por 1.000 ft a perder", delta_color="off")
        c4.metric("EET pelo perfil", f"{int(p['eet_perfil_min']) // 60:02d}:{int(p['eet_perfil_min']) % 60:02d}",
                  f"você informou {eet // 60:02d}:{eet % 60:02d}", delta_color="off")
    real = st.session_state.get("tracklog_real")
    st.image(pv.grafico_png(p, real=real), use_container_width=True)
    extra = _avisos_elevacao(plano)
    st.caption(("Vento: " + (f"{rt.texto_componente(vento_kt)} no cruzeiro e metade disso na subida/descida. "
                             if vento_kt is not None else "sem vento (calcule o vento na rota para incluí-lo). "))
               + f"Fonte dos desempenhos: {pv.FONTE}. Peso, temperatura, SID/STAR e ATC mudam tudo isso: "
               "é um exercício de planejamento, não o perfil do FMS. " + extra)
    comparar_voo_real(p, real, plano)
    return p


def _mmss(minutos):
    return "—" if minutos is None else f"{int(minutos) // 60:02d}:{int(round(minutos)) % 60:02d}"


def tabela_comparacao_real(p, r):
    """Simulado × real, linha a linha (tudo em texto para a tabela ficar alinhada)."""
    subir = p["fl"] * 100 - p["elev_origem"]
    roc_sim = subir / p["toc_min"] if p["toc_min"] else None
    rod_sim = (p["fl"] * 100 - p["elev_destino"]) / p["tod_min"] if p["tod_min"] else None
    nm1000_sim = p["tod_nm"] / max((p["fl"] * 100 - p["elev_destino"]) / 1000, 0.1)
    def n(v, fmt="{:.0f}"):
        return "—" if v is None else fmt.format(v)
    linhas = [
        ("Nível de cruzeiro", f"FL{p['fl']:03d}", f"FL{r['nivel_fl']:03d}"),
        ("TOC: distância da decolagem", n(p["toc_nm"], "{:.0f} NM"), n(r["toc_nm"], "{:.0f} NM")),
        ("TOC: tempo de subida", n(p["toc_min"], "{:.0f} min"), n(r["toc_min"], "{:.0f} min")),
        ("Razão média de subida", n(roc_sim, "{:.0f} ft/min"), n(r["roc_medio"], "{:.0f} ft/min")),
        ("TOD: distância antes do destino", n(p["tod_nm"], "{:.0f} NM"), n(r["tod_nm"], "{:.0f} NM")),
        ("Descida: duração", n(p["tod_min"], "{:.0f} min"), n(r["tod_min"], "{:.0f} min")),
        ("Razão média de descida", n(rod_sim, "{:.0f} ft/min"), n(r["rod_medio"], "{:.0f} ft/min")),
        ("NM por 1.000 ft na descida (regra: 3)", f"{nm1000_sim:.1f}", f"{r['nm_por_1000ft']:.1f}"),
        ("Distância percorrida", f"{p['dist_total_nm']:.0f} NM", f"{r['total_nm']:.0f} NM"),
        ("Tempo em voo (decolagem ao pouso)", _mmss(p["eet_perfil_min"]), _mmss(r["total_min"])),
    ]
    return [{"Item": a, "Simulado": b, "Voo real": c} for a, b, c in linhas]


def _cred_opensky():
    """(client_id, client_secret) dos Secrets do Streamlit, ou (None, None) se não houver."""
    try:
        return st.secrets.get("OPENSKY_CLIENT_ID"), st.secrets.get("OPENSKY_CLIENT_SECRET")
    except Exception:
        return None, None


@st.cache_data(ttl=3600, show_spinner=False)          # voos de dias passados não mudam
def _voos_do_dia(origem, destino, dia, cred):
    return osk.voos_do_dia(origem, destino, dia, cred)


@st.cache_data(ttl=30, show_spinner=False)            # ao vivo: 30 s
def _no_ar(limites, cred):
    return osk.no_ar_perto(limites, cred)


def _guardar_real(pontos, origem_txt, ao_vivo=False, margem_ft=300):
    real = tl.perfil_real(pontos, margem_ft)
    real.update(fonte=origem_txt, ao_vivo=ao_vivo)
    st.session_state["tracklog_real"] = real
    st.rerun()


def _escolher_e_comparar(voos, chave, cred, ao_vivo=False):
    """Caixa de seleção com os voos + botão que baixa a trajetória e compara."""
    escolha = st.selectbox("Escolha o voo", voos, format_func=lambda v: v["rotulo"], key=f"os_sel_{chave}")
    if st.button("📊 Comparar este voo", type="primary", key=f"os_cmp_{chave}"):
        try:
            with st.spinner("Baixando a trajetória na OpenSky..."):
                pontos = osk.trajetoria(escolha["icao24"], escolha["meio"], cred)
            # a OpenSky arredonda a altitude da trajetória em degraus de 1.000 ft
            _guardar_real(pontos, f"{escolha['indicativo']} (OpenSky" + (", ao vivo)" if ao_vivo else ")"),
                          ao_vivo, margem_ft=1000)
        except osk.ErroOpenSky as e:
            st.warning(str(e), icon="⚠️")
        except Exception as e:
            st.warning(f"OpenSky indisponível agora ({type(e).__name__}). Use a aba Colar track log.", icon="⚠️")


def comparar_voo_real(p, real, plano):
    """Caixa para comparar o perfil simulado com um voo REAL: buscando na OpenSky
    (voos de ontem para trás, ou no ar agora) ou colando o track log do FlightAware."""
    titulo = "🛰️ Comparar com um voo real" + (f" · {real['fonte']}" if real and real.get("fonte") else "")
    with st.expander(titulo, expanded=bool(real)):
        st.caption("Para uma comparação justa, planeje aqui a mesma origem, destino, rota, nível e tipo de "
                   "aeronave do voo real.")
        cred = _cred_opensky()
        aba_busca, aba_vivo, aba_colar = st.tabs(["🔎 Buscar voo (OpenSky)", "📡 No ar agora", "📋 Colar track log"])

        with aba_busca:
            if not all(cred):
                st.info("Para buscar voos passados, cadastre OPENSKY_CLIENT_ID e OPENSKY_CLIENT_SECRET nos "
                        "Secrets do Streamlit (conta gratuita em opensky-network.org).", icon="🔑")
            ontem = (datetime.now(timezone.utc) - timedelta(days=1)).date()
            dia = st.date_input("Dia do voo (UTC)", ontem, min_value=ontem - timedelta(days=29), max_value=ontem,
                                format="DD/MM/YYYY", key="os_dia",
                                help="A OpenSky fecha a lista de voos à noite: só há voos de ontem para trás, "
                                     "e trajetórias só dos últimos 30 dias.")
            st.caption(f"Voos de **{plano[0]} → {plano[1]}** nesse dia (destino estimado pela OpenSky).")
            if st.button("🔎 Listar voos", key="os_listar"):
                try:
                    with st.spinner("Consultando a OpenSky..."):
                        st.session_state["os_voos"] = _voos_do_dia(plano[0], plano[1], dia, cred)
                except osk.ErroOpenSky as e:
                    st.session_state.pop("os_voos", None)
                    st.warning(str(e), icon="⚠️")
                except Exception as e:
                    st.warning(f"OpenSky indisponível agora ({type(e).__name__}).", icon="⚠️")
            voos = st.session_state.get("os_voos")
            if voos == []:
                st.caption("Nenhum voo encontrado entre esses aeródromos nesse dia.")
            elif voos:
                _escolher_e_comparar(voos, "dia", cred)

        with aba_vivo:
            st.caption("Aviões no ar agora perto da sua rota (funciona até sem conta). "
                       "Se o voo ainda não pousou, o TOD real ainda não aconteceu.")
            if st.button("📡 Ver quem está no ar", key="os_vivo"):
                pts = _pernas(plano)
                lats, lons = [a for a, _ in pts], [b for _, b in pts]
                limites = (round(min(lats) - 1, 1), round(min(lons) - 1, 1),
                           round(max(lats) + 1, 1), round(max(lons) + 1, 1))
                try:
                    st.session_state["os_no_ar"] = _no_ar(limites, cred)
                except Exception as e:
                    st.warning(str(e) if isinstance(e, osk.ErroOpenSky)
                               else f"OpenSky indisponível agora ({type(e).__name__}).", icon="⚠️")
            no_ar = st.session_state.get("os_no_ar")
            if no_ar == []:
                st.caption("Nenhum avião no ar nessa região agora.")
            elif no_ar:
                _escolher_e_comparar(no_ar, "vivo", cred, ao_vivo=True)

        with aba_colar:
            st.caption("No FlightAware, abra o voo, clique em **Exibir o track log**, selecione a tabela inteira "
                       "(do cabeçalho até a chegada), copie e cole abaixo. Também vale o CSV ou o KML do botão "
                       "**Google Earth**.")
            texto = st.text_area("Cole aqui a tabela do track log", height=110, key="tl_texto",
                                 placeholder="Horário  Latitude  Longitude  Rota  nós  km/h  metros  Taxa ...")
            arq = st.file_uploader("ou envie o arquivo (CSV ou KML)", type=["csv", "txt", "kml", "kmz"],
                                   key="tl_arquivo")
            if st.button("📊 Comparar", type="primary", key="tl_comparar"):
                pontos, erro = tl.ler(texto=texto, arquivo=arq.getvalue() if arq else None,
                                      nome_arquivo=arq.name if arq else "")
                if erro:
                    st.warning(erro, icon="⚠️")
                else:
                    _guardar_real(pontos, "track log colado")

        if real and st.button("🧹 Limpar comparação", key="tl_limpar"):
            st.session_state.pop("tracklog_real", None)
            st.rerun()
        if real:
            if abs(real["nivel_fl"] - p["fl"]) >= 10:
                st.info(f"O voo real nivelou no FL{real['nivel_fl']:03d} e o seu plano está no {fl_txt(p['fl'])}. "
                        f"Para comparar no mesmo nível, planeje no FL{real['nivel_fl']:03d}.", icon="ℹ️")
            if real["total_min"] is None:
                st.caption("O arquivo não trouxe a hora de cada ponto: comparamos só as distâncias.")
            st.dataframe(tabela_comparacao_real(p, real), hide_index=True, use_container_width=True)
            st.caption("Linha verde no gráfico = voo real. TOC/TOD reais = primeiro e último ponto a menos de "
                       "300 ft do nível máximo. A descida real costuma começar antes (STAR, restrições do ATC, "
                       "vetores) e a subida de um avião leve costuma ser mais rápida que a média da tabela.")


def aba_vento(plano, fl, voo):
    if not plano:
        st.info("Preencha os Dados do voo (lá em cima) e clique em Planejar voo para ver o vento na rota.",
                icon="🧭")
        return
    # O GFS pesa alguns MB por validade: só baixa quando o usuário pedir (depois fica no cache)
    if not st.session_state.get("vento_ligado"):
        bloco_perfil(plano, fl, voo)
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
    perfil = bloco_perfil(plano, fl, voo, res["componente_media"])
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
    # a coluna Fase só faz sentido no nível do perfil (o escolhido)
    st.dataframe(_tabela_vento(linhas, perfil if escolha == fl else None), hide_index=True,
                 use_container_width=True)
    if escolha == fl:
        st.caption("Fase: onde o avião estaria pelo perfil simulado. Nos pontos em subida/descida o vento "
                   f"da tabela é o do {fl_txt(fl)}, não o da altitude real do avião naquele ponto.")
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
                    pontos_raios, satelite=None, gfs_val=None, sigwx=None, agora=None, aeronave=None):
    """Junta tudo num dicionário para o relatorio_pdf.gerar(). Não usa nada do Streamlit
    (assim dá para testar fora do site).
    opcoes  : conjunto com "mapa", "aerodromos", "em_rota", "sigmet", "raios", "vento", "sigwx"
    satelite: (data_url, limites, instante) ou None
    gfs_val : {validade: dados do GFS} ou None
    sigwx   : lista de cartas de sigwx_do_voo() ou None
    aeronave: código de pv.AERONAVES para o perfil TOC/TOD (None = A320)"""
    from . import mapa_estatico as me
    agora = agora or datetime.now(timezone.utc)
    origem, destino, altn = plano
    etd, eta, eet = horarios(voo)
    pernas = _pernas(plano)
    amostras = rt.pontos_da_rota(pernas, 10)
    b = {"origem": origem, "destino": destino, "altn": altn, "nivel": fl_txt(fl),
         "horarios": txt_horarios(voo),
         # distância = soma das pernas; rumo = direção geral de origem para destino
         "distancia_nm": round(distancia_total(pernas)), "rumo": round(rt.rumo_verdadeiro(pernas[0], pernas[-1])),
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
    rota = rota_ativa(plano)
    b["resumo"] = [
        ("Rota", (rota["texto"] + f"  ({b['distancia_nm']} NM)") if rota
         else f"direta (linha reta, {b['distancia_nm']} NM)"),
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
                "resumo_txt": resumo_vento_txt(res), "mapa_png": png_v,
                "componente_media": res["componente_media"]}
            b["resumo"].insert(1, (f"Vento no {fl_txt(fl)}",
                                   f"{rt.texto_componente(res['componente_media'])} em média, "
                                   f"máx. {res['vento_max']} kt"))
        else:
            b["indisponiveis"].append("modelo GFS indisponível: o PDF saiu sem a parte de vento.")

    # ---------- perfil vertical (TOC/TOD) ----------
    if "perfil" in opcoes:
        vento_kt = b["vento"]["componente_media"] if b.get("vento") else None
        p = perfil_do_voo(plano, fl, aeronave, vento_kt or 0)
        b["perfil"] = {"txt": pv.resumo_txt(p, etd), "png": pv.grafico_png(p), "avisos": p["avisos"],
                       "nota": (f"Regra prática 3:1: TOD a {p['regra_3x1_nm']:.0f} NM do destino. "
                                + (f"EET estimado pelo perfil: {int(p['eet_perfil_min']) // 60:02d}:"
                                   f"{int(p['eet_perfil_min']) % 60:02d}. " if p["eet_perfil_min"] else "")
                                + ("Vento: " + rt.texto_componente(vento_kt) + " no cruzeiro e metade na "
                                   "subida/descida. " if vento_kt is not None else "Calculado sem vento. ")
                                + f"Desempenhos: {pv.FONTE}. " + _avisos_elevacao(plano))}
        b["resumo"].insert(2, ("Perfil (simulado)", pv.resumo_txt(p)))
        if b.get("vento"):
            for l in b["vento"]["linhas"]:
                l["fase"] = pv.texto_fase(p, l["dist_nm"])

    # ---------- mapa ----------
    if "mapa" in opcoes:
        pts = [ad.COORDS[i] for i in plano if i] + pernas
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
            tipo = "visível (cores reais)" if len(satelite) > 3 and satelite[3].get("canal") == "VIS" else "IR"
            partes.append(f"Situação ATUAL: satélite GOES-19 {tipo} de {satelite[2]:%d/%m %H:%M}Z")
        partes.append(f"Etiquetas: categoria de voo FAA pelo METAR. Corredor da rota: {corredor_nm} NM")
        if folha.avisos:
            partes.append("Mapa de fundo indisponível no momento.")
        b["mapa_legenda"] = ". ".join(partes)

    if "sigwx" in opcoes:
        b["sigwx"] = [c for c in (sigwx or []) if c["png"]]
        for c in b["sigwx"]:
            if c.get("amd"):
                b["indisponiveis"].append(f"SIGWX válida {c['validade']:%d/%m %H}Z foi EMENDADA (AMD): "
                                          "o briefing usa a versão emendada.")
        faltando = [c for c in (sigwx or []) if not c["png"] and c["validade"]]
        if not b["sigwx"]:
            b["indisponiveis"].append("carta SIGWX indisponível na REDEMET: o PDF saiu sem ela.")
        elif faltando:
            b["indisponiveis"].append("SIGWX não encontrada para: " +
                                      ", ".join(f"{c['validade']:%d/%m %H}Z" for c in faltando) + ".")
    return b


ITENS_PDF = {   # chave: (texto da caixa de seleção, marcada por padrão?)
    "mapa": ("🗺️ Mapa da rota (satélite, SIGMET, raios, aeródromos)", True),
    "aerodromos": ("📋 METAR / TAF de origem, destino e alternativa", True),
    "em_rota": ("🛬 METAR / TAF dos aeródromos no meio da rota", True),
    "sigmet": ("⚡ SIGMET que afetam a rota (decodificados)", True),
    "raios": ("🌩️ Raios perto da rota", True),
    "vento": ("🌬️ Vento e temperatura no nível e vizinhos (GFS)", True),
    "perfil": ("📈 Perfil vertical simulado (TOC/TOD)", True),
    "sigwx": ("🗺️ Cartas SIGWX das validades do voo", True),
}


def aba_gerar_voo(plano, fl, voo, api_key, fontes):
    """fontes = {"goes", "metars_e_tafs", "sigmets", "raios"} (funções com cache do app.py)"""
    if not plano:
        st.info("Preencha os Dados do voo (lá em cima) e clique em Planejar voo "
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
        canal_sat = st.radio("Satélite no mapa do PDF", ["IR", "VIS"], horizontal=True,
                             format_func=lambda c: "Infravermelho (topo das nuvens)" if c == "IR"
                             else "Visível em cores reais (só de dia)")
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
                    satelite = fontes["goes"](canal_sat)
                    # recorte detalhado (~2 km) da região da rota, do mesmo horário: PDF bem mais nítido
                    if "goes_rota" in fontes:
                        from . import satelite as sat_mod
                        regiao = sat_mod.regiao_da_rota([ad.COORDS[i] for i in plano if i])
                        try:
                            satelite = fontes["goes_rota"](canal_sat, regiao, satelite[3]["arquivo"])
                        except Exception:
                            pass                      # fica com a imagem geral
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
                                satelite, gfs_val, sigwx, aeronave=aeronave_escolhida())
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
