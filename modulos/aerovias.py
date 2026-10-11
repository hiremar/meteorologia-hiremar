"""AEROVIAS do GEOAISWEB (DECEA): baixar, entender e "andar" por elas.

Ideia geral (como num mapa de metrô):
  - cada FIXO (GERKA, SAMGA, KEXIT...) é uma ESTAÇÃO;
  - cada SEGMENTO de aerovia (GERKA -> ISMOB na UZ26) é um TRILHO ligando duas estações;
  - a AEROVIA (UZ26) é a "linha do metrô": a sequência de trilhos com o mesmo nome.

Quando o aluno escreve a rota "UKBEV UZ26 SAMGA", queremos saber por quais estações a
linha UZ26 passa entre UKBEV e SAMGA. É isso que a função caminho_na_aerovia() faz.

Fonte: serviço WFS (dados vetoriais, não imagem) do GeoServer do GEOAISWEB, camadas
vw_aerovia_alta_v2 (espaço aéreo superior) e vw_aerovia_baixa_v2 (inferior).
Dados públicos; mudam a cada emenda AIRAC (por isso o cache de 1 dia no app.py).
"""
import json
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import requests

URL_WFS = "https://geoaisweb.decea.mil.br/geoserver/ICA/ows"
CAMADAS = {"alta": "ICA:vw_aerovia_alta_v2", "baixa": "ICA:vw_aerovia_baixa_v2"}

# Só os campos que usamos (a camada tem ~40; pedir menos deixa o download bem menor)
CAMPOS = ("text_designator,sequence,from_fix_ident,to_fix_ident,direction,"
          "lower_limit,uom_lower_limit,upper_limit,uom_upper_limit,geom")


# ---------------------------------------------------------------------------
# 1) Baixar
# ---------------------------------------------------------------------------
# Cópia guardada no repositório (pasta dados/), atualizada toda semana pelo robô
# .github/workflows/aerovias.yml. Usada quando o GEOAISWEB está fora do ar.
PASTA_COPIA = Path(__file__).resolve().parent.parent / "dados"


def arquivo_copia(nivel):
    return PASTA_COPIA / f"aerovias_{nivel}.json"


