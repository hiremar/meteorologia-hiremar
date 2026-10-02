#!/usr/bin/env python3
"""
FECHAMENTO MENSAL — parte REDEMET (roda no início de cada mês, antes da auditoria).

Rebusca o mês inteiro na REDEMET, DIA A DIA, para os 21 aeródromos, e com isso:

  1) COMPLETA a planilha "<MES><ANO> CONSISTÊNCIA.xlsx": se o robô diário
     perdeu algum dia (ex.: SBSP 9, 13 e 14/09/2026), as mensagens entram
     agora, antes da auditoria. Só acrescenta; nunca apaga nada.

  2) Gera "ATRASOS_METAR_SPECI_<AAAA>_<MM>_FINAL.xlsx" (pasta Indicadores MET),
     a mesma do Colab "Atrasos de METAR", agora com:
        - aba RESUMO por aeródromo (é dela que sai a coluna E PROVISÓRIA);
        - aba AUSENTES (METAR que faltou numa hora em que a estação SEMPRE emite);
        - abas por aeródromo com os atrasos e a aba "Todos COR".
     Critérios: METAR atrasado com >= 5 min, SPECI com >= 15 min, COR com > 10 min
     (COR não entra no indicador). SBSP: ignora 02:01Z–08:59Z (AUTOMETAR).

  3) Gera "SBSP_AUTOMETAR_<MES><ANO>.xlsx": a estatística À PARTE do
     período AUTOMETAR de Congonhas (03Z..08Z): previstos, recebidos,
     atrasados, ausentes e alertas de consistência. Serve para confrontar o
     relatório do DECEA, que conta essas horas contra a EMS-SP.

Uso:
    python mensal_redemet.py                 # mês anterior, Drive (GitHub Actions)
    python mensal_redemet.py --mes 2026-09
    python mensal_redemet.py --mes 2026-09 --local-consistencia PASTA --local-indicadores PASTA
    --forcar  -> regrava ATRASOS/SBSP mesmo que você tenha editado o arquivo à mão
"""
import argparse
import calendar
import io
import time
from datetime import datetime

import pandas as pd

from comum import (AEROPORTOS, MESES_ABREV, SBSP_HORAS_AUTO, abrir_pastas,
                   argumentos_pastas, buscar_redemet, chave_redemet, eh_auto,
                   gravar_abas, juntar_e_limpar, ler_abas, ler_mes,
                   mensagens_para_planilha, na_janela_auto_sbsp,
                   nome_consistencia, para_datahora)

LIMITE_METAR = 5.0     # minutos
LIMITE_SPECI = 15.0
LIMITE_COR = 10.0
# Uma hora cheia é "regular" (a estação sempre emite METAR nela) se apareceu
# em pelo menos 90% dos dias do mês. Só as horas regulares geram ausência.
FRACAO_HORA_REGULAR = 0.9


def nome_atrasos(ano, mes):
    return f'ATRASOS_METAR_SPECI_{ano}_{mes:02d}_FINAL.xlsx'


def nome_sbsp_auto(ano, mes):
    return f'SBSP_AUTOMETAR_{MESES_ABREV[mes - 1]}{ano}.xlsx'


# ----------------------------------------------------------------------------
# 1) BUSCA DO MÊS INTEIRO
# ----------------------------------------------------------------------------
def buscar_mes(ano, mes, buscar=buscar_redemet, chave=None):
    """Devolve ({aero: [itens]}, {aero: [dias que falharam]})."""
    ndias = calendar.monthrange(ano, mes)[1]
    hoje = datetime.utcnow()
    itens, falhas = {}, {}
    for aero in AEROPORTOS:
        print(f'>>> {aero}...', end=' ', flush=True)
        itens[aero], falhas[aero] = [], []
        for dia in range(1, ndias + 1):
            d = datetime(ano, mes, dia)
            if d > hoje:
                break
            s = d.strftime('%Y%m%d')
            r = buscar(aero, s + '00', s + '23', chave) if chave else buscar(aero, s + '00', s + '23')
            if r is None:
                falhas[aero].append(dia)
            else:
                itens[aero].extend(r)
            time.sleep(0.02)
        print(f'{len(itens[aero])} msgs' + (f' | ⚠️ dias sem resposta: {falhas[aero]}' if falhas[aero] else ''))
    return itens, falhas


