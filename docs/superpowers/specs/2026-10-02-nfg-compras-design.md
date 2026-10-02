# NFG Compras — Design

**Data:** 2026-10-02 · **Status:** aprovado em brainstorming, aguardando revisão do spec escrito

## 1. Objetivo

Sistema local em Python, com interface Streamlit, para **analisar compras mensais no nível de produto**.
O usuário envia o relatório CSV exportado do site Nota Fiscal Gaúcha (NFG). O sistema consulta cada nota
na SEFAZ-RS pela chave de acesso, extrai cabeçalho, itens, totais e pagamentos, grava tudo num SQLite local
e oferece análises (mês a mês, por loja, por categoria, ranking, histórico de preço) com exportação.

**Critério de sucesso:** importar o CSV de exemplo (11 notas), baixar automaticamente as 10 NFC-e, ver os 18
itens da nota Zaffari de 26/09/2026 com valores idênticos ao DANFE impresso, e ver o gasto de setembro/2026
por loja e por categoria.

## 2. Fatos verificados (investigação de 2026-10-02)

- **CSV do NFG:** UTF-8, separador vírgula, todos os campos entre aspas, 11 colunas:
  `"", Munic., Razão Social, Emissão (dd/mm/aa), Número, TipoDoc., Chave de Acesso, Valor (R$1.234,56), Data Registro, Tipo Operação, Situação Docto`.
  A chave vem com **um espaço no meio** (`4326…54765 1210…`) — remover espaços → 44 dígitos.
  `TipoDoc.` ∈ {`Nota Fiscal de Consumidor Eletrônica`, `Nota Fiscal Eletrônica`}.
- **Consulta pública de NFC-e (sem login, sem captcha):**
  1. `GET https://www.sefaz.rs.gov.br/ASP/AAE_ROOT/NFE/SAT-WEB-NFE-NFC_1.asp?chaveNFe=<chave>` (formulário; estabelece cookies)
  2. `POST https://www.sefaz.rs.gov.br/ASP/AAE_ROOT/NFE/SAT-WEB-NFE-NFC_2.asp` com form `HML=false` (produção; `true` = homologação), `chaveNFe=<chave>` e `Action=Avançar` (iso-8859-1) → HTML completo da NFC-e.
  Página codificada em `iso-8859-1`.
- **Rotas descartadas:** `dfe-portal.svrs.rs.gov.br/Nfce/Consulta` exige login gov.br; `/Dfe/QrCodeNFce?p=` exige hash CSC (inexistente no CSV).
- **Estrutura do HTML (XSLT 1.10):**
  - Emitente: 1º `td.NFCCabecalho_SubTitulo` dentro de `table.NFCCabecalho` = razão social; `td.NFCCabecalho_SubTitulo1` seguinte contém `CNPJ: xx.xxx.xxx/xxxx-xx  Inscrição Estadual: nnn`; o próximo `td.NFCCabecalho_SubTitulo1` = endereço (partes separadas por vírgula e quebras de linha).
  - Texto `NFC-e nº: N Série: S Data de Emissão: dd/mm/aaaa hh:mm:ss`; `Protocolo de Autorização: N`.
  - Itens: `tr` com `id` começando em `Item + ` → 6 `td.NFCDetalhe_Item`: código, descrição, qtde, un, vl unit, vl total (decimais com vírgula).
  - Totais: linhas com `Valor total R$` (bruto), `Valor descontos R$`; `valor_total` armazenado = valor pago (total − descontos, ou `Valor a pagar R$` se existir); após `FORMA PAGAMENTO`, cada linha = (forma, valor).
  - Contém CPF do consumidor — **não armazenar**.
- **NF-e (modelo 55):** itens não disponíveis publicamente só com a chave. Detalhe vem do **XML** anexado pelo usuário.
- Fixture real anonimizada: `tests/fixtures/nfce_zaffari.html`. CSV de exemplo: `tests/fixtures/relatorio_nfg.csv`.

## 3. Arquitetura

Núcleo `nfg/` sem dependência de Streamlit; páginas finas que chamam o núcleo.

```
nfg-compras/
├── app.py                    # Início: resumo do mês
├── pages/
│   ├── 1_Importar.py
│   ├── 2_Notas.py
│   ├── 3_Análises.py
│   └── 4_Categorias.py
├── nfg/
│   ├── models.py             # dataclasses NotaResumo, Nota, Item, Pagamento, Estabelecimento
│   ├── util.py               # parse de dinheiro/decimal BR, chave (normalizar, validar DV, modelo), normalizar texto
│   ├── csv_import.py         # CSV NFG → list[NotaResumo]
│   ├── sefaz_client.py       # HTTP etapa 1 + etapa 2 → HTML (str)
│   ├── nfce_parser.py        # HTML → Nota
│   ├── nfe_xml_parser.py     # XML NF-e → Nota
│   ├── db.py                 # conexão, schema, repositório
│   ├── coleta.py             # orquestração do lote com callback de progresso
│   ├── categorias.py         # regras + overrides; seed de categorias
│   └── analises.py           # consultas → pandas.DataFrame
├── tests/ (+ fixtures/)
└── data/                     # nfg.db, html_bruto/<chave>.html  (gitignored)
```

