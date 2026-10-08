"""PDF do "Gerar voo": o pacote de briefing de instrução, com as cores do site.

Usa a reportlab, que monta o PDF com "flowables": blocos (parágrafo, tabela,
imagem...) que vão sendo empilhados e quebram de página sozinhos.

Quem chama (modulos/planejamento.py) entrega um dicionário 'b' já com tudo pronto
(textos, imagens PNG em bytes, tabelas). Aqui é só a DIAGRAMAÇÃO.
"""
import io
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)
from xml.sax.saxutils import escape

from . import metar as mt

# Cores do site
AZUL = colors.HexColor("#0b1a27")
AZUL2 = colors.HexColor("#13263a")
AMARELO = colors.HexColor("#f1c40f")
LARANJA = colors.HexColor("#ff9800")
CINZA = colors.HexColor("#5b6b78")
VERDE_MSG = colors.HexColor("#e9f7ec")
AZUL_MSG = colors.HexColor("#e8f0ff")

LARG = A4[0] - 30 * mm          # largura útil da página


def _t(texto):
    """As fontes padrão do PDF (Helvetica/Courier) não têm alguns símbolos.
    Trocamos por equivalentes e escapamos <, > e & (o Paragraph lê uma espécie de HTML)."""
    trocas = {"→": "->", "✈": "", "⚠": "", "·": "·", "–": "-", "—": "-", "≥": ">=", "≤": "<=",
              "−": "-", "’": "'", "“": '"', "”": '"'}
    s = str(texto)
    for a, b in trocas.items():
        s = s.replace(a, b)
    s = s.encode("latin-1", "replace").decode("latin-1")
    return escape(s)


E = {   # estilos de texto
    "titulo": ParagraphStyle("titulo", fontName="Helvetica-Bold", fontSize=20, leading=24, textColor=AZUL),
    "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=10.5, leading=14, textColor=CINZA),
    "secao": ParagraphStyle("secao", fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=colors.white),
    "corpo": ParagraphStyle("corpo", fontName="Helvetica", fontSize=9.5, leading=12.5),
    "peq": ParagraphStyle("peq", fontName="Helvetica", fontSize=8, leading=10, textColor=CINZA),
    "rot": ParagraphStyle("rot", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=CINZA),
    "msg": ParagraphStyle("msg", fontName="Courier", fontSize=8.8, leading=11.2),
    "aviso": ParagraphStyle("aviso", fontName="Helvetica-Bold", fontSize=9, leading=12,
                            textColor=colors.HexColor("#8a4b00")),
    "cel": ParagraphStyle("cel", fontName="Helvetica", fontSize=8.5, leading=10.5, alignment=TA_CENTER),
    "celb": ParagraphStyle("celb", fontName="Helvetica-Bold", fontSize=8.5, leading=10.5,
                           alignment=TA_CENTER, textColor=colors.white),
}


def _secao(texto):
    """Faixa azul-marinho com filete amarelo à esquerda (o "título de seção")."""
    t = Table([["", Paragraph(_t(texto), E["secao"])]], colWidths=[2.2 * mm, LARG - 2.2 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), AMARELO), ("BACKGROUND", (1, 0), (1, 0), AZUL2),
                           ("LEFTPADDING", (1, 0), (1, 0), 8), ("TOPPADDING", (0, 0), (-1, -1), 5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    esp = Spacer(1, 2.5 * mm)
    t.keepWithNext = esp.keepWithNext = True      # o título nunca fica sozinho no pé da página
    return [Spacer(1, 4 * mm), t, esp]


def _caixa_msg(texto, fundo=VERDE_MSG, borda=colors.HexColor("#2e9e44")):
    """Mensagem METAR/TAF em fonte de máquina de escrever, numa caixinha colorida."""
    p = Paragraph(_t(texto).replace("\n", "<br/>"), E["msg"])
    t = Table([[p]], colWidths=[LARG])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fundo), ("LINEBEFORE", (0, 0), (0, -1), 2.5, borda),
                           ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    return t


