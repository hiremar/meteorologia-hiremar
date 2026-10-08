"""Modelo GFS (NOAA): vento e temperatura em níveis de voo, sobre a América do Sul.

De onde vem: servidor NOMADS da NOAA, com o "grib filter", que corta o arquivo
global e manda só a região, as variáveis e os níveis que pedimos (~2 a 4 MB).
Dado público, sem chave. O formato é GRIB2; quem lê é o 'cfgrib' (via eccodes).

COMO ACRESCENTAR UMA VARIÁVEL NO FUTURO (ex.: gelo)
  1. Garanta que o dado bruto chega: acrescente em VARS_GRIB (ex.: "CLWMR").
  2. Escreva uma função  calc_xxx(nivel_dados) -> campo  (veja calc_temperatura).
  3. Registre em VARIAVEIS com tipo "escalar" (cores) ou "vetor" (setas).
  O mapa passa a oferecer a nova variável sozinho.
"""
import os
import tempfile
from datetime import datetime, timedelta, timezone

import numpy as np
import requests

# Região pedida ao NOMADS (longitude em 0..360, como o GFS usa)
REGIAO = {"toplat": 16, "bottomlat": -60, "leftlon": 265, "rightlon": 335}
PASSO_MAPA = 2            # 0,25° x 2 = 0,5° na camada do mapa (menos peso na página)
KT = 1.943844             # m/s -> nós

# Níveis oferecidos: rótulo -> ("iso", hPa) ou ("sup", altura em m)
# FL aproximado pela atmosfera padrão (ISA)
NIVEIS = {
    "Superfície (10 m)":   ("sup", 10),
    "FL030 · 925 hPa":     ("iso", 925),
    "FL050 · 850 hPa":     ("iso", 850),
    "FL100 · 700 hPa":     ("iso", 700),
    "FL140 · 600 hPa":     ("iso", 600),
    "FL180 · 500 hPa":     ("iso", 500),
    "FL210 · 450 hPa":     ("iso", 450),
    "FL240 · 400 hPa":     ("iso", 400),
    "FL270 · 350 hPa":     ("iso", 350),
    "FL300 · 300 hPa":     ("iso", 300),
    "FL340 · 250 hPa":     ("iso", 250),
    "FL390 · 200 hPa":     ("iso", 200),
    "FL450 · 150 hPa":     ("iso", 150),
}
VARS_GRIB = ["UGRD", "VGRD", "TMP", "RH"]      # RH já vem para o futuro cálculo de gelo


# ---------------------------------------------------------------------------
# Variáveis que o mapa sabe mostrar  (a "brecha" para o futuro fica aqui)
# ---------------------------------------------------------------------------
def calc_vento(d):
    """(u, v) em nós. u = componente para leste, v = para norte."""
    return d["u"] * KT, d["v"] * KT


def calc_temperatura(d):
    return d["t"] - 273.15                       # Kelvin -> °C


def calc_potencial_gelo(d):
    """ESPAÇO RESERVADO. Uma ideia simples para começar (a validar por você):
         gelo possível onde  -20 °C <= T <= 0 °C  e  UR >= 80 %.
       Métodos mais completos: índices usados no CIP/FIP da NOAA, Schultz &
       Politovich (1992), ou água líquida super-resfriada (CLWMR) do modelo."""
    raise NotImplementedError


VARIAVEIS = {
    "vento": {"nome": "Vento (setas)", "tipo": "vetor", "unidade": "kt", "calc": calc_vento},
    "temperatura": {"nome": "Temperatura", "tipo": "escalar", "unidade": "°C", "calc": calc_temperatura},
    # "gelo": {"nome": "Potencial de gelo", "tipo": "escalar", "unidade": "", "calc": calc_potencial_gelo},
}


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def _url(data_run, hora_run, fhora):
    niveis = [f"lev_{hpa}_mb=on" for tipo, hpa in NIVEIS.values() if tipo == "iso"]
    niveis += ["lev_10_m_above_ground=on", "lev_2_m_above_ground=on"]
    vars_ = [f"var_{v}=on" for v in VARS_GRIB]
    arquivo = f"gfs.t{hora_run:02d}z.pgrb2.0p25.f{fhora:03d}"
    pasta = f"%2Fgfs.{data_run}%2F{hora_run:02d}%2Fatmos"
    regiao = "&".join(f"{k}={v}" for k, v in REGIAO.items())
    return ("https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl?"
            f"file={arquivo}&{'&'.join(niveis)}&{'&'.join(vars_)}&subregion=&{regiao}&dir={pasta}")


