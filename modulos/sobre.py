"""Página "Sobre o professor": currículo em formato de página de perfil.

Como funciona (para estudar):
- Todo o texto fica nas listas/dicionários do começo do arquivo (DADOS). Para atualizar o
  currículo, é só editar ali; o desenho da página (HTML + CSS mais abaixo) não precisa mexer.
- A função `mostrar_sobre()` monta um bloco de HTML e entrega ao Streamlit com
  st.markdown(..., unsafe_allow_html=True).
- E-mail e telefone NÃO entram nesta página, de propósito (site público).
"""
import html

import streamlit as st

# ----------------------------------------------------------------------------
# 1. DADOS DO CURRÍCULO (edite aqui)
# ----------------------------------------------------------------------------
NOME = "Prof. Me. Hiremar Soares"
SUBTITULO = "Meteorologista · Professor universitário · Instrutor de Meteorologia Aeronáutica"
LOCAL = "São Paulo, SP"
LATTES = "http://lattes.cnpq.br/4090433887712772"

RESUMO = (
    "Meteorologista com atuação na aviação civil e militar, com experiência técnica e acadêmica "
    "desde 2005. Mestre e Bacharel em Meteorologia pela Universidade de São Paulo (USP), é professor "
    "universitário desde 2017 e instrutor de Meteorologia Aeronáutica na LATAM Airlines Brasil. "
    "Sua docência é voltada à formação de pilotos, DOVs e comissários, com ênfase em conteúdo "
    "operacional, segurança de voo, ensino digital e pesquisa aplicada à meteorologia operacional."
)

# (número grande, legenda)
DESTAQUES = [
    ("2005", "na meteorologia operacional"),
    ("2012", "instrutor de meteorologia para tripulantes"),
    ("2017", "professor universitário"),
    ("2021", "livro publicado"),
]

FORMACAO = [
    ("Mestrado em Meteorologia", "USP · Instituto de Astronomia, Geofísica e Ciências Atmosféricas (IAG)", "2016",
     "Dissertação: Análise das ocorrências de cisalhamento de vento no Aeroporto de Guarulhos (SP) "
     "para prevenção de acidentes aeronáuticos. Orientador: Prof. Dr. Ricardo de Camargo."),
    ("Bacharelado em Meteorologia", "USP · IAG", "2013", ""),
]

EXPERIENCIA = [
    ("Instrutor de Meteorologia Aeronáutica", "LATAM Airlines Brasil", "2012–2018 e 2024–atual",
     "Meteorologia aplicada ao voo para pilotos, comissários e DOVs; treinamentos presenciais e em plataforma digital."),
    ("Professor de Meteorologia e disciplinas ligadas à aviação", "Universidade Anhembi Morumbi", "2017–atual",
     "Meteorologia Aeronáutica e Climatologia no curso de Aviação Civil; orientação de TCC; conteudista e tutor "
     "de EAD em meteorologia."),
    ("Auxiliar Técnico – Meteorologista", "Força Aérea Brasileira (FAB)", "2005–atual",
     "Apoio operacional à navegação aérea; atuação nos Centros Meteorológicos do Aeroporto de Congonhas "
     "(2007–2014); treinamentos de AVSEC e de segurança operacional."),
]

PUBLICACOES = [
    "SILVA, H. A. J. S.; CABRAL, E. Meteorologia Aplicada à Aviação: PP, PC, PLA, DOV e Comissário de Voo "
    "– Avião e Helicóptero. São Paulo: Espaço Aéreo, 2021.",
]

ORIENTACOES = [
    "Meteorologia e Radio Patrulha na Aviação · Anhembi Morumbi, 2018",
    "Aplicação de Energia Limpa nos Aeroportos Brasileiros · Anhembi Morumbi, 2018",
    "Membro avaliador de banca de TCC · Curso de Meteorologia, USP, 2022",
]

CERTIFICACOES = [
    ("2024", "Familiarização AVSEC (Segurança da Aviação Civil) · DECEA / CRCEA-SE"),
    ("2018", "O Ensino Superior no Século XXI · OneFaculty"),
    ("2017", "Introdução ao Ensino e Aprendizagem Digital · OneFaculty"),
    ("2014", "Formação de Instrutores (24 h) · LATAM Airlines Brasil"),
    ("2006", "MET011: Interpretação de Imagens de Satélite e Radar Meteorológico (46 h) · ICEA"),
]

