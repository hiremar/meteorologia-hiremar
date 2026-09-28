#!/usr/bin/env python3
"""
Preenche a planilha "Indicadores de Meteorologia atualizada 2026.xlsx" (no
Google Drive) com os resultados da auditoria de consistência de um mês:
número de mensagens e erros de consistência, por aeródromo.

As colunas de porcentagem (G = pontualidade, H = consistência) já têm
FÓRMULA na planilha (ex.: =(D58-F58)/D58) — este script nunca escreve nelas,
só em D e F. A fórmula recalcula sozinha quando a planilha é aberta.

Se a linha do mês/ano ainda não existir na aba do aeródromo, o script cria
uma nova linha automaticamente (copiando o nome da estação da última linha
existente e repetindo as fórmulas de G/H para a linha nova).

Fonte dos dados: a aba RESUMO de AUDITORIA_<MES><ANO> CONSISTÊNCIA.xlsx,
gerada pelo auditoria_metar.py (mesma pasta CONSISTENCIA do Drive).

Modos de uso
------------
1) GitHub Actions (roda logo depois do auditoria_metar.py, dia 2):
       python atualizar_indicadores_drive.py
    -> usa o mês ANTERIOR, lê a auditoria da pasta CONSISTENCIA
       (DRIVE_FOLDER_ID) e atualiza a planilha na pasta Indicadores MET
       (INDICADORES_FOLDER_ID), ambas via conta de serviço (GCP_SA_KEY).

2) Mês específico:
       python atualizar_indicadores_drive.py --mes 2026-09
"""
import argparse
import io
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import openpyxl

MESES_ABREV = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN',
               'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']
MESES_PT = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
            'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']

NOME_PLANILHA_INDICADORES = os.environ.get(
    'INDICADORES_FILE_NAME', 'Indicadores de Meteorologia atualizada 2026.xlsx')

XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


# ----------------------------------------------------------------------------
# GOOGLE DRIVE (conta de serviço)
# ----------------------------------------------------------------------------
def drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(os.environ['GCP_SA_KEY'])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=creds, cache_discovery=False)


def achar_arquivo(svc, nome, pasta_id):
    nome_q = nome.replace("'", "\\'")
    q = f"name = '{nome_q}' and '{pasta_id}' in parents and trashed = false"
    r = svc.files().list(q=q, fields='files(id,name)', supportsAllDrives=True,
                          includeItemsFromAllDrives=True).execute()
    arqs = r.get('files', [])
    return arqs[0]['id'] if arqs else None


def baixar(svc, file_id):
    from googleapiclient.http import MediaIoBaseDownload
    buf = io.BytesIO()
    req = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
    dl = MediaIoBaseDownload(buf, req)
    feito = False
    while not feito:
        _, feito = dl.next_chunk()
    buf.seek(0)
    return buf


def enviar(svc, buf, file_id, pasta_id, nome):
    from googleapiclient.http import MediaIoBaseUpload
    media = MediaIoBaseUpload(buf, mimetype=XLSX_MIME, resumable=False)
    if file_id:
        svc.files().update(fileId=file_id, media_body=media, supportsAllDrives=True).execute()
        print(f'♻️  Atualizado no Drive: {nome}')
    else:
        body = {'name': nome, 'parents': [pasta_id]}
        svc.files().create(body=body, media_body=media, fields='id', supportsAllDrives=True).execute()
        print(f'📁 Criado no Drive: {nome}')


# ----------------------------------------------------------------------------
# LÓGICA DE ATUALIZAÇÃO
# ----------------------------------------------------------------------------
def ler_resumo(buf_auditoria):
    wb = openpyxl.load_workbook(buf_auditoria, data_only=True)
    ws = wb['RESUMO']
    resumo = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        aero, mensagens, alertas = row[0], row[1], row[2]
        if aero is None:
            continue
        resumo[str(aero).upper()] = (mensagens, alertas)
    return resumo


