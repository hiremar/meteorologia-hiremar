"""Aeródromos exibidos no mapa: os que atendem as 27 capitais + alguns extras,
e os principais da América do Sul (lista EXTERIOR, mais abaixo).

Para acrescentar um aeródromo, basta copiar uma linha e trocar os dados.
Coordenadas em graus decimais (sul e oeste são negativos).
"""

#            ICAO     cidade                 UF    lat        lon
AERODROMOS = [
    ("SBRB", "Rio Branco",            "AC",  -9.8689,  -67.8981),
    ("SBMO", "Maceió",                "AL",  -9.5108,  -35.7917),
    ("SBMQ", "Macapá",                "AP",   0.0506,  -51.0722),
    ("SBEG", "Manaus",                "AM",  -3.0386,  -60.0497),
    ("SBSV", "Salvador",              "BA", -12.9086,  -38.3225),
    ("SBFZ", "Fortaleza",             "CE",  -3.7763,  -38.5326),
    ("SBBR", "Brasília",              "DF", -15.8692,  -47.9208),
    ("SBVT", "Vitória",               "ES", -20.2581,  -40.2864),
    ("SBGO", "Goiânia",               "GO", -16.6320,  -49.2207),
    ("SBSL", "São Luís",              "MA",  -2.5854,  -44.2341),
    ("SBCY", "Cuiabá",                "MT", -15.6529,  -56.1167),
    ("SBCG", "Campo Grande",          "MS", -20.4687,  -54.6725),
    ("SBCF", "Belo Horizonte/Confins", "MG", -19.6244, -43.9719),
    ("SBBH", "Belo Horizonte/Pampulha", "MG", -19.8512, -43.9506),
    ("SBBE", "Belém",                 "PA",  -1.3792,  -48.4763),
    ("SBJP", "João Pessoa",           "PB",  -7.1458,  -34.9486),
    ("SBCT", "Curitiba",              "PR", -25.5285,  -49.1758),
    ("SBRF", "Recife",                "PE",  -8.1265,  -34.9236),
    ("SBTE", "Teresina",              "PI",  -5.0599,  -42.8235),
    ("SBGL", "Rio de Janeiro/Galeão", "RJ", -22.8100,  -43.2506),
    ("SBRJ", "Rio de Janeiro/S. Dumont", "RJ", -22.9105, -43.1631),
    ("SBSG", "Natal",                 "RN",  -5.7681,  -35.3761),
    ("SBPA", "Porto Alegre",          "RS", -29.9944,  -51.1714),
    ("SBPV", "Porto Velho",           "RO",  -8.7093,  -63.9023),
    ("SBBV", "Boa Vista",             "RR",   2.8414,  -60.6922),
    ("SBFL", "Florianópolis",         "SC", -27.6703,  -48.5525),
    ("SBSP", "São Paulo/Congonhas",   "SP", -23.6261,  -46.6564),
    ("SBGR", "São Paulo/Guarulhos",   "SP", -23.4356,  -46.4731),
    ("SBAR", "Aracaju",               "SE", -10.9840,  -37.0703),
    ("SBPJ", "Palmas",                "TO", -10.2915,  -48.3570),
    # extras (não são capitais, mas são muito usados)
    ("SBKP", "Campinas/Viracopos",    "SP", -23.0074,  -47.1345),
    # --- região de São Paulo (coordenadas aproximadas; conferir no AISWEB se precisar) ---
    ("SBBP", "Bragança Paulista",     "SP", -22.9792,  -46.5375),
    ("SBJD", "Jundiaí",               "SP", -23.1817,  -46.9436),
    ("SDAM", "Campinas/Amarais",      "SP", -22.8592,  -47.1083),
    ("SDCO", "Sorocaba",              "SP", -23.4781,  -47.4900),
    ("SBJH", "São Roque/Catarina",    "SP", -23.4264,  -47.1656),
    ("SBMT", "São Paulo/Campo de Marte", "SP", -23.5091, -46.6378),
    ("SBST", "Santos (Base Aérea)",   "SP", -23.9281,  -46.2997),
    ("SBSJ", "São José dos Campos",   "SP", -23.2292,  -45.8615),
    ("SBTA", "Taubaté",               "SP", -23.0401,  -45.5160),
    ("SBGW", "Guaratinguetá",         "SP", -22.7916,  -45.2048),
    # --- região do Rio de Janeiro (CRCEA-SE) ---
    ("SBAF", "Rio de Janeiro/Afonsos", "RJ", -22.8750, -43.3847),
    ("SBJR", "Rio de Janeiro/Jacarepaguá", "RJ", -22.9875, -43.3700),
    ("SBSC", "Rio de Janeiro/Santa Cruz", "RJ", -22.9324, -43.7191),
    ("SBMI", "Maricá",                "RJ", -22.9196,  -42.8309),
    ("SBES", "São Pedro da Aldeia",   "RJ", -22.8128,  -42.0926),
    ("SBCB", "Cabo Frio",             "RJ", -22.9217,  -42.0743),
]

