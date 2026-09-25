#!/usr/bin/env python3
"""
Auditor de consistência METAR/SPECI (ICA 105-15).

Modos de uso
------------
1) GitHub Actions (automático, todo dia 2):
       python auditoria_metar.py
   -> audita o mês ANTERIOR. Lê e grava na pasta do Google Drive (DRIVE_FOLDER_ID)
      usando a conta de serviço (GCP_SA_KEY).

2) Mês específico no Actions ou no terminal:
       python auditoria_metar.py --mes 2026-09

3) Arquivo local (teste / Colab):
       python auditoria_metar.py --input "SET2026 CONSISTÊNCIA.xlsx" --saida AUDITORIA_SET2026.xlsx
"""
import argparse
import io
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

# ----------------------------------------------------------------------------
# CONFIGURAÇÕES
# ----------------------------------------------------------------------------
MESES = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN',
         'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']

PRESSAO_MIN, PRESSAO_MAX = 900, 1060      # limites de QNH aceitos (hPa)
VARIACAO_MAX_TEMP = 8                     # °C em até 1 h
VARIACAO_MAX_QNH = 5                      # hPa em até 1 h
JANELA_COMPARACAO = timedelta(hours=1)

AERO_RVR_OBRIGATORIO = ['SBGR', 'SBSP', 'SBSJ', 'SBGL', 'SBKP']

SIGLAS_VALIDAS = {
    'DZ', 'RA', 'SN', 'SG', 'PL', 'DS', 'SS', 'FZDZ', 'FZRA', 'FZUP', 'FC',
    'SHGR', 'SHGS', 'SHRA', 'SHSN', 'SHUP', 'TSGR', 'TSGS', 'TSRA', 'TSSN',
    'TSUP', 'UP', 'FG', 'BR', 'HZ', 'SA', 'DU', 'FU', 'VA', 'SQ', 'PO', 'TS',
    'BCFG', 'BLDU', 'BLSA', 'BLSN', 'DRDU', 'DRSA', 'DRSN', 'VCFG', 'FZFG',
    'MIFG', 'PRFG', '//',
}
TERMOS_IGNORAR = {'METAR', 'SPECI', 'AUTO', 'COR', 'NIL', 'CAVOK', 'NCD', 'NSC',
                  'SKC', 'KT', 'WS', 'ALL', 'RWY', 'RMK', 'VRB', 'CB', 'TCU'}

OBSCURECEDORES = {'BR', 'HZ', 'FG', 'FU', 'DU', 'SA', 'VA',
                  'BCFG', 'MIFG', 'PRFG', 'FZFG', 'BLDU', 'BLSA'}

FENOMENOS_RE = ['RA', 'DZ', 'TS', 'GR', 'GS', 'SH', 'VA', 'DS', 'SS', 'FC', 'SQ']
_alt = '|'.join(FENOMENOS_RE)
RE_FENO_RE = re.compile(rf'\b(?<!-)(?:{_alt}){{2,6}}\b|\b(?<!-)(?:{_alt})\b')

RE_VENTO = re.compile(
    r'(?<!\S)(VRB|\d{3}|/{3})(P?\d{2}|//)(G\d{2,3})?KT(?:\s(\d{3})V(\d{3}))?(?!\S)')
RE_NUVEM = re.compile(
    r'(?<!\S)(FEW|SCT|BKN|OVC|///)(\d{3}|///)(CB|TCU|///)?(?!\S)')
RE_VV = re.compile(r'(?<!\S)VV(\d{3}|///)(?!\S)')
RE_TS = re.compile(r'(VC)?[-+]?TS(RA|SN|GR|GS|UP)*')
RE_RVR = re.compile(r'(?<!\S)R\d{2}[LRC]?/\S+')
RE_VIS = re.compile(r'(?<!\S)(\d{4})(?:\s(\d{4})(NE|NW|SE|SW|N|E|S|W))?(?!\S)')
RE_TEMP = re.compile(r'(?<!\S)(M?\d{2})/(M?\d{2})(?!\S)')
RE_QNH = re.compile(r'(?<!\S)Q(\d{4})(?!\d)')


