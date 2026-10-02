"""
ROBÔ DIÁRIO — REDEMET -> planilha mensal de CONSISTÊNCIA no Google Drive.

Todo dia (agendador.yml) busca os METAR/SPECI dos últimos 4 dias dos 21
aeródromos e acrescenta o que faltar na planilha do mês ("SET2026
CONSISTÊNCIA.xlsx", uma aba por aeródromo). Repetidas são ignoradas.

Mudanças de out/2026:
  - a consulta à REDEMET agora lê TODAS as páginas da resposta (antes só a
    1ª página era lida e mensagens podiam se perder);
  - o código de Drive/planilha foi para o comum.py (compartilhado).
Lembrete: se algum dia ficar faltando, o FECHAMENTO MENSAL (mensal_redemet.py)
rebusca o mês inteiro, dia a dia, e completa a planilha.
"""
import argparse
import datetime
import os
import time

import pandas as pd

from comum import (AEROPORTOS, PastaDrive, PastaLocal, buscar_redemet,
                   chave_redemet, gravar_abas, juntar_e_limpar, ler_abas,
                   mensagens_para_planilha, nome_consistencia)

DIAS_PARA_TRAS = 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--local-consistencia', help='pasta local (Colab/teste) em vez do Drive')
    args = ap.parse_args()

    chave = chave_redemet()
    hoje = datetime.datetime.now(datetime.timezone.utc)
    ini = (hoje - datetime.timedelta(days=DIAS_PARA_TRAS)).strftime('%Y%m%d') + '00'
    fim = hoje.strftime('%Y%m%d') + '23'
    print('🚀 Iniciando Automação OPMET')
    print(f'📅 Período de busca REDEMET: {ini[:8]} até {fim[:8]}')

    if args.local_consistencia:
        pasta = PastaLocal(args.local_consistencia)
    else:
        pasta = PastaDrive(os.environ['DRIVE_FOLDER_ID']) if os.environ.get('DRIVE_FOLDER_ID') \
            else _pasta_por_nome('CONSISTENCIA')

    # 1) Baixa tudo da REDEMET
    novas_por_aero = {}
    for aero in AEROPORTOS:
        itens = buscar_redemet(aero, ini, fim, chave)
        if itens is None:
            print(f'❌ {aero}: REDEMET não respondeu após 3 tentativas.')
            continue
        linhas = mensagens_para_planilha(itens)
        if linhas:
            novas_por_aero[aero] = pd.DataFrame(linhas)
        time.sleep(0.05)

    # 2) Quais meses apareceram (na virada do mês, 2 meses)
    meses = {(hoje.year, hoje.month)}
    for df in novas_por_aero.values():
        d = pd.to_datetime(df['DATA_HORA_UTC'], errors='coerce').dropna()
        meses.update(zip(d.dt.year, d.dt.month))

    # 3) Para cada mês: baixa a planilha, junta, salva
    for (ano, mes) in sorted(meses):
        nome = nome_consistencia(ano, mes)
        existe = pasta.achar(nome)
        abas = ler_abas(pasta.baixar(nome)) if existe else {}
        print(f"{'✅ Planilha existente' if existe else 'ℹ️ Nova planilha'} '{nome}'")

        do_mes = {}
        for aero, df in novas_por_aero.items():
            d = pd.to_datetime(df['DATA_HORA_UTC'], errors='coerce')
            do_mes[aero] = df[(d.dt.year == ano) & (d.dt.month == mes)]
        novas = juntar_e_limpar(abas, do_mes)
        print(f"➕ '{nome}': {novas} mensagem(ns) nova(s).")

        if existe and novas == 0:
            print(f"⏭️ '{nome}' já estava em dia; nada a enviar.")
            continue
        if not abas:
            print(f"⏭️ Sem mensagens para '{nome}' ainda.")
            continue
        pasta.enviar(nome, gravar_abas(abas))


def _pasta_por_nome(nome_pasta):
    """Compatibilidade: sem DRIVE_FOLDER_ID, acha a pasta pelo nome (como antes)."""
    from comum import TENTATIVAS_DRIVE, drive_service
    svc = drive_service()
    q = f"name = '{nome_pasta}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    achadas = svc.files().list(q=q, fields='files(id,name)').execute(
        num_retries=TENTATIVAS_DRIVE).get('files', [])
    if not achadas:
        raise SystemExit(f"❌ Pasta '{nome_pasta}' não encontrada no Google Drive.")
    return PastaDrive(achadas[0]['id'], svc)


if __name__ == '__main__':
    main()
