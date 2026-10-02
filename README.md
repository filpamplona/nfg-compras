# NFG Compras

Aplicativo local (Streamlit) que importa o relatório CSV da **Nota Fiscal Gaúcha**, baixa cada NFC-e na consulta pública da SEFAZ-RS, guarda os itens em SQLite e mostra análises das suas compras: gasto por mês, por loja e por categoria, ranking de produtos e histórico de preços.

## Instalação

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
```

## Uso

```bash
streamlit run app.py
```

Fluxo:

1. Exporte o relatório de notas (CSV) no portal da Nota Fiscal Gaúcha.
2. Página **Importar**: envie o CSV.
3. Clique em **Baixar pendentes** para coletar as NFC-e (há uma pausa de 1,5 s entre notas).
4. Para NF-e (modelo 55), anexe o arquivo **XML** da nota na própria página.
5. Veja o resultado em **Início**, **Notas**, **Análises** e **Categorias**.

## Onde ficam os dados

Tudo fica na sua máquina, na pasta `data/` (banco `nfg.db` e `html_bruto/`). Para usar outra pasta, defina a variável de ambiente `NFG_DATA_DIR`. Nada é enviado a terceiros; o único acesso externo é a consulta pública da SEFAZ-RS.

## Limitações

- **NF-e (modelo 55) só entra com o XML**: a consulta pública não traz os itens.
- **A SEFAZ pode bloquear** (HTTP 403/429 ou captcha). Nesse caso o app **para** o lote e avisa; ele nunca tenta contornar o bloqueio. Tente de novo mais tarde.
- **O CPF não é armazenado**: é mascarado antes de qualquer HTML ser salvo.
- Análises consideram apenas notas de aquisição com situação Normal.

## Testes

```bash
pytest              # testes offline
NFG_CHAVE_ONLINE="<chave de uma NFC-e sua>" pytest -m online    # consulta real à SEFAZ-RS (usa a internet)
```

As chaves de acesso nos dados de teste (`tests/fixtures`) são fictícias, com dígito verificador válido mas sem nota correspondente na SEFAZ. Não publique chaves reais: a página de consulta da SEFAZ mostra o CPF do consumidor.