# ----------------------------------------------------------------------------
# MOTOR DE AUDITORIA
# ----------------------------------------------------------------------------
def auditoria_detalhada(df_aero, nome_aba):
    alertas = []
    df_aero = df_aero.copy()
    df_aero['DATA_HORA_UTC'] = pd.to_datetime(df_aero['DATA_HORA_UTC'])
    df_aero = df_aero.sort_values('DATA_HORA_UTC')

    ultimo_dt = None            # data/hora da mensagem anterior (qualquer uma)
    ultimo_feno_re = []         # fenômenos da mensagem anterior (regra RE)
    # Referências VÁLIDAS por parâmetro: (valor, data/hora).
    # Só entram valores que passaram nas regras básicas. Assim, um erro de digitação
    # (ex.: Q1100) gera UM alerta e não contamina a comparação com o METAR seguinte.
    ref = {'temp': None, 'dp': None, 'pres': None}

    def ref_valida(campo, agora):
        r = ref[campo]
        if r and (agora - r[1]) <= JANELA_COMPARACAO:
            return r[0]
        return None

    for _, row in df_aero.iterrows():
        msg = str(row['MENSAGEM']).upper().strip()
        data_hora = row['DATA_HORA_UTC']
        erros = []  # lista de (campo, texto)

        def add(campo, texto):
            erros.append((campo, texto))

        if 'NIL' in msg:
            continue

        tokens = msg.rstrip('=').split()
        corpo = re.split(r'\sQ\d{4}', msg)[0]          # tudo antes do QNH
        corpo_sem_rvr = RE_RVR.sub(' ', corpo)
        tem_cavok = 'CAVOK' in tokens

        intervalo_valido = (ultimo_dt is not None
                            and (data_hora - ultimo_dt) <= JANELA_COMPARACAO)

        # --- VENTO -----------------------------------------------------------
        m = RE_VENTO.search(msg)
        if m:
            dir_w, vel_w, gust_w, v_min, v_max = m.groups()
            if dir_w.isdigit() and dir_w != '000' and int(dir_w) % 10 != 0:
                add('Vento', f'Regra 1 Vento: Direção {dir_w}° inválida. Múltiplo de 10.')
            if v_min and v_max and (int(v_min) % 10 != 0 or int(v_max) % 10 != 0):
                add('Vento', f'Regra Vento: Variação {v_min}V{v_max} deve ter múltiplos de 10.')
            if gust_w and vel_w != '//':
                v_base = 99 if 'P' in vel_w else int(vel_w)
                v_gust = int(gust_w[1:])
                if (v_gust - v_base) < 10:
                    add('Vento', f'Regra 4 Vento: Rajada {gust_w} inválida. Diferença < 10KT.')
            if vel_w == '00' and dir_w != '000':
                add('Vento', 'Regra 5 Vento: Vento calmo (00KT) exige direção 000.')
            elif dir_w == '000' and vel_w not in ('//', '00'):
                add('Vento', 'Regra 5 Vento: Vento de Norte com velocidade deve ser 360 e não 000.')

        # --- VISIBILIDADE E RVR ------------------------------------------------
        vis_pred = 9999 if tem_cavok else None
        vis_min_val = None
        mv = RE_VIS.search(corpo_sem_rvr)
        if mv:
            vis_pred = int(mv.group(1))
            if ((vis_pred < 800 and vis_pred % 50 != 0)
                    or (800 <= vis_pred < 5000 and vis_pred % 100 != 0)
                    or (5000 <= vis_pred < 9000 and vis_pred % 1000 != 0)):
                add('Visibilidade', f'Regra 1 Vis: {vis_pred}m fora do incremento regulamentar.')
            if mv.group(2):
                vis_min_val = int(mv.group(2))
                if vis_pred > 1500:
                    if vis_min_val >= (vis_pred / 2) or vis_min_val > 4900:
                        add('Visibilidade', f'Regra 3 Vis: Mínima {vis_min_val}m incompatível.')
                elif vis_min_val >= vis_pred:
                    add('Visibilidade', f'Regra 4 Vis: Mínima {vis_min_val}m deve ser menor que a predominante.')

            if nome_aba.upper() in AERO_RVR_OBRIGATORIO:
                if vis_pred < 2000 or (vis_min_val is not None and vis_min_val < 2000):
                    if not RE_RVR.search(corpo):
                        add('Visibilidade',
                            f'Regra RVR: Em {nome_aba}, Art. 72. ICA 105-15 - O valor do RVR deve ser '
                            'informado em metros, durante os períodos em que qualquer visibilidade ou '
                            'alcance visual na pista for inferior a 2.000 m.')

        # --- PRECIPITAÇÃO LEVE x OBSCURECIMENTO ---------------------------------
        precip_leve = next((t for t in tokens if re.match(r'-(RA|SN|GR|PL|GS|SG|UP)', t)), None)
        tem_obscurecimento = any(t.lstrip('+-') in OBSCURECEDORES for t in tokens)
        if precip_leve and vis_pred is not None and vis_pred < 5000 and not tem_obscurecimento:
            add('Tempo Presente',
                f'Regra Especial: Precipitação leve {precip_leve} com vis < 5000m exige obscurecimento.')

        # --- TEMPO PRESENTE -----------------------------------------------------
        for tok in tokens:
            if not re.fullmatch(r'[+-]?([A-Z]{2,6}|//)', tok):
                continue
            sigla = tok.lstrip('+-')
            if sigla in TERMOS_IGNORAR or sigla == nome_aba.upper():
                continue
            if any(ch.isdigit() for ch in sigla):
                continue
            # tempo recente (REtsra, RERA, REFZDZ...) é validado pela regra de RE
            base = sigla[2:] if (sigla.startswith('RE') and len(sigla) > 3) else sigla
            if base not in SIGLAS_VALIDAS and not any(s in base for s in ('TS', 'SH', 'RA', 'GR', 'GS', 'DZ', 'SN')):
                add('Tempo Presente', f"Regra Tempo: Sigla '{tok}' não reconhecida.")
            if sigla.startswith('RE') and len(sigla) > 3:
                continue
            if vis_pred is not None:
                if sigla == 'BR' and not (1000 <= vis_pred <= 5000):
                    add('Tempo Presente', 'Regra 2.1 Tempo: BR exige vis 1000-5000m.')
                if sigla == 'HZ' and vis_pred > 5000:
                    add('Tempo Presente', 'Regra 2.1 Tempo: HZ exige vis <= 5000m.')
                # FG puro exige vis < 1000m (ICA: exceto se qualificado por MI, BC, PR ou VC)
                if sigla == 'FG' and vis_pred >= 1000:
                    add('Tempo Presente', 'Regra 2.1 Tempo: FG exige vis < 1000m.')

        # --- NEBULOSIDADE -------------------------------------------------------
        nuvens = RE_NUVEM.findall(corpo)
        tem_vv = RE_VV.search(corpo)
        tem_ts = any(RE_TS.fullmatch(t) for t in corpo.split())
        if tem_vv and nuvens:
            add('Nebulosidade', 'Regra 2 Neb: VV e nuvens são excludentes.')
        for _, altura, tipo in nuvens:
            if altura.isdigit() and int(altura) > 250:
                add('Nebulosidade', f'Regra 1 Neb: Altura {altura} acima de 250.')
            if tipo == 'TCU' and tem_ts:
                add('Nebulosidade', 'Regra 4 Neb: TCU incompatível com TS.')
        if tem_ts and not tem_vv and not any(t == 'CB' for _, _, t in nuvens):
            add('Nebulosidade', 'Regra 1 Neb (OBS): TS exige nuvem CB.')

        # --- TEMPERATURA ------------------------------------------------------
        mt = RE_TEMP.search(corpo)
        if mt:
            t_str, dp_str = mt.groups()
            t_atual = int(t_str.replace('M', '-'))
            dp_atual = int(dp_str.replace('M', '-'))
            if t_atual < dp_atual:
                add('Temperatura', f'Regra Temp: Temperatura ({t_str}) menor que orvalho ({dp_str}).')
            else:
                ref_t = ref_valida('temp', data_hora)
                ref_dp = ref_valida('dp', data_hora)
                if ref_t is not None and abs(t_atual - ref_t) > VARIACAO_MAX_TEMP:
                    add('Temperatura', f'Aviso Temp: Variação brusca T (>{VARIACAO_MAX_TEMP}°C) em 1h.')
                if ref_dp is not None and abs(dp_atual - ref_dp) > VARIACAO_MAX_TEMP:
                    add('Temperatura', f'Aviso Temp: Variação brusca DP (>{VARIACAO_MAX_TEMP}°C) em 1h.')
                ref['temp'] = (t_atual, data_hora)
                ref['dp'] = (dp_atual, data_hora)

        # --- PRESSÃO ----------------------------------------------------------
        mq = RE_QNH.search(msg)
        if mq:
            q_atual = int(mq.group(1))
            if not (PRESSAO_MIN <= q_atual <= PRESSAO_MAX):
                # UM alerta só; valor inválido não vira referência para o próximo METAR
                add('Pressão', f'Regra Pressão: Q{q_atual} fora do limite ({PRESSAO_MIN}-{PRESSAO_MAX} hPa).')
            else:
                ref_q = ref_valida('pres', data_hora)
                if ref_q is not None and abs(q_atual - ref_q) > VARIACAO_MAX_QNH:
                    add('Pressão', f'Aviso Pressão: Variação brusca QNH (>{VARIACAO_MAX_QNH} hPa) em 1h.')
                ref['pres'] = (q_atual, data_hora)

        # --- RMK: TEMPO RECENTE (art. 97 ICA 105-15) ----------------------------
        feno_atual = []
        for f in RE_FENO_RE.findall(corpo):
            if f not in feno_atual:
                feno_atual.append(f)
        if intervalo_valido:
            for f in ultimo_feno_re:
                if f'RE{f}' not in msg:
                    add('RMK', f'Regra RMK art. 97, § 1º, da ICA 105-15: Fenômeno {f} anterior exige RE{f} no RMK deste registro.')

        if 'WS ' in msg and not re.search(r'WS (ALL RWY|R\d{2}[LRC]?)', msg):
            add('RMK', 'Regra RMK: Formato de Windshear (WS) inválido. Use WS ALL RWY ou WS Rxx[RL].')

        if not msg.endswith('='):
            add('Sintaxe', "Regra Sintaxe: Mensagem deve terminar obrigatoriamente com '='.")

        # --- REGISTRO -----------------------------------------------------------
        for campo, texto in erros:
            alertas.append({
                'Data/Hora UTC': data_hora.strftime('%d/%m %H:%MZ'),
                'Mensagem Original': msg,
                'Falha Detectada': texto,
                'Campo': campo,
            })
        ultimo_dt = data_hora
        ultimo_feno_re = feno_atual

    return alertas


