"""Leitura do METAR: visibilidade, teto e categoria de voo.

Dois critérios disponíveis:

  FAA (o mesmo que o meteoblue usa nas etiquetas VFR/MVFR/IFR/LIFR)
      LIFR : teto < 500 ft        ou visibilidade < 1 SM   (1.609 m)
      IFR  : teto 500 a <1000 ft  ou visibilidade 1 a <3 SM (até 4.827 m)
      MVFR : teto 1000 a 3000 ft  ou visibilidade 3 a 5 SM  (até 8.047 m)
      VFR  : teto > 3000 ft       e  visibilidade > 5 SM

  REDEMET (as cores do mapa de aeródromos da REDEMET)
      verde   : visibilidade >= 5000 m  e teto >= 1500 ft
      amarelo : visibilidade 1500 a <5000 m  ou teto 600 a <1500 ft
      vermelho: visibilidade < 1500 m        ou teto < 600 ft

"Teto" = a camada BKN, OVC ou VV mais baixa.
"""
import re
from datetime import datetime, timedelta, timezone

SM = 1609.34  # 1 milha terrestre em metros

# Cada categoria: (etiqueta, cor de fundo, cor do texto)
CATEGORIAS_FAA = {
    "VFR":  ("VFR",  "#2e9e44", "#ffffff"),
    "MVFR": ("MVFR", "#3f6fd8", "#ffffff"),
    "IFR":  ("IFR",  "#d7263d", "#ffffff"),
    "LIFR": ("LIFR", "#b02fb5", "#ffffff"),
    "ND":   ("N/D",  "#8a949e", "#ffffff"),
}
CATEGORIAS_REDEMET = {
    "VERDE":    ("", "#1fbf3f", "#ffffff"),
    "AMARELO":  ("", "#f2b705", "#000000"),
    "VERMELHO": ("", "#e0202b", "#ffffff"),
    "ND":       ("", "#b8c0c8", "#000000"),
}


def _parte_principal(metar):
    """Corta o que não é observação atual: RMK (observações) e a tendência
    (BECMG, TEMPO, NOSIG), para não confundir com a visibilidade/teto de agora."""
    return re.split(r"\s(?:RMK|BECMG|TEMPO|NOSIG)\b", metar)[0]


def visibilidade_m(metar):
    """Visibilidade predominante em metros (None se não achar).
    CAVOK -> 10000.  '9999' -> 10000.  Aceita também milhas (ex.: 10SM, 1/2SM)."""
    corpo = _parte_principal(metar)
    if re.search(r"\bCAVOK\b", corpo):
        return 10000
    for tok in corpo.split()[2:]:                    # pula "METAR SBGR" / "SBGR 291700Z"
        if re.fullmatch(r"\d{6}Z", tok):             # é o horário, não visibilidade
            continue
        m = re.fullmatch(r"(\d{4})(NDV|[NSEW]{1,2})?", tok)
        if m:
            v = int(m.group(1))
            return 10000 if v == 9999 else v
        m = re.fullmatch(r"[PM]?(\d+)?(?:_?(\d)/(\d))?SM", tok.replace(" ", "_"))
        if m and (m.group(1) or m.group(2)):
            milhas = int(m.group(1) or 0) + (int(m.group(2)) / int(m.group(3)) if m.group(2) else 0)
            return round(milhas * SM)
    return None


def teto_ft(metar):
    """Altura do teto em pés: a camada BKN/OVC/VV mais baixa.
    Retorna None quando não há teto (FEW, SCT, NSC, CAVOK...).
    VV/// (céu obscurecido, altura não informada) é tratado como teto 0."""
    corpo = _parte_principal(metar)
    alturas = []
    for tipo, alt in re.findall(r"\b(BKN|OVC|VV)(\d{3}|///)", corpo):
        if alt == "///":
            if tipo == "VV":
                alturas.append(0)
            continue
        alturas.append(int(alt) * 100)
    return min(alturas) if alturas else None


def categoria_faa(vis, teto):
    if vis is None and teto is None:
        return "ND"
    vis = 99999 if vis is None else vis
    teto = 99999 if teto is None else teto
    if teto < 500 or vis < 1 * SM:
        return "LIFR"
    if teto < 1000 or vis < 3 * SM:
        return "IFR"
    if teto <= 3000 or vis <= 5 * SM:
        return "MVFR"
    return "VFR"


def categoria_redemet(vis, teto):
    if vis is None and teto is None:
        return "ND"
    vis = 99999 if vis is None else vis
    teto = 99999 if teto is None else teto
    if vis < 1500 or teto < 600:
        return "VERMELHO"
    if vis < 5000 or teto < 1500:
        return "AMARELO"
    return "VERDE"


def horario_metar(metar, agora=None):
    """Lê o grupo ddhhmmZ e devolve um datetime em UTC (ou None).
    Se o dia do METAR for maior que o de hoje, é do mês anterior."""
    m = re.search(r"\b(\d{2})(\d{2})(\d{2})Z\b", metar)
    if not m:
        return None
    agora = agora or datetime.now(timezone.utc)
    dia, hora, minuto = (int(x) for x in m.groups())
    ano, mes = agora.year, agora.month
    if dia > agora.day:                     # virou o mês
        mes -= 1
        if mes == 0:
            ano, mes = ano - 1, 12
    try:
        return datetime(ano, mes, dia, hora, minuto, tzinfo=timezone.utc)
    except ValueError:
        return None


def analisar(metar, agora=None):
    """Resumo usado pelo mapa e pelos cartões."""
    agora = agora or datetime.now(timezone.utc)
    vis, teto = visibilidade_m(metar), teto_ft(metar)
    hora = horario_metar(metar, agora)
    idade_min = int((agora - hora).total_seconds() // 60) if hora else None
    return {
        "vis_m": vis,
        "teto_ft": teto,
        "faa": categoria_faa(vis, teto),
        "redemet": categoria_redemet(vis, teto),
        "hora": hora,
        "idade_min": idade_min,
        # REDEMET considera "atual" a mensagem da hora corrente; aqui: até 90 min
        "antigo": idade_min is None or idade_min > 90,
    }


def formatar_taf(taf):
    """Quebra o TAF em linhas antes de BECMG, TEMPO, PROB e FM (fica bem mais legível)."""
    # (?<!PROB\d\d) evita separar "PROB30 TEMPO", que é um grupo só
    return re.sub(r"(?<!PROB\d\d)\s+(?=(?:BECMG|TEMPO|PROB\d{2}|FM\d{6})\b)", "\n    ", taf.strip())
