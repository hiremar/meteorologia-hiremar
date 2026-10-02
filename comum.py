#!/usr/bin/env python3
"""
Peças compartilhadas pelos robôs da Subdivisão de Meteorologia (CRCEA-SE).

Aqui ficam as coisas que TODOS os scripts usam, para não repetir código:
  - a lista dos 21 aeródromos e os nomes dos meses;
  - a consulta à API da REDEMET (com novas tentativas e páginas);
  - a "pasta" onde os arquivos ficam, que pode ser:
        PastaDrive  -> Google Drive pela conta de serviço (GitHub Actions)
        PastaLocal  -> uma pasta do computador / Drive montado no Colab
    Os dois tipos têm os MESMOS métodos (achar, baixar, enviar...), então os
    scripts funcionam igual no GitHub e no Colab, sem mudar uma linha.
"""
import io
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

import requests

# ----------------------------------------------------------------------------
# CONSTANTES
# ----------------------------------------------------------------------------
AEROPORTOS = [
    'SBAF', 'SDAM', 'SBBP', 'SBCB', 'SDCO', 'SBES', 'SBGL', 'SBGR', 'SBGW',
    'SBJD', 'SBJH', 'SBJR', 'SBKP', 'SBMI', 'SBMT', 'SBRJ', 'SBSC', 'SBSJ',
    'SBSP', 'SBST', 'SBTA',
]
MESES_ABREV = ['JAN', 'FEV', 'MAR', 'ABR', 'MAI', 'JUN',
               'JUL', 'AGO', 'SET', 'OUT', 'NOV', 'DEZ']
MESES_PT = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
            'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro']

XLSX_MIME = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

# SBSP (EMS-SP): o operador trabalha das 09:00Z às 02:00Z. Entre 02:01Z e
# 08:59Z quem emite é o AUTOMETAR -> fora da nossa "jurisdição" para atraso,
# ausência e consistência. As horas cheias de METAR AUTO são 03Z..08Z.
SBSP_AUTO_INI = (2, 1)    # 02:01Z
SBSP_AUTO_FIM = (8, 59)   # 08:59Z
SBSP_HORAS_AUTO = [3, 4, 5, 6, 7, 8]

TENTATIVAS_DRIVE = 6      # erros passageiros do Google (ex.: 503)


def na_janela_auto_sbsp(dt):
    """True se o horário (datetime) cai na janela do AUTOMETAR de SBSP."""
    hm = (dt.hour, dt.minute)
    return SBSP_AUTO_INI <= hm <= SBSP_AUTO_FIM


def nome_consistencia(ano, mes):
    """(2026, 9) -> 'SET2026 CONSISTÊNCIA.xlsx'"""
    return f'{MESES_ABREV[mes - 1]}{ano} CONSISTÊNCIA.xlsx'


def mes_anterior(hoje=None):
    hoje = hoje or datetime.now(timezone.utc)
    ultimo = hoje.replace(day=1) - timedelta(days=1)
    return ultimo.year, ultimo.month


def ler_mes(texto):
    """'2026-09' -> (2026, 9). Vazio/None -> mês anterior."""
    if texto:
        ano, mes = map(int, texto.split('-'))
        return ano, mes
    return mes_anterior()


def eh_auto(msg):
    return re.search(r'\bAUTO\b', msg or '') is not None


# ----------------------------------------------------------------------------
# REDEMET
# ----------------------------------------------------------------------------
URL_REDEMET = 'https://api-redemet.decea.mil.br/mensagens/metar/{aero}'


def chave_redemet():
    chave = os.environ.get('REDEMET_KEY')
    if not chave:
        raise SystemExit('ERRO: chave da REDEMET não configurada (variável REDEMET_KEY).')
    return chave


