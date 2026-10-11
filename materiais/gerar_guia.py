"""Gera o guia do aluno: materiais/Guia_Planejamento_de_Voo.pdf

Como usar (no seu computador ou no Colab, dentro da pasta do repositório):
    python materiais/gerar_guia.py

O texto do guia está todo AQUI, em blocos (capa, passo 1, passo 2...). Mudou o site?
Edite o bloco correspondente e rode de novo. As figuras ficam em materiais/imagens_guia/
(prints do site; para trocar um print, salve por cima com o mesmo nome).
A figura do exemplo de rota é desenhada pelo próprio script (função figura_rota).
"""
import io
import math
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

PASTA = Path(__file__).parent
IMG = PASTA / "imagens_guia"
SAIDA = PASTA / "Guia_Planejamento_de_Voo.pdf"

# ---------------------------------------------------------------------------
# Cores (as mesmas do site)
# ---------------------------------------------------------------------------
AZUL_TOPO = colors.HexColor("#0b1a27")
AZUL = colors.HexColor("#13263a")
AMARELO = colors.HexColor("#f1c40f")
LARANJA = colors.HexColor("#e67e00")
FUNDO_LARANJA = colors.HexColor("#fff1e0")
FUNDO_AMARELO = colors.HexColor("#fff9e0")
FUNDO_CIANO = colors.HexColor("#e6fbfd")
CIANO = colors.HexColor("#00b8c8")
CINZA = colors.HexColor("#5c6c79")
LINHA = colors.HexColor("#d5dbe0")

LARG = A4[0] - 36 * mm          # largura útil da página

# ---------------------------------------------------------------------------
# Estilos de texto
# ---------------------------------------------------------------------------
def estilo(nome, **k):
    base = dict(fontName="Helvetica", fontSize=9.5, leading=13.2, textColor=colors.HexColor("#1d2731"))
    base.update(k)
    return ParagraphStyle(nome, **base)

TXT = estilo("txt")
TXT_P = estilo("txt_p", fontSize=8.6, leading=11.6)
LEGENDA = estilo("leg", fontName="Helvetica-Oblique", fontSize=8, leading=10.5, textColor=CINZA)
H1 = estilo("h1", fontName="Helvetica-Bold", fontSize=24, leading=28, textColor=AZUL)
SUB = estilo("sub", fontSize=11, leading=15, textColor=CINZA)
H3 = estilo("h3", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=AZUL, spaceBefore=4)
BARRA = estilo("barra", fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=colors.white)
CEL = estilo("cel", fontSize=8.6, leading=11.3)
CEL_B = estilo("cel_b", fontName="Helvetica-Bold", fontSize=8.6, leading=11.3)
CEL_CAB = estilo("cel_cab", fontName="Helvetica-Bold", fontSize=8.6, leading=11.3, textColor=colors.white)
MONO = estilo("mono", fontName="Courier-Bold", fontSize=10, leading=13, textColor=colors.HexColor("#0b3d44"))
NUM = estilo("num", fontName="Helvetica-Bold", fontSize=20, leading=22, textColor=AMARELO)
CARD_T = estilo("card_t", fontName="Helvetica-Bold", fontSize=9, leading=11.5, textColor=colors.white)
CARD_X = estilo("card_x", fontSize=7.6, leading=9.8, textColor=colors.HexColor("#c9d3dc"))


def p(texto, st=TXT):
    return Paragraph(texto, st)


def lista(itens, st=TXT):
    """Lista com marcadores."""
    return [Paragraph(f"• {t}", ParagraphStyle("li", parent=st, leftIndent=10, firstLineIndent=-8,
                                               spaceAfter=1.5)) for t in itens]


def secao(titulo, novo=False):
    """Barra azul-escura com o título da seção (e um selo NOVO, se for o caso)."""
    t = titulo + ("  <font color='#f1c40f' size='8.5'>&nbsp;&nbsp;NOVO</font>" if novo else "")
    tb = Table([[Paragraph(t, BARRA)]], colWidths=[LARG])
    tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), AZUL), ("LEFTPADDING", (0, 0), (-1, -1), 9),
                            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                            ("LINEBELOW", (0, 0), (-1, -1), 2, AMARELO)]))
    return [Spacer(1, 4), tb, Spacer(1, 7)]


def caixa(titulo, conteudo, fundo=FUNDO_LARANJA, borda=LARANJA):
    """Caixa de destaque com barra colorida à esquerda (Antes de começar, Dica de instrutor...)."""
    corpo = [Paragraph(f"<b>{titulo}</b>", TXT)] + (conteudo if isinstance(conteudo, list) else [p(conteudo)])
    tb = Table([[corpo]], colWidths=[LARG])
    tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fundo), ("LINEBEFORE", (0, 0), (0, -1), 3.5, borda),
                            ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return [Spacer(1, 4), tb, Spacer(1, 8)]


def tabela(cabecalho, linhas, larguras, mono_col=None):
    """Tabela com cabeçalho azul e linhas finas. mono_col = coluna em fonte de máquina (rota)."""
    dados = [[Paragraph(c, CEL_CAB) for c in cabecalho]]
    for ln in linhas:
        dados.append([Paragraph(c, estilo("m", fontName="Courier-Bold", fontSize=8.6, leading=11.3)
                                if i == mono_col else (CEL_B if i == 0 else CEL)) for i, c in enumerate(ln)])
    tb = Table(dados, colWidths=[LARG * f for f in larguras], repeatRows=1)
    tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), AZUL), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LINEBELOW", (0, 1), (-1, -1), 0.5, LINHA), ("BOX", (0, 0), (-1, -1), 0.5, LINHA),
                            ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    return tb