def auditar_planilha(fonte, destino):
    """fonte/destino: caminho ou objeto BytesIO. Retorna resumo por aeródromo."""
    xl = pd.ExcelFile(fonte)
    resumo = []
    abas_erro = {}
    for aba in xl.sheet_names:
        df = xl.parse(aba)
        if 'MENSAGEM' not in df.columns or 'DATA_HORA_UTC' not in df.columns:
            continue
        df = df.dropna(subset=['MENSAGEM'])
        res = auditoria_detalhada(df, aba)
        resumo.append({'Aeródromo': aba, 'Mensagens': len(df), 'Alertas': len(res)})
        if res:
            abas_erro[aba] = pd.DataFrame(res)
        print(f"{'🚩' if res else '✅'} {aba}: {len(res)} alertas em {len(df)} mensagens")

    with pd.ExcelWriter(destino, engine='xlsxwriter') as writer:
        pd.DataFrame(resumo).to_excel(writer, sheet_name='RESUMO', index=False)
        writer.sheets['RESUMO'].set_column('A:C', 14)
        wb = writer.book
        fmt = wb.add_format({'text_wrap': True, 'valign': 'top'})
        for aba, df_final in abas_erro.items():
            df_final.to_excel(writer, sheet_name=aba, index=False)
            ws = writer.sheets[aba]
            ws.set_column('A:A', 15)
            ws.set_column('B:B', 65, fmt)
            ws.set_column('C:C', 55, fmt)
            ws.set_column('D:D', 18)
    return resumo