# ---------------------------------------------------------------------------
# AMÉRICA DO SUL (fora do Brasil): capitais + principais aeroportos.
# Aqui a terceira coluna é o PAÍS (no Brasil é a UF). Sem cartas/aerovias do DECEA:
# no planejamento o voo para o exterior fica em linha reta.
# Coordenadas aproximadas do aeródromo (conferir na AIP do país se precisar).
# ---------------------------------------------------------------------------
EXTERIOR = [
    # Argentina
    ("SAEZ", "Buenos Aires/Ezeiza",       "Argentina", -34.8222, -58.5358),
    ("SABE", "Buenos Aires/Aeroparque",   "Argentina", -34.5592, -58.4156),
    ("SACO", "Córdoba",                   "Argentina", -31.3236, -64.2080),
    ("SAME", "Mendoza",                   "Argentina", -32.8317, -68.7929),
    ("SAAR", "Rosario",                   "Argentina", -32.9036, -60.7850),
    ("SARI", "Puerto Iguazú",             "Argentina", -25.7373, -54.4734),
    ("SAZS", "Bariloche",                 "Argentina", -41.1512, -71.1575),
    ("SAWH", "Ushuaia",                   "Argentina", -54.8433, -68.2958),
    # Uruguai
    ("SUMU", "Montevidéu/Carrasco",       "Uruguai",   -34.8384, -56.0308),
    ("SULS", "Punta del Este",            "Uruguai",   -34.8551, -55.0943),
    # Paraguai
    ("SGAS", "Assunção",                  "Paraguai",  -25.2400, -57.5191),
    ("SGES", "Ciudad del Este",           "Paraguai",  -25.4544, -54.8429),
    # Chile
    ("SCEL", "Santiago",                  "Chile",     -33.3930, -70.7858),
    ("SCDA", "Iquique",                   "Chile",     -20.5352, -70.1813),
    ("SCFA", "Antofagasta",               "Chile",     -23.4445, -70.4451),
    ("SCTE", "Puerto Montt",              "Chile",     -41.4389, -73.0940),
    ("SCCI", "Punta Arenas",              "Chile",     -53.0026, -70.8546),
    # Bolívia
    ("SLLP", "La Paz/El Alto",            "Bolívia",   -16.5133, -68.1923),
    ("SLVR", "Santa Cruz/Viru Viru",      "Bolívia",   -17.6448, -63.1354),
    ("SLCB", "Cochabamba",                "Bolívia",   -17.4211, -66.1771),
    # Peru
    ("SPJC", "Lima",                      "Peru",      -12.0219, -77.1143),
    ("SPZO", "Cusco",                     "Peru",      -13.5357, -71.9388),
    # Equador
    ("SEQM", "Quito",                     "Equador",    -0.1292, -78.3575),
    ("SEGU", "Guayaquil",                 "Equador",    -2.1574, -79.8836),
    # Colômbia
    ("SKBO", "Bogotá",                    "Colômbia",    4.7016, -74.1469),
    ("SKRG", "Medellín/Rionegro",         "Colômbia",    6.1645, -75.4231),
    ("SKCL", "Cali",                      "Colômbia",    3.5432, -76.3816),
    # Venezuela e Guianas
    ("SVMI", "Caracas/Maiquetía",         "Venezuela",  10.6031, -66.9906),
    ("SYCJ", "Georgetown",                "Guiana",      6.4985, -58.2541),
    ("SMJP", "Paramaribo",                "Suriname",    5.4528, -55.1878),
    ("SOCA", "Caiena",                    "Guiana Francesa", 4.8198, -52.3604),
]

# Listas separadas: a REDEMET pode não ter mensagem de aeródromo estrangeiro, então o
# app.py pede o Brasil e o exterior em consultas diferentes (um não derruba o outro).
LISTA_BRASIL = [a[0] for a in AERODROMOS]
LISTA_EXTERIOR = [a[0] for a in EXTERIOR]
AERODROMOS = AERODROMOS + EXTERIOR                  # daqui para baixo: todos juntos

# Dicionários de acesso rápido:  COORDS["SBGR"] -> [-23.4356, -46.4731]
COORDS = {icao: [lat, lon] for icao, _, _, lat, lon in AERODROMOS}
NOMES = {icao: f"{cidade} ({uf})" for icao, cidade, uf, _, _ in AERODROMOS}
LISTA_ICAO = [a[0] for a in AERODROMOS]


def rotulo(icao):
    """'SBGR' -> 'SBGR · São Paulo/Guarulhos (SP)'  (usado nas caixas de seleção)"""
    return f"{icao} · {NOMES.get(icao, '')}"