def figura(nome, largura, legenda=None, altura_max=None, em_tabela=False):
    """Imagem de materiais/imagens_guia/ (ou bytes), mantendo a proporção."""
    fonte = IMG / nome if isinstance(nome, str) else nome
    from PIL import Image as PILImage
    with PILImage.open(fonte if isinstance(fonte, Path) else io.BytesIO(fonte.getvalue())) as im:
        w, h = im.size
    alt = largura * h / w
    if altura_max and alt > altura_max:
        largura, alt = largura * altura_max / alt, altura_max
    if not isinstance(fonte, Path):
        fonte.seek(0)
    img = Image(str(fonte) if isinstance(fonte, Path) else fonte, width=largura, height=alt)
    partes = [img]
    if legenda:
        partes += [Spacer(1, 2), p(legenda, LEGENDA)]
    if em_tabela:                       # dentro de uma célula de tabela: lista simples
        return partes
    return KeepTogether(partes + [Spacer(1, 6)])


def fichas_rota(fichas):
    """A rota 'desmontada': cada palavra numa ficha colorida conforme o que ela é."""
    cores = {"fixo": (colors.HexColor("#d9fbff"), CIANO), "via": (colors.HexColor("#e4e9ff"), colors.HexColor("#4b67e0")),
             "ign": (colors.HexColor("#eeeeee"), colors.HexColor("#9a9a9a"))}
    linha1, linha2, estilos = [], [], []
    for k, (txt, tipo, rot) in enumerate(fichas):
        fundo, borda = cores[tipo]
        linha1.append(Paragraph(f"<font name='Courier-Bold' size='9.5'>{txt}</font>",
                                ParagraphStyle("f", alignment=TA_CENTER, leading=12)))
        linha2.append(Paragraph(rot, ParagraphStyle("fr", fontSize=6.8, leading=8.2, alignment=TA_CENTER,
                                                    textColor=CINZA)))
        estilos += [("BACKGROUND", (k, 0), (k, 0), fundo), ("BOX", (k, 0), (k, 0), 0.9, borda)]
    tb = Table([linha1, linha2], colWidths=[LARG / len(fichas)] * len(fichas))
    tb.setStyle(TableStyle(estilos + [("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, 0), 5),
                                      ("BOTTOMPADDING", (0, 0), (-1, 0), 5), ("LEFTPADDING", (0, 0), (-1, -1), 2),
                                      ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
    return [tb, Spacer(1, 8)]


# ---------------------------------------------------------------------------
# Figura do exemplo: SBGR -> SBBR pela UZ26 (coordenadas reais do GEOAISWEB, emenda 01/10/2026)
# ---------------------------------------------------------------------------
EXEMPLO = [("SBGR", -23.4356, -46.4731, "ad"), ("GERKA", -22.551304, -47.076787, "fixo"),
           ("ISMOB", -21.789178, -47.197016, "fixo"), ("BIXAN", -21.360347, -47.253242, "fixo"),
           ("KEXIT", -20.583617, -47.382581, "fixo"), ("KOMLU", -19.7515, -47.5075, "fixo"),
           ("SAMGA", -19.0315, -47.6125, "fixo"), ("VULPA", -18.605656, -47.671531, "fixo"),
           ("AZOIC", -18.304167, -47.715833, "fixo"), ("SEKPO", -15.488889, -48.181111, "fixo"),
           ("SBBR", -15.8692, -47.9208, "ad")]


def dist_nm(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(h))


def figura_rota():
    """Desenha o exemplo com matplotlib e devolve a imagem (PNG em memória) e as distâncias."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    pts = [(la, lo) for _, la, lo, _ in EXEMPLO]
    pela_rota = sum(dist_nm(a, b) for a, b in zip(pts, pts[1:]))
    reta = dist_nm(pts[0], pts[-1])
    fig, ax = plt.subplots(figsize=(7.6, 5.4), dpi=200)
    fig.patch.set_facecolor("#0b1a27"); ax.set_facecolor("#13263a")
    lons, lats = [p[1] for p in pts], [p[0] for p in pts]
    ax.plot([lons[0], lons[-1]], [lats[0], lats[-1]], ls=(0, (5, 4)), color="#9fb3c4", lw=1.4,
            label=f"Linha reta: {reta:.0f} NM")
    ax.plot(lons, lats, color="black", lw=5, alpha=.55)
    ax.plot(lons, lats, color="#00f2ff", lw=2.6, label=f"Pela rota: {pela_rota:.0f} NM")
    for nome, la, lo, tipo in EXEMPLO:
        if tipo == "ad":
            ax.plot(lo, la, marker="s", ms=9, color="#f1c40f", mec="black")
            ax.annotate(nome, (lo, la), xytext=(8, -4), textcoords="offset points", color="#f1c40f",
                        fontsize=10, fontweight="bold")
        else:
            ax.plot(lo, la, marker="o", ms=5.5, color="#00f2ff", mec="black")
            ax.annotate(nome, (lo, la), xytext=(7, 1), textcoords="offset points", color="#cff9ff",
                        fontsize=7.5, fontweight="bold",
                        bbox=dict(boxstyle="round,pad=0.15", fc="#06131e", ec="#00f2ff", lw=.6))
    ax.annotate("UZ26\n(mão única\npara o norte)", (-47.45, -20.2), xytext=(-51.6, -20.4), color="#9db1ff",
                fontsize=8.5, fontweight="bold", arrowprops=dict(arrowstyle="->", color="#9db1ff"))
    ax.annotate("DCT", (-46.8, -23.0), xytext=(-45.6, -22.3), color="#cff9ff", fontsize=8,
                arrowprops=dict(arrowstyle="->", color="#cff9ff"))
    ax.set_xlim(-53.5, -42.0); ax.set_ylim(-24.1, -14.9)
    ax.set_aspect(1 / math.cos(math.radians(19.5)))       # corrige a "esticada" da longitude
    ax.tick_params(colors="#9fb3c4", labelsize=7)
    for s in ax.spines.values():
        s.set_color("#24445f")
    ax.grid(color="#24445f", lw=.5)
    ax.set_xlabel("longitude", color="#9fb3c4", fontsize=7.5); ax.set_ylabel("latitude", color="#9fb3c4", fontsize=7.5)
    leg = ax.legend(loc="lower left", fontsize=8.5, facecolor="#06131e", edgecolor="#24445f")
    for t in leg.get_texts():
        t.set_color("#e6edf3")
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor()); plt.close(fig)
    buf.seek(0)
    return buf, round(pela_rota), round(reta)


# ---------------------------------------------------------------------------
# Cabeçalho e rodapé de cada página
# ---------------------------------------------------------------------------
def pagina(canvas, doc):
    w, h = A4
    canvas.saveState()
    canvas.setFillColor(AZUL_TOPO)
    canvas.rect(0, h - 15 * mm, w, 15 * mm, fill=1, stroke=0)
    canvas.setFillColor(AMARELO); canvas.setFont("Helvetica-Bold", 9.5)
    canvas.drawString(18 * mm, h - 9.5 * mm, "Meteorologia Aeronáutica · Prof. Hiremar")
    canvas.setFillColor(colors.HexColor("#c9d3dc")); canvas.setFont("Helvetica", 8.5)
    canvas.drawRightString(w - 18 * mm, h - 9.5 * mm, "Guia do Planejamento de Voo, da Rota e do Perfil")
    canvas.setFillColor(LARANJA); canvas.setFont("Helvetica-Bold", 6.6)
    canvas.drawString(18 * mm, 10 * mm, "MATERIAL DE INSTRUÇÃO - não substitui as fontes oficiais (REDEMET, "
                                        "AISWEB, NOTAM). Não usar para decisão operacional real.")
    canvas.setFillColor(CINZA); canvas.setFont("Helvetica", 7.5)
    canvas.drawRightString(w - 18 * mm, 10 * mm, f"pág. {doc.page}")
    canvas.restoreState()


# ---------------------------------------------------------------------------
# O CONTEÚDO
# ---------------------------------------------------------------------------
def conteudo():
    f = []
    png_rota, nm_rota, nm_reta = figura_rota()

    # ===== CAPA =====
    f += [Spacer(1, 4), p("Guia do Planejamento de Voo", H1), Spacer(1, 4),
          p("Como montar o briefing meteorológico, a rota e o perfil do seu voo no site "
            "<b>meteorologia-hiremar-aviacao.streamlit.app</b>, passo a passo.", SUB), Spacer(1, 10)]
    passos = [("1", "Dados do voo", "Planejar voo: origem, destino, alternativa, aeronave, nível, ETD e EET."),
              ("2", "Escreva a rota", "Opcional: fixos e aerovias, como no plano de voo. Vazio = linha reta."),
              ("3", "Leia o mapa", "Rota, aerovias, cartas ENRC, satélite, SIGMET, raios e categorias."),
              ("4", "Use as abas", "METAR/TAF, cartas, consulta, SIGWX, vento, perfil TOC/TOD e voo real."),
              ("5", "Gere o PDF", "Escolha o que entra e baixe o pacote de briefing colorido.")]
    cards = [[p(n, NUM), Spacer(1, 3), p(t, CARD_T), Spacer(1, 2), p(x, CARD_X)] for n, t, x in passos]
    tb = Table([cards], colWidths=[LARG / 5] * 5)
    tb.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), AZUL), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("LINEAFTER", (0, 0), (-2, -1), 0.6, colors.HexColor("#24445f")),
                            ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                            ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
    f += [tb, Spacer(1, 10)]
    f += caixa("Antes de começar", [
        p("Este site é <b>material de instrução</b>. Ele reúne dados reais (REDEMET, satélite GOES-19, modelo GFS, "
          "aerovias do GEOAISWEB, voos reais da OpenSky) para você <b>treinar</b> o briefing meteorológico e o "
          "planejamento. Não substitui a REDEMET, o AISWEB, os NOTAM nem o briefing oficial, e não deve ser usado "
          "para decisão operacional real."),
        p("<b>Todos os horários são UTC (Z).</b> Horário de Brasília = UTC - 3 h. Ex.: decolar às 18:30 de "
          "Brasília = 21:30Z.")])
    f += [p("O fluxo é o mesmo de um briefing de verdade: primeiro o <b>quadro geral</b> (mapa, sistemas, SIGMET, "
            "trovoadas), depois os <b>aeródromos</b> (METAR/TAF de origem, destino e alternativa) e por fim o "
            "<b>voo em rota</b> (SIGWX, vento e temperatura no seu nível e o perfil de subida e descida). "
            "No final, tudo vira um PDF para levar ao voo, à aula ou ao simulador."), Spacer(1, 8),
          p("<b>Assim fica o PDF que você vai gerar:</b>", H3)]
    f.append(figura("capa_pdf.jpg", LARG * 0.5, "Primeira página de um briefing gerado no site "
                    "(SBGR para SBRJ pela rota NIBRU KEVUN UMBAD, alternativa SBGL, FL270).", altura_max=100 * mm))
    f.append(PageBreak())

    # ===== PASSO 1 =====
    f += secao("Passo 1 · Preencha os Dados do voo")
    f += [p("No menu da esquerda, escolha <b>Planejar voo</b>. No alto da página aparece a caixa "
            "<b>Dados do voo</b>. Preencha:"), Spacer(1, 3)]
    f.append(figura("formulario.jpg", LARG, "A caixa Dados do voo (aqui já com um voo planejado SBSP para SBRJ). "
                    "Depois de planejar, ela fica recolhida: clique no título para alterar.", altura_max=72 * mm))
    f.append(tabela(["Campo", "O que colocar"], [
        ["Origem, destino, alternativa", "Aeródromos do Brasil (capitais, principais, os do CRCEA-SE e da aviação geral "
         "da TMA-SP, como SBMT, SBJD, SBBP e SDCO) e <b>da América do Sul</b>. A alternativa é opcional."],
        ["Rota (opcional)", "Fixos e aerovias, como no plano de voo (veja o Passo 2). Vazio = linha reta."],
        ["Aeronave", "<b>Novo.</b> Usada só para o <b>perfil simulado de subida e descida</b> (TOC e TOD), do Cessna "
         "172 ao Boeing 777. Não muda o vento nem a meteorologia."],
        ["Nível de cruzeiro", "De FL030 a FL450, de 10 em 10 (lembre da regra de níveis por rumo)."],
        ["Data e hora da decolagem", "Em UTC, de 1 h atrás até 24 h à frente. O padrão vem daqui a uns 30 minutos."],
        ["Tempo de voo · EET", "hh:mm (ex.: 01:30). Com ele o site calcula o ETA e a hora em que você passa por "
         "cada ponto da rota."],
    ], [0.30, 0.70]))
    f += [Spacer(1, 6), p("Clique em <b>Planejar voo</b>. Para começar outro, use <b>Limpar planejamento</b>. "
                          "O botão <b>Como planejar (guia em PDF)</b> abre este guia. Depois de planejar, o título "
                          "da página mostra origem, destino e nível, os horários <b>ETD · EET · ETA</b> e, se você "
                          "escreveu uma rota, a <b>rota por extenso</b> com a distância:")]
    f.append(figura("titulo_rota.jpg", LARG * 0.8, None, altura_max=22 * mm))
    f += caixa("Dica de instrutor", "Quer só treinar a leitura? Deixe o horário padrão (próximos minutos). Quer "
               "simular um voo de amanhã cedo? Coloque a decolagem para amanhã: o vento e a SIGWX passam a ser os "
               "previstos para aquele horário, como num briefing de véspera.", FUNDO_AMARELO, AMARELO)
    f.append(PageBreak())

    # ===== PASSO 2: ROTA =====
    f += secao("Passo 2 · Escreva a rota (aerovias)")
    f += [p("Sem rota, o site liga origem e destino por uma <b>linha reta</b> (a ortodrômica). Na vida real o "
            "avião voa por <b>aerovias</b>: corredores publicados pelo DECEA, ligando <b>fixos</b> (pontos com nome "
            "de 5 letras, como SAMGA, ou auxílios como VOR). Escrevendo a rota, o mapa, o vento, o perfil, os SIGMET "
            "e o PDF passam a seguir o caminho de verdade."), Spacer(1, 6),
          p("Como escrever", H3),
          p("Igual ao campo 15 do plano de voo: <b>FIXO AEROVIA FIXO</b>... Cada aerovia fica entre o fixo onde "
            "você entra e o fixo onde você sai. Um fixo solto é voo direto (DCT). Exemplo de SBGR para SBBR:"),
          Spacer(1, 5)]
    f += fichas_rota([("N0450F360", "ign", "velocidade/nível<br/>(ignorado)"), ("AMVU5A", "ign", "SID<br/>(ignorada)"),
                      ("GERKA", "fixo", "fixo onde<br/>entro"), ("UZ26", "via", "aerovia"),
                      ("SEKPO", "fixo", "fixo onde<br/>saio"), ("DCT", "ign", "direto<br/>(opcional)"),
                      ("BSI", "fixo", "VOR/fixo<br/>direto"), ("IRUL1A", "ign", "STAR<br/>(ignorada)")])
    f += [p("O site entende a rota sozinho: anda pela UZ26 de GERKA até SEKPO passando por todos os fixos do meio "
            "(ISMOB, BIXAN, KEXIT, KOMLU, SAMGA, VULPA, AZOIC), que no plano de voo ficam implícitos. Você pode "
            "colar a rota inteira do SimBrief ou do SkyVector: SID, STAR e velocidade/nível são ignorados.", TXT),
          Spacer(1, 4)]
    f.append(figura(png_rota, LARG, f"Exemplo com as coordenadas reais do GEOAISWEB: SBGR para SBBR pela "
                    f"UZ26 (GERKA a SEKPO). Pela rota: {nm_rota} NM; em linha reta: {nm_reta} NM "
                    f"(+{(nm_rota / nm_reta - 1) * 100:.0f}%). Simplificado: sem SID e STAR.", altura_max=125 * mm))
    f.append(PageBreak())

    f += secao("Passo 2 · Rota: o que o site faz e onde achar rotas")
    f.append(tabela(["Você escreve", "O site faz"], [
        ["GERKA UZ26 SEKPO", "Segue a aerovia fixo a fixo e desenha cada um no mapa, com o nome."],
        ["... SEKPO BSI", "Fixo solto depois de outro = direto (DCT). A palavra DCT é opcional."],
        ["AMVU5A, IRUL1A", "SID e STAR: ignoradas, com aviso (procedimentos ainda não são desenhados)."],
        ["N0450F360", "Velocidade e nível do plano de voo: ignorados (o nível vem do campo Nível)."],
        ["UKBEV UZ26 SAMGA", "Se o fixo não está mais na aerovia (rota de AIRAC antigo), o site entra/sai pelo "
         "fixo da aerovia mais próximo (até 100 NM) e avisa."],
        ["SAMGA UZ26 GERKA", "Aceita, mas avisa: a UZ26 é de mão única para o norte nesse trecho (contramão)."],
        ["um fixo que não existe", "Explica o problema e desenha em linha reta, para o resto do briefing seguir."],
    ], [0.30, 0.70], mono_col=0))
    f += [Spacer(1, 8), p("O que muda quando há rota", H3)] + lista([
        "Abaixo do título: a rota por extenso e a comparação <b>NM pela rota × NM em linha reta</b>.",
        "<b>Vento na rota</b> e <b>perfil vertical</b>: os pontos seguem os fixos, com a hora de passagem em cada um.",
        "<b>SIGMET e raios no corredor</b> e <b>aeródromos em rota</b>: calculados em volta do caminho real.",
        "<b>PDF</b>: a capa ganha a linha <b>Rota</b> e o mapa desenha o caminho pelos fixos."])
    f += [Spacer(1, 6), p("Leia o nome da aerovia (Anexo 11 da OACI)", H3),
          p("O nome diz muito: as letras mostram o tipo de rota e o prefixo <b>U</b> indica espaço aéreo superior. "
            "No Brasil, o espaço aéreo superior fica acima do FL245.")]
    f.append(tabela(["Parte do nome", "Significa", "Exemplo"], [
        ["U na frente", "Upper: espaço aéreo superior", "<b>U</b>Z26 (a do exemplo)"],
        ["A, B, G, R", "Rede regional, não RNAV", "UA..., UB..., UG..."],
        ["L, M, N, P", "Rede regional, RNAV", "UL..., UM..., UN..."],
        ["H, J, V, W", "Fora da rede regional, não RNAV", "W... (muito usadas nas inferiores)"],
        ["Q, T, Y, Z", "Fora da rede regional, RNAV", "U<b>Z</b>26: RNAV, superior"],
    ], [0.22, 0.43, 0.35]))
    f += [Spacer(1, 8), p("Onde achar uma rota para treinar", H3)] + lista([
        "<b>No próprio site</b>: na barra lateral, em <i>Cartas aeronáuticas (DECEA)</i>, ligue as cartas <b>ENRC</b> "
        "(alta ou baixa) e siga as aerovias entre origem e destino. As <b>aerovias perto da rota</b> também aparecem "
        "no mapa: passe o mouse para ver nome, trecho e limites.",
        "<b>AISWEB</b> (aisweb.decea.mil.br): cartas ENRC oficiais e as rotas publicadas.",
        "<b>SkyVector</b> e <b>SimBrief</b>: geram rotas prontas. Atenção ao ciclo AIRAC: rota de base antiga "
        "pode citar fixos que mudaram (o site avisa)."])
    f += caixa("Para pensar em aula", "Compare o mesmo voo em linha reta e pela rota. Quantas milhas a mais? "
               "Algum SIGMET que estava fora da linha reta passou a cruzar a rota? Um aeródromo em rota entrou ou "
               "saiu do corredor? É assim que a rota muda o briefing.", FUNDO_AMARELO, AMARELO)
    f.append(PageBreak())

    # ===== PASSO 3: MAPA =====
    f += secao("Passo 3 · Leia o mapa")
    f.append(figura("mapa.jpg", LARG, "Exemplo: SBGR para SBRJ pela rota NIBRU KEVUN UMBAD, FL270, com as cartas "
                    "ENRC de alta ligadas, satélite IR, SIGMET (polígonos), raios e a categoria de cada aeródromo.",
                    altura_max=88 * mm))
    f.append(tabela(["No mapa", "O que significa"], [
        ["Linha ciano", "A rota: pelos fixos (com o nome de cada um) se você escreveu a rota; senão, a linha reta."],
        ["Tracejado roxo", "A perna do destino para a alternativa."],
        ["Linhas azuis finas", "Aerovias perto da rota (alta a partir do FL245, ou baixa), do GEOAISWEB. Passe o "
         "mouse: nome, trecho, limites e se é mão única."],
        ["Etiquetas VFR / MVFR / IFR / LIFR", "Categoria de voo pelo METAR (critério FAA). Etiqueta transparente = "
         "METAR com mais de 90 min. N/D = sem METAR."],
        ["Anel dourado em volta da etiqueta", "Aviso de aeródromo (AD WRNG) vigente. Passe o mouse para ler."],
        ["Polígonos coloridos", "SIGMET: vermelho = trovoada, amarelo = turbulência, azul = gelo. Clique para ver "
         "decodificado."],
        ["Raiozinhos", "Descargas da última hora: vermelho 0-15 min, amarelo 15-30, verde 30-45, azul 45-60."],
        ["Cores do satélite IR", "Topo das nuvens: quanto mais frio (amarelo, vermelho, rosa), mais alto o topo; "
         "tons fortes indicam convecção. Passe o mouse para ler a temperatura."],
    ], [0.30, 0.70]))
    f += [Spacer(1, 6), p("Camadas da barra lateral", H3)] + lista([
        "<b>Satélite</b>: infravermelho (canal 13), relevo 3D ou visível em cores reais (só de dia).",
        "<b>SIGMET e raios</b> e <b>Aeródromos</b>: liga/desliga e escolhe etiquetas VFR/IFR ou bolinhas REDEMET.",
        "<b>Cartas meteorológicas</b>: a <b>SIGWX</b> encaixada no mapa e o vento/temperatura do modelo GFS.",
        "<b>Cartas aeronáuticas (DECEA)</b>: cartas de rota <b>ENRC</b> (baixa L1-L9 ou alta H1-H9), cartas visuais "
        "<b>WAC</b> e as aerovias perto da rota."])
    f += [p("Use também o botão de camadas no canto superior direito do mapa para trocar o mapa de fundo.")]
    f.append(PageBreak())

    # ===== PASSO 4: ABAS =====
    f += secao("Passo 4 · Use as abas do Briefing do voo")
    f += [p("Embaixo do mapa fica o <b>Briefing do voo</b>, com seis abas: <b>Dados da rota</b>, <b>Cartas</b>, "
            "<b>Consultar mensagens</b>, <b>SIGWX</b>, <b>Vento na rota</b> e <b>Gerar voo (PDF)</b>."), Spacer(1, 4),
          p("Dados da rota", H3),
          p("METAR e TAF completos de origem, destino e alternativa, com a categoria de voo e os avisos de "
            "aeródromo decodificados."),
          p("Cartas", H3),
          p("Atalho para as cartas de aeródromo (SID, STAR, IAC, ADC) de origem, destino e alternativa no AISWEB, a "
            "fonte oficial. Em breve a lista completa aparece no próprio site."),
          p("Consultar mensagens", H3),
          p("Funciona como a <i>Consulta Mensagens</i> da REDEMET e <b>não depende da rota</b>: qualquer localidade "
            "(até 6 por vez), qualquer período (até 31 dias), METAR/SPECI e/ou TAF. Dá para filtrar por texto (ex.: "
            "<b>TS</b>, <b>SPECI</b>, <b>BKN004</b>) e baixar em TXT ou CSV (abre no Excel). Ótimo para estudar como "
            "o tempo evoluiu num dia de frente fria.")]
    f.append(figura("consulta.jpg", LARG, None, altura_max=24 * mm))
    f += [p("SIGWX", H3),
          p("Mostra as cartas de tempo significativo (SFC/FL250, do CIMAER) <b>das validades que cobrem o seu voo</b>. "
            "Cada carta vale de 3 h antes até 3 h depois do horário de validade (veja a regra na página de "
            "validades). Quando a CIMAER <b>emenda</b> uma carta, o site usa a versão emendada e avisa em amarelo: "
            "<b>CARTA EMENDADA (AMD)</b>. Confira sempre a validade impressa no quadro da carta.")]
    f.append(figura("sigwx.jpg", LARG, None, altura_max=28 * mm))
    f += [p("Vento na rota", H3),
          p("No alto da aba aparece o <b>perfil vertical simulado</b> (próxima página). Depois, clique em "
            "<b>Calcular vento na rota</b> (a primeira vez demora um pouco: o site baixa o modelo GFS). Com rota "
            "escrita, os pontos seguem os fixos. Você recebe:")] + lista([
        "<b>Comparação de níveis</b>: o seu FL e os vizinhos no mesmo sentido de voo (±2.000 ft), com a componente "
        "média, o vento máximo, a temperatura e o desvio ISA. Bom para decidir se vale subir ou descer.",
        "<b>Tabela ponto a ponto</b>: distância, <b>fase do voo</b> (subida, cruzeiro, descida), <b>hora estimada</b> "
        "de passagem, posição, vento, temperatura, desvio ISA, componente (cauda ou proa) e a validade do modelo.",
        "<b>Mapa de barbelas</b> com os pontos da tabela numerados."])
    f.append(figura("vento.jpg", LARG * 0.75, "Componente: cauda = vento a favor, proa = vento contra. Desvio ISA: "
                    "quanto a temperatura real está acima (+) ou abaixo (-) da atmosfera padrão no seu nível.",
                    altura_max=32 * mm))
    f.append(PageBreak())

    # ===== PERFIL VERTICAL =====
    f += secao("Passo 4 · Perfil vertical simulado: TOC e TOD", novo=True)
    f += [p("Com a aeronave escolhida nos Dados do voo, o site estima onde o avião termina a subida e onde começa a "
            "descida. A conta é a mesma que se faz no papel, só que em degraus de 500 ft, trocando a razão e a "
            "velocidade a cada faixa de altitude (o avião sobe bem mais rápido perto do solo do que perto do teto):")]
    f += caixa("A conta, degrau por degrau", lista([
        "<b>Tempo</b> (min) = pés a subir ÷ razão de subida (ft/min)",
        "<b>Distância</b> (NM) = velocidade no solo (GS) × tempo ÷ 60",
        "A velocidade indicada (IAS) vira verdadeira (TAS) pela atmosfera padrão: mais ou menos +2% a cada "
        "1.000 ft. Abaixo do FL100, no máximo 250 kt.",
        "Vento: a componente média do cruzeiro e metade dela na subida e na descida."]),
        colors.HexColor("#eef3f7"), AZUL)
    f.append(figura("perfil.jpg", LARG, "O quadro do perfil na aba Vento na rota (exemplo com A320 no FL100).",
                    altura_max=82 * mm))
    f.append(tabela(["No quadro", "O que significa"], [
        ["TOC (topo da subida)", "Distância e tempo da decolagem até nivelar no cruzeiro, com a hora estimada."],
        ["TOD (início da descida)", "Quantas NM antes do destino começa a descida, e quanto tempo ela dura."],
        ["Regra prática 3:1", "3 NM para cada 1.000 ft a perder. A linha pontilhada no gráfico, para comparar."],
        ["EET pelo perfil", "Tempo de voo estimado pela conta (decolagem ao pouso). Compare com o EET que você "
         "informou: o seu EET deve incluir táxi e procedimentos."],
        ["Coluna Fase (tabela de vento)", "Onde o avião estaria em cada ponto: subida ~FL170, cruzeiro, descida "
         "~FL120. Nos pontos em subida/descida o vento da tabela é o do nível de cruzeiro."],
    ], [0.30, 0.70]))
    f += [Spacer(1, 6), p("<b>Aeronaves disponíveis</b>: Cessna 172, Cirrus SR22, Cessna 208 Caravan, Pilatus PC-12, "
                          "ATR 72, Phenom 100 e 300, Embraer E195 (aproximação do E195-E2), A319, A320, A320neo, "
                          "A321, A321neo, 737-800, 737 MAX 8, 767-300, 787-9, 777-300ER e A350-900. Se o nível "
                          "estiver acima do teto da aeronave, ou a rota for curta demais para chegar a ele, o site "
                          "avisa e mostra até onde o avião sobe.", TXT_P)]
    f += caixa("De onde vêm os números", "EUROCONTROL Aircraft Performance Database: valores <b>médios e "
               "indicativos</b>, feitos para treinar controladores. O avião real depende de peso, temperatura, "
               "regime de potência, SID/STAR e do controle. É um exercício de planejamento, não o perfil do FMS.",
               FUNDO_LARANJA, LARANJA)
    f.append(PageBreak())

    # ===== VOO REAL =====
    f += secao("Passo 4 · Compare com um voo real", novo=True)
    f += [p("Logo abaixo do gráfico do perfil fica a caixa <b>Comparar com um voo real</b>. Ela desenha, em "
            "<b>verde</b>, o perfil de um voo que de fato aconteceu sobre o perfil simulado (azul), e monta uma "
            "tabela <b>Simulado × Voo real</b>. Para a comparação ser justa, planeje a mesma origem, destino, rota, "
            "nível e tipo de aeronave do voo real.")]
    f.append(figura("comparar.jpg", LARG, None, altura_max=20 * mm))
    f.append(tabela(["Aba", "Como usar"], [
        ["Buscar voo real", "Escolha o <b>dia</b> e o <b>voo</b> (indicativo e horários) e clique em <b>Comparar "
         "este voo</b>. São voos reais captados pela rede de receptores ADS-B da <b>OpenSky Network</b>, dos últimos "
         "30 dias, entre os principais aeroportos do Brasil e os de aviação geral da TMA-SP. Os voos de um dia "
         "aparecem a partir da manhã seguinte."],
        ["Colar track log", "No <b>FlightAware</b>, abra o voo, clique em <b>Exibir o track log</b>, selecione a "
         "tabela inteira (do cabeçalho até a chegada), copie e cole na caixa. Também vale o arquivo CSV ou o KML "
         "do botão Google Earth. Serve para qualquer voo que você ache por lá."],
    ], [0.22, 0.78]))
    f += [Spacer(1, 6)]
    f.append(figura("comparacao.png", LARG, "Exemplo de 10/10/2026: o voo real TAM3974 (A319, SBGR para SBRJ, "
                    "nivelado no FL250, track log do FlightAware) em verde, sobre o perfil simulado em azul.",
                    altura_max=70 * mm))
    f.append(tabela(["", "Simulado (A319)", "Voo real (TAM3974)"], [
        ["TOC: distância da decolagem", "75 NM", "49 NM"],
        ["TOD: distância antes do destino", "61 NM", "99 NM"],
        ["NM por 1.000 ft na descida", "2,4", "4,0 (a regra diz 3)"],
    ], [0.40, 0.30, 0.30]))
    f += caixa("Para pensar em aula", lista([
        "O avião real subiu <b>mais rápido</b> que a tabela: perna curta, avião leve, pouco combustível.",
        "E começou a descer <b>bem antes</b>, com um trecho quase nivelado no meio da descida: STAR e restrições do "
        "controle. A regra 3:1 ficou mais perto da realidade que o desempenho puro da tabela.",
        "Tente com o mesmo par em outro horário, outro tipo de aeronave ou o sentido contrário (SBRJ para SBGR): o "
        "perfil muda com a terminal de chegada."]), FUNDO_AMARELO, AMARELO)
    f.append(PageBreak())

    # ===== PASSO 5: PDF + VALIDADES =====
    f += secao("Passo 5 · Gere o PDF do briefing")
    f += [p("Na aba <b>Gerar voo (PDF)</b>, marque o que deve entrar, escolha o satélite do mapa (infravermelho ou "
            "visível), a <b>largura do corredor</b> (25, 50 ou 100 NM para cada lado da rota) e clique em <b>Gerar "
            "voo (PDF)</b>. Quando aparecer <b>Briefing pronto!</b>, clique em <b>Baixar o PDF do briefing</b>. Os "
            "avisos amarelos dizem o que merece atenção (uma SIGWX emendada, uma fonte fora do ar).")]
    f.append(figura("gerar_pdf.jpg", LARG * 0.82, None, altura_max=70 * mm))
    f.append(tabela(["No PDF", "Para que serve"], [
        ["Capa com resumo", "<b>Rota</b> (por extenso e em NM), vento no nível, <b>perfil (TOC/TOD)</b>, horários, "
         "pior categoria, SIGMET perto da rota, raios, avisos de aeródromo e aeródromos em rota."],
        ["Mapa da rota", "A situação ATUAL: satélite, SIGMET, raios e categorias, com a rota pelos fixos."],
        ["METAR/TAF", "Origem, destino, alternativa e os aeródromos no meio da rota (dentro do corredor, fora da "
         "área de 40 NM em volta da origem, do destino e da alternativa)."],
        ["SIGMET decodificados", "Só os que cruzam a rota ou estão no corredor, com a resposta: <b>atinge o seu "
         "nível?</b>"],
        ["Raios", "Quantas descargas no corredor na última hora. É observação, não previsão."],
        ["Vento e temperatura", "Os três níveis lado a lado, ponto a ponto, com a hora, a fase do voo e a validade."],
        ["Perfil vertical", "O gráfico do TOC e do TOD, com a regra 3:1 e o EET estimado."],
        ["SIGWX", "As cartas das validades do voo (a emendada, se houver AMD)."],
    ], [0.26, 0.74]))
    f += secao("Validade das cartas: a regra do Doc 8896 (OACI)")
    f += [p("O <b>Doc 8896 (Manual of Aeronautical Meteorological Practice), item 5.3.3.4</b>, orienta o uso das "
            "cartas de previsão de horário fixo. O site segue essa regra automaticamente:"), Spacer(1, 4)]
    f.append(tabela(["Produto", "Validades", "Pode ser usado"], [
        ["Vento e temperatura em altitude", "de 3 em 3 h (00, 03, 06... Z)", "de 1 h 30 min antes a 1 h 30 min depois"],
        ["SIGWX", "de 6 em 6 h (00, 06, 12, 18Z)", "de 3 h antes a 3 h depois"]], [0.34, 0.31, 0.35]))
    f += caixa("Exemplo do próprio Doc 8896: voo das 12:00 às 19:00Z (7 h)", lista([
        "<b>Vento e temperatura</b>: três validades, <b>12, 15 e 18Z</b>.",
        "<b>SIGWX</b>: duas validades, <b>12 e 18Z</b>.",
        "No site, cada ponto da rota usa a validade mais próxima da <b>hora em que você passa por ele</b>. Por isso "
        "o tempo de voo (EET) é importante."]), colors.HexColor("#eef3f7"), AZUL)
    f += [p("Observação: o vento do site vem do <b>modelo GFS</b> (NOAA), não da carta WAFS. Para fins de instrução "
            "usamos a mesma regra de validade, por analogia.")]
    f += caixa("Carta emendada (AMD)", "Quando a CIMAER publica uma <b>emenda</b> de uma SIGWX, a carta original "
               "ganha o aviso <i>THERE IS AN AMENDMENT FOR THIS CHART</i>. O site escolhe sozinho a versão emendada e "
               "avisa na tela e no PDF. Num briefing real, confira sempre se não saiu outra emenda depois.",
               FUNDO_LARANJA, LARANJA)

    # ===== CHECKLIST =====
    f += secao("Checklist do briefing meteorológico e da rota")
    itens = [
        "Rota: escrita e conferida no mapa? Aerovias no sentido certo (sem aviso de contramão) e nível dentro dos "
        "limites da aerovia (passe o mouse na linha azul)?",
        "Quadro geral: há sistemas frontais, linhas de instabilidade ou áreas de convecção perto da rota (satélite, "
        "raios)?",
        "SIGMET: algum cruza a rota? Atinge o meu nível? Qual o movimento e a tendência (INTSF, WKN, NC)?",
        "Origem: METAR atual e TAF para a hora da decolagem. Há aviso de aeródromo?",
        "Destino: TAF para o ETA (com margem). Há TEMPO/PROB com teto ou visibilidade abaixo dos mínimos?",
        "Alternativa: atende aos mínimos de alternativa no horário previsto?",
        "Aeródromos em rota: algum serve de pouso de emergência? Como está o tempo neles?",
        "SIGWX da(s) validade(s) do voo (é emendada?): CB, turbulência, gelo, jato, tropopausa e frentes na rota.",
        "Vento no nível: componente média (proa ou cauda), vento máximo e desvio ISA. Algum nível vizinho é melhor?",
        "Perfil: onde fica o TOC e o TOD? O que há de tempo nesses trechos de subida e descida (gelo, turbulência, "
        "CB na terminal)? O nível é alcançável nessa distância?",
        "Temperatura no nível e risco de gelo: entre 0 e -20 °C com umidade, atenção.",
        "Conferir tudo nas fontes oficiais (REDEMET, AISWEB, NOTAM) antes de um voo real."]
    tb = Table([[p("[ ]", CEL_B), p(t, CEL)] for t in itens], colWidths=[LARG * 0.06, LARG * 0.94])
    tb.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINHA),
                            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    f += [tb]
    f += secao("Bom saber")
    f += lista([
        "<b>Aeródromos</b>: capitais, principais aeroportos, os do CRCEA-SE e os de aviação geral da TMA-SP, além das "
        "capitais e principais aeroportos da América do Sul. Na <b>Consultar mensagens</b> vale qualquer localidade "
        "da REDEMET.",
        "<b>Voos para fora do Brasil</b>: dá para planejar, por exemplo, SBGR para SCEL (Santiago); o METAR/TAF vem "
        "da REDEMET. Como o site só tem as aerovias do DECEA, escreva a rota até o último fixo brasileiro: dali o "
        "site segue em linha reta até o destino.",
        "<b>Aerovias</b>: vêm do GEOAISWEB (DECEA) e são atualizadas a cada emenda AIRAC. Só existem para o "
        "espaço aéreo brasileiro; fora dele a rota segue em linha reta.",
        "<b>Mensagens corrigidas (COR)</b>: a REDEMET guarda só a versão corrigida; a mensagem original não aparece "
        "na consulta.",
        "<b>Se uma fonte estiver fora do ar</b> (REDEMET em manutenção, GEOAISWEB momentaneamente fora do ar), o site "
        "avisa na tela e no PDF o que ficou faltando e segue com o resto do briefing, em vez de travar ou mostrar dado "
        "vazio como se fosse tempo bom. As aerovias têm uma cópia guardada: a rota continua seguindo os fixos.",
        "<b>Simulador</b>: como os dados são reais e do momento, o briefing combina com simuladores que usam "
        "meteorologia em tempo real (MSFS, X-Plane) e com voos na IVAO. Planeje, gere o PDF e voe com o mesmo tempo "
        "que você estudou."])
    f += [Spacer(1, 14), p("<b>Bons voos e bons estudos!</b>", estilo("fim", fontSize=11, textColor=AZUL)),
          p("Prof. Me. Hiremar Soares — Meteorologista", estilo("ass", fontSize=10, textColor=CINZA))]
    return f


def gerar():
    doc = SimpleDocTemplate(str(SAIDA), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=22 * mm, bottomMargin=18 * mm, title="Guia do Planejamento de Voo",
                            author="Prof. Me. Hiremar Soares",
                            subject="Como fazer o briefing meteorológico, a rota e o perfil de voo no site Meteorologia Aeronáutica")
    doc.build(conteudo(), onFirstPage=pagina, onLaterPages=pagina)
    print("Guia gerado:", SAIDA)


if __name__ == "__main__":
    gerar()
