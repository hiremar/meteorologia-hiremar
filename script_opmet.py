import os
import json
import io
import time
import datetime
import requests
import pandas as pd
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

# --- 1. CONFIGURAÇÕES ---
# A chave NÃO fica mais escrita aqui: vem do cofre do GitHub (Settings -> Secrets
# -> Actions -> REDEMET_KEY), entregue pelo agendador.yml como variável de ambiente.
API_KEY = os.environ.get('REDEMET_KEY')
if not API_KEY:
    raise SystemExit('ERRO: secret REDEMET_KEY não configurado no GitHub (Settings -> Secrets -> Actions).')
AEROPORTOS = [
    'sbaf', 'sdam', 'sbbp', 'sbcb', 'sdco', 'sbes', 'sbgl', 'sbgr', 'sbgw',
    'sbjd', 'sbjh', 'sbjr', 'sbkp', 'sbmi', 'sbmt', 'sbrj', 'sbsc', 'sbsj',
    'sbsp', 'sbst', 'sbta'
]
PASTA_DRIVE_NOME = "CONSISTENCIA"  # Nome exato da pasta no Drive

# Quantas vezes repetir uma chamada ao Google Drive quando ele responde com erro
# passageiro (ex.: 503 "Service Unavailable", que derrubou a rodada de 01/10/2026).
# A biblioteca do Google espera um pouco mais a cada tentativa (1s, 2s, 4s, ...).
TENTATIVAS_DRIVE = 6

MESES_PT = {
    1: 'JAN', 2: 'FEV', 3: 'MAR', 4: 'ABR', 5: 'MAI', 6: 'JUN',
    7: 'JUL', 8: 'AGO', 9: 'SET', 10: 'OUT', 11: 'NOV', 12: 'DEZ'
}


def nome_planilha(ano, mes):
    """Monta o nome da planilha de um mês. Ex.: (2026, 9) -> 'SET2026 CONSISTÊNCIA.xlsx'"""
    return f"{MESES_PT[mes]}{ano} CONSISTÊNCIA.xlsx"


hoje = datetime.datetime.now(datetime.timezone.utc)

# Busca os últimos 4 dias para garantir atualização sem perder mensagens
data_fim_dt = hoje
data_ini_dt = hoje - datetime.timedelta(days=4)
DATA_INICIO = data_ini_dt.strftime('%Y%m%d')
DATA_FIM = data_fim_dt.strftime('%Y%m%d')

print("🚀 Iniciando Automação OPMET")
print(f"📅 Período de busca REDEMET: {DATA_INICIO} até {DATA_FIM}")

# --- 2. AUTENTICAÇÃO COM GOOGLE DRIVE ---
sa_info = json.loads(os.environ['GCP_SA_KEY'])
creds = service_account.Credentials.from_service_account_info(
    sa_info, scopes=['https://www.googleapis.com/auth/drive']
)
drive_service = build('drive', 'v3', credentials=creds, cache_discovery=False)

# Localiza a pasta no Google Drive
query = f"name = '{PASTA_DRIVE_NOME}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
response = drive_service.files().list(q=query, fields="files(id, name)").execute(num_retries=TENTATIVAS_DRIVE)
folders = response.get('files', [])

if not folders:
    raise Exception(f"❌ Pasta '{PASTA_DRIVE_NOME}' não encontrada no Google Drive.")

folder_id = folders[0]['id']


# --- 3. CONSULTA API REDEMET (primeiro baixa tudo, depois decide para qual planilha vai) ---
# Antes, o script jogava fora as mensagens que não eram do mês de "hoje".
# Isso fazia perder o fim do último dia do mês: no dia 01/10 a busca trazia o
# dia 30/09 completo, mas ele era descartado porque o script só olhava a
# planilha de OUTUBRO. Agora guardamos TUDO e, no passo 4, cada mensagem vai
# para a planilha do mês dela (30/09 -> SET2026, 01/10 -> OUT2026).
novas_por_aero = {}  # ex.: {'SBGR': DataFrame com DATA_HORA_UTC e MENSAGEM}

for aero in AEROPORTOS:
    aero_upper = aero.upper()
    url = f"https://api-redemet.decea.mil.br/mensagens/metar/{aero}?api_key={API_KEY}&data_ini={DATA_INICIO}00&data_fim={DATA_FIM}23"

    # A REDEMET às vezes também falha por instantes; tentamos até 3 vezes.
    data = None
    for tentativa in range(1, 4):
        try:
            resp = requests.get(url, timeout=60)
            data = resp.json()
            break
        except Exception as e:
            print(f"⚠️ {aero_upper}: tentativa {tentativa} falhou ({e})")
            time.sleep(5 * tentativa)

    if data is None:
        print(f"❌ Erro ao consultar {aero_upper}: REDEMET não respondeu após 3 tentativas.")
        continue

    mensagens_lista = []
    if data.get('status') and data.get('data') and data['data'].get('data'):
        for item in data['data']['data']:
            msg = item.get('mens', '')
            dt = item.get('validade_inicial', '')

            if ("METAR" in msg or "SPECI" in msg) and ("AUTO" not in msg) and ("não localizada" not in msg.lower()):
                mensagens_lista.append({'DATA_HORA_UTC': dt, 'MENSAGEM': msg})

    if mensagens_lista:
        novas_por_aero[aero_upper] = pd.DataFrame(mensagens_lista)

    time.sleep(0.05)