def tabela(itens_aero, aero, ano, mes):
    """Itens crus da API -> DataFrame limpo, só do mês, com tipo/COR/AUTO/atraso."""
    linhas = []
    for it in itens_aero:
        msg = (it.get('mens') or '').strip()
        if not msg or 'não localizada' in msg.lower():
            continue
        if not (msg.startswith('METAR') or msg.startswith('SPECI')):
            continue
        dt = para_datahora(it.get('validade_inicial'))
        rec = para_datahora(it.get('recebimento'))
        if dt is None or dt.year != ano or dt.month != mes:
            continue
        linhas.append({
            'AEROPORTO': aero,
            'TIPO': 'METAR' if msg.startswith('METAR') else 'SPECI',
            'COR': ' COR ' in f' {msg} ',
            'AUTO': eh_auto(msg),
            'DT_MSG': dt,
            'RECEBIMENTO': rec,
            'ATRASO_MIN': round((rec - dt).total_seconds() / 60, 1) if rec else None,
            'MENSAGEM': msg,
        })
    df = pd.DataFrame(linhas)
    if not df.empty:
        df = df.drop_duplicates(subset=['DT_MSG', 'MENSAGEM']).sort_values('DT_MSG').reset_index(drop=True)
    return df


# ----------------------------------------------------------------------------
# 2) ATRASOS E AUSÊNCIAS (operador)
# ----------------------------------------------------------------------------
def atrasos_e_ausencias(df, aero, dias_falhos):
    """Devolve (df_atrasos_reais, df_cor, df_ausentes) para um aeródromo."""
    vazio = pd.DataFrame()
    if df.empty:
        return vazio, vazio, vazio
    op = df[~df['AUTO']].copy()
    if aero == 'SBSP':
        op = op[~op['DT_MSG'].apply(na_janela_auto_sbsp)]

    # ATRASOS: por horário nominal, vale o 1º recebimento da versão original (não COR)
    orig = op[~op['COR'] & op['RECEBIMENTO'].notna()]
    orig = orig.sort_values('RECEBIMENTO').drop_duplicates(subset=['TIPO', 'DT_MSG'], keep='first')
    lim = orig['TIPO'].map({'METAR': LIMITE_METAR, 'SPECI': LIMITE_SPECI})
    atrasos = orig[orig['ATRASO_MIN'] >= lim].copy()
    atrasos['STATUS'] = 'ATRASO REAL'

    cor = op[op['COR'] & op['RECEBIMENTO'].notna()].copy()
    cor['STATUS'] = cor['ATRASO_MIN'].apply(lambda m: 'COR ATRASADA' if m > LIMITE_COR else 'COR PONTUAL')

    # AUSÊNCIAS: descobre o "horário de funcionamento" da estação pelo próprio
    # mês — uma hora cheia é REGULAR se teve METAR de operador em pelo menos
    # 90% dos dias (ex.: SDAM 12-14Z e 17-21Z; o intervalo 15-16Z não é regular).
    # Dia regular sem o METAR dessa hora = ausente (provisório).
    metar_h = op[(op['TIPO'] == 'METAR') & (op['DT_MSG'].dt.minute == 0)]
    tem = set(metar_h['DT_MSG'])
    dias_validos = sorted({d.day for d in df['DT_MSG']} - set(dias_falhos))
    ausentes = []
    if dias_validos:
        ano, mes = df['DT_MSG'].iloc[0].year, df['DT_MSG'].iloc[0].month
        cont = metar_h[metar_h['DT_MSG'].dt.day.isin(dias_validos)]['DT_MSG'].dt.hour.value_counts()
        regulares = sorted(h for h, n in cont.items() if n >= FRACAO_HORA_REGULAR * len(dias_validos))
        agora = datetime.utcnow()
        for dia in dias_validos:
            for h in regulares:
                alvo = datetime(ano, mes, dia, h)
                if alvo in tem or alvo > agora:
                    continue
                if aero == 'SBSP' and na_janela_auto_sbsp(alvo):
                    continue
                ausentes.append({'AEROPORTO': aero, 'TIPO': 'METAR',
                                 'HORA_PREVISTA_Z': alvo.strftime('%d/%m/%Y %H:%MZ'),
                                 'HORAS_REGULARES_DA_ESTACAO': ','.join(f'{x:02d}' for x in regulares)})
    return atrasos, cor, pd.DataFrame(ausentes)