def atualizar_indicadores(buf_indicadores, resumo, ano, mes_pt):
    wb = openpyxl.load_workbook(buf_indicadores)  # mantém fórmulas/formatação
    nao_encontrados, linhas_criadas = [], []

    for aero, (mensagens, alertas) in resumo.items():
        if aero not in wb.sheetnames:
            nao_encontrados.append(aero)
            continue

        ws = wb[aero]

        linha_alvo = None
        ultima_linha_dado = None
        for row in ws.iter_rows(min_row=2):
            if row[0].value is not None:
                ultima_linha_dado = row
            if row[1].value == ano and row[2].value == mes_pt:
                linha_alvo = row
                break

        if linha_alvo is None:
            # Mês ainda não tem linha na planilha -> cria uma nova,
            # logo depois da última linha com dado, copiando o nome da
            # estação e repetindo as fórmulas de pontualidade/consistência.
            nova_linha_num = (ultima_linha_dado[0].row + 1) if ultima_linha_dado else 2
            estacao = ultima_linha_dado[0].value if ultima_linha_dado else aero
            ws.cell(row=nova_linha_num, column=1, value=estacao)          # A: Estação
            ws.cell(row=nova_linha_num, column=2, value=ano)              # B: ano
            ws.cell(row=nova_linha_num, column=3, value=mes_pt)           # C: mês
            ws.cell(row=nova_linha_num, column=7,                        # G: % pontualidade
                    value=f'=(D{nova_linha_num}-E{nova_linha_num})/D{nova_linha_num}')
            ws.cell(row=nova_linha_num, column=8,                        # H: % consistência
                    value=f'=(D{nova_linha_num}-F{nova_linha_num})/D{nova_linha_num}')
            linha_alvo = list(ws[nova_linha_num])
            linhas_criadas.append(aero)

        linha_alvo[3].value = mensagens   # D: numero de mensagens
        linha_alvo[5].value = alertas     # F: erros de consistência
        # G e H já são fórmulas — não escrevemos nelas, a planilha recalcula
        # sozinha ao abrir. E (mensagens atrasadas) também não é tocado aqui:
        # vem do relatório do DECEA, via o notebook do Colab.

    saida = io.BytesIO()
    wb.save(saida)
    saida.seek(0)
    return saida, nao_encontrados, linhas_criadas


def mes_anterior(hoje=None):
    hoje = hoje or datetime.now(timezone.utc)
    primeiro = hoje.replace(day=1)
    ultimo_mes = primeiro - timedelta(days=1)
    return ultimo_mes.year, ultimo_mes.month


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mes', help='AAAA-MM (padrão: mês anterior)')
    args = ap.parse_args()

    if args.mes:
        ano, mes = map(int, args.mes.split('-'))
    else:
        ano, mes = mes_anterior()

    nome_auditoria = f'AUDITORIA_{MESES_ABREV[mes - 1]}{ano} CONSISTÊNCIA.xlsx'
    mes_pt = MESES_PT[mes - 1]

    pasta_consistencia = os.environ['DRIVE_FOLDER_ID']
    pasta_indicadores = os.environ['INDICADORES_FOLDER_ID']

    svc = drive_service()

    fid_auditoria = achar_arquivo(svc, nome_auditoria, pasta_consistencia)
    if not fid_auditoria:
        print(f'❌ Auditoria não encontrada na pasta CONSISTENCIA: {nome_auditoria}')
        sys.exit(1)

    fid_indicadores = achar_arquivo(svc, NOME_PLANILHA_INDICADORES, pasta_indicadores)
    if not fid_indicadores:
        print(f'❌ Planilha de indicadores não encontrada: {NOME_PLANILHA_INDICADORES}')
        sys.exit(1)

    print(f'⬇️  Baixando {nome_auditoria}')
    buf_auditoria = baixar(svc, fid_auditoria)
    resumo = ler_resumo(buf_auditoria)

    print(f'⬇️  Baixando {NOME_PLANILHA_INDICADORES}')
    buf_indicadores = baixar(svc, fid_indicadores)

    saida, nao_encontrados, linhas_criadas = atualizar_indicadores(buf_indicadores, resumo, ano, mes_pt)

    enviar(svc, saida, fid_indicadores, pasta_indicadores, NOME_PLANILHA_INDICADORES)

    if nao_encontrados:
        print(f'⚠️  Aeródromos da auditoria sem aba correspondente em Indicadores: {nao_encontrados}')
    if linhas_criadas:
        print(f'ℹ️  Linha de {mes_pt}/{ano} criada automaticamente para: {linhas_criadas}')

    print('✅ Indicadores atualizados (número de mensagens + erros de consistência).')


if __name__ == '__main__':
    main()


if __name__ == '__main__':
    main()
