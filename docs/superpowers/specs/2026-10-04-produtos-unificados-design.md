# Produtos Unificados — Design

**Data:** 2026-10-04 · **Status:** aprovado em brainstorming, aguardando revisão do spec escrito

## 1. Objetivo

Nova seção **Produtos** que agrupa as descrições que cada estabelecimento dá a um mesmo produto num
**produto unificado**, preservando os nomes originais, para decidir numa compra futura em qual loja o
produto está mais barato.

**Critério de sucesso:**
- `QJO MUSSARELA S.CLARA FAT 1KG`, `QJO MUSSARELA TIROLEZ FAT 1KG` (Zaffari) e `QJO.MUSS.FAT.DALIA`
  (Atacadão) ficam vinculados ao mesmo produto (`QUEIJO MUSSARELA FATIADO 1KG`), e esse produto é a
  1ª sugestão para cada uma das três descrições.
- `QJO PARMESAO PRES RAL 100G` e `PAO QJO F.MINAS TRAD CG 820G` **nunca** recebem esse produto como sugestão.
- A aba "Comparar" mostra, para o produto, o último preço em cada loja com data e nome original,
  destacando o mais barato, e o gráfico do histórico de preço por loja.

## 2. Fatos verificados (análise de `data/nfg.db` em 2026-10-04)

- 611 itens, 304 descrições distintas, 9 CNPJs (8 empresas; Zaffari com 2 filiais), notas de 06–09/2026.
  ~75% dos itens são do Zaffari.
- **Nenhuma descrição exata se repete entre lojas.**
- **Não há EAN/GTIN nem NCM**: a página de consulta da NFC-e não os exibe (0 ocorrências nos 38 HTMLs em
  `data/html_bruto`) e os parsers não os capturam. Agrupamento por código de barras é inviável hoje.
- `itens.codigo` é o código interno da loja: estável dentro da loja, sem significado entre lojas
  (o mesmo valor `6752` designa produtos diferentes em lojas diferentes).
- `itens.id` é regenerado a cada reprocessamento da nota (`salvar_nota` faz DELETE + INSERT), portanto não
  pode ser chave de vínculo.
- Estilos de nome: Zaffari abreviado e padronizado (`TIPO QUALIFICADOR MARCA ATRIB TAMANHO`); Atacadão
  com pontos e quase nunca com tamanho (`QJO.MUSS.FAT.DALIA`); Seven Boys/Bistek/Panvel por extenso.
- Unidades sujas: `UND9`, `KG9`, `PCT9` (Atacadão), `UNID`, `un`, `CXA1`, `CAIXA`, `VIDRO`, etc.
- Protótipo de normalização + similaridade: as três mussarelas viram {QUEIJO, MUSSARELA, FATIADO};
  a regra "primeira palavra = tipo" separa `PAO QJO` de `QJO`. A melhor heurística teve ~73% de acerto na
  faixa alta; os erros são variantes (C/20 vs C/30, 30% vs 60%, PRATO vs MUSSARELA). **Conclusão:
  sugerir + confirmação humana**, com vínculo automático só em casos seguros.

## 3. Decisões

- **Abordagem A:** catálogo manual com sugestões ranqueadas (descartadas: agrupamento automático com
  revisão; regras por regex).
- **Um produto por tamanho:** `COCA-COLA 290ML` e `COCA-COLA 600ML` são produtos distintos; a comparação é
  por preço unitário. Descrição sem tamanho entra no produto que o usuário escolher.
- **Preço de comparação:** `itens.valor_unitario` (preço de gôndola, sem o rateio do desconto da nota).
  Para produtos de venda `KG` o valor unitário já é R$/kg.
- **Comparação:** último preço por loja + histórico.
- **Marca não diferencia produto** (mussarela Santa Clara e Tirolez são o mesmo produto).

## 4. Modelo de dados

Criado pela migração **v3** (`PRAGMA user_version = 3`), atômica e idempotente como `_migrar_v1/_v2`
em `nfg/categorias.py`; `garantir_seed` de banco novo passa a marcar `user_version = 3`.