def salvar_copia(nivel, segs):
    """Grava os segmentos num JSON (com a data do download) na pasta dados/."""
    PASTA_COPIA.mkdir(exist_ok=True)
    conteudo = {"baixado_em": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%MZ"), "segmentos": segs}
    arquivo_copia(nivel).write_text(json.dumps(conteudo, ensure_ascii=False, separators=(",", ":")),
                                    encoding="utf-8")


def ler_copia(nivel):
    """(segmentos, 'AAAA-MM-DD HH:MMZ') da cópia guardada, ou (None, None) se não existir."""
    try:
        conteudo = json.loads(arquivo_copia(nivel).read_text(encoding="utf-8"))
        return conteudo["segmentos"], conteudo["baixado_em"]
    except Exception:
        return None, None


def baixar(nivel, timeout=(10, 45)):
    """Baixa TODOS os segmentos de uma camada ("alta" ou "baixa") e devolve uma lista
    de dicionários simples (ver _segmento). WFS versão 1.0.0 => coordenadas em (lon, lat).
    timeout = (10 s para conectar, 45 s de silêncio no meio do download): servidor fora do ar
    desiste rápido em vez de prender a página por minutos."""
    params = {"service": "WFS", "version": "1.0.0", "request": "GetFeature",
              "typeName": CAMADAS[nivel], "outputFormat": "application/json",
              "propertyName": CAMPOS}
    r = requests.get(URL_WFS, params=params, timeout=timeout)
    r.raise_for_status()
    return ler_geojson(r.json(), nivel)


def ler_geojson(dados, nivel=""):
    """GeoJSON do GeoServer -> lista de segmentos. Separado do download para dar para
    testar com um arquivo salvo, sem internet."""
    segs = []
    for f in dados.get("features", []):
        s = _segmento(f, nivel)
        if s:
            segs.append(s)
    return segs


def _segmento(f, nivel):
    p = f.get("properties") or {}
    g = f.get("geometry") or {}
    # A linha pode vir como LineString [[lon,lat],...] ou MultiLineString [[[lon,lat],...],...]
    coords = g.get("coordinates") or []
    if g.get("type") == "MultiLineString":
        coords = [c for parte in coords for c in parte]
    if len(coords) < 2 or not p.get("text_designator"):
        return None
    pts = [[c[1], c[0]] for c in coords]          # (lon, lat) -> [lat, lon], o padrão do site
    return {"aerovia": p["text_designator"].strip().upper(),
            "seq": p.get("sequence") or 0,
            "de": (p.get("from_fix_ident") or "").strip().upper(),
            "para": (p.get("to_fix_ident") or "").strip().upper(),
            "direcao": (p.get("direction") or "BOTH").upper(),     # FORWARD, BACKWARD ou BOTH
            "base": _nivel_txt(p.get("lower_limit"), p.get("uom_lower_limit")),
            "topo": _nivel_txt(p.get("upper_limit"), p.get("uom_upper_limit")),
            "nivel": nivel,
            "pts": pts}


def _nivel_txt(valor, unidade):
    """(255, 'FL') -> 'FL255' ; (999, 'FL') -> 'UNL' ; (5000, 'FT') -> '5000 ft'"""
    if valor is None:
        return "?"
    if (unidade or "").upper() == "FL":
        return "UNL" if valor >= 999 else f"FL{int(valor):03d}"
    return f"{int(valor)} {(unidade or '').lower()}".strip()


# ---------------------------------------------------------------------------
# 2) Organizar: dicionário de fixos e de aerovias
# ---------------------------------------------------------------------------
def montar_rede(segmentos):
    """Devolve (fixos, aerovias):
      fixos    = {"SAMGA": [lat, lon], ...}   (tirados das pontas dos segmentos)
      aerovias = {"UZ26": [segmento, segmento, ...], ...}"""
    fixos, aerovias = {}, {}
    for s in segmentos:
        if s["de"]:
            fixos.setdefault(s["de"], s["pts"][0])
        if s["para"]:
            fixos.setdefault(s["para"], s["pts"][-1])
        aerovias.setdefault(s["aerovia"], []).append(s)
    return fixos, aerovias


def caminho_na_aerovia(segs, inicio, fim):
    """Estações da linha entre 'inicio' e 'fim', seguindo os trilhos daquela aerovia.
    Busca em largura (BFS): sai do 'inicio' e vai visitando os vizinhos, camada por camada,
    até achar o 'fim'. Devolve (lista de fixos [inicio, ..., fim], avisos) ou (None, avisos)."""
    vizinhos = {}                                   # fixo -> [(fixo vizinho, segmento, sentido_ok)]
    for s in segs:
        # sentido_ok: dá para voar de -> para? FORWARD/BOTH sim. E para -> de? BACKWARD/BOTH sim.
        vizinhos.setdefault(s["de"], []).append((s["para"], s, s["direcao"] in ("FORWARD", "BOTH")))
        vizinhos.setdefault(s["para"], []).append((s["de"], s, s["direcao"] in ("BACKWARD", "BOTH")))
    if inicio not in vizinhos or fim not in vizinhos:
        return None, []
    veio_de = {inicio: None}                        # para refazer o caminho de trás para frente
    fila = deque([inicio])
    while fila:
        atual = fila.popleft()
        if atual == fim:
            break
        for prox, seg, ok in vizinhos[atual]:
            if prox not in veio_de:
                veio_de[prox] = (atual, seg, ok)
                fila.append(prox)
    if fim not in veio_de:
        return None, []
    caminho, contramao, f = [fim], [], fim
    while veio_de[f] is not None:
        anterior, seg, ok = veio_de[f]
        if not ok:
            contramao.append((anterior, f, seg))
        caminho.append(anterior)
        f = anterior
    avisos = []
    if contramao:                                   # um aviso só, com o trecho todo
        contramao.reverse()
        a, b, seg = contramao[0][0], contramao[-1][1], contramao[0][2]
        avisos.append(f"{a}→{b} na {seg['aerovia']}: aerovia de mão única no sentido contrário "
                      f"({seg['direcao']}). No mundo real esse trecho não seria aceito.")
    return caminho[::-1], avisos


# ---------------------------------------------------------------------------
# 3) Ler a rota que o aluno digitou
# ---------------------------------------------------------------------------
# Procedimento SID/STAR: letras + 1 dígito + 1 letra (AMVU5A, IRUL1A). Aerovia não termina em letra.
_PROCEDIMENTO = re.compile(r"^[A-Z]{2,6}\d[A-Z]$")
# Velocidade/nível do plano de voo (N0452F360, M078F350, K0830S1100...), sozinho ou após "/"
_VEL_NIVEL = re.compile(r"^[NKM]\d{3,4}[FASM]\d{3,4}$")


def ler_rota(texto, fixos, aerovias, origem=None, destino=None):
    """Interpreta a rota digitada. Exemplos aceitos:
         "UKBEV UZ26 SAMGA VUKEP"         (fixo, aerovia, fixo, fixo direto)
         "AMVU5A UKBEV UZ26 SAMGA DCT VUKEP IRUL1A"   (SID/STAR são ignoradas)
         "N0452F360 UKBEV UZ26 SAMGA"     (velocidade/nível ignorados)
    Devolve um dicionário:
      ok      : True/False
      pontos  : [{"ident", "lat", "lon", "via"}, ...]   (via = aerovia ou "DCT")
      avisos  : textos informativos (o que foi ignorado, mão única...)
      erro    : texto do problema quando ok = False"""
    fichas = [t for t in re.split(r"[\s,]+", (texto or "").upper()) if t]
    fichas = [t.split("/")[0] for t in fichas]                  # "SAMGA/N0450F360" -> "SAMGA"
    avisos, limpas = [], []
    for t in fichas:
        if not t or t == "DCT" or _VEL_NIVEL.match(t) or t in (origem, destino):
            continue
        if _PROCEDIMENTO.match(t) and t not in fixos and t not in aerovias:
            avisos.append(f"{t}: parece SID/STAR, ignorado (procedimentos ainda não são desenhados).")
            continue
        limpas.append(t)

    pontos, i = [], 0
    while i < len(limpas):
        t = limpas[i]
        if t in aerovias and t not in fixos:
            # Aerovia: precisa de um fixo ANTES (onde entra) e um DEPOIS (onde sai)
            if not pontos:
                return _falha(f"A rota começa pela aerovia {t}: escreva antes o fixo onde você entra nela.")
            if i + 1 >= len(limpas):
                return _falha(f"Depois da aerovia {t} falta o fixo onde você sai dela.")
            entrada, saida = pontos[-1]["ident"], limpas[i + 1]
            na_via = {s["de"] for s in aerovias[t]} | {s["para"] for s in aerovias[t]}
            # Tolerância de AIRAC: rota de base antiga (SimBrief, simulador) pode citar um fixo que
            # hoje não está mais na aerovia. Entramos/saímos pelo fixo da aerovia mais próximo.
            if entrada not in na_via:
                perto, d = _mais_proximo(fixos[entrada], na_via, fixos)
                if perto is None or d > MAX_DESVIO_NM:
                    return _falha(f"{entrada} não está na aerovia {t} (base atual do DECEA) e não há "
                                  f"fixo dela a menos de {MAX_DESVIO_NM} NM.")
                avisos.append(f"{entrada} não está na {t} na base atual do DECEA: segui direto até "
                              f"{perto} ({d:.0f} NM) para entrar na aerovia. Rota de AIRAC antigo?")
                pontos.append(_ponto(perto, fixos, "DCT"))
                entrada = perto
            saida_original = None
            if saida not in na_via:
                if saida not in fixos:
                    return _falha(f"Depois da aerovia {t}, não reconheci o fixo '{saida}'.")
                perto, d = _mais_proximo(fixos[saida], na_via, fixos)
                if perto is None or d > MAX_DESVIO_NM:
                    return _falha(f"{saida} não está na aerovia {t} e não há fixo dela a menos de "
                                  f"{MAX_DESVIO_NM} NM.")
                avisos.append(f"{saida} não está na {t} na base atual do DECEA: saí da aerovia em "
                              f"{perto} e segui direto ({d:.0f} NM). Rota de AIRAC antigo?")
                saida_original, saida = saida, perto
            caminho, mao_unica = caminho_na_aerovia(aerovias[t], entrada, saida)
            if caminho is None:
                return _falha(f"Não achei um caminho de {entrada} até {saida} pela aerovia {t}. "
                              f"Confira se os dois fixos estão nela.")
            avisos += mao_unica
            for f in caminho[1:]:
                pontos.append(_ponto(f, fixos, t))
            if saida_original:                       # o fixo pedido, fora da aerovia: direto
                pontos.append(_ponto(saida_original, fixos, "DCT"))
            i += 2                                   # já usamos a aerovia e o fixo de saída
        elif t in fixos:
            pontos.append(_ponto(t, fixos, "DCT"))
            i += 1
        else:
            return _falha(f"Não reconheci '{t}': não é fixo nem aerovia da base do DECEA "
                          f"(fixos só de procedimento, VOR/NDB fora de aerovia e coordenadas ainda "
                          f"não são aceitos).")
    if not pontos:
        return _falha("A rota ficou vazia: escreva pelo menos um fixo (ex.: UKBEV UZ26 SAMGA).")
    return {"ok": True, "pontos": pontos, "avisos": avisos, "erro": None}


MAX_DESVIO_NM = 100      # até quanto aceitamos "puxar" um fixo de AIRAC antigo até a aerovia


def _mais_proximo(posicao, candidatos, fixos):
    """O fixo de 'candidatos' mais perto de 'posicao' [lat, lon]: (ident, distância NM)."""
    from .rota import distancia_nm
    melhor = min(((distancia_nm(posicao, fixos[c]), c) for c in candidatos if c in fixos), default=None)
    return (melhor[1], melhor[0]) if melhor else (None, None)


def _ponto(ident, fixos, via):
    lat, lon = fixos[ident]
    return {"ident": ident, "lat": lat, "lon": lon, "via": via}


def _falha(texto):
    return {"ok": False, "pontos": [], "avisos": [], "erro": texto}


def texto_expandido(pontos):
    """Rota por extenso, agrupando as aerovias: 'UKBEV UZ26 SAMGA DCT VUKEP'."""
    if not pontos:
        return ""
    partes = [pontos[0]["ident"]]
    for i in range(1, len(pontos)):
        p = pontos[i]
        prox = pontos[i + 1] if i + 1 < len(pontos) else None
        if p["via"] == "DCT":
            partes.append(p["ident"])                    # direto: o fixo sempre aparece
        elif prox is None or prox["via"] != p["via"]:
            partes += [p["via"], p["ident"]]             # fim do trecho na aerovia: "UZ26 SAMGA"
        # (fixos no MEIO da aerovia ficam implícitos, como no plano de voo)
    return " ".join(partes)


# ---------------------------------------------------------------------------
# 4) Recorte para o mapa: só os segmentos perto da rota
# ---------------------------------------------------------------------------
def segmentos_na_caixa(segmentos, caixa):
    """caixa = [lat_min, lat_max, lon_min, lon_max]. Fica o segmento que tem ao menos
    um ponto dentro da caixa (rápido e suficiente para desenhar referência)."""
    la0, la1, lo0, lo1 = caixa
    return [s for s in segmentos
            if any(la0 <= la <= la1 and lo0 <= lo <= lo1 for la, lo in s["pts"])]