def _imagem(png, largura=LARG, altura_max=200 * mm):
    """Imagem PNG (bytes) ajustada à largura, mantendo a proporção."""
    leitor = ImageReader(io.BytesIO(png))
    w, h = leitor.getSize()
    escala = min(largura / w, altura_max / h)
    return Image(io.BytesIO(png), width=w * escala, height=h * escala)


def _chip_categoria(cat):
    texto, fundo, cor = mt.CATEGORIAS_FAA[cat]
    t = Table([[Paragraph(f"<font color='{cor}'><b>{texto}</b></font>", E["cel"])]], colWidths=[15 * mm])
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(fundo)),
                           ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    return t


def _bloco_aerodromo(a):
    """Cartão de um aeródromo: título + categoria, avisos de aeródromo, METAR e TAF."""
    titulo = f"<b>{_t(a['papel'])}: {_t(a['icao'])}</b>  <font color='#5b6b78'>{_t(a['nome'])}</font>"
    if a.get("idade"):
        titulo += f"  <font size=8 color='#5b6b78'>(METAR há {a['idade']} min)</font>"
    cab = Table([[Paragraph(titulo, E["corpo"]), _chip_categoria(a["cat"])]],
                colWidths=[LARG - 17 * mm, 17 * mm])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    partes = [cab]
    for linhas, bruto in a.get("avisos", []):
        partes.append(Paragraph("AVISO DE AERÓDROMO: " + _t(" · ".join(linhas)), E["aviso"]))
        partes.append(_caixa_msg(bruto, colors.HexColor("#fff4d6"), colors.HexColor("#ffbe00")))
    partes.append(Paragraph("METAR", E["rot"]))
    partes.append(_caixa_msg(a["metar"] or "não disponível"))
    if a.get("mostrar_taf", True):
        partes.append(Paragraph("TAF", E["rot"]))
        partes.append(_caixa_msg(mt.formatar_taf(a["taf"]) if a["taf"] else "não disponível",
                                 AZUL_MSG, colors.HexColor("#3f6fd8")))
    partes.append(Spacer(1, 3 * mm))
    return KeepTogether(partes)


