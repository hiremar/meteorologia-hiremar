# Robôs da Subdivisão de Meteorologia (CRCEA-SE)

Tudo roda no GitHub Actions e grava no Google Drive (pasta `FAB/Indicadores MET`).

| Robô (aba Actions) | Quando | O que faz |
|---|---|---|
| **Automacao METAR REDEMET** (`agendador.yml` → `script_opmet.py`) | todo dia ~03:23 BRT | Busca os METAR/SPECI dos últimos 4 dias e acrescenta na `<MES><ANO> CONSISTÊNCIA.xlsx` |
| **Fechamento mensal** (`auditoria-mensal.yml`) | dias 1 a 5, às 06:37 e 12:47 BRT | 1) `mensal_redemet.py`: rebusca o mês inteiro, completa a CONSISTÊNCIA, gera `ATRASOS_METAR_SPECI_AAAA_MM_FINAL.xlsx` e `SBSP_AUTOMETAR_<MES><ANO>.xlsx` · 2) `auditoria_metar.py`: gera a `AUDITORIA_...` · 3) `atualizar_indicadores_drive.py`: preenche D, E (provisório) e F · 4) lê o PDF do DECEA, se já chegou · 5) `gerar_dashboard.py`: gera `IndicadorMET_<MES><ANO>.html` |
| **Relatório DECEA** (`decea-relatorio.yml` → `decea_relatorio.py`) | todo dia ~08:13 BRT (ou à mão) | Se houver PDF novo com "CRCEA" no nome, grava na coluna E o total OFICIAL (atrasadas + ausentes, METAR + SPECI; em SBSP, sem 02:01Z–08:59Z), gera `DECEA_<MES><ANO>_ATRASOS_AUSENCIAS.xlsx` e refaz o HTML |

## Regras de proteção (para não estragar seus ajustes)
- O robô deixa uma **nota** em cada célula da planilha de Indicadores que ele preenche.
- Se você mudar o valor, ele não mexe mais na célula.
- O valor do DECEA (nota "OFICIAL") nunca é trocado pelo da REDEMET.
- Se você editar a `AUDITORIA_...`, a `ATRASOS_...` ou a `SBSP_AUTOMETAR_...` no Drive, elas não são regeradas.
- Para passar por cima de tudo isso: Actions → robô → **Run workflow** → marque **forcar**.

## Plano B
`colab/Robo_Meteorologia_PlanoB.ipynb` roda os mesmos scripts no Colab, com o Drive montado.
