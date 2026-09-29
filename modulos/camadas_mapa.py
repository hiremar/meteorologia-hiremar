"""Tudo que é desenhado no mapa (folium = Python que gera um mapa Leaflet)."""
import html
import json

import folium
from jinja2 import Template
from folium.map import Layer

from .aerodromos import AERODROMOS, NOMES
from . import metar as mt
from . import redemet as rd

# ---------------------------------------------------------------------------
# 1) Mapas de fundo — nenhum exige chave de API
# ---------------------------------------------------------------------------
ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/{}/MapServer/tile/{{z}}/{{y}}/{{x}}"

MAPAS_FUNDO = [
    # (nome no menu, url, atribuição, zoom máximo)
    ("Escuro", ESRI.format("Canvas/World_Dark_Gray_Base"), "Tiles © Esri", 16),
    ("Político (OpenStreetMap)", "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
     "© OpenStreetMap contributors", 19),
    ("Relevo (OpenTopoMap)", "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
     "© OpenStreetMap contributors, SRTM | © OpenTopoMap (CC-BY-SA)", 17),
    ("Imagem de satélite (Esri)", ESRI.format("World_Imagery"),
     "Tiles © Esri — Esri, Maxar, Earthstar Geographics", 18),
]


def adicionar_mapas_fundo(m, inicial="Escuro"):
    for nome, url, attr, zmax in MAPAS_FUNDO:
        folium.TileLayer(url, attr=attr, name=nome, max_zoom=zmax, overlay=False,
                         show=(nome == inicial)).add_to(m)
    # Camada "política": fronteiras, estados e nomes de cidades, POR CIMA de tudo
    # (num painel próprio, acima do satélite e abaixo dos marcadores)
    folium.map.CustomPane("rotulos", z_index=450).add_to(m)
    folium.TileLayer(ESRI.format("Reference/World_Boundaries_and_Places"), attr="© Esri",
                     name="Fronteiras e nomes", overlay=True, show=True, pane="rotulos",
                     max_zoom=16).add_to(m)


# ---------------------------------------------------------------------------
# 2) Aeródromos com categoria de voo e METAR/TAF ao passar o mouse
# ---------------------------------------------------------------------------
CSS_MAPA = """
<style>
 .cat {font: 700 10px/14px 'Segoe UI',Arial,sans-serif; padding: 0 4px; border-radius: 3px;
       text-align:center; box-shadow: 0 0 0 1px rgba(0,0,0,.55); white-space:nowrap}
 .cat.velho {opacity:.5}
 .bol {width:12px;height:12px;border-radius:50%;box-shadow:0 0 0 1.5px #111}
 .bol.velho {background:transparent !important; border:3px solid; box-sizing:border-box}
 .leaflet-tooltip.msg-tip {width:max-content; max-width:min(560px, 80vw); white-space:normal; font:12px/1.35 Consolas,monospace;
       background:#0d1b28; color:#e8eef3; border:1px solid #2c4a63; box-shadow:0 2px 10px rgba(0,0,0,.5)}
 .msg-tip b.t {color:#f1c40f; font-family:'Segoe UI',Arial,sans-serif}
 .msg-tip pre {white-space:pre-wrap; margin:2px 0 6px; font:inherit; color:#bdf5c4}
 .msg-tip .sub {color:#9fb3c4; font-family:'Segoe UI',Arial,sans-serif; font-size:11px}
 .legenda-mapa {background:rgba(13,27,40,.9); color:#e8eef3; padding:6px 8px; border-radius:6px;
       font:11px/1.3 'Segoe UI',Arial,sans-serif; box-shadow:0 1px 6px rgba(0,0,0,.5)}
 .legenda-mapa .barra {height:10px; width:240px; border-radius:2px; margin:4px 0 2px}
 .legenda-mapa .ticks {display:flex; justify-content:space-between; width:240px; color:#c9d3dc}
 .legenda-mapa .leitura {color:#f1c40f; margin-top:3px; min-height:14px}
</style>
"""


