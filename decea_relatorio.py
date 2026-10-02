#!/usr/bin/env python3
"""
ROBÔ DO RELATÓRIO DO DECEA — "MENSAGENS AUSENTES OU INCLUÍDAS COM ATRASO".

Todo dia ele olha a pasta "Indicadores MET". Se encontrar um PDF com
"CRCEA" no nome que ainda não foi lido (ou que foi trocado por um novo com o
mesmo nome), ele:

  1) descobre o mês pelo "Data Inicial" do relatório;
  2) soma, por aeródromo, ATRASADAS + AUSENTES de METAR e SPECI (TAF fica de fora);
  3) SBSP: tira o que for de 02:01Z a 08:59Z (AUTOMETAR, fora da jurisdição)
     e lista essas linhas à parte, para você confrontar o DECEA;
  4) grava esse total na coluna E (mensagens atrasadas) da planilha de
     Indicadores — é o valor OFICIAL e substitui o provisório da REDEMET;
     não mexe em valores que você digitou à mão (ex.: meses antigos);
  5) salva "DECEA_<MES><ANO>_ATRASOS_AUSENCIAS.xlsx" com o detalhamento e a
     comparação com a REDEMET;
  6) gera de novo o dashboard HTML.

Uso:
    python decea_relatorio.py                 # procura PDFs novos no Drive
    python decea_relatorio.py --forcar        # relê todos os PDFs da pasta
    python decea_relatorio.py --pdf arquivo.pdf --local-indicadores PASTA ...
"""
import argparse
import io
import re
from datetime import datetime

import openpyxl
import pandas as pd

from comum import (MESES_ABREV, MESES_PT, abrir_pastas, argumentos_pastas,
                   na_janela_auto_sbsp)

RE_ITEM = re.compile(
    r'^(METAR|SPECI)\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})\s+(ATRASADO|AUSENTE)'
    r'(?:\s*-->\s*INSERIDO\s+ÀS\s+(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}))?')
CHAVE_MARCA = 'decea_lido_md5'


def ler_pdf(buf):
    import pdfplumber
    with pdfplumber.open(buf) as pdf:
        return '\n'.join(p.extract_text() or '' for p in pdf.pages)


def interpretar(texto):
    """Lê o texto do PDF. Devolve (ano, mes, totais, itens).
    totais: {(aero, tipo): {'previsto','enviado','atrasadas','ausentes'}}
    itens : lista de dicts (uma linha de ATRASADO/AUSENTE cada)."""
    if 'DECEA' not in texto.upper() and 'CRCEA' not in texto.upper() \
            and 'AUSENTES OU INCLU' not in texto.upper():
        raise ValueError('Esse PDF não parece ser o relatório do DECEA.')
    m = re.search(r'Data Inicial:\s*\d{2}/(\d{2})/(\d{4})', texto)
    if not m:
        raise ValueError('Não achei a "Data Inicial" no relatório.')
    mes, ano = int(m.group(1)), int(m.group(2))

    tipo, aero = None, None
    totais, itens = {}, []
    for linha in texto.split('\n'):
        l = linha.strip()
        if l.startswith('Tipo Meteorológico') and 'Horário' not in l and 'Estado' not in l:
            t = l.replace('Tipo Meteorológico', '').strip().upper()
            tipo = 'METAR' if t.startswith('METAR') else 'SPECI' if t.startswith('SPECI') else 'TAF'
            continue
        mloc = re.match(r'^Localidade:\s*(\S+)', l)
        if mloc:
            aero = mloc.group(1).upper()
            if tipo in ('METAR', 'SPECI'):
                totais.setdefault((aero, tipo), {'previsto': None, 'enviado': None,
                                                 'atrasadas': 0, 'ausentes': 0})
            continue
        if tipo not in ('METAR', 'SPECI') or not aero:
            continue
        for rotulo, campo in (('Total Previsto', 'previsto'), ('Total Enviado', 'enviado'),
                              ('Atrasadas', 'atrasadas'), ('Ausentes', 'ausentes')):
            mm = re.match(rf'^{rotulo}:\s*(\d+)', l)
            if mm:
                totais[(aero, tipo)][campo] = int(mm.group(1))
        mi = RE_ITEM.match(l)
        if mi:
            t, data, hora, estado, d_ins, h_ins = mi.groups()
            dt = datetime.strptime(f'{data} {hora}', '%d/%m/%Y %H:%M')
            ins = datetime.strptime(f'{d_ins} {h_ins}', '%d/%m/%Y %H:%M') if d_ins else None
            itens.append({'AERÓDROMO': aero, 'TIPO': t, 'HORÁRIO (Z)': dt, 'ESTADO': estado,
                          'INSERIDO ÀS (Z)': ins,
                          'ATRASO (min)': round((ins - dt).total_seconds() / 60) if ins else None,
                          'JANELA AUTOMETAR SBSP': aero == 'SBSP' and na_janela_auto_sbsp(dt)})
    return ano, mes, totais, itens


