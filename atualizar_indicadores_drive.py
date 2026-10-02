#!/usr/bin/env python3
"""
Preenche a planilha "Indicadores de Meteorologia atualizada 2026.xlsx"
(pasta Indicadores MET) com os números do mês, por aeródromo:

    D  numero de mensagens      <- "Soma Operador" do Relatorio_METAR_<AAAA>_<MM>.xlsx
                                   (METAR+SPECI de operador, 1 por horário, COR vale);
                                   se ele não existir, usa o RESUMO da AUDITORIA
    E  mensagens atrasadas      <- RESUMO do ATRASOS_METAR_SPECI_<AAAA>_<MM>_FINAL.xlsx
                                   (PROVISÓRIO, REDEMET: atrasadas + ausentes)
                                   depois substituído pelo DECEA (decea_relatorio.py)
    F  erros de consistência    <- RESUMO da AUDITORIA

G e H (porcentagens) são FÓRMULAS da planilha e nunca são tocadas.

PROTEÇÃO DOS SEUS AJUSTES
Cada célula que o robô escreve ganha uma NOTA (comentário) dizendo a fonte e
o valor que ele colocou. Na próxima rodada:
  - célula vazia                          -> o robô preenche;
  - nota do robô e valor igual ao da nota -> o robô pode atualizar;
  - valor diferente da nota / sem nota    -> foi você que mexeu: NÃO mexe;
  - nota "DECEA" na coluna E              -> a REDEMET nunca sobrescreve.
--forcar ignora a proteção (menos a do DECEA).

Uso:
    python atualizar_indicadores_drive.py               # mês anterior, Drive
    python atualizar_indicadores_drive.py --mes 2026-09 [--forcar]
"""
import argparse
import io
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import openpyxl
from openpyxl.comments import Comment

from comum import (MESES_ABREV, MESES_PT, abrir_pastas, argumentos_pastas,
                   ler_mes, nome_consistencia)

NOME_PLANILHA_INDICADORES = os.environ.get(
    'INDICADORES_FILE_NAME', 'Indicadores de Meteorologia atualizada 2026.xlsx')

COL_D, COL_E, COL_F, COL_G, COL_H = 4, 5, 6, 7, 8
RE_NOTA = re.compile(r'\[robô fonte=(\w+) valor=([^\]]*)\]')


# ----------------------------------------------------------------------------
# CÉLULAS COM NOTA DO ROBÔ
# ----------------------------------------------------------------------------
def nota_do_robo(cell):
    """Devolve (fonte, valor_texto) se a célula tem nota do robô; senão None."""
    if cell.comment and cell.comment.text:
        m = RE_NOTA.search(cell.comment.text)
        if m:
            return m.group(1), m.group(2)
    return None


def _igual(a, b):
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


def escrever(cell, valor, fonte, forcar=False):
    """Escreve 'valor' respeitando a proteção. Devolve 'escrito', 'igual' ou o motivo de não escrever."""
    nota = nota_do_robo(cell)
    if fonte != 'DECEA' and nota and nota[0] == 'DECEA':
        return 'protegido (DECEA)'
    vazio = cell.value is None or str(cell.value).strip() == ''
    pode = (fonte == 'DECEA' and (vazio or nota or forcar)) or vazio or forcar \
        or (nota is not None and _igual(cell.value, nota[1]))
    if not pode:
        return 'editado à mão (mantido)'
    if not vazio and _igual(cell.value, valor) and nota and nota[0] == fonte:
        return 'igual'
    cell.value = valor
    descricao = {'AUDITORIA': 'auditoria de consistência (GitHub)',
                 'CONTAGEM': 'METAR+SPECI de operador (Relatorio_METAR, REDEMET)',
                 'REDEMET': 'PROVISÓRIO — atrasos+ausências pela REDEMET',
                 'DECEA': 'OFICIAL — relatório do DECEA (atrasadas+ausentes, METAR+SPECI)'}[fonte]
    texto = (f'Preenchido pelo robô em {datetime.now(timezone.utc):%d/%m/%Y %H:%MZ}: {descricao}.\n'
             f'Se você alterar o valor, o robô não mexe mais nesta célula.\n'
             f'[robô fonte={fonte} valor={valor}]')
    cell.comment = Comment(texto, 'robô')
    cell.comment.width, cell.comment.height = 300, 110
    return 'escrito'


def linha_do_mes(ws, ano, mes_pt, criar=True):
    """Acha (ou cria) a linha do mês/ano na aba do aeródromo. Devolve o nº da linha."""
    ultima = None
    for row in ws.iter_rows(min_row=2):
        if row[0].value is not None:
            ultima = row[0].row
        try:
            ano_cel = int(row[1].value) if row[1].value is not None else None
        except (TypeError, ValueError):
            ano_cel = None
        if ano_cel == ano and str(row[2].value or '').strip().lower() == mes_pt:
            return row[0].row
    if not criar:
        return None
    n = (ultima + 1) if ultima else 2
    estacao = ws.cell(row=ultima, column=1).value if ultima else ws.title
    ws.cell(row=n, column=1, value=estacao)
    ws.cell(row=n, column=2, value=ano)
    ws.cell(row=n, column=3, value=mes_pt)
    ws.cell(row=n, column=COL_G, value=f'=(D{n}-E{n})/D{n}')
    ws.cell(row=n, column=COL_H, value=f'=(D{n}-F{n})/D{n}')
    # copia a formatação da linha de cima (cores, bordas, %)
    if ultima:
        for c in range(1, 9):
            de, para = ws.cell(row=ultima, column=c), ws.cell(row=n, column=c)
            if de.has_style:
                para._style = de._style
    return n


