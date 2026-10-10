# Como testar e publicar as melhorias (sem arriscar o site que está no ar)

## 1. Subir numa branch de teste (5 min)
1. Abra github.com/hiremar/meteorologia-hiremar.
2. Clique em **Add file → Upload files**.
3. Descompacte o zip e arraste para a página **todo o conteúdo** dele:
   `app.py`, `requirements.txt`, `COMO_PUBLICAR.md` e as pastas `modulos`,
   `simuladores` e `.streamlit`.
   (A pasta `.streamlit` começa com ponto; se o Windows escondê-la, ative
   "Itens ocultos" no Explorador de Arquivos.)
4. Lá embaixo, marque **"Create a new branch for this commit"**, dê o nome
   `melhorias` e clique em **Propose changes**. Não precisa abrir o Pull Request agora.
   O site oficial continua intacto, porque ele lê a branch `main`.

## 2. Criar um site de teste a partir dessa branch
1. Entre em share.streamlit.io → **Create app** → "Deploy a public app from GitHub".
2. Repositório `hiremar/meteorologia-hiremar`, branch **melhorias**, arquivo `app.py`.
3. Em **Advanced settings → Secrets**, cole a mesma linha do site oficial:
   `REDEMET_KEY = "sua-chave"`
4. **Deploy**. A primeira instalação demora alguns minutos (tem bibliotecas novas).

## 3. Conferir
- Aeródromos das capitais com VFR/MVFR/IFR/LIFR; passe o mouse para ver METAR e TAF.
- Na barra lateral, marque "Modelo GFS" e troque nível e validade.
- Troque o mapa de fundo pelo botão de camadas (canto superior direito).
- Escolha origem e destino e clique em **Planejar voo**.
- Se algo falhar, o site mostra um aviso amarelo dizendo o quê. Copie o texto e me mande.

## 4. Publicar de verdade
Quando estiver tudo certo: no GitHub, **Pull requests → New pull request**,
base `main` ← compare `melhorias` → **Create** → **Merge**. O site oficial
se atualiza sozinho. Depois pode apagar o app de teste no share.streamlit.io.

## Depois de aprovar um Pull Request: faça o Reboot
O Streamlit relê o `app.py` sozinho, mas às vezes continua com a versão ANTIGA dos
arquivos da pasta `modulos/` na memória. Resultado: parte do site nova, parte velha
(aconteceu em 10/10/2026: o campo Aeronave apareceu, mas o PDF saiu sem o TOC/TOD).
Sempre que a mudança mexer em `modulos/`:
1. No site, clique em **Manage app** (canto inferior direito).
2. **⋮ → Reboot app** e espere ~1 minuto.