def consolidar(totais, itens):
    """Total por aeródromo para a coluna E (+ conferência com as linhas do PDF)."""
    aeros = sorted({a for a, _ in totais})
    df_it = pd.DataFrame(itens)
    linhas = []
    for a in aeros:
        tm = totais.get((a, 'METAR'), {})
        ts = totais.get((a, 'SPECI'), {})
        soma_pdf = (tm.get('atrasadas', 0) + tm.get('ausentes', 0)
                    + ts.get('atrasadas', 0) + ts.get('ausentes', 0))
        da = df_it[df_it['AERÓDROMO'] == a] if not df_it.empty else df_it
        n_itens = len(da)
        n_auto = int(da['JANELA AUTOMETAR SBSP'].sum()) if n_itens else 0
        # Para SBSP, usa as linhas do PDF (precisa separar por horário).
        total_ind = soma_pdf - n_auto
        linhas.append({
            'Aeródromo': a,
            'METAR previsto': tm.get('previsto'),
            'METAR enviado': tm.get('enviado'),
            'METAR atrasadas': tm.get('atrasadas', 0),
            'METAR ausentes': tm.get('ausentes', 0),
            'SPECI enviado': ts.get('enviado'),
            'SPECI atrasadas': ts.get('atrasadas', 0),
            'Soma do PDF (METAR+SPECI)': soma_pdf,
            'Excluídas janela AUTOMETAR (SBSP)': n_auto,
            'Total p/ indicador (coluna E)': total_ind,
            'Conferência linhas x totais': 'OK' if n_itens == soma_pdf else f'⚠️ {n_itens} linhas x {soma_pdf}',
        })
    return pd.DataFrame(linhas)


def comparar_redemet(pasta_ind, ano, mes, df_res):
    from mensal_redemet import nome_atrasos
    nome = nome_atrasos(ano, mes)
    if not pasta_ind.achar(nome):
        return df_res
    red = pd.read_excel(pasta_ind.baixar(nome), sheet_name='RESUMO')
    col = next((c for c in red.columns if str(c).startswith('Total p/ indicador')), None)
    if col is None:
        return df_res
    mapa = dict(zip(red['Aeródromo'], red[col]))
    df_res = df_res.copy()
    df_res['Provisório REDEMET'] = df_res['Aeródromo'].map(mapa)
    df_res['Diferença DECEA − REDEMET'] = df_res['Total p/ indicador (coluna E)'] - df_res['Provisório REDEMET']
    return df_res


def planilha_detalhe(df_res, itens, ano, mes):
    df_it = pd.DataFrame(itens)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter', datetime_format='dd/mm/yyyy hh:mm') as w:
        df_res.to_excel(w, sheet_name='RESUMO', index=False)
        w.sheets['RESUMO'].set_column('A:A', 12)
        w.sheets['RESUMO'].set_column('B:N', 18)
        w.sheets['RESUMO'].write(len(df_res) + 2, 0,
                                 f'Relatório DECEA de {MESES_PT[mes - 1]}/{ano}. Coluna E = atrasadas + ausentes '
                                 '(METAR + SPECI, sem TAF). SBSP sem 02:01Z–08:59Z (AUTOMETAR).')
        (df_it if not df_it.empty else pd.DataFrame(columns=['AERÓDROMO'])).to_excel(
            w, sheet_name='DETALHES', index=False)
        w.sheets['DETALHES'].set_column('A:G', 20)
        auto = df_it[df_it['JANELA AUTOMETAR SBSP']] if not df_it.empty else df_it
        (auto if not auto.empty else pd.DataFrame(columns=['AERÓDROMO'])).to_excel(
            w, sheet_name='SBSP_AUTOMETAR', index=False)
        w.sheets['SBSP_AUTOMETAR'].set_column('A:G', 20)
    buf.seek(0)
    return buf