```sql
CREATE TABLE IF NOT EXISTS produtos (
  id INTEGER PRIMARY KEY,
  nome TEXT UNIQUE NOT NULL,        -- "QUEIJO MUSSARELA FATIADO 1KG" (editável)
  tipo TEXT NOT NULL,               -- "QUEIJO MUSSARELA" (tipo + qualificador)
  tamanho TEXT,                     -- "1KG", "C/20"; NULL para granel
  venda TEXT NOT NULL DEFAULT 'UN' CHECK (venda IN ('UN','KG'))
);
CREATE TABLE IF NOT EXISTS produto_vinculo (
  cnpj TEXT NOT NULL,
  codigo TEXT NOT NULL,
  produto_id INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
  origem TEXT NOT NULL CHECK (origem IN ('manual','auto')),
  PRIMARY KEY (cnpj, codigo)
);
CREATE TABLE IF NOT EXISTS produto_ignorado (
  cnpj TEXT NOT NULL,
  codigo TEXT NOT NULL,
  PRIMARY KEY (cnpj, codigo)
);
```

- **Chave do item:** `(cnpj_emitente, codigo)`. Item sem `codigo` usa `codigo = 'DESC:' || descricao_norm`
  (função `chave_item(cnpj, codigo, descricao)` em `nfg/produtos.py`).
- Nomes originais vêm de `itens.descricao` em tempo de leitura; nada é copiado.
- Excluir produto → vínculos removidos em cascata → itens voltam à fila. Notas nunca são alteradas.

## 5. Arquitetura

Novo módulo `nfg/produtos.py` (não importa streamlit), nova página `pages/5_Produtos.py`, ajuste pequeno
em `pages/1_Importar.py` e migração v3 em `nfg/categorias.py` (onde está o mecanismo de `user_version`).

### 5.1 Normalização

`normalizar_produto(descricao: str, unidade: str | None) -> Assinatura`

```python
@dataclass(frozen=True)
class Assinatura:
    tipo: str                         # "QUEIJO MUSSARELA"
    tokens: frozenset[str]            # tokens significativos (sem marca, sem stop-words, sem tamanho)
    tamanho: tuple[Decimal, str] | None   # (1000, "G"), (1500, "ML"), (20, "UN"), (30, "%")
    venda: str                        # "UN" | "KG"
```

Passos:
1. `util.normalizar_texto` (maiúsculas, sem acento).
2. Colar marcas abreviadas com ponto (`S.CLARA` → `SCLARA`, `B.VILLE` → `BVILLE`, `S.BOYS` → `SBOYS`).
3. Extrair tamanho: `\d+(,\d+)?\s?(KG|G|L|ML|M)\b` (M = ML truncado), embalagem `C/?\d+`, `L\d+`,
   `\d+X\d+(G|ML)`, percentual `\d+%`. Converte para G/ML/UN/%; remove o trecho do texto.
4. Pontuação (`.`, `/`, `-`, `*`, `,`) → espaço; exceto `C/` e `S/` que viram tokens `COM`/`SEM`.
5. Expandir abreviações por dicionário `ABREVIACOES` (~60 entradas: QJO→QUEIJO, MUSS→MUSSARELA,
   FAT→FATIADO, RAL→RALADO, LT/LTE→LEITE, CHOC→CHOCOLATE, ACHOC→ACHOCOLATADO, BISC→BISCOITO,
   IOG→IOGURTE, CR→CREME, REFRIG→REFRIGERANTE, CG/CONG→CONGELADO, PARB→PARBOILIZADO, CAIP→CAIPIRA,
   INT→INTEGRAL, TRAD→TRADICIONAL, VH/VIN→VINHO, LIMP→LIMPADOR, …) e sinônimos de cabeça
   `SINONIMOS_TIPO` (OVOS→OVO, KITKAT→CHOCOLATE KIT KAT, COCA→REFRIGERANTE COCA, PAOZINHO→PAO, …).
6. Remover tokens de marca (`MARCAS`, ~40) e stop-words (DE, DA, DO, E, AO, PACOTE, GRANEL, KG, …).
7. `tipo` = 1º token + 2º token (quando existir); `tokens` = conjunto restante.
8. `venda` = `KG` se unidade normalizada for `KG` (`normalizar_unidade`: `UND9`/`UNID`/`un` → `UN`,
   `KG9`/`kg` → `KG`, `PCT\d`→`PCT`, `CXA\d`/`CAIXA`/`CX` → `CX`), senão `UN`.

