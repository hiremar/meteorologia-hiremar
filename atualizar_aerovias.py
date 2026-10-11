"""Robô semanal: baixa as aerovias de alta e de baixa do GEOAISWEB e guarda uma cópia em
dados/aerovias_alta.json e dados/aerovias_baixa.json.

O site usa essa cópia quando o GEOAISWEB está fora do ar (a rota continua seguindo as
aerovias em vez de virar linha reta). Roda pelo .github/workflows/aerovias.yml.
Se o GEOAISWEB estiver fora do ar na hora do robô, a cópia antiga fica como está.
"""
import sys

from modulos import aerovias as av

falhou = False
for nivel in ("alta", "baixa"):
    try:
        segs = av.baixar(nivel, timeout=(20, 120))       # robô sem pressa: espera mais que o site
    except Exception as e:
        print(f"[aerovias {nivel}] GEOAISWEB não respondeu ({type(e).__name__}): mantendo a cópia antiga")
        falhou = True
        continue
    if len(segs) < 100:                                     # resposta suspeita: não sobrescreve
        print(f"[aerovias {nivel}] só {len(segs)} segmentos: mantendo a cópia antiga")
        falhou = True
        continue
    av.salvar_copia(nivel, segs)
    print(f"[aerovias {nivel}] {len(segs)} segmentos salvos")

sys.exit(1 if falhou else 0)