def buscar_redemet(aero, data_ini, data_fim, chave=None, tentativas=3):
    """Busca METAR/SPECI de um aeródromo entre data_ini e data_fim
    (strings 'AAAAMMDDHH'). Devolve a LISTA de mensagens (dicts da API:
    'mens', 'validade_inicial', 'recebimento'...) ou None se a REDEMET falhou.

    A API devolve as mensagens em PÁGINAS. Antes só a 1ª página era lida;
    agora seguimos 'last_page' até o fim, para não perder mensagens.
    """
    chave = chave or chave_redemet()
    url = URL_REDEMET.format(aero=aero.lower())
    todas = []
    pagina, ultima = 1, 1
    while pagina <= ultima:
        params = {'api_key': chave, 'data_ini': data_ini, 'data_fim': data_fim}
        if pagina > 1:
            params['page'] = pagina
        dados = None
        for t in range(1, tentativas + 1):
            try:
                r = requests.get(url, params=params, timeout=60)
                dados = r.json()
                break
            except Exception as e:  # rede, timeout, resposta que não é JSON...
                print(f'   ⚠️ {aero} {data_ini}: tentativa {t} falhou ({e})')
                time.sleep(5 * t)
        if dados is None:
            return None
        bloco = dados.get('data') or {}
        if isinstance(bloco, dict):
            todas.extend(bloco.get('data') or [])
            try:
                ultima = int(bloco.get('last_page') or 1)
            except (TypeError, ValueError):
                ultima = 1
        elif isinstance(bloco, list):
            todas.extend(bloco)
        pagina += 1
        if ultima > 50:   # trava de segurança
            break
    return todas