def _tabela(cab, linhas, larguras, cores_linha=None):
    dados = [[Paragraph(_t(c), E["celb"]) for c in cab]]
    dados += [[Paragraph(_t(v).replace("\n", "<br/>"), E["cel"]) for v in l] for l in linhas]
    t = Table(dados, colWidths=larguras, repeatRows=1)
    estilo = [("BACKGROUND", (0, 0), (-1, 0), AZUL2), ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d3dc")),
              ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f6f9")]),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("TOPPADDING", (0, 0), (-1, -1), 3),
              ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    for (lin, col, cor) in (cores_linha or []):
        estilo.append(("BACKGROUND", (col, lin + 1), (col, lin + 1), cor))
    t.setStyle(TableStyle(estilo))
    return t


def _posicao(l):
    return f"{abs(l['lat']):.1f}{'S' if l['lat'] < 0 else 'N'} {abs(l['lon']):.1f}{'W' if l['lon'] < 0 else 'E'}"


def _comp(c):
    """+12 -> 'cauda 12 kt' ; -20 -> 'proa 20 kt'"""
    return "nulo" if abs(c) < 1 else f"{'cauda' if c > 0 else 'proa'} {abs(c)} kt"


def _pagina(canvas, doc, titulo):
    """Cabeçalho e rodapé de TODAS as páginas (desenhados direto na "tela" do PDF)."""
    canvas.saveState()
    w, h = A4
    canvas.setFillColor(AZUL)
    canvas.rect(0, h - 14 * mm, w, 14 * mm, stroke=0, fill=1)
    canvas.setFillColor(AMARELO)
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(15 * mm, h - 9 * mm, "Meteorologia Aeronáutica · Prof. Hiremar")
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica", 9)
    canvas.drawRightString(w - 15 * mm, h - 9 * mm, _t(titulo).replace("&gt;", ">"))
    canvas.setFillColor(LARANJA)
    canvas.setFont("Helvetica-Bold", 7.5)
    canvas.drawString(15 * mm, 8 * mm, "MATERIAL DE INSTRUÇÃO - não substitui as fontes oficiais "
                                       "(REDEMET, AISWEB, NOTAM). Não usar para decisão operacional real.")
    canvas.setFillColor(CINZA)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(w - 15 * mm, 8 * mm, f"pág. {doc.page}")
    canvas.restoreState()


def gerar(b):
    """b = dicionário montado em planejamento.py. Devolve os bytes do PDF."""
    buf = io.BytesIO()
    rota_txt = f"{b['origem']} -> {b['destino']}" + (f" (altn {b['altn']})" if b.get("altn") else "")
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=20 * mm, bottomMargin=16 * mm,
                            title=f"Briefing {rota_txt}", author="Prof. Hiremar Soares")
    hist = []

    # ---------------- capa / resumo ----------------
    hist.append(Paragraph(_t(f"Briefing de voo: {rota_txt}"), E["titulo"]))
    agora = b.get("gerado_em") or datetime.now(timezone.utc)
    hist.append(Paragraph(_t(
        f"{b['nivel']} · {b.get('horarios', '')} · distância {b['distancia_nm']} NM · "
        f"rumo verdadeiro inicial {b['rumo']:03d}° · gerado em {agora:%d/%m/%Y %H:%M}Z"), E["sub"]))
    if b.get("resumo"):
        hist.append(Spacer(1, 3 * mm))
        linhas = [[Paragraph(f"<b>{_t(k)}</b>", E["corpo"]), Paragraph(_t(v), E["corpo"])] for k, v in b["resumo"]]
        t = Table(linhas, colWidths=[45 * mm, LARG - 45 * mm])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f3f6f9")),
                               ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c9d3dc")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        hist.append(t)
    for aviso in b.get("indisponiveis", []):
        hist.append(Paragraph("Atenção: " + _t(aviso), E["aviso"]))

    if b.get("mapa_png"):
        hist += _secao("Mapa da rota: satélite, SIGMET, raios e aeródromos")
        hist.append(_imagem(b["mapa_png"], altura_max=150 * mm))
        if b.get("mapa_legenda"):
            hist.append(Paragraph(_t(b["mapa_legenda"]), E["peq"]))

    # ---------------- aeródromos ----------------
    if b.get("aerodromos"):
        hist += _secao("Origem, destino e alternativa: METAR e TAF")
        hist += [_bloco_aerodromo(a) for a in b["aerodromos"]]
    if b.get("em_rota") is not None:
        hist += _secao(f"Aeródromos no meio da rota (até {b['corredor_nm']} NM dela)")
        if b["em_rota"]:
            hist += [_bloco_aerodromo(a) for a in b["em_rota"]]
        else:
            hist.append(Paragraph("Nenhum aeródromo do site dentro do corredor (fora das áreas de 40 NM em volta "
                                  "da origem, do destino e da alternativa).", E["corpo"]))

    # ---------------- SIGMET ----------------
    if b.get("sigmets") is not None:
        hist += _secao(f"SIGMET que cruzam a rota ou estão a até {b['corredor_nm']} NM")
        if not b["sigmets"]:
            hist.append(Paragraph("Nenhum SIGMET vigente perto da rota.", E["corpo"]))
        for d, bruto, no_nivel in b["sigmets"]:
            nivel = {True: f"ATINGE o {b['nivel'].split(' ')[0]}", False: "fora do seu nível",
                     None: "níveis não informados"}[no_nivel]
            campos = [("FIR", d.get("fir")), ("Validade", d.get("validade")), ("Fenômeno", d.get("fenomeno")),
                      ("Situação", d.get("situacao")), ("Níveis", d.get("niveis")),
                      ("Movimento", d.get("movimento")), ("No seu nível?", nivel)]
            texto = "<br/>".join(f"<b>{_t(k)}:</b> {_t(v)}" for k, v in campos if v)
            cab = Paragraph(f"<font color='{d['cor']}'><b>{_t(d['titulo'])}</b></font>", E["corpo"])
            hist.append(KeepTogether([cab, Paragraph(texto, E["corpo"]),
                                      _caixa_msg(bruto, colors.HexColor("#f6f6f6"), colors.HexColor(d["cor"])),
                                      Spacer(1, 3 * mm)]))
    if b.get("raios_txt"):
        hist += _secao("Descargas atmosféricas (raios)")
        hist.append(Paragraph(_t(b["raios_txt"]), E["corpo"]))

    # ---------------- vento ----------------
    if b.get("vento"):
        v = b["vento"]
        hist.append(PageBreak())
        hist += _secao(f"Vento e temperatura: {v['nivel']} e níveis vizinhos (modelo GFS)")
        hist.append(Paragraph(_t(v["fonte"]), E["peq"]))
        hist.append(Spacer(1, 2 * mm))
        comp = v["comparacao"]
        hist.append(_tabela(list(comp[0]), [list(l.values()) for l in comp],
                            [42 * mm, 38 * mm, 28 * mm, 40 * mm, LARG - 148 * mm],
                            [(i, 0, colors.HexColor("#fff4c2")) for i, l in enumerate(comp) if "escolhido" in l["Nível"]]))
        hist.append(Spacer(1, 3 * mm))
        # Tabela ponto a ponto: os três níveis lado a lado (vento / temperatura / componente)
        niveis = v["niveis"]
        cab = ["Nº", "Hora", "Posição"] + [n + (" *" if n == v["nivel"] else "") for n in niveis] + ["GFS"]
        linhas, cores = [], []
        for i, l in enumerate(v["linhas"]):
            celulas = [str(l["n"]), f"{l['hora']:%H:%M}Z", f"{l['dist_nm']} NM\n" + _posicao(l)]
            for j, n in enumerate(niveis):
                x = l["por_nivel"][n]
                celulas.append(f"{x['vento']}\n{x['temp_c']} °C ISA{x['isa_desvio']:+d}\n"
                               f"{_comp(x['componente'])}")
                if x["componente"] <= -15:
                    cores.append((i, 3 + j, colors.HexColor("#ffe3e3")))
                elif x["componente"] >= 15:
                    cores.append((i, 3 + j, colors.HexColor("#e2f7e6")))
            celulas.append(f"{l['validade']:%d/%m %H}Z")
            linhas.append(celulas)
        larg_n = (LARG - 10 * mm - 15 * mm - 28 * mm - 20 * mm) / len(niveis)
        hist.append(_tabela(cab, linhas, [10 * mm, 15 * mm, 28 * mm] + [larg_n] * len(niveis) + [20 * mm], cores))
        hist.append(Paragraph("* nível escolhido. Verde = vento de cauda >= 15 kt; vermelho = proa >= 15 kt.",
                              E["peq"]))
        hist.append(Spacer(1, 2 * mm))
        hist.append(Paragraph(_t(v["resumo_txt"]), E["corpo"]))
        if v.get("mapa_png"):
            hist.append(Spacer(1, 3 * mm))
            hist.append(_imagem(v["mapa_png"], altura_max=150 * mm))
            hist.append(Paragraph("Os números no mapa são os pontos da tabela. Barbelas: traço longo = 10 kt, "
                                  "traço curto = 5 kt, bandeira = 50 kt; a haste aponta para DE ONDE o vento sopra.",
                                  E["peq"]))

    # ---------------- SIGWX ----------------
    for carta in b.get("sigwx") or []:
        hist.append(PageBreak())
        hist += _secao(carta["titulo"])
        hist.append(Paragraph(_t(carta["nota"]), E["peq"]))
        hist.append(_imagem(carta["png"], altura_max=215 * mm))

    hist += [Spacer(1, 6 * mm), Paragraph(
        "Fontes: METAR, TAF, SIGMET, aviso de aeródromo, raios (STSC) e SIGWX: API REDEMET (DECEA). "
        "Satélite: NOAA GOES-19. Vento e temperatura: modelo NOAA GFS 0,25°. Mapa de fundo: Esri. "
        "Documento gerado automaticamente para fins de instrução.", E["peq"])]

    doc.build(hist, onFirstPage=lambda c, d: _pagina(c, d, rota_txt),
              onLaterPages=lambda c, d: _pagina(c, d, rota_txt))
    return buf.getvalue()
