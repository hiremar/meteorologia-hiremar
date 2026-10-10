"""Perfil vertical do voo: TOC (Top of Climb) e TOD (Top of Descent). SIMULADO, para instrução.

A ideia é a mesma da conta que se faz no papel:
    tempo de subida = pés a subir ÷ razão de subida
    distância       = velocidade no solo (GS) × tempo ÷ 60
Só que, em vez de usar UMA razão de subida para tudo, dividimos a subida em degraus de
500 ft e, em cada degrau, usamos a razão e a velocidade daquela faixa de altitude
(o avião sobe bem mais rápido perto do solo do que perto do teto). A descida é igual, ao contrário.

De onde vêm os números: EUROCONTROL Aircraft Performance Database (base de treinamento de
controladores). Valores INDICATIVOS e médios: o avião real depende de peso, temperatura,
vento, regime de potência, restrições da SID/STAR e do ATC. NÃO usar para decisão real.
"""
import math

FONTE = "EUROCONTROL Aircraft Performance Database (valores indicativos, só para instrução)"

# Cada fase da EUROCONTROL é (velocidade, razão em ft/min). None = a base não tem o dado.
#   ini   : subida inicial até 5.000 ft        (IAS kt, ROC)
#   s150  : subida até o FL150                  (IAS kt, ROC)
#   s240  : subida até o FL240                  (IAS kt, ROC)
#   smach : subida acima do FL240, em Mach      (Mach,   ROC)
#   cruz  : cruzeiro                            (TAS kt, Mach ou None)
#   dmach : descida inicial até o FL240, Mach   (Mach,   ROD)
#   d100  : descida até o FL100                 (IAS kt, ROD)
#   apch  : aproximação (abaixo do FL100)       (IAS kt, ROD)
#   teto  : teto (FL)
AERONAVES = {
    # ---- aviação geral ----
    "C172": {"nome": "Cessna 172", "ini": (90, 400), "s150": None, "s240": None, "smach": None,
             "cruz": (115, None), "dmach": None, "d100": (120, 500), "apch": (110, 500), "teto": 130},
    "SR22": {"nome": "Cirrus SR22", "ini": (75, 1260), "s150": (110, 600), "s240": (110, 600), "smach": None,
             "cruz": (180, None), "dmach": None, "d100": (140, 1000), "apch": (120, 1000), "teto": 175},
    "C208": {"nome": "Cessna 208 Caravan", "ini": (115, 800), "s150": (130, 500), "s240": (130, 500),
             "smach": None, "cruz": (160, None), "dmach": None, "d100": (160, 500), "apch": (120, 500),
             "teto": 260},
    "PC12": {"nome": "Pilatus PC-12", "ini": (130, 1700), "s150": (130, 1000), "s240": (130, 700),
             "smach": None, "cruz": (270, None), "dmach": None, "d100": (210, 1500), "apch": (180, 1500),
             "teto": 300},
    # ---- turbo-hélices regionais ----
    "AT72": {"nome": "ATR 72", "ini": (140, 1500), "s150": (210, 1000), "s240": (210, 1000), "smach": None,
             "cruz": (275, None), "dmach": None, "d100": (260, 1500), "apch": (200, 1500), "teto": 250},
    # ---- jatos executivos ----
    "E50P": {"nome": "Embraer Phenom 100", "ini": (200, 3500), "s150": (260, 2500), "s240": (260, 2000),
             "smach": (0.68, 2000), "cruz": (370, 0.70), "dmach": (0.69, 1500), "d100": (250, 2500),
             "apch": (140, 1500), "teto": 410},
    "E55P": {"nome": "Embraer Phenom 300", "ini": (200, 4000), "s150": (260, 2500), "s240": (260, 2000),
             "smach": (0.75, 2000), "cruz": (450, 0.77), "dmach": (0.76, 1500), "d100": (250, 2500),
             "apch": (170, 1500), "teto": 450},
    # ---- jatos regionais / NARROW ----
    "E195": {"nome": "Embraer E195 (E195-E2 aproximado)", "ini": (190, 3000), "s150": (300, 2500),
             "s240": (300, 2000), "smach": (0.75, 1500), "cruz": (447, 0.78), "dmach": (0.76, 2000),
             "d100": (250, 2500), "apch": (230, 1600), "teto": 410},
    "A319": {"nome": "Airbus A319", "ini": (165, 2500), "s150": (290, 2200), "s240": (290, 1500),
             "smach": (0.78, 1000), "cruz": (450, 0.79), "dmach": (0.78, 1000), "d100": (290, 3500),
             "apch": (230, 1500), "teto": 390},
    "A320": {"nome": "Airbus A320", "ini": (175, 2500), "s150": (290, 2000), "s240": (290, 1400),
             "smach": (0.78, 1000), "cruz": (450, 0.79), "dmach": (0.78, 1000), "d100": (290, 3500),
             "apch": (250, 1500), "teto": 390},
    "A20N": {"nome": "Airbus A320neo", "ini": (175, 2200), "s150": (290, 2000), "s240": (290, 1500),
             "smach": (0.78, 1000), "cruz": (450, 0.78), "dmach": (0.78, 1000), "d100": (290, 3000),
             "apch": (250, 1500), "teto": 390},
    "A321": {"nome": "Airbus A321", "ini": (175, 2500), "s150": (290, 2000), "s240": (290, 1800),
             "smach": (0.78, 1000), "cruz": (450, 0.79), "dmach": (0.78, 1000), "d100": (290, 2500),
             "apch": (225, 1500), "teto": 410},
    "A21N": {"nome": "Airbus A321neo", "ini": (175, 2000), "s150": (290, 1500), "s240": (290, 1200),
             "smach": (0.78, 1000), "cruz": (450, 0.78), "dmach": (0.78, 1500), "d100": (290, 2500),
             "apch": (250, 1300), "teto": 390},
    "B738": {"nome": "Boeing 737-800", "ini": (165, 3000), "s150": (290, 2000), "s240": (290, 2000),
             "smach": (0.78, 1500), "cruz": (460, 0.79), "dmach": (0.78, 800), "d100": (280, 3500),
             "apch": (250, 1500), "teto": 410},
    "B38M": {"nome": "Boeing 737 MAX 8", "ini": (165, 2500), "s150": (290, 2300), "s240": (290, 2000),
             "smach": (0.78, 1500), "cruz": (453, 0.79), "dmach": (0.78, 1000), "d100": (290, 3500),
             "apch": (250, 1500), "teto": 410},
    # ---- widebody ----
    "B763": {"nome": "Boeing 767-300", "ini": (190, 3000), "s150": (290, 2500), "s240": (290, 2000),
             "smach": (0.72, 1000), "cruz": (460, 0.80), "dmach": (0.72, 1000), "d100": (290, 3000),
             "apch": (230, 1500), "teto": 450},
    "B789": {"nome": "Boeing 787-9", "ini": (190, 2700), "s150": (290, 2000), "s240": (290, 1500),
             "smach": (0.84, 1000), "cruz": (490, 0.85), "dmach": (0.85, 2500), "d100": (300, 2500),
             "apch": (240, 1500), "teto": 430},
    "B77W": {"nome": "Boeing 777-300ER", "ini": (200, 3000), "s150": (300, 2500), "s240": (300, 2000),
             "smach": (0.83, 1500), "cruz": (490, 0.84), "dmach": (0.84, 1000), "d100": (300, 3000),
             "apch": (240, 1500), "teto": 430},
    "A359": {"nome": "Airbus A350-900", "ini": (220, 3000), "s150": (300, 2300), "s240": (300, 1600),
             "smach": (0.82, 1400), "cruz": (490, 0.85), "dmach": (0.85, 1500), "d100": (250, 3000),
             "apch": (240, 1500), "teto": 430},
}
PADRAO = "A320"