def _formatar_lista(df):
    if df.empty:
        return pd.DataFrame(columns=['AEROPORTO', 'TIPO', 'STATUS', 'HORA_MSG_Z',
                                     'RECEBIMENTO_API', 'ATRASO_MIN', 'MENSAGEM'])
    return pd.DataFrame({
        'AEROPORTO': df['AEROPORTO'],
        'TIPO': df['TIPO'],
        'STATUS': df['STATUS'],
        'HORA_MSG_Z': df['DT_MSG'].dt.strftime('%d%H%MZ'),
        'RECEBIMENTO_API': df['RECEBIMENTO'].dt.strftime('%Y-%m-%d %H:%M:%S'),
        'ATRASO_MIN': df['ATRASO_MIN'],
        'MENSAGEM': df['MENSAGEM'],
    })


def gerar_planilha_atrasos(tabelas, falhas):
    resumo, por_aero, cors, auss = [], {}, [], []
    for aero in AEROPORTOS:
        df = tabelas.get(aero, pd.DataFrame())
        atr, cor, aus = atrasos_e_ausencias(df, aero, set(falhas.get(aero, [])))
        n_metar = int((atr['TIPO'] == 'METAR').sum()) if not atr.empty else 0
        n_speci = int((atr['TIPO'] == 'SPECI').sum()) if not atr.empty else 0
        resumo.append({
            'Aeródromo': aero,
            'METAR atrasados': n_metar,
            'SPECI atrasados': n_speci,
            'METAR ausentes (provisório)': len(aus),
            'Total p/ indicador (coluna E)': n_metar + n_speci + len(aus),
            'COR atrasadas (>10 min, fora do indicador)':
                int((cor['STATUS'] == 'COR ATRASADA').sum()) if not cor.empty else 0,
            'Dias sem resposta da REDEMET': ', '.join(map(str, falhas.get(aero, []))),
        })
        por_aero[aero] = _formatar_lista(atr)
        if not cor.empty:
            cors.append(_formatar_lista(cor))
        if not aus.empty:
            auss.append(aus)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
        df_res = pd.DataFrame(resumo)
        df_res.to_excel(w, sheet_name='RESUMO', index=False)
        w.sheets['RESUMO'].set_column('A:A', 12)
        w.sheets['RESUMO'].set_column('B:G', 22)
        nota = ('PROVISÓRIO (REDEMET). O oficial é o relatório do DECEA (banco OPMET), '
                'que substitui a coluna E quando o PDF chega. SBSP: 02:01Z–08:59Z excluído (AUTOMETAR).')
        w.sheets['RESUMO'].write(len(resumo) + 2, 0, nota)
        aus_df = pd.concat(auss, ignore_index=True) if auss else pd.DataFrame(
            columns=['AEROPORTO', 'TIPO', 'HORA_PREVISTA_Z', 'HORAS_REGULARES_DA_ESTACAO'])
        aus_df.to_excel(w, sheet_name='AUSENTES', index=False)
        w.sheets['AUSENTES'].set_column('A:E', 18)
        for aero in sorted(por_aero):
            por_aero[aero].to_excel(w, sheet_name=aero, index=False)
            w.sheets[aero].set_column('A:F', 16)
            w.sheets[aero].set_column('G:G', 110)
        cor_df = pd.concat(cors, ignore_index=True).sort_values('ATRASO_MIN', ascending=False) \
            if cors else _formatar_lista(pd.DataFrame())
        cor_df.to_excel(w, sheet_name='Todos COR', index=False)
        w.sheets['Todos COR'].set_column('G:G', 110)
    buf.seek(0)
    return buf, pd.DataFrame(resumo)