def aplicar(wb, valores, ano, mes, fonte, forcar=False):
    """valores = {'SBMT': {COL_D: 591, COL_F: 21}, ...}. Devolve relatório (lista de linhas)."""
    mes_pt = MESES_PT[mes - 1]
    rel = []
    for aero, cols in valores.items():
        if aero not in wb.sheetnames:
            rel.append(f'⚠️ {aero}: sem aba na planilha de Indicadores')
            continue
        ws = wb[aero]
        n = linha_do_mes(ws, ano, mes_pt)
        partes = []
        for col, v in cols.items():
            res = escrever(ws.cell(row=n, column=col), v, fonte, forcar)
            partes.append(f"{'DEF'[col - 4]}={v} ({res})")
        rel.append(f'{aero} linha {n}: ' + ', '.join(partes))
    return rel


# ----------------------------------------------------------------------------
def ler_resumo_auditoria(buf):
    ws = openpyxl.load_workbook(buf, data_only=True)['RESUMO']
    out = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0]:
            out[str(row[0]).upper()] = {COL_D: int(row[1] or 0), COL_F: int(row[2] or 0)}
    return out


def ler_quantidade(buf):
    ws = openpyxl.load_workbook(buf, data_only=True).worksheets[0]
    cab = [str(c.value or '').strip() for c in ws[1]]
    if 'Soma Operador' not in cab:
        return {}
    i = cab.index('Soma Operador')
    return {str(r[0]).upper(): {COL_D: int(r[i])} for r in ws.iter_rows(min_row=2, values_only=True)
            if r[0] and r[i] is not None}


def ler_resumo_atrasos(buf):
    ws = openpyxl.load_workbook(buf, data_only=True)['RESUMO']
    cab = [str(c.value or '') for c in ws[1]]
    try:
        i = next(k for k, t in enumerate(cab) if t.startswith('Total p/ indicador'))
    except StopIteration:
        return {}
    out = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] and re.fullmatch(r'S[BD][A-Z]{2}', str(row[0])) and row[i] is not None:
            out[str(row[0]).upper()] = {COL_E: int(row[i])}
    return out


def executar(ano, mes, pasta_cons, pasta_ind, forcar=False):
    from mensal_redemet import nome_atrasos, nome_quantidade
    nome_aud = f'AUDITORIA_{nome_consistencia(ano, mes)}'
    if not pasta_ind.achar(NOME_PLANILHA_INDICADORES):
        print(f'❌ Planilha de indicadores não encontrada: {NOME_PLANILHA_INDICADORES}')
        sys.exit(1)
    wb = openpyxl.load_workbook(pasta_ind.baixar(NOME_PLANILHA_INDICADORES))
    rel = []

    contagem = {}
    nome_q = nome_quantidade(ano, mes)
    if pasta_ind.achar(nome_q):
        contagem = ler_quantidade(pasta_ind.baixar(nome_q))
    if pasta_cons.achar(nome_aud):
        aud = ler_resumo_auditoria(pasta_cons.baixar(nome_aud))
        if contagem:   # D vem da contagem do operador; F da auditoria
            for aero, cols in aud.items():
                cols.pop(COL_D, None)
            rel += aplicar(wb, contagem, ano, mes, 'CONTAGEM', forcar)
        rel += aplicar(wb, aud, ano, mes, 'AUDITORIA', forcar)
    else:
        print(f'⚠️ {nome_aud} não encontrada — F não atualizado.')
        if contagem:
            rel += aplicar(wb, contagem, ano, mes, 'CONTAGEM', forcar)

    nome_atr = nome_atrasos(ano, mes)
    if pasta_ind.achar(nome_atr):
        rel += aplicar(wb, ler_resumo_atrasos(pasta_ind.baixar(nome_atr)), ano, mes, 'REDEMET', forcar)
    else:
        print(f'⚠️ {nome_atr} não encontrada — E (provisório) não atualizado.')

    saida = io.BytesIO()
    wb.save(saida)
    pasta_ind.enviar(NOME_PLANILHA_INDICADORES, saida)
    print('\n'.join(rel))
    print(f'✅ Indicadores de {MESES_PT[mes - 1]}/{ano} atualizados.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mes', help='AAAA-MM (padrão: mês anterior)')
    ap.add_argument('--forcar', action='store_true', help='sobrescreve mesmo valores editados à mão')
    argumentos_pastas(ap)
    args = ap.parse_args()
    ano, mes = ler_mes(args.mes)
    pasta_cons, pasta_ind = abrir_pastas(args)
    executar(ano, mes, pasta_cons, pasta_ind, args.forcar)


if __name__ == '__main__':
    main()