# Elevação (ft) dos aeródromos mais usados. Faltando aqui = 0 ft (e o site avisa).
# Confira no ROTAER/AIP antes de usar em aula; acrescente outros copiando uma linha.
ELEVACAO_FT = {
    "SBGR": 2461, "SBSP": 2631, "SBKP": 2170, "SBBR": 3497, "SBCF": 2715, "SBBH": 2589,
    "SBCT": 2988, "SBRJ": 11, "SBGL": 28, "SBPA": 11, "SBFL": 16, "SBCG": 1833, "SBCY": 617,
}


def rotulo(codigo):
    """'A320' -> 'A320 · Airbus A320'  (para a caixa de seleção)"""
    return f"{codigo} · {AERONAVES[codigo]['nome']}"


# ---------------------------------------------------------------------------
# Atmosfera padrão (ISA): precisamos dela para passar de IAS para TAS
# ---------------------------------------------------------------------------
def _temp_isa_k(h_ft):
    """Temperatura ISA em kelvin: cai 1,98 °C a cada 1.000 ft até 36.089 ft, depois fica -56,5 °C."""
    return max(288.15 - 0.0019812 * h_ft, 216.65)


def _densidade_relativa(h_ft):
    """σ = densidade no nível ÷ densidade ao nível do mar (ISA)."""
    if h_ft <= 36089:
        return (1 - 6.8756e-6 * h_ft) ** 4.2559
    return 0.2971 * math.exp(-(h_ft - 36089) / 20806)