**Stack:** Python 3.11, streamlit, requests, beautifulsoup4, lxml, pandas, plotly, openpyxl; dev: pytest, responses.

## 4. Modelo de dados (SQLite)

Valores monetários totais em **centavos (INTEGER)**; no Python, `Decimal`. Quantidade e valor unitário como `TEXT` decimal exato (ex. `"0.9399"`, `"21.8"`) convertidos para `Decimal`.

```sql
CREATE TABLE estabelecimentos (
  cnpj TEXT PRIMARY KEY,            -- só dígitos
  razao_social TEXT, nome_csv TEXT,
  inscricao_estadual TEXT, endereco TEXT, municipio TEXT
);
CREATE TABLE notas (
  chave TEXT PRIMARY KEY,           -- 44 dígitos
  modelo INTEGER NOT NULL,          -- 65 NFC-e, 55 NF-e (chave[20:22])
  cnpj_emitente TEXT REFERENCES estabelecimentos(cnpj),  -- da chave (chave[6:20]) já na importação
  numero TEXT, serie TEXT,
  emissao TEXT NOT NULL,            -- ISO 8601; do CSV (data) e depois da nota (data+hora)
  valor_total_centavos INTEGER NOT NULL,
  valor_descontos_centavos INTEGER DEFAULT 0,
  protocolo TEXT,
  situacao_csv TEXT, tipo_operacao TEXT,
  status TEXT NOT NULL,             -- pendente | coletada | erro | sem_itens
  erro_msg TEXT, aviso TEXT,        -- aviso: ex. soma dos itens ≠ total
  tentativas INTEGER NOT NULL DEFAULT 0,
  importada_em TEXT, coletada_em TEXT
);
CREATE TABLE itens (
  id INTEGER PRIMARY KEY,
  chave TEXT NOT NULL REFERENCES notas(chave) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  codigo TEXT, descricao TEXT NOT NULL,
  quantidade TEXT NOT NULL, unidade TEXT,
  valor_unitario TEXT NOT NULL,     -- decimal exato em texto (ex. "21.8"; NF-e pode ter até 10 casas)
  valor_total_centavos INTEGER NOT NULL,
  UNIQUE (chave, seq)
);
CREATE TABLE pagamentos (
  id INTEGER PRIMARY KEY,
  chave TEXT NOT NULL REFERENCES notas(chave) ON DELETE CASCADE,
  forma TEXT NOT NULL, valor_centavos INTEGER NOT NULL
);
CREATE TABLE categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE NOT NULL);
CREATE TABLE regras_categoria (
  id INTEGER PRIMARY KEY, padrao TEXT NOT NULL,   -- regex, case-insensitive, aplicada à descrição normalizada
  categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
  prioridade INTEGER NOT NULL DEFAULT 100          -- menor = avaliada primeiro
);
CREATE TABLE categoria_manual (
  cnpj TEXT NOT NULL, codigo TEXT NOT NULL,
  categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
  PRIMARY KEY (cnpj, codigo)
);
```

Regras:
- Importação de CSV é **idempotente** (upsert por chave; nota já `coletada` não é rebaixada).
- Gravação de nota coletada = transação única: atualiza `notas`, upsert `estabelecimentos`, substitui `itens` e `pagamentos` da chave.
- **CPF nunca é persistido** (nem no HTML bruto: o HTML salvo tem o CPF mascarado por regex antes de gravar em disco).
- Categoria de um item é **calculada**, não armazenada: `categoria_manual(cnpj, codigo)` → primeira regra (ordem prioridade, id) que casar com a descrição normalizada → `"Sem categoria"`.
- Validação pós-parse: se `Σ itens − descontos ≠ total` (tolerância 1 centavo), grava `aviso`.
- `PRAGMA foreign_keys = ON` em toda conexão.

## 5. Fluxo de coleta

1. **Importar CSV** (`csv_import.ler(bytes) → list[NotaResumo]`): tenta UTF-8-sig, cai para latin-1; normaliza chave; valida 44 dígitos + DV módulo 11; linhas inválidas são reportadas, não abortam. `db.importar_resumos()` retorna contagem `{novas, existentes, invalidas, nfe}`. Status inicial: `pendente` (modelo 65) ou `sem_itens` (modelo 55).
2. **Baixar pendentes** (`coleta.coletar(repo, cliente, on_progress, pausa=1.5)`): para cada nota `pendente` ou `erro` com `tentativas < 3` e erro não-definitivo:
   - `cliente.buscar(chave) → str` (Session; GET etapa 1, POST etapa 2 com `HML=false`; timeout 20 s; 2 retentativas em erro de rede/5xx com backoff 2 s, 5 s);
   - mascara CPF, salva `data/html_bruto/<chave>.html`;
   - `nfce_parser.parse(html) → Nota`; grava; status `coletada`;
   - dorme `pausa` segundos; chama `on_progress(i, total, nota_ou_erro)`.