def para_datahora(texto):
    try:
        return datetime.strptime(str(texto)[:19], '%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------
# PASTAS (Drive ou local) — mesma "cara" para os dois
# ----------------------------------------------------------------------------
class PastaLocal:
    """Pasta do computador (ou do Drive montado no Colab)."""

    def __init__(self, caminho):
        self.caminho = caminho
        os.makedirs(caminho, exist_ok=True)

    def __repr__(self):
        return f'PastaLocal({self.caminho})'

    def achar(self, nome):
        p = os.path.join(self.caminho, nome)
        return p if os.path.exists(p) else None

    def baixar(self, nome):
        with open(os.path.join(self.caminho, nome), 'rb') as f:
            return io.BytesIO(f.read())

    def enviar(self, nome, buf, mime=XLSX_MIME):
        buf.seek(0)
        with open(os.path.join(self.caminho, nome), 'wb') as f:
            f.write(buf.read())
        print(f'💾 Salvo: {nome}')

    def editado_pelo_usuario(self, nome):
        # No modo local não há como saber quem editou; quem roda à mão decide.
        return False

    def listar(self, contendo='', extensao=''):
        saida = []
        for n in os.listdir(self.caminho):
            if contendo.lower() in n.lower() and n.lower().endswith(extensao.lower()):
                p = os.path.join(self.caminho, n)
                saida.append({'id': p, 'name': n, 'md5Checksum': _md5(p),
                              'modifiedTime': os.path.getmtime(p)})
        return saida

    def baixar_id(self, file_id):
        with open(file_id, 'rb') as f:
            return io.BytesIO(f.read())

    # Controle de "já processado" (PDF do DECEA): arquivo .json ao lado
    def _controle(self):
        p = os.path.join(self.caminho, '.controle_robo.json')
        return p, (json.load(open(p)) if os.path.exists(p) else {})

    def marca(self, file_id, chave):
        _, c = self._controle()
        return c.get(f'{os.path.basename(file_id)}|{chave}')

    def marcar(self, file_id, chave, valor):
        p, c = self._controle()
        c[f'{os.path.basename(file_id)}|{chave}'] = valor
        json.dump(c, open(p, 'w'), indent=1)


def _md5(caminho):
    import hashlib
    h = hashlib.md5()
    with open(caminho, 'rb') as f:
        h.update(f.read())
    return h.hexdigest()


class PastaDrive:
    """Pasta do Google Drive acessada pela conta de serviço (GCP_SA_KEY)."""

    def __init__(self, folder_id, svc=None):
        self.folder_id = folder_id
        self.svc = svc or drive_service()

    def __repr__(self):
        return f'PastaDrive({self.folder_id})'

    def _buscar(self, nome):
        nome_q = nome.replace("'", "\\'")
        q = f"name = '{nome_q}' and '{self.folder_id}' in parents and trashed = false"
        r = self.svc.files().list(
            q=q, fields='files(id,name,modifiedTime,lastModifyingUser(emailAddress,me))',
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute(num_retries=TENTATIVAS_DRIVE)
        arqs = r.get('files', [])
        return arqs[0] if arqs else None

    def achar(self, nome):
        a = self._buscar(nome)
        return a['id'] if a else None

    def baixar_id(self, file_id):
        from googleapiclient.http import MediaIoBaseDownload
        buf = io.BytesIO()
        req = self.svc.files().get_media(fileId=file_id, supportsAllDrives=True)
        dl = MediaIoBaseDownload(buf, req)
        feito = False
        while not feito:
            _, feito = dl.next_chunk(num_retries=TENTATIVAS_DRIVE)
        buf.seek(0)
        return buf

    def baixar(self, nome):
        fid = self.achar(nome)
        if not fid:
            raise FileNotFoundError(nome)
        return self.baixar_id(fid)

    def enviar(self, nome, buf, mime=XLSX_MIME):
        from googleapiclient.http import MediaIoBaseUpload
        buf.seek(0)
        media = MediaIoBaseUpload(buf, mimetype=mime, resumable=True)
        fid = self.achar(nome)
        if fid:
            self.svc.files().update(fileId=fid, media_body=media, supportsAllDrives=True
                                    ).execute(num_retries=TENTATIVAS_DRIVE)
            print(f'♻️  Atualizado no Drive: {nome}')
        else:
            body = {'name': nome, 'parents': [self.folder_id]}
            self.svc.files().create(body=body, media_body=media, fields='id',
                                    supportsAllDrives=True).execute(num_retries=TENTATIVAS_DRIVE)
            print(f'📁 Criado no Drive: {nome}')

    def editado_pelo_usuario(self, nome):
        """True se a última pessoa a mexer no arquivo NÃO foi o robô.
        Serve para não apagar os ajustes manuais do Hiremar."""
        a = self._buscar(nome)
        if not a:
            return False
        quem = a.get('lastModifyingUser') or {}
        return not quem.get('me', False)

    def listar(self, contendo='', extensao=''):
        q = f"'{self.folder_id}' in parents and trashed = false"
        r = self.svc.files().list(
            q=q, fields='files(id,name,md5Checksum,modifiedTime,appProperties)',
            supportsAllDrives=True, includeItemsFromAllDrives=True, pageSize=1000,
        ).execute(num_retries=TENTATIVAS_DRIVE)
        return [f for f in r.get('files', [])
                if contendo.lower() in f['name'].lower()
                and f['name'].lower().endswith(extensao.lower())]

    def marca(self, file_id, chave):
        f = self.svc.files().get(fileId=file_id, fields='appProperties',
                                 supportsAllDrives=True).execute(num_retries=TENTATIVAS_DRIVE)
        return (f.get('appProperties') or {}).get(chave)

    def marcar(self, file_id, chave, valor):
        self.svc.files().update(fileId=file_id, body={'appProperties': {chave: valor}},
                                supportsAllDrives=True).execute(num_retries=TENTATIVAS_DRIVE)


def drive_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    info = json.loads(os.environ['GCP_SA_KEY'])
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=['https://www.googleapis.com/auth/drive'])
    return build('drive', 'v3', credentials=creds, cache_discovery=False)


def abrir_pastas(args):
    """Devolve (pasta_consistencia, pasta_indicadores).
    --local-consistencia / --local-indicadores -> pastas do computador/Colab.
    Sem isso -> Google Drive, pelos secrets DRIVE_FOLDER_ID e INDICADORES_FOLDER_ID."""
    if getattr(args, 'local_consistencia', None) or getattr(args, 'local_indicadores', None):
        return (PastaLocal(args.local_consistencia or args.local_indicadores),
                PastaLocal(args.local_indicadores or args.local_consistencia))
    svc = drive_service()
    return (PastaDrive(os.environ['DRIVE_FOLDER_ID'], svc),
            PastaDrive(os.environ['INDICADORES_FOLDER_ID'], svc))


def argumentos_pastas(ap):
    ap.add_argument('--local-consistencia', help='pasta local da CONSISTENCIA (Colab/teste)')
    ap.add_argument('--local-indicadores', help='pasta local "Indicadores MET" (Colab/teste)')


# ----------------------------------------------------------------------------
# PLANILHA MENSAL DE CONSISTÊNCIA (uma aba por aeródromo)
# ----------------------------------------------------------------------------
def ler_abas(buf):
    import pandas as pd
    xls = pd.ExcelFile(buf)
    return {s: pd.read_excel(xls, sheet_name=s) for s in xls.sheet_names}


def juntar_e_limpar(abas, novas_por_aero):
    """Acrescenta as mensagens novas em cada aba, tira repetidas e ordena.
    Devolve quantas linhas foram realmente acrescentadas."""
    import pandas as pd
    antes = sum(len(df) for df in abas.values())
    for aero, df_novo in novas_por_aero.items():
        if df_novo is None or df_novo.empty:
            continue
        abas[aero] = pd.concat([abas[aero], df_novo], ignore_index=True) if aero in abas else df_novo.copy()
    for aba, df in list(abas.items()):
        if df.empty or 'DATA_HORA_UTC' not in df.columns:
            continue
        df = df.copy()
        df['_DT'] = pd.to_datetime(df['DATA_HORA_UTC'], errors='coerce')
        df['MENSAGEM'] = df['MENSAGEM'].astype(str).str.strip()
        df = df.drop_duplicates(subset=['_DT', 'MENSAGEM']).sort_values('_DT').reset_index(drop=True)
        df['DATA_HORA_UTC'] = df['_DT'].dt.strftime('%Y-%m-%d %H:%M:%S')
        abas[aba] = df.drop(columns=['_DT'])
    return sum(len(df) for df in abas.values()) - antes


def gravar_abas(abas):
    """Gera o .xlsx (em memória) com a formatação padrão da CONSISTÊNCIA."""
    import pandas as pd
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as writer:
        wb = writer.book
        f_wrap = wb.add_format({'text_wrap': True, 'valign': 'top', 'border': 1})
        f_head = wb.add_format({'bold': True, 'bg_color': '#D7E4BC', 'border': 1})
        ordem = [a for a in AEROPORTOS if a in abas] + [a for a in abas if a not in AEROPORTOS]
        for aba in ordem:
            df = abas[aba]
            cols = [c for c in ['DATA_HORA_UTC', 'MENSAGEM'] if c in df.columns]
            df_s = df[cols] if cols else df
            df_s.to_excel(writer, sheet_name=aba, index=False)
            ws = writer.sheets[aba]
            for i, v in enumerate(df_s.columns.values):
                ws.write(0, i, v, f_head)
            ws.set_column('A:A', 20, f_wrap)
            ws.set_column('B:B', 150, f_wrap)
    buf.seek(0)
    return buf


def mensagens_para_planilha(itens):
    """Itens da REDEMET -> linhas (DATA_HORA_UTC, MENSAGEM) que vão para a
    CONSISTÊNCIA: só METAR/SPECI de operador (sem AUTO, sem 'não localizada')."""
    linhas = []
    for it in itens:
        msg = (it.get('mens') or '').strip()
        if not msg or 'não localizada' in msg.lower():
            continue
        if not (msg.startswith('METAR') or msg.startswith('SPECI')) or eh_auto(msg):
            continue
        linhas.append({'DATA_HORA_UTC': it.get('validade_inicial', ''), 'MENSAGEM': msg})
    return linhas


# ----------------------------------------------------------------------------
# ERROS VISÍVEIS NO GITHUB
# ----------------------------------------------------------------------------
def rodar(main):
    """Roda main(); se der erro, além do traceback normal, publica o erro como
    "annotation" do GitHub (aparece no resumo da execução, em vermelho)."""
    import traceback
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        tb = traceback.format_exc()
        print(tb)
        if os.environ.get('GITHUB_ACTIONS'):
            linhas = tb.strip().splitlines()[-12:]
            msg = '%0A'.join(l.replace('%', '%25').replace('\r', '') for l in linhas)
            print(f'::error title=Falha no robô::{msg}')
        raise SystemExit(1)