def _tooltip_html(icao, metar, taf, info):
    idade = "" if info is None or info["idade_min"] is None else f" · há {info['idade_min']} min"
    partes = [f"<b class='t'>{icao}</b> <span class='sub'>{html.escape(NOMES.get(icao, ''))}{idade}</span>"]
    partes.append(f"<pre>{html.escape(metar) if metar else 'METAR não disponível'}</pre>")
    if taf:
        partes.append(f"<pre>{html.escape(mt.formatar_taf(taf))}</pre>")
    return "".join(partes)


def adicionar_aerodromos(m, metars, tafs, estilo="FAA"):
    """estilo 'FAA' = etiquetas VFR/MVFR/IFR/LIFR ; 'REDEMET' = bolinhas coloridas."""
    grupo = folium.FeatureGroup(name="Aeródromos (capitais)", show=True)
    for icao, _, _, lat, lon in AERODROMOS:
        metar = (metars.get(icao) or {}).get("mens", "")
        taf = (tafs.get(icao) or {}).get("mens", "")
        info = mt.analisar(metar) if metar else None
        velho = " velho" if (info is None or info["antigo"]) else ""
        if estilo == "FAA":
            chave = info["faa"] if info else "ND"
            texto, fundo, cor = mt.CATEGORIAS_FAA[chave]
            icone = folium.DivIcon(
                html=f"<div class='cat{velho}' style='background:{fundo};color:{cor}'>{texto}</div>",
                icon_size=(34, 14), icon_anchor=(17, 7))
        else:
            chave = info["redemet"] if info else "ND"
            _, fundo, _ = mt.CATEGORIAS_REDEMET[chave]
            icone = folium.DivIcon(
                html=f"<div class='bol{velho}' style='background:{fundo};border-color:{fundo}'></div>",
                icon_size=(12, 12), icon_anchor=(6, 6))
        # aeroportos vizinhos (SBGL/SBRJ, SBSP/SBGR) se sobrepõem no zoom baixo:
        # o pior tempo fica por cima, para nunca ficar escondido
        gravidade = {"LIFR": 4, "VERMELHO": 4, "IFR": 3, "AMARELO": 3, "MVFR": 2}.get(chave, 1)
        folium.Marker(
            [lat, lon], icon=icone, z_index_offset=gravidade * 1000,
            tooltip=folium.Tooltip(_tooltip_html(icao, metar, taf, info), sticky=True, class_name="msg-tip"),
        ).add_to(grupo)
    grupo.add_to(m)


def legenda_categorias(estilo="FAA"):
    if estilo == "FAA":
        itens = "".join(
            f"<span class='cat' style='background:{f};color:{c};display:inline-block;margin-right:4px'>{t}</span>"
            for k, (t, f, c) in mt.CATEGORIAS_FAA.items())
        nota = "critério FAA (meteoblue). Transparente = METAR com mais de 90 min."
    else:
        nomes = {"VERDE": "vis ≥5 km e teto ≥1500 ft", "AMARELO": "vis 1,5–5 km ou teto 600–1500 ft",
                 "VERMELHO": "vis <1,5 km ou teto <600 ft", "ND": "sem METAR"}
        itens = "<br>".join(
            f"<span class='bol' style='display:inline-block;vertical-align:middle;background:{f}'></span> {nomes[k]}"
            for k, (_, f, _) in mt.CATEGORIAS_REDEMET.items())
        nota = "critério das cores da REDEMET. Vazada = METAR com mais de 90 min."
    return f"<div class='legenda-mapa'>{itens}<div style='margin-top:4px;color:#9fb3c4'>{nota}</div></div>"