def baixar(horas_a_frente=0, agora=None, alvo=None):
    """Acha a rodada mais recente já publicada e baixa a previsão válida para
    'agora + horas_a_frente' (ou para o instante 'alvo', se informado, já em hora cheia).
    Retorna (bytes_grib, info) ou levanta exceção.

    O GFS roda 00, 06, 12 e 18Z e fica disponível ~3,5 a 5 h depois.
    Tentamos da rodada mais nova para a mais velha."""
    agora = agora or datetime.now(timezone.utc)
    alvo = alvo or (agora + timedelta(hours=horas_a_frente)).replace(minute=0, second=0, microsecond=0)
    ultima = agora.replace(hour=agora.hour - agora.hour % 6, minute=0, second=0, microsecond=0)
    erros = []
    for k in range(5):                                   # até 24 h para trás
        run = ultima - timedelta(hours=6 * k)
        fhora = int((alvo - run).total_seconds() // 3600)
        if fhora < 0 or fhora > 120:
            continue
        url = _url(f"{run:%Y%m%d}", run.hour, fhora)
        try:
            r = requests.get(url, timeout=60)
        except Exception as e:
            erros.append(f"{run:%d/%HZ}: {type(e).__name__}")
            continue
        if r.status_code == 200 and r.content[:4] == b"GRIB":
            return r.content, {"run": run, "fhora": fhora, "valido": run + timedelta(hours=fhora)}
        # rodada que ainda não saiu: o NOMADS responde 403/404 ou uma página de texto
        erros.append(f"{run:%d/%HZ}: ainda não publicada" if r.status_code in (200, 403, 404)
                     else f"{run:%d/%HZ}: HTTP {r.status_code}")
    raise RuntimeError("GFS indisponível (" + "; ".join(erros[-3:]) + ")")


# ---------------------------------------------------------------------------
# Leitura do GRIB2
# ---------------------------------------------------------------------------
def _pegar(ds, *nomes):
    """cfgrib dá nomes curtos às variáveis ('u', 'v', 't', 'r'...). Pega o primeiro que existir."""
    for n in nomes:
        if n in ds.data_vars:
            return ds[n]
    raise KeyError(f"nenhuma das variáveis {nomes} no GRIB (há: {list(ds.data_vars)})")


def ler_grib(conteudo):
    """bytes GRIB2 -> dicionário simples de matrizes numpy (fácil de guardar em cache):
       {"lat": [...], "lon": [...], "niveis": {"FL180 · 500 hPa": {"u":..,"v":..,"t":..,"rh":..}, ...}}"""
    import xarray as xr   # cfgrib é usado por baixo pelo xarray (engine="cfgrib")

    with tempfile.TemporaryDirectory() as tmp:
        caminho = os.path.join(tmp, "gfs.grib2")
        with open(caminho, "wb") as f:
            f.write(conteudo)
        abrir = lambda filtro: xr.open_dataset(
            caminho, engine="cfgrib",
            backend_kwargs={"filter_by_keys": filtro, "indexpath": ""}).load()
        iso = abrir({"typeOfLevel": "isobaricInhPa"})
        sup10 = abrir({"typeOfLevel": "heightAboveGround", "level": 10})

    # GFS vem com latitude do norte para o sul e longitude 0..360: arrumamos
    lat = iso["latitude"].values
    lon = iso["longitude"].values
    lon = np.where(lon > 180, lon - 360, lon)
    ordem_lat = np.argsort(lat)

    def arrumar(campo):
        return np.asarray(campo, dtype="float32")[ordem_lat, :]

    u, v = _pegar(iso, "u"), _pegar(iso, "v")
    t, rh = _pegar(iso, "t"), _pegar(iso, "r")
    niveis = {}
    for rotulo, (tipo, valor) in NIVEIS.items():
        if tipo == "iso":
            sel = dict(isobaricInhPa=valor)
            niveis[rotulo] = {"u": arrumar(u.sel(**sel)), "v": arrumar(v.sel(**sel)),
                              "t": arrumar(t.sel(**sel)), "rh": arrumar(rh.sel(**sel))}
        else:
            niveis[rotulo] = {"u": arrumar(_pegar(sup10, "u10", "u")),
                              "v": arrumar(_pegar(sup10, "v10", "v")),
                              "t": None, "rh": None}      # T a 2 m poderia entrar aqui
    return {"lat": lat[ordem_lat], "lon": lon, "niveis": niveis}


def grade_para_mapa(dados, rotulo_nivel, chave_var):
    """Prepara o campo pedido para o desenho no navegador (reduzido para 0,5°).
    Vetor -> {"u": [...], "v": [...]} ; escalar -> {"s": [...]} (listas achatadas,
    linha a linha, do sul para o norte). Números arredondados para a página ficar leve."""
    var = VARIAVEIS[chave_var]
    d = dados["niveis"][rotulo_nivel]
    if var["tipo"] == "escalar" and d.get("t") is None:
        raise ValueError(f"{var['nome']} não disponível em {rotulo_nivel}")
    lat = dados["lat"][::PASSO_MAPA]
    lon = dados["lon"][::PASSO_MAPA]
    grade = {"lat0": float(lat[0]), "dlat": float(lat[1] - lat[0]), "nlat": len(lat),
             "lon0": float(lon[0]), "dlon": float(lon[1] - lon[0]), "nlon": len(lon)}
    # float64 antes de arredondar: evita "12.300000190734863" (ruído do float32) na página
    reduzir = lambda c: np.round(np.asarray(c, "float64")[::PASSO_MAPA, ::PASSO_MAPA], 1).ravel().tolist()
    if var["tipo"] == "vetor":
        u, v = var["calc"](d)
        grade["u"], grade["v"] = reduzir(u), reduzir(v)
    else:
        grade["s"] = reduzir(var["calc"](d))
    return grade