def tas_de_ias(ias, h_ft):
    """TAS ≈ IAS ÷ √σ  (o ar rarefeito faz o avião andar mais rápido do que o velocímetro mostra:
    regra de bolso ≈ +2% a cada 1.000 ft)."""
    return ias / math.sqrt(_densidade_relativa(h_ft))


def tas_de_mach(mach, h_ft):
    """TAS = Mach × velocidade do som; a velocidade do som só depende da temperatura (661,5 kt a 15 °C)."""
    return mach * 661.47 * math.sqrt(_temp_isa_k(h_ft) / 288.15)


# ---------------------------------------------------------------------------
# Qual velocidade e razão usar em cada altitude
# ---------------------------------------------------------------------------
def _primeiro(*opcoes):
    """O primeiro dado que existe (a base não tem tudo para os aviões menores)."""
    return next(o for o in opcoes if o)


def _subida(av, h_ft):
    """(TAS kt, razão ft/min) na subida a h_ft."""
    if h_ft < 5000:
        ias, roc = av["ini"]
    elif h_ft < 15000:
        ias, roc = _primeiro(av["s150"], av["ini"])
    elif h_ft < 24000 or not av["smach"]:
        ias, roc = _primeiro(av["s240"], av["s150"], av["ini"])
    else:
        mach, roc = av["smach"]
        ias = _primeiro(av["s240"], av["s150"])[0]
        # sobe em IAS constante até o Mach alcançar o valor de subida (crossover); dali em diante, Mach
        return min(tas_de_ias(ias, h_ft), tas_de_mach(mach, h_ft)), roc
    if h_ft < 10000:
        ias = min(ias, 250)              # limite de 250 kt abaixo do FL100
    return tas_de_ias(ias, h_ft), roc


def _descida(av, h_ft):
    """(TAS kt, razão ft/min) na descida a h_ft."""
    if h_ft > 24000 and av["dmach"]:
        mach, rod = av["dmach"]
        return min(tas_de_mach(mach, h_ft), tas_de_ias(av["d100"][0], h_ft)), rod
    if h_ft > 10000:
        ias, rod = av["d100"]
    else:
        ias, rod = _primeiro(av["apch"], av["d100"])
        ias = min(ias, 250)
    return tas_de_ias(ias, h_ft), rod


def _trecho(av, de_ft, ate_ft, vento_kt, fase, passo=500):
    """Percorre de de_ft até ate_ft em degraus de 500 ft.
    Devolve lista de pontos (distância NM, tempo min, altitude ft) desde o início do trecho."""
    pontos = [(0.0, 0.0, de_ft)]
    dist = tempo = 0.0
    h = de_ft
    sentido = 1 if ate_ft > de_ft else -1
    while (ate_ft - h) * sentido > 0:
        dh = min(passo, abs(ate_ft - h))
        meio = h + sentido * dh / 2                       # usa a altitude do meio do degrau
        tas, razao = (_subida if fase == "subida" else _descida)(av, meio)
        dt = dh / razao                                   # minutos para subir/descer este degrau
        gs = max(tas + vento_kt, 30)                      # velocidade no solo (vento de cauda +, proa -)
        dist += gs * dt / 60
        tempo += dt
        h += sentido * dh
        pontos.append((dist, tempo, h))
    return pontos


def _altitude_em(pontos, d, antes=None):
    """Altitude na distância d, interpolando (regra de três) entre os pontos [(dist, alt)].
    Antes do primeiro ponto devolve 'antes' (ou a altitude do primeiro ponto)."""
    if d <= pontos[0][0]:
        return pontos[0][1] if antes is None else antes
    for (d1, h1), (d2, h2) in zip(pontos, pontos[1:]):
        if d1 <= d <= d2:
            return h1 if d2 == d1 else h1 + (h2 - h1) * (d - d1) / (d2 - d1)
    return pontos[-1][1]