3. **Anexar XML NF-e** (`nfe_xml_parser.parse(bytes) → Nota`): namespace `http://www.portalfiscal.inf.br/nfe`; `infNFe/@Id` (sem `NFe`) = chave; `emit`, `ide/dhEmi`, `det/prod` (`cProd, xProd, qCom, uCom, vUnCom, vProd`), `total/ICMSTot/vNF`, `vDesc`, `pag/detPag` (`tPag` → nome da forma, `vPag`). Cria ou completa a nota → `coletada`.
4. **Reprocessar HTMLs salvos:** re-parseia todos os arquivos de `html_bruto/` sem rede.

**Erros:**

| Situação | Detecção | Resultado |
|---|---|---|
| Rede / timeout / 5xx | exceção `requests` | `ErroRede`; retenta 2×; depois `erro` (retentável, `tentativas += 1`) |
| Rejeição SEFAZ (nota inexistente etc.) | sem `table.NFCCabecalho`, texto de mensagem presente | `NotaNaoEncontrada`; `erro` definitivo (`tentativas = 3`) |
| Layout desconhecido | estrutura esperada ausente | `LayoutDesconhecido`; `erro` retentável após reprocessamento |
| Bloqueio / captcha | HTTP 403/429 ou `captcha` no HTML | `BloqueioSefaz`; **interrompe o lote** e avisa; nunca contorna |
| Soma ≠ total | validação | grava normalmente + `aviso` |

Uma nota com erro nunca derruba o lote (exceto `BloqueioSefaz`).

## 6. Interface (Streamlit)

- **Início:** seletor de mês (padrão: mais recente com dados); métricas: total do mês, Δ% vs mês anterior, nº de compras, ticket médio, nº de notas pendentes/erro; barras dos últimos 12 meses.
- **Importar:** upload CSV → prévia + botão Importar → resumo de contagens; upload múltiplo de XML NF-e; botão "Baixar notas pendentes (N)" com `st.progress` + log; botão "Reprocessar HTMLs salvos".
- **Notas:** tabela filtrável (mês, loja, status) com ícones ✓ ⏳ ⚠ 📎; seleção mostra cabeçalho, itens com categoria, pagamentos, erro/aviso e botão "Tentar novamente".
- **Análises** (filtro de período global): abas Mensal (barras empilhadas por categoria + tabela), Por loja (gasto, visitas, ticket médio), Por categoria (rosca + linhas mensais), Ranking (top N por valor e por frequência), Histórico de preço (busca por texto na descrição normalizada; preço unitário × data, uma série por loja). Cada aba: "Baixar CSV" e "Baixar Excel". Exportação completa notas+itens+categoria em `.xlsx`.
- **Categorias:** CRUD de categorias e regras com contagem ao vivo de itens casados; lista "Sem categoria" ordenada por valor com `st.data_editor` para atribuição manual em lote. Seed: Hortifruti, Padaria, Carnes, Laticínios/Frios, Mercearia, Bebidas, Doces/Snacks, Limpeza, Higiene, Outros, com regras iniciais.

Análises consideram apenas notas com `tipo_operacao = 'Aquisição'` e `situacao_csv = 'Normal'` (quando presentes). Totais mensais usam `valor_total` da nota (inclui NF-e sem itens); análises por produto/categoria usam itens.

**Fora do escopo v1:** orçamento/metas, alertas, multiusuário, login, nuvem, leitura de QR Code, IA para categorias.

## 7. Testes

TDD com pytest em todo o núcleo.

- `util`: dinheiro BR, decimal BR, chave (normalização, DV, modelo, CNPJ), normalização de texto.
- `csv_import`: fixture real; encodings; chave inválida; NF-e.
- `nfce_parser`: fixture real → 18 itens, valores exatos, emitente, nº/série/emissão/protocolo, total 382,47, desconto 0, pagamento Cartão de Crédito 382,47; HTML de rejeição → `NotaNaoEncontrada`; HTML aleatório → `LayoutDesconhecido`.
- `nfe_xml_parser`: XML sintético.
- `sefaz_client`: `responses` — sequência GET→POST, campos do form, decodificação iso-8859-1, retry, 403/429 → `BloqueioSefaz`.
- `db`: SQLite em memória — idempotência, transação, cascade, centavos.
- `coleta`: cliente falso — sucesso, layout, rede, bloqueio interrompe; callback.
- `categorias`: precedência manual > regra (prioridade) > Sem categoria.
- `analises`: dados conhecidos → DataFrames esperados.
- UI: smoke test `streamlit.testing.v1.AppTest` por página.
- `pytest -m online` (fora da suíte padrão): consulta real da chave Zaffari e parse.