Dicionários ficam em constantes no módulo; ampliá-los é a forma de melhorar sugestões.

### 5.2 Sugestões

`sugerir(conn, descricao: str, unidade: str | None, n: int = 3) -> list[Sugestao]`

```python
@dataclass(frozen=True)
class Sugestao:
    produto_id: int
    nome: str
    score: float      # 0–100
    motivo: str       # "mesmo tipo + qualificador; tamanho não informado"
```

A assinatura de cada produto é calculada a partir de `nome` + `venda` (nome segue o mesmo vocabulário),
enriquecida pelos tokens das descrições já vinculadas a ele.

- **Vetos (score não calculado):** 1º token do tipo diferente; tamanho conhecido nos dois lados e diferente;
  `venda` diferente.
- **Score:** `70 × Jaccard(tokens)` + `20` se o 2º token do tipo coincide + `10` se tamanho coincide
  (tamanho ausente em um lado: +0, sem veto).
- Retorna até `n` produtos com score > 0, ordenados por score desc, nome asc.
- Cálculo em memória sobre todo o catálogo (volume pequeno); sem dependências novas.

### 5.3 Vínculo e catálogo

```python
def criar_produto(conn, nome: str, tipo: str, tamanho: str | None, venda: str) -> int
def atualizar_produto(conn, produto_id: int, **campos) -> None
def excluir_produto(conn, produto_id: int) -> None
def vincular(conn, cnpj: str, codigo: str, produto_id: int, origem: str = "manual") -> None  # upsert
def desvincular(conn, cnpj: str, codigo: str) -> None
def ignorar(conn, cnpj: str, codigo: str) -> None
def restaurar(conn, cnpj: str, codigo: str) -> None
def sugerir_nome(descricao: str, unidade: str | None) -> tuple[str, str, str | None, str]
    # (nome, tipo, tamanho, venda) pré-preenchidos para "Criar produto"
def vincular_automaticos(conn) -> int
```

Nome duplicado levanta `ProdutoDuplicado` (em `nfg/erros.py`).

`vincular_automaticos` liga, com `origem='auto'`, apenas itens pendentes que:
1. têm o mesmo `codigo` de um item já vinculado em outro CNPJ com a **mesma raiz** (8 primeiros dígitos);
2. têm descrição **idêntica após `normalizar_texto` sem pontuação/asteriscos** a uma descrição já vinculada.

### 5.4 Consultas (DataFrames)

```python
def pendentes_df(conn) -> DataFrame
    # [cnpj, codigo, loja, descricao (mais recente), unidade, ultimo_preco, ultima_data, compras]
    # itens de notas válidas sem vínculo e não ignorados; ordenado por compras desc
def catalogo_df(conn) -> DataFrame       # [id, nome, tipo, tamanho, venda, lojas, vinculos]
def vinculos_df(conn, produto_id) -> DataFrame   # [cnpj, codigo, loja, descricao, origem]
def ignorados_df(conn) -> DataFrame      # [cnpj, codigo, loja, descricao]
def comparar_produto(conn, produto_id) -> DataFrame
    # [loja, ultimo_preco, ultima_data, descricao_original, dif_reais, dif_pct, mais_barato]
    # uma linha por loja (CNPJ unificado como em analises._unificar_loja), ordenado por ultimo_preco
def historico_produto(conn, produto_id) -> DataFrame    # [emissao, loja, valor_unitario, descricao]
def visao_geral_df(conn) -> DataFrame
    # produtos comprados em 2+ lojas: [produto, loja_mais_barata, menor_preco, maior_preco, dif_pct]
```

Todas filtram notas válidas com o mesmo critério `_VALIDA` de `nfg/analises.py` e usam `_vazio(cols)`
para resultado vazio.

## 6. Interface — `pages/5_Produtos.py`

Mesmo padrão de `pages/4_Categorias.py` (`abrir_repo()`, `avisar()` com flash em `session_state`,
`st.session_state.pop(<key>)` + `st.rerun()` após salvar). Ao abrir, chama `vincular_automaticos`.

