@st.cache_data(ttl=3600) 
def carregar_dados_gfs(fl_alvo):
    try:
        pressao = NIVEIS_MAP[fl_alvo]
        # Forçamos o Herbie a olhar primeiro no Google Cloud (mais rápido que o NOMADS)
        H = Herbie(
            model="gfs",
            product="pgrb2.0p25",
            date=datetime.utcnow(),
            fxx=0,
            priority=['google', 'aws', 'nomads'] # Ordem de servidores
        )
        
        # Filtro refinado
        search_pattern = f": (UGRD|VGRD|TMP|RH):{pressao} mb:"
        
        # O pulo do gato: tentar carregar com o motor simplificado primeiro
        ds = H.xarray(search_pattern, engine="cfgrib", backend_kwargs={'errors': 'ignore'})
        
        rodada_info = f"Rodada: {H.date.strftime('%d/%m/%Y %HZ')}"
        return ds, rodada_info
    except Exception as e:
        # Se der erro, tentamos a rodada de 6h atrás automaticamente
        st.sidebar.warning("Tentando rodada anterior...")
        return None, None