# ----------------------------------------------------------------------------
# 3) SBSP — PERÍODO AUTOMETAR (relatório à parte)
# ----------------------------------------------------------------------------
def relatorio_sbsp_auto(df, ano, mes, dias_falhos):
    from auditoria_metar import auditoria_detalhada
    ndias = calendar.monthrange(ano, mes)[1]
    detalhe = []
    metars = df[(df['TIPO'] == 'METAR')] if not df.empty else df
    for dia in range(1, ndias + 1):
        if dia in dias_falhos:
            continue
        for h in SBSP_HORAS_AUTO:
            alvo = datetime(ano, mes, dia, h, 0)
            if alvo > datetime.utcnow():
                continue
            cand = metars[metars['DT_MSG'] == alvo] if not metars.empty else metars
            if cand is None or cand.empty:
                detalhe.append({'Horário previsto (Z)': alvo.strftime('%d/%m/%Y %H:%M'),
                                'Estado': 'AUSENTE', 'Recebido em': '', 'Atraso (min)': None,
                                'Emitido por': '', 'Mensagem': ''})
                continue
            prim = cand.sort_values('RECEBIMENTO').iloc[0]
            atraso = prim['ATRASO_MIN']
            estado = 'ATRASADO' if (atraso is not None and atraso >= LIMITE_METAR) else 'NO HORÁRIO'
            detalhe.append({'Horário previsto (Z)': alvo.strftime('%d/%m/%Y %H:%M'),
                            'Estado': estado,
                            'Recebido em': prim['RECEBIMENTO'].strftime('%d/%m/%Y %H:%M') if prim['RECEBIMENTO'] is not None else '',
                            'Atraso (min)': atraso,
                            'Emitido por': 'AUTOMETAR' if prim['AUTO'] else 'OPERADOR',
                            'Mensagem': prim['MENSAGEM']})
    det = pd.DataFrame(detalhe)

    # Consistência das mensagens AUTO da janela (mesmas regras do auditor humano)
    if not df.empty:
        auto = df[df['AUTO'] & df['DT_MSG'].apply(na_janela_auto_sbsp)]
    else:
        auto = df
    alertas = pd.DataFrame()
    if auto is not None and not auto.empty:
        entrada = pd.DataFrame({'DATA_HORA_UTC': auto['DT_MSG'], 'MENSAGEM': auto['MENSAGEM']})
        alertas = pd.DataFrame(auditoria_detalhada(entrada, 'SBSP'))
    n_speci_auto = int(((auto['TIPO'] == 'SPECI')).sum()) if auto is not None and not auto.empty else 0

    prev = len(det)
    cont = det['Estado'].value_counts() if prev else pd.Series(dtype=int)
    atras, ausen = int(cont.get('ATRASADO', 0)), int(cont.get('AUSENTE', 0))
    resumo = pd.DataFrame([
        ['Período', f'{MESES_ABREV[mes - 1]}/{ano} — horas cheias 03Z a 08Z (janela 02:01Z–08:59Z)'],
        ['METAR previstos', prev],
        ['Recebidos', prev - ausen],
        ['No horário', int(cont.get('NO HORÁRIO', 0))],
        ['Atrasados (>= 5 min)', atras],
        ['Ausentes', ausen],
        ['Eficiência (%)', round(100 * (prev - atras - ausen) / prev, 2) if prev else None],
        ['SPECI AUTO na janela', n_speci_auto],
        ['Mensagens AUTO auditadas', 0 if auto is None else len(auto)],
        ['Alertas de consistência (AUTO)', len(alertas)],
        ['Dias sem resposta da REDEMET', ', '.join(map(str, sorted(dias_falhos)))],
        ['Observação', 'Fora da jurisdição do operador da EMS-SP. NÃO entra no indicador. '
                       'Compare com as linhas 03Z–08Z de SBSP no PDF do DECEA '
                       '(arquivo DECEA_..._ATRASOS_AUSENCIAS.xlsx, aba SBSP_AUTOMETAR).'],
    ], columns=['Item', 'Valor'])

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='xlsxwriter') as w:
        resumo.to_excel(w, sheet_name='RESUMO', index=False)
        w.sheets['RESUMO'].set_column('A:A', 34)
        w.sheets['RESUMO'].set_column('B:B', 90)
        det.to_excel(w, sheet_name='HORARIOS', index=False)
        w.sheets['HORARIOS'].set_column('A:E', 18)
        w.sheets['HORARIOS'].set_column('F:F', 110)
        nao_ok = det[det['Estado'] != 'NO HORÁRIO'] if prev else det
        nao_ok.to_excel(w, sheet_name='ATRASOS_AUSENCIAS', index=False)
        w.sheets['ATRASOS_AUSENCIAS'].set_column('A:E', 18)
        w.sheets['ATRASOS_AUSENCIAS'].set_column('F:F', 110)
        (alertas if not alertas.empty else pd.DataFrame(
            columns=['Data/Hora UTC', 'Mensagem Original', 'Falha Detectada', 'Campo'])
         ).to_excel(w, sheet_name='CONSISTENCIA_AUTO', index=False)
        w.sheets['CONSISTENCIA_AUTO'].set_column('B:C', 65)
    buf.seek(0)
    return buf, resumo