def processar_pdf(buf_pdf, pasta_ind, forcar=False):
    from atualizar_indicadores_drive import COL_E, NOME_PLANILHA_INDICADORES, aplicar
    ano, mes, totais, itens = interpretar(ler_pdf(buf_pdf))
    print(f'📅 Relatório DECEA de {MESES_PT[mes - 1]}/{ano}')
    df_res = consolidar(totais, itens)
    df_res = comparar_redemet(pasta_ind, ano, mes, df_res)
    print(df_res[['Aeródromo', 'Soma do PDF (METAR+SPECI)', 'Excluídas janela AUTOMETAR (SBSP)',
                  'Total p/ indicador (coluna E)', 'Conferência linhas x totais']].to_string(index=False))

    nome_det = f'DECEA_{MESES_ABREV[mes - 1]}{ano}_ATRASOS_AUSENCIAS.xlsx'
    pasta_ind.enviar(nome_det, planilha_detalhe(df_res, itens, ano, mes))

    wb = openpyxl.load_workbook(pasta_ind.baixar(NOME_PLANILHA_INDICADORES))
    valores = {r['Aeródromo']: {COL_E: int(r['Total p/ indicador (coluna E)'])} for _, r in df_res.iterrows()}
    rel = aplicar(wb, valores, ano, mes, 'DECEA', forcar)
    saida = io.BytesIO()
    wb.save(saida)
    pasta_ind.enviar(NOME_PLANILHA_INDICADORES, saida)
    print('\n'.join(rel))
    return ano, mes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--forcar', action='store_true',
                    help='relê PDFs já lidos e sobrescreve até valores digitados à mão')
    ap.add_argument('--pdf', help='PDF local específico (Colab/teste)')
    ap.add_argument('--sem-dashboard', action='store_true')
    argumentos_pastas(ap)
    args = ap.parse_args()
    _, pasta_ind = abrir_pastas(args)

    lidos = []
    if args.pdf:
        with open(args.pdf, 'rb') as f:
            lidos.append(processar_pdf(io.BytesIO(f.read()), pasta_ind, args.forcar))
    else:
        pdfs = pasta_ind.listar(contendo='crcea', extensao='.pdf')
        if not pdfs:
            print('ℹ️ Nenhum PDF com "CRCEA" no nome na pasta Indicadores MET.')
        for p in pdfs:
            md5 = p.get('md5Checksum') or p.get('modifiedTime')
            if not args.forcar and pasta_ind.marca(p['id'], CHAVE_MARCA) == str(md5):
                print(f"⏭️ {p['name']} já foi lido antes.")
                continue
            print(f"📎 Lendo {p['name']}")
            try:
                lidos.append(processar_pdf(pasta_ind.baixar_id(p['id']), pasta_ind, args.forcar))
            except ValueError as e:
                print(f"⚠️ {p['name']}: {e}")
                continue
            try:
                pasta_ind.marcar(p['id'], CHAVE_MARCA, str(md5))
            except Exception as e:  # sem permissão de editar o PDF: só relê amanhã (inofensivo)
                print(f"ℹ️ Não consegui marcar {p['name']} como lido ({e}).")

    if lidos and not args.sem_dashboard:
        import gerar_dashboard
        gerar_dashboard.executar(pasta_ind)
    print('✅ Fim.' if lidos else '✅ Nada novo do DECEA.')


if __name__ == '__main__':
    from comum import rodar
    rodar(main)