# ----------------------------------------------------------------------------
# GOOGLE DRIVE (conta de serviço) — usado no GitHub Actions
# ----------------------------------------------------------------------------
XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


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


def enviar(svc, buf, nome, pasta_id):
    from googleapiclient.http import MediaIoBaseUpload
    media = MediaIoBaseUpload(buf, mimetype=XLSX_MIME, resumable=False)
    existente = achar_arquivo(svc, nome, pasta_id)
    if existente:
        svc.files().update(
            fileId=existente, 
            media_body=media, 
            supportsAllDrives=True
        ).execute()
        print(f'♻️  Atualizado no Drive: {nome}')
    else:
        # Força o salvamento direto no diretório pai compartilhado
        body = {
            'name': nome, 
            'parents': [pasta_id]
        }
        svc.files().create(
            body=body, 
            media_body=media, 
            fields='id', 
            supportsAllDrives=True
        ).execute()
        print(f'📁 Criado no Drive: {nome}')


def mes_anterior(hoje=None):
    hoje = hoje or datetime.now(timezone.utc)
    primeiro = hoje.replace(day=1)
    ultimo_mes = primeiro - timedelta(days=1)
    return ultimo_mes.year, ultimo_mes.month


def nome_planilha(ano, mes):
    return f'{MESES[mes - 1]}{ano} CONSISTÊNCIA.xlsx'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mes', help='AAAA-MM (padrão: mês anterior)')
    ap.add_argument('--input', help='planilha local (pula o Drive)')
    ap.add_argument('--saida', help='arquivo de saída local')
    args = ap.parse_args()

    if args.input:
        saida = args.saida or 'AUDITORIA_' + os.path.basename(args.input)
        auditar_planilha(args.input, saida)
        print(f'📁 Salvo em: {saida}')
        return

    if args.mes:
        ano, mes = map(int, args.mes.split('-'))
    else:
        ano, mes = mes_anterior()
    nome = nome_planilha(ano, mes)
    pasta_id = os.environ['DRIVE_FOLDER_ID']

    svc = drive_service()
    fid = achar_arquivo(svc, nome, pasta_id)
    if not fid:
        print(f'❌ Planilha não encontrada na pasta do Drive: {nome}')
        sys.exit(1)

    print(f'⬇️  Baixando {nome}')
    origem = baixar(svc, fid)
    saida = io.BytesIO()
    auditar_planilha(origem, saida)
    saida.seek(0)
    enviar(svc, saida, f'AUDITORIA_{nome}', pasta_id)
    print('✅ Auditoria finalizada')


if __name__ == '__main__':
    main()