# Descobre quais meses apareceram nos dados baixados (normalmente 1; na virada
# do mês, 2 — por exemplo setembro E outubro).
meses_encontrados = set()
for df in novas_por_aero.values():
    datas = pd.to_datetime(df['DATA_HORA_UTC'], errors='coerce').dropna()
    meses_encontrados.update(zip(datas.dt.year, datas.dt.month))

# Inclui sempre o mês corrente, para a planilha do mês novo ser criada
# automaticamente assim que chegar a primeira mensagem dele.
meses_encontrados.add((hoje.year, hoje.month))


# --- 4. FUNÇÕES DE APOIO PARA O DRIVE ---
def baixar_planilha(nome):
    """Procura a planilha no Drive. Devolve (id_do_arquivo, {aba: DataFrame}).
    Se não existir, devolve (None, {})."""
    q = f"name = '{nome}' and '{folder_id}' in parents and trashed = false"
    achados = drive_service.files().list(q=q, fields="files(id, name)").execute(
        num_retries=TENTATIVAS_DRIVE).get('files', [])
    if not achados:
        return None, {}

    file_id = achados[0]['id']
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, drive_service.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = downloader.next_chunk(num_retries=TENTATIVAS_DRIVE)
    fh.seek(0)
    xls = pd.ExcelFile(fh)
    abas = {sheet: pd.read_excel(xls, sheet_name=sheet) for sheet in xls.sheet_names}
    return file_id, abas


def salvar_planilha(nome, file_id, abas):
    """Gera o .xlsx com a formatação padrão e envia ao Drive
    (atualiza se já existe, cria se é nova)."""
    output_buffer = io.BytesIO()
    with pd.ExcelWriter(output_buffer, engine='xlsxwriter') as writer:
        workbook = writer.book
        format_wrap = workbook.add_format({'text_wrap': True, 'valign': 'top', 'border': 1})
        format_header = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})

        # Abas na ordem da lista AEROPORTOS (e qualquer aba extra no fim)
        ordem = [a.upper() for a in AEROPORTOS if a.upper() in abas]
        ordem += [a for a in abas if a not in ordem]

        for aba in ordem:
            df = abas[aba]
            cols = [c for c in ['DATA_HORA_UTC', 'MENSAGEM'] if c in df.columns]
            df_salvar = df[cols] if cols else df
            df_salvar.to_excel(writer, sheet_name=aba, index=False)

            worksheet = writer.sheets[aba]
            for col_num, value in enumerate(df_salvar.columns.values):
                worksheet.write(0, col_num, value, format_header)
            worksheet.set_column('A:A', 20, format_wrap)
            worksheet.set_column('B:B', 150, format_wrap)

    output_buffer.seek(0)
    media = MediaIoBaseUpload(
        output_buffer,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        resumable=True
    )

    if file_id:
        drive_service.files().update(fileId=file_id, media_body=media).execute(num_retries=TENTATIVAS_DRIVE)
        print(f"✨ Planilha '{nome}' atualizada com sucesso no Google Drive!")
    else:
        file_metadata = {'name': nome, 'parents': [folder_id]}
        drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute(
            num_retries=TENTATIVAS_DRIVE)
        print(f"✨ Nova planilha '{nome}' criada com sucesso no Google Drive!")


# --- 5. PARA CADA MÊS: BAIXA A PLANILHA, JUNTA AS NOVAS, LIMPA E SALVA ---
for (ano, mes) in sorted(meses_encontrados):
    nome = nome_planilha(ano, mes)
    file_id, abas = baixar_planilha(nome)
    if file_id:
        print(f"✅ Planilha existente '{nome}' baixada ({len(abas)} abas).")
    else:
        print(f"ℹ️ Planilha '{nome}' não encontrada no Drive. Uma nova será criada.")

    linhas_antes = sum(len(df) for df in abas.values())

    for aero_upper, df_novos in novas_por_aero.items():
        # Separa só as mensagens deste ano/mês
        datas = pd.to_datetime(df_novos['DATA_HORA_UTC'], errors='coerce')
        df_mes = df_novos[(datas.dt.year == ano) & (datas.dt.month == mes)]
        if df_mes.empty:
            continue
        if aero_upper in abas:
            abas[aero_upper] = pd.concat([abas[aero_upper], df_mes], ignore_index=True)
        else:
            abas[aero_upper] = df_mes.copy()

    # Limpeza: remove repetidas (a busca de 4 dias sempre traz mensagens que
    # já estavam na planilha) e ordena por data/hora.
    for aba, df in abas.items():
        if df.empty:
            continue
        df = df.copy()
        df['DATA_HORA_DT'] = pd.to_datetime(df['DATA_HORA_UTC'], errors='coerce')
        df_limpo = df.drop_duplicates(subset=['DATA_HORA_DT', 'MENSAGEM']).copy()
        df_limpo = df_limpo.sort_values(by='DATA_HORA_DT').reset_index(drop=True)
        df_limpo['DATA_HORA_UTC'] = df_limpo['DATA_HORA_DT'].dt.strftime('%Y-%m-%d %H:%M:%S')
        abas[aba] = df_limpo.drop(columns=['DATA_HORA_DT'], errors='ignore')

    linhas_depois = sum(len(df) for df in abas.values())
    novas = linhas_depois - linhas_antes
    print(f"➕ '{nome}': {novas} mensagem(ns) nova(s).")

    # Se a planilha já existia e nada mudou, não precisa reenviar.
    if file_id and novas == 0:
        print(f"⏭️ '{nome}' já estava em dia; nada a enviar.")
        continue
    if not abas:
        print(f"⏭️ Sem mensagens para '{nome}' ainda; nada a criar.")
        continue

    salvar_planilha(nome, file_id, abas)