# ---------------------------------------------------------------------------
# 3) SIGMET
# ---------------------------------------------------------------------------
def adicionar_sigmets(m, textos):
    """Desenha os SIGMETs que têm polígono. Devolve a lista dos que NÃO puderam
    ser desenhados (ex.: 'N OF S20'), para o site listar em texto."""
    grupo = folium.FeatureGroup(name="SIGMET", show=True)
    nao_desenhados = []
    for txt in textos:
        pts = rd.coordenadas_sigmet(txt)
        fen, cor = rd.fenomeno_sigmet(txt)
        if len(pts) >= 3:
            folium.Polygon(
                pts, color=cor, weight=2, fill=True, fill_opacity=0.22,
                tooltip=f"SIGMET {fen} {rd.niveis_sigmet(txt)}",
                popup=folium.Popup(f"<pre style='white-space:pre-wrap;font:12px monospace'>{html.escape(txt)}</pre>",
                                   max_width=520),
            ).add_to(grupo)
        else:
            nao_desenhados.append(txt)
    grupo.add_to(m)
    return nao_desenhados


# ---------------------------------------------------------------------------
# 4) Legenda fixa no canto do mapa
# ---------------------------------------------------------------------------
class Legenda(folium.MacroElement):
    _template = Template("""
        {% macro script(this, kwargs) %}
        (function(){
          var c = L.control({position: {{ this.posicao|tojson }}});
          c.onAdd = function(){ var d = L.DomUtil.create('div'); d.innerHTML = {{ this.html|tojson }};
                                L.DomEvent.disableClickPropagation(d); return d; };
          c.addTo({{ this._parent.get_name() }});
        })();
        {% endmacro %}
    """)

    def __init__(self, html_legenda, posicao="bottomright"):
        super().__init__()
        self._name = "Legenda"
        self.html = html_legenda
        self.posicao = posicao


# ---------------------------------------------------------------------------
# 5) Camada do modelo (setas de vento ou campo colorido), desenhada no navegador
# ---------------------------------------------------------------------------
# Escalas de cor: (valor, cor). Vento: roxo -> amarelo (paleta "plasma", sequencial).
# Temperatura: azul (frio) -> cinza em 0 °C -> vermelho (quente), útil para o gelo.
ESCALAS = {
    "vento": [[0, "#4c02a1"], [20, "#7e03a8"], [40, "#a92395"], [60, "#cc4778"],
              [80, "#e56b5d"], [100, "#f89441"], [120, "#fdc328"], [150, "#f0f921"]],
    "temperatura": [[-60, "#313695"], [-40, "#4575b4"], [-20, "#74add1"], [-10, "#abd9e9"],
                    [0, "#d9d9d9"], [10, "#fdae61"], [20, "#f46d43"], [30, "#d73027"], [40, "#a50026"]],
}

# O código JavaScript fica num arquivo separado (camada_modelo.js), para ficar legível.
with open(__file__.replace("camadas_mapa.py", "camada_modelo.js"), encoding="utf-8") as _f:
    _JS_CAMADA = _f.read()


class CamadaModelo(Layer):
    """Camada Leaflet própria. Os dados da grade vão embutidos na página e o
    navegador desenha: a cada zoom/arrasto recalcula onde cabem as setas,
    então a densidade se adapta ao zoom. Entra no seletor de camadas do mapa."""

    _template = Template("""
        {% macro header(this, kwargs) %}
            <script>{{ this.js }}</script>
        {% endmacro %}
        {% macro script(this, kwargs) %}
            var {{ this.get_name() }} = new L.CamadaModelo(
                {{ this.grade|tojson }}, {{ this.opcoes|tojson }});
            {% if this.mostrar %}{{ this.get_name() }}.addTo({{ this._parent.get_name() }});{% endif %}
        {% endmacro %}
    """)

    def __init__(self, grade, chave_var, tipo, unidade, titulo, name="Modelo", show=True):
        # show=False no pai: quem adiciona ao mapa é o nosso template (funciona
        # igual em versões antigas e novas do folium)
        super().__init__(name=name, overlay=True, control=True, show=False)
        self._name = "CamadaModelo"
        self.js = _JS_CAMADA
        self.mostrar = show
        self.grade = grade
        self.opcoes = {"tipo": tipo, "unidade": unidade, "titulo": titulo,
                       "escala": ESCALAS[chave_var], "espaco": 34}
