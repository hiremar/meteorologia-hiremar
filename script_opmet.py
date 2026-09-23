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
API_KEY = 'tyZcJePk7Y5v7QZGbqXiDQwHaGQFli9J5HfQh15f'
AEROPORTOS = [
    'sbaf', 'sdam', 'sbbp', 'sbcb', 'sdco', 'sbes', 'sbgl', 'sbgr', 'sbgw',
    'sbjd', 'sbjh', 'sbjr', 'sbkp', 'sbmi', 'sbmt', 'sbrj', 'sbsc', 'sbsj',
    'sbsp', 'sbst', 'sbta'
]
PASTA_DRIVE_NOME = "CONSISTENCIA"  # Nome exato da pasta no Drive

# Define o nome da planilha do mês atual dinamicamente (ex: SET2026 CONSISTÊNCIA.xlsx)
hoje = datetime.datetime.now(datetime.timezone.utc)
MESES_PT = {
    1: 'JAN', 2: 'FEV', 3: 'MAR', 4: 'ABR', 5: 'MAI', 6: 'JUN',
    7: 'JUL', 8: 'AGO', 9: 'SET', 10: 'OUT', 11: 'NOV', 12: 'DEZ'
}
NOME_PLANILHA = f"{MESES_PT[hoje.month]}{hoje.year} CONSISTÊNCIA.xlsx"

# Busca os últimos 4 dias para garantir atualização sem perder mensagens
data_fim_dt = hoje
data_ini_dt = hoje - datetime.timedelta(days=4)
DATA_INICIO = data_ini_dt.strftime('%Y%m%d')
DATA_FIM = data_fim_dt.strftime('%Y%m%d')

print(f"🚀 Iniciando Automação OPMET para a planilha: '{NOME_PLANILHA}'")
print(f"📅 Período de busca REDEMET: {DATA_INICIO} até {DATA_FIM}")

# --- 2. AUTENTICAÇÃO COM GOOGLE DRIVE ---
sa_info = json.loads(os.environ['GCP_SA_KEY'])
creds = service_account.Credentials.from_service_account_info(
    sa_info, scopes=['https://www.googleapis.com/auth/drive']
)
drive_service = build('drive', 'v3', credentials=creds)

# Localiza a pasta no Google Drive
query = f"name = '{PASTA_DRIVE_NOME}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
response = drive_service.files().list(q=query, fields="files(id, name)").execute()
folders = response.get('files', [])

if not folders:
    raise Exception(f"❌ Pasta '{PASTA_DRIVE_NOME}' não encontrada no Google Drive.")

folder_id = folders[0]['id']

# --- 3. VERIFICA SE A PLANILHA MESTRE DO MÊS EXISTE NO DRIVE ---
query_file = f"name = '{NOME_PLANILHA}' and '{folder_id}' in parents and trashed = false"
file_response = drive_service.files().list(q=query_file, fields="files(id, name)").execute()
files_found = file_response.get('files', [])

abas_consolidadas = {}
file_id_existente = None

if files_found:
    file_id_existente = files_found[0]['id']
    request = drive_service.files().get_media(fileId=file_id_existente)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    fh.seek(0)
    xls_mestre = pd.ExcelFile(fh)
    for sheet in xls_mestre.sheet_names:
        abas_consolidadas[sheet] = pd.read_excel(xls_mestre, sheet_name=sheet)
    print(f"✅ Planilha existente '{NOME_PLANILHA}' baixada ({len(abas_consolidadas)} abas).")
else:
    print(f"ℹ️ Planilha '{NOME_PLANILHA}' não encontrada no Drive. Uma nova será criada.")

# --- 4. CONSULTA API REDEMET ---
for aero in AEROPORTOS:
    aero_upper = aero.upper()
    url = f"https://api-redemet.decea.mil.br/mensagens/metar/{aero}?api_key={API_KEY}&data_ini={DATA_INICIO}00&data_fim={DATA_FIM}23"

    try:
        resp = requests.get(url)
        data = resp.json()
        mensagens_lista = []

        if data.get('status') and data.get('data') and data['data'].get('data'):
            for item in data['data']['data']:
                msg = item.get('mens', '')
                dt = item.get('validade_inicial', '')

                if ("METAR" in msg or "SPECI" in msg) and ("AUTO" not in msg) and ("não localizada" not in msg.lower()):
                    mensagens_lista.append({'DATA_HORA_UTC': dt, 'MENSAGEM': msg})

        if mensagens_lista:
            df_novos = pd.DataFrame(mensagens_lista)
            if aero_upper in abas_consolidadas:
                abas_consolidadas[aero_upper] = pd.concat([abas_consolidadas[aero_upper], df_novos], ignore_index=True)
            else:
                abas_consolidadas[aero_upper] = df_novos
    except Exception as e:
        print(f"❌ Erro ao consultar {aero_upper}: {e}")

    time.sleep(0.05)

# --- 5. LIMPEZA E ORDENAÇÃO ---
for aba, df in abas_consolidadas.items():
    if df.empty:
        continue
    df['DATA_HORA_DT'] = pd.to_datetime(df['DATA_HORA_UTC'], errors='coerce')
    df_limpo = df.drop_duplicates(subset=['DATA_HORA_DT', 'MENSAGEM']).copy()
    df_limpo = df_limpo.sort_values(by='DATA_HORA_DT').reset_index(drop=True)
    df_limpo['DATA_HORA_UTC'] = df_limpo['DATA_HORA_DT'].dt.strftime('%Y-%m-%d %H:%M:%S')
    df_limpo = df_limpo.drop(columns=['DATA_HORA_DT'], errors='ignore')
    abas_consolidadas[aba] = df_limpo

# --- 6. SALVA COM FORMATAÇÃO PADRÃO E ENVIA AO GOOGLE DRIVE ---
output_buffer = io.BytesIO()
with pd.ExcelWriter(output_buffer, engine='xlsxwriter') as writer:
    workbook = writer.book
    format_wrap = workbook.add_format({'text_wrap': True, 'valign': 'top', 'border': 1})
    format_header = workbook.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})

    for aba, df in abas_consolidadas.items():
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

if file_id_existente:
    drive_service.files().update(fileId=file_id_existente, media_body=media).execute()
    print(f"✨ Planilha '{NOME_PLANILHA}' atualizada com sucesso no Google Drive!")
else:
    file_metadata = {'name': NOME_PLANILHA, 'parents': [folder_id]}
    drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    print(f"✨ Nova planilha '{NOME_PLANILHA}' criada com sucesso no Google Drive!")
