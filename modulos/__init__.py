# Pasta "modulos": cada arquivo cuida de uma parte do site.
#   aerodromos.py   -> lista das capitais (código ICAO e coordenadas)
#   metar.py        -> lê o METAR e decide VFR / MVFR / IFR / LIFR
#   redemet.py      -> conversa com a API da REDEMET (METAR, TAF, SIGMET)
#   satelite.py     -> baixa e processa o GOES-19 (infravermelho e visível)
#   modelo_gfs.py   -> baixa o GFS (vento, temperatura...) da NOAA
#   camadas_mapa.py -> tudo que é desenhado no mapa