def calcular(tipo, fl, dist_total_nm, elev_origem_ft=0, elev_destino_ft=0, vento_cruzeiro_kt=0):
    """Perfil vertical completo. vento_cruzeiro_kt = componente média no nível (+ cauda, - proa).
    Na subida e na descida usamos METADE desse vento (perto do solo o vento costuma ser mais fraco).

    Devolve um dicionário com:
      toc_nm, toc_min           distância e tempo da decolagem até o TOC
      tod_nm, tod_min           distância e tempo do TOD até o pouso (TOD = dist_total - tod_nm)
      regra_3x1_nm              estimativa da regra prática (3 NM por 1.000 ft a perder)
      eet_perfil_min            tempo de voo estimado pelo perfil (subida + cruzeiro + descida)
      atinge_nivel              False se a rota é curta demais para chegar ao FL
      perfil                    [(dist NM desde a origem, altitude ft)] para desenhar o gráfico
      avisos                    textos para mostrar ao aluno"""
    av = AERONAVES[tipo]
    alvo = fl * 100
    avisos = []
    if fl > av["teto"]:
        avisos.append(f"O FL{fl:03d} está acima do teto de referência do {av['nome']} (FL{av['teto']:03d}).")
    sub = _trecho(av, elev_origem_ft, alvo, vento_cruzeiro_kt / 2, "subida")
    des = _trecho(av, alvo, elev_destino_ft, vento_cruzeiro_kt / 2, "descida")
    toc_nm, toc_min = sub[-1][0], sub[-1][1]
    tod_nm, tod_min = des[-1][0], des[-1][1]

    tas_cruz, mach_cruz = av["cruz"]
    if mach_cruz and alvo >= 24000:
        tas_cruz = tas_de_mach(mach_cruz, alvo)
    gs_cruz = max(tas_cruz + vento_cruzeiro_kt, 30)
    cruzeiro_nm = dist_total_nm - toc_nm - tod_nm
    atinge = cruzeiro_nm >= 0

    if atinge:
        perfil = [(d, h) for d, _, h in sub] + [(dist_total_nm - tod_nm + d, h) for d, _, h in des]
        eet = toc_min + cruzeiro_nm / gs_cruz * 60 + tod_min
    else:
        # Rota curta: a subida e a descida se cruzam antes do FL. Achamos a altitude do encontro.
        avisos.append(f"Rota curta: com {dist_total_nm:.0f} NM o {av['nome']} não chega ao FL{fl:03d} "
                      f"(precisaria de ~{toc_nm + tod_nm:.0f} NM). Escolha um nível mais baixo.")
        subida_em = [(d, h) for d, _, h in sub]
        descida_em = [(dist_total_nm - tod_nm + d, h) for d, _, h in des]
        perfil, eet = [], None
        for d, h in subida_em:
            # Onde a linha de subida encontra a linha de descida, o avião tem de começar a descer.
            if h >= _altitude_em(descida_em, d, alvo):
                break
            perfil.append((d, h))
        topo = perfil[-1] if perfil else (0, elev_origem_ft)
        perfil += [(d, h) for d, h in descida_em if d > topo[0]]

    perder = max(alvo - elev_destino_ft, 0)
    return {"tipo": tipo, "nome": av["nome"], "fl": fl,
            "toc_nm": toc_nm, "toc_min": toc_min, "tod_nm": tod_nm, "tod_min": tod_min,
            "regra_3x1_nm": perder / 1000 * 3,
            "eet_perfil_min": eet, "atinge_nivel": atinge, "dist_total_nm": dist_total_nm,
            "tas_cruzeiro": round(tas_cruz), "perfil": perfil, "avisos": avisos,
            "elev_origem": elev_origem_ft, "elev_destino": elev_destino_ft}


def fase_no_ponto(p, dist_nm):
    """'subida' / 'cruzeiro' / 'descida' e a altitude estimada (ft) num ponto da rota."""
    perfil = p["perfil"]
    alvo = p["fl"] * 100
    alt = _altitude_em(perfil, dist_nm)
    if p["atinge_nivel"] and p["toc_nm"] <= dist_nm <= p["dist_total_nm"] - p["tod_nm"]:
        return "cruzeiro", alvo
    topo = max(perfil, key=lambda x: x[1])[0]
    return ("subida" if dist_nm < topo else "descida"), alt


def texto_fase(p, dist_nm):
    """Texto curto para a tabela: 'subida ~FL120', 'cruzeiro', 'descida ~FL080'."""
    fase, alt = fase_no_ponto(p, dist_nm)
    if fase == "cruzeiro":
        return "cruzeiro"
    if p["atinge_nivel"] and alt >= p["fl"] * 100 - 500:       # a menos de 500 ft do nível
        return "no TOC" if fase == "subida" else "no TOD"
    return f"{fase} ~FL{round(alt / 1000) * 10:03d}" if alt >= 1000 else f"{fase} (< 1.000 ft)"