AREAS = [
    "Meteorologia Aeronáutica", "Meteorologia Operacional", "Segurança de Voo e AVSEC",
    "Formação de profissionais da aviação", "Ensino digital e conteúdo didático",
]

IDIOMAS = "Inglês: leitura boa · escrita razoável · conversação razoável"

RODAPE = ("Site pessoal de apoio ao ensino. O conteúdo não representa posição oficial de nenhuma instituição "
          "e não substitui as fontes oficiais de informação meteorológica e aeronáutica.")

# ----------------------------------------------------------------------------
# 2. ESTILO (CSS). As classes começam com "sb-" para não interferir no resto do site.
# ----------------------------------------------------------------------------
CSS = """
<style>
.sb-hero { position:relative; overflow:hidden; border:1px solid #24445f; border-radius:18px;
  background: linear-gradient(135deg,#0f2740 0%,#0b1a27 60%,#10304d 100%); padding:34px 36px 30px; margin-bottom:18px; }
.sb-hero svg.sb-iso { position:absolute; inset:0; width:100%; height:100%; opacity:.55; pointer-events:none; }
.sb-hero > *:not(svg) { position:relative; }
.sb-kicker { color:#00d4e6; letter-spacing:.18em; font-size:.75rem; font-weight:700; text-transform:uppercase; }
.sb-hero h1 { color:#f1c40f !important; font-size:2.3rem !important; margin:6px 0 4px !important; padding:0 !important; }
.sb-sub { color:#d6e2ec; font-size:1.05rem; margin:0 0 16px; }
.sb-badges { display:flex; flex-wrap:wrap; gap:8px; }
.sb-badge { background:rgba(19,38,58,.85); border:1px solid #2c5373; color:#cfe3f3; border-radius:999px;
  padding:4px 12px; font-size:.82rem; text-decoration:none !important; }
.sb-badge.link { border-color:#f1c40f; color:#ffe27a; }
.sb-stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:18px; }
.sb-stat { background:#13263a; border:1px solid #24445f; border-radius:14px; padding:14px 16px; }
.sb-stat b { display:block; color:#f1c40f; font-size:1.7rem; line-height:1.1; }
.sb-stat span { color:#aebfcc; font-size:.82rem; }
.sb-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr)); gap:16px; margin-bottom:16px; }
.sb-card { background:#13263a; border:1px solid #24445f; border-radius:14px; padding:20px 22px; }
.sb-card h2 { color:#f1c40f !important; font-size:1.15rem !important; margin:0 0 12px !important; padding:0 !important; }
.sb-card p { color:#dbe6ee; line-height:1.55; margin:0 0 8px; }
.sb-item { border-left:3px solid #00d4e6; padding:2px 0 2px 14px; margin:0 0 14px; }
.sb-item:last-child { margin-bottom:0; }
.sb-item .t { color:#fff; font-weight:600; }
.sb-item .o { color:#9fd8e6; font-size:.92rem; }
.sb-item .d { color:#f1c40f; font-size:.82rem; font-weight:600; }
.sb-item .x { color:#c3d1dc; font-size:.9rem; line-height:1.45; margin-top:3px; }
.sb-li { color:#dbe6ee; font-size:.93rem; line-height:1.45; margin:0 0 9px; }
.sb-li b { color:#f1c40f; margin-right:8px; }
.sb-chips { display:flex; flex-wrap:wrap; gap:8px; }
.sb-chip { background:#0b1a27; border:1px solid #2c5373; color:#cfe3f3; border-radius:8px; padding:5px 11px; font-size:.86rem; }
.sb-foot { color:#8ea3b3; font-size:.8rem; text-align:center; margin-top:10px; line-height:1.5; }
@media (max-width:700px){ .sb-hero{padding:24px 18px} .sb-hero h1{font-size:1.7rem !important} .sb-grid{grid-template-columns:1fr} }
</style>
"""