**Aba Comparar**
- Visão geral (`visao_geral_df`) no topo.
- Selectbox com busca de produto → tabela `comparar_produto` com destaque da linha mais barata;
  sufixo "R$/kg" para `venda='KG'`; gráfico plotly de `historico_produto` (uma linha por loja).
- Produto comprado em só uma loja: `st.info("Comprado só em <loja>")` + tabela.

**Aba A vincular**
- Contador "N itens a vincular"; `st.dataframe(pendentes_df, on_select="rerun", selection_mode="single-row")`.
- Item selecionado: até 3 sugestões (nome, score, motivo) com botão **Vincular** cada; selectbox
  "Outro produto" + **Vincular**; formulário **Criar produto** pré-preenchido por `sugerir_nome`
  (nome, tipo, tamanho, venda) que cria e vincula; botão **Ignorar**.

**Aba Catálogo**
- `st.data_editor` de `catalogo_df` (nome, tipo, tamanho, venda editáveis; exclusão de linhas) +
  botão Salvar.
- Produto selecionado → `vinculos_df` com botão **Desvincular** por item.
- Expander "Ignorados" com **Restaurar**.

**`pages/1_Importar.py`:** após importação/coleta chama `vincular_automaticos` e mostra
"N itens novos aguardando vínculo em Produtos" quando `len(pendentes_df) > 0`.

`pages/3_Análises.py` e funções existentes não mudam.

## 7. Erros e casos-limite

- Nome duplicado → `ProdutoDuplicado` → `avisar(..., "error")`; nada gravado.
- Migração v3 com `BEGIN`/`ROLLBACK`; idempotente. Recomenda-se copiar `data/nfg.db` antes da 1ª execução
  (convenção `nfg.backup-AAAA-MM-DD.db`).
- Reprocessar nota não afeta vínculos (chave `(cnpj, codigo)`).
- Código cuja descrição mudou mantém o vínculo; telas mostram a descrição mais recente.
- Notas canceladas/inválidas excluídas de pendentes e comparações.
- Produto sem compras em notas válidas: aparece no catálogo, some da visão geral.

## 8. Testes

- `tests/test_produtos_normalizacao.py` — `normalizar_produto`/`normalizar_unidade`: abreviações, pontos,
  tamanhos (`1KG`, `820G`, `1,5L`, `750M`, `C/20`, `C20`, `L16`, `30%`), unidades (`UND9`, `KG9`, `un`);
  as três mussarelas têm mesmo `tipo` e `tokens`; parmesão e pão de queijo têm `tipo` diferente.
- `tests/test_produtos_sugestao.py` — produto `QUEIJO MUSSARELA FATIADO 1KG` é 1º para as três
  descrições; nunca sugerido para parmesão / pão de queijo; vetos C/20×C/30, KG×UN; PRATO abaixo de
  MUSSARELA; `sugerir_nome`.
- `tests/test_produtos_vinculo.py` — CRUD, `ProdutoDuplicado`, ignorar/restaurar, `vincular_automaticos`
  (raiz de CNPJ, descrição idêntica normalizada), exclusão devolve à fila, reprocessar nota mantém vínculo,
  `chave_item` sem código.
- `tests/test_produtos_comparacao.py` — `comparar_produto` (último preço por loja, mais barato, diferenças),
  venda KG, nota cancelada excluída, `historico_produto`, `visao_geral_df`, `pendentes_df`.
- `tests/test_migracao.py` — v2 → v3 em banco "antigo"; idempotência; banco novo nasce em v3.
- `tests/test_ui.py` — página no `test_pagina_carrega`; vincular por sugestão; criar produto; ignorar;
  aba Comparar mostra a loja mais barata.

Fixtures: reutilizar `repo_dados` de `tests/conftest.py`, acrescentando um helper que salva notas com as
descrições do critério de sucesso (Zaffari e Atacadão) via `nota()`/`item()`.

## 9. Fora de escopo

- Captura de EAN/NCM (só possível no XML de NF-e modelo 55; pode alimentar a sugestão no futuro).
- Comparação por preço/kg entre tamanhos diferentes.
- Lista de compras / roteiro de lojas.
- Aprendizado automático de abreviações a partir das confirmações (os dicionários são editados em código).