# ----------------------------------------------------------------------------
def gravar_protegido(pasta, nome, buf, forcar):
    if pasta.achar(nome) and pasta.editado_pelo_usuario(nome) and not forcar:
        print(f'✋ {nome} foi editado por você depois do robô — mantido (use --forcar para regravar).')
        return False
    pasta.enviar(nome, buf)
    return True


def executar(ano, mes, pasta_cons, pasta_ind, forcar=False, buscar=buscar_redemet):
    print(f'🗓️  Fechamento REDEMET de {MESES_ABREV[mes - 1]}/{ano}')
    chave = None if buscar is not buscar_redemet else chave_redemet()
    itens, falhas = buscar_mes(ano, mes, buscar, chave)

    # 1) Completar a CONSISTÊNCIA
    nome = nome_consistencia(ano, mes)
    abas = ler_abas(pasta_cons.baixar(nome)) if pasta_cons.achar(nome) else {}
    novas = {}
    for aero, lista in itens.items():
        linhas = mensagens_para_planilha(lista)
        if linhas:
            df = pd.DataFrame(linhas)
            d = pd.to_datetime(df['DATA_HORA_UTC'], errors='coerce')
            novas[aero] = df[(d.dt.year == ano) & (d.dt.month == mes)]
    acrescentadas = juntar_e_limpar(abas, novas)
    if acrescentadas > 0:
        print(f'🧩 {nome}: {acrescentadas} mensagem(ns) que faltavam foram acrescentadas.')
        pasta_cons.enviar(nome, gravar_abas(abas))
    else:
        print(f'✅ {nome} já estava completa.')

    # 2) Atrasos/ausências
    tabelas = {a: tabela(itens[a], a, ano, mes) for a in AEROPORTOS}
    buf, resumo = gerar_planilha_atrasos(tabelas, falhas)
    gravar_protegido(pasta_ind, nome_atrasos(ano, mes), buf, forcar)
    print(resumo[['Aeródromo', 'METAR atrasados', 'SPECI atrasados',
                  'METAR ausentes (provisório)', 'Total p/ indicador (coluna E)']].to_string(index=False))

    # 3) SBSP AUTOMETAR
    buf_sp, res_sp = relatorio_sbsp_auto(tabelas['SBSP'], ano, mes, set(falhas.get('SBSP', [])))
    gravar_protegido(pasta_ind, nome_sbsp_auto(ano, mes), buf_sp, forcar)
    print('\n📊 SBSP AUTOMETAR:')
    print(res_sp.head(7).to_string(index=False))
    return resumo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mes', help='AAAA-MM (padrão: mês anterior)')
    ap.add_argument('--forcar', action='store_true')
    argumentos_pastas(ap)
    args = ap.parse_args()
    ano, mes = ler_mes(args.mes)
    pasta_cons, pasta_ind = abrir_pastas(args)
    executar(ano, mes, pasta_cons, pasta_ind, args.forcar)


if __name__ == '__main__':
    main()