# Linhas curvas de fundo do cabeçalho, imitando isóbaras de uma carta sinótica.
ISOBARAS = """
<svg class="sb-iso" viewBox="0 0 900 260" preserveAspectRatio="none" fill="none" stroke="#2f8fb0" stroke-width="1.2">
<path d="M-20 210 C150 120 300 250 470 160 S760 70 940 150"/>
<path d="M-20 180 C150 90 300 220 470 130 S760 40 940 120" opacity=".8"/>
<path d="M-20 150 C150 60 300 190 470 100 S760 10 940 90" opacity=".6"/>
<path d="M-20 240 C150 150 300 280 470 190 S760 100 940 180" opacity=".7"/>
<circle cx="760" cy="120" r="34" opacity=".5"/><circle cx="760" cy="120" r="62" opacity=".35"/>
<circle cx="760" cy="120" r="92" opacity=".2"/>
</svg>
"""


def _e(texto):
    """Escapa caracteres especiais (<, >, &) para não quebrar o HTML."""
    return html.escape(texto, quote=True)


def _itens(lista):
    """Monta os blocos 'título / organização / data / texto' usados em Formação e Experiência."""
    saida = []
    for titulo, org, data, extra in lista:
        saida.append(
            '<div class="sb-item">'
            f'<div class="t">{_e(titulo)}</div><div class="o">{_e(org)}</div><div class="d">{_e(data)}</div>'
            + (f'<div class="x">{_e(extra)}</div>' if extra else "")
            + "</div>"
        )
    return "".join(saida)


def montar_html():
    """Junta tudo em um único texto HTML (sem linhas em branco, que o Markdown interpretaria)."""
    destaques = "".join(f'<div class="sb-stat"><b>{_e(n)}</b><span>{_e(t)}</span></div>' for n, t in DESTAQUES)
    certs = "".join(f'<div class="sb-li"><b>{_e(a)}</b>{_e(t)}</div>' for a, t in CERTIFICACOES)
    pubs = "".join(f'<p>{_e(p)}</p>' for p in PUBLICACOES)
    orient = "".join(f'<div class="sb-li">{_e(o)}</div>' for o in ORIENTACOES)
    areas = "".join(f'<span class="sb-chip">{_e(a)}</span>' for a in AREAS)

    return (
        CSS
        + '<div class="sb-hero">' + ISOBARAS
        + '<div class="sb-kicker">Meteorologia aeronáutica · Ensino · Segurança de voo</div>'
        + f'<h1>{_e(NOME)}</h1><p class="sb-sub">{_e(SUBTITULO)}</p>'
        + '<div class="sb-badges">'
        + f'<span class="sb-badge">📍 {_e(LOCAL)}</span>'
        + '<span class="sb-badge">🎓 USP · IAG</span>'
        + f'<a class="sb-badge link" href="{_e(LATTES)}" target="_blank" rel="noopener">🔗 Currículo Lattes</a>'
        + "</div></div>"
        + f'<div class="sb-stats">{destaques}</div>'
        + '<div class="sb-card" style="margin-bottom:16px"><h2>Resumo profissional</h2>'
        + f"<p>{_e(RESUMO)}</p></div>"
        + '<div class="sb-grid">'
        + f'<div class="sb-card"><h2>Experiência</h2>{_itens(EXPERIENCIA)}</div>'
        + f'<div class="sb-card"><h2>Formação acadêmica</h2>{_itens(FORMACAO)}</div>'
        + "</div>"
        + '<div class="sb-grid">'
        + f'<div class="sb-card"><h2>Publicações</h2>{pubs}</div>'
        + f'<div class="sb-card"><h2>Orientações e bancas</h2>{orient}</div>'
        + "</div>"
        + '<div class="sb-grid">'
        + f'<div class="sb-card"><h2>Certificações e cursos</h2>{certs}</div>'
        + f'<div class="sb-card"><h2>Áreas de atuação</h2><div class="sb-chips">{areas}</div>'
        + f'<h2 style="margin-top:18px !important">Idiomas</h2><p>{_e(IDIOMAS)}</p></div>'
        + "</div>"
        + f'<div class="sb-foot">{_e(RODAPE)}</div>'
    )


def mostrar_sobre():
    """Chamada pelo app.py quando a pessoa abre a aba 'Sobre o professor'."""
    st.markdown(montar_html(), unsafe_allow_html=True)