def resumo_txt(p, etd=None):
    """Uma linha para o briefing: TOC e TOD com distância, tempo e (se tiver ETD) hora."""
    from datetime import timedelta
    h_toc = f" ({etd + timedelta(minutes=p['toc_min']):%H:%MZ})" if etd else ""
    tod_da_origem = p["dist_total_nm"] - p["tod_nm"]
    if not p["atinge_nivel"]:
        return f"{p['nome']}: rota curta, não atinge o FL{p['fl']:03d}."
    return (f"{p['nome']}: TOC a {p['toc_nm']:.0f} NM / {p['toc_min']:.0f} min da decolagem{h_toc} · "
            f"TOD a {p['tod_nm']:.0f} NM do destino ({tod_da_origem:.0f} NM da origem), "
            f"descida de ~{p['tod_min']:.0f} min")


def grafico_png(p, titulo="", real=None):
    """Desenho do perfil vertical (distância × altitude), em PNG, para o site e o PDF.
    real (opcional) = tracklog.perfil_real(): desenha o voo REAL por cima, em verde."""
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    xs = [d for d, _ in p["perfil"]]
    ys = [h / 100 for _, h in p["perfil"]]          # em FL (centenas de pés)
    fig, ax = plt.subplots(figsize=(9, 3.2), dpi=130)
    ax.fill_between(xs, ys, color="#1f77b4", alpha=0.12)
    ax.plot(xs, ys, color="#1f77b4", lw=2.2, label="simulado")
    x_max, y_max = p["dist_total_nm"], max(max(ys), p["fl"])
    if real:
        rx = [d for d, _ in real["perfil"]]
        ry = [h / 100 for _, h in real["perfil"]]
        ax.plot(rx, ry, color="#2e9e44", lw=2, label="voo real (track log)")
        for x, nome in ((real["toc_nm"], "TOC"), (real["total_nm"] - real["tod_nm"], "TOD")):
            ax.plot([x], [real["nivel_fl"]], marker="v", color="#2e9e44", ms=7)
            ax.annotate(f"{nome} real\n{x:.0f} NM", (x, real["nivel_fl"]), xytext=(0, -26),
                        textcoords="offset points", ha="center", fontsize=7.5, color="#1d6b2d")
        x_max, y_max = max(x_max, real["total_nm"]), max(y_max, max(ry))
    if p["atinge_nivel"]:
        d_tod = p["dist_total_nm"] - p["tod_nm"]
        for x, nome in ((p["toc_nm"], "TOC"), (d_tod, "TOD")):
            ax.axvline(x, color="#e8a317", ls="--", lw=1.2)
            ax.annotate(f"{nome}\n{x:.0f} NM", (x, p["fl"]), xytext=(0, 6), textcoords="offset points",
                        ha="center", va="bottom", fontsize=8, color="#7a5300", fontweight="bold")
        # regra prática 3:1, tracejada, para comparar com o perfil "do avião"
        x3 = p["dist_total_nm"] - p["regra_3x1_nm"]
        ax.plot([x3, p["dist_total_nm"]], [p["fl"], p["elev_destino"] / 100], color="#888", ls=":", lw=1.4,
                label=f"regra 3:1 (TOD a {p['regra_3x1_nm']:.0f} NM do destino)")
    else:
        d_topo, h_topo = max(p["perfil"], key=lambda x: x[1])
        ax.axhline(p["fl"], color="#d7263d", ls="--", lw=1)
        ax.annotate(f"FL{p['fl']:03d} pedido: não atinge", (p["dist_total_nm"] / 2, p["fl"]), xytext=(0, 4),
                    textcoords="offset points", ha="center", fontsize=8, color="#d7263d")
        ax.annotate(f"topo ~FL{round(h_topo / 1000) * 10:03d}", (d_topo, h_topo / 100), xytext=(0, 6),
                    textcoords="offset points", ha="center", fontsize=8, fontweight="bold")
    ax.legend(loc="lower center", fontsize=8, frameon=False, ncol=3)
    ax.set_xlim(0, x_max)
    ax.set_ylim(0, y_max * 1.22)
    ax.set_xlabel("distância desde a origem (NM)")
    ax.set_ylabel("nível (FL)")
    ax.set_title(titulo or f"Perfil vertical simulado · {p['nome']} · FL{p['fl']:03d}", fontsize=10)
    ax.grid(alpha=0.3)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return buf.getvalue()
