# Produtos Unificados Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Seção "Produtos" que vincula as descrições de cada loja a produtos unificados (um por tamanho), sugere vínculos por similaridade e compara o último preço por loja com histórico.

**Architecture:** Tabelas novas no `SCHEMA` de `nfg/db.py`. `nfg/produtos_texto.py` = funções puras (normalização, tamanho, pontuação, nome sugerido) com dicionários em constantes. `nfg/produtos.py` = catálogo/vínculos (SQL), sugestões, fila e comparações (pandas). Página fina `pages/5_Produtos.py` no padrão de `pages/4_Categorias.py`.

**Tech Stack:** Python 3.11, sqlite3, pandas, streamlit 1.64, plotly; pytest + `streamlit.testing.v1.AppTest`. Sem dependências novas.

**Spec:** `docs/superpowers/specs/2026-10-04-produtos-unificados-design.md` — leia antes de cada tarefa.

## Global Constraints

- Rodar tudo a partir de `nfg-compras/` com `.venv\Scripts\python -m pytest`; a suíte inteira (hoje 184 testes) deve continuar verde ao fim de cada tarefa.
- Código, identificadores e mensagens de UI em português (como no spec).
- `nfg/` nunca importa `streamlit`.
- Vínculo é sempre por `(cnpj, codigo)` com `codigo` vindo de `chave_item`; **nunca** referenciar `itens.id`.
- Itens só contam se a nota passa no filtro `_VALIDA` de `nfg/analises.py` (importar a constante, não copiar).
- Preço de comparação = `itens.valor_unitario` (sem rateio de desconto).
- Não alterar `PRAGMA user_version` (continua 2) nem as funções existentes de `nfg/analises.py`.
- Testes de UI: `AppTest.from_file(..., default_timeout=30)`, seleção de tabela via `at.session_state["<key>"] = {"selection": {"rows": [i], "columns": []}}`.
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Item sem `codigo` (NULL ou "")** — deve ter chave estável `DESC:<descricao normalizada>` e ser vinculável. Teste em Task 1.
2. **Descrição sem palavras significativas** (ex.: `"*"`, `"KG"`, só marca) — normalização não quebra, `sugerir` devolve `[]`, `sugerir_nome` devolve a descrição normalizada como nome. Testes em Tasks 2 e 3.
3. **Renomear/criar produto com nome já existente** — `ProdutoDuplicado`, nada gravado, UI mostra erro. Testes em Tasks 1 e 6.
4. **Excluir produto com vínculos** — itens voltam à fila "A vincular". Teste em Task 4.
5. **Produto cujas compras estão todas em notas canceladas** — `comparar_produto` vazio, ausente da visão geral, sem exceção na UI. Teste em Task 5.

---

### Task 1: Tabelas, catálogo e vínculos

**Files:**
- Modify: `nfg/db.py` (`SCHEMA`), `nfg/erros.py`, `tests/conftest.py`
- Create: `nfg/produtos.py`
- Test: `tests/test_produtos_vinculo.py`

**Interfaces:**
- Produces (em `nfg/produtos.py`):
  - `chave_item(cnpj: str, codigo: str | None, descricao: str) -> tuple[str, str]` — `(cnpj, codigo)` ou `(cnpj, "DESC:" + normalizar_texto(descricao))` se `codigo` vazio/None.
  - `criar_produto(conn, nome: str, tipo: str, tamanho: str | None, venda: str) -> int` — `nome` passa por `normalizar_texto`; duplicado → `ProdutoDuplicado`.
  - `atualizar_produto(conn, produto_id: int, **campos) -> None` — campos ∈ {nome, tipo, tamanho, venda}; duplicado → `ProdutoDuplicado`.
  - `excluir_produto(conn, produto_id: int) -> None`
  - `vincular(conn, cnpj: str, codigo: str, produto_id: int, origem: str = "manual") -> None` — upsert; remove de `produto_ignorado`.
  - `desvincular(conn, cnpj, codigo) -> None`, `ignorar(conn, cnpj, codigo) -> None` (remove vínculo), `restaurar(conn, cnpj, codigo) -> None`
- Produces (em `nfg/erros.py`): `class ProdutoDuplicado(ErroNFG)`
- Produces (em `tests/conftest.py`): fixture `repo_produtos` (abaixo) e constantes acessíveis via atributos da fixture: `repo_produtos.zaf`, `.zaf2`, `.atac` (CNPJs).

- [ ] **Step 1: Adicionar a fixture `repo_produtos` em `tests/conftest.py`**

Estende `repo_dados` (reaproveita `nota()`/`item()` — extraia-os para funções de módulo do conftest para reuso). `zaf = nota_zaffari.emitente`, `zaf2 = Estabelecimento(zaf.cnpj[:8] + "002590", "CIA ZAFFARI FILIAL")`, `atac` = o mesmo `75315333008860`. Notas:

| chave | emitente | emissão | itens `(seq, cod, desc, qtd, un, vu)` |
|---|---|---|---|
| `"4"*44` | zaf | 2026-09-01 | (1,"101","QJO MUSSARELA S.CLARA FAT 1KG","1","UN","52.90"), (2,"102","QJO MUSSARELA TIROLEZ FAT 1KG","1","UN","48.90"), (3,"103","QJO PARMESAO PRES RAL 100G","1","UN","12.98"), (4,"104","PAO QJO F.MINAS TRAD CG 820G","1","UN","28.90"), (5,"105","QJO PRATO S.CLARA FAT 1KG","1","UN","52.90"), (6,"106","BANANA PRATA GRANEL","1.5","KG","6.98") |
| `"5"*44` | atac | 2026-09-05 | (1,"6752","QJO.MUSS.FAT.DALIA","1","UND9","47.90"), (2,"6753","BANANA PRATA","2","KG9","5.49"), (3,None,"SACOLA","1","UN","0.10") |
| `"6"*44` | zaf | 2026-09-20 | (1,"102","QJO MUSSARELA TIROLEZ FAT 1KG","1","UN","51.90") |
| `"7"*44` | zaf2 | 2026-09-22 | (1,"101","QJO MUSSARELA S.CLARA FAT 1KG","1","UN","50.90") |
| `"8"*44` | atac | 2026-09-25 | (1,"6752","QJO.MUSS.FAT.DALIA","1","UND9","10.00") — depois `situacao_csv='Cancelada'` |

`valor_total` de cada nota = soma dos itens. Expor os CNPJs com `repo.zaf = zaf.cnpj` etc. (atributos no objeto `Repositorio`).

- [ ] **Step 2: Escrever os testes que falham** em `tests/test_produtos_vinculo.py`

```python
def test_banco_antigo_ganha_tabelas_e_user_version_segue(tmp_path):
    # cria nfg.db sem as tabelas novas (executa SCHEMA antigo = sem 'produtos'), PRAGMA user_version=2,
    # reabre com conectar(); assert tabelas produtos/produto_vinculo/produto_ignorado existem e user_version == 2
def test_chave_item_com_e_sem_codigo():
    assert chave_item("1", "101", "X") == ("1", "101")
    assert chave_item("1", None, "Sacola  ") == ("1", "DESC:SACOLA")
    assert chave_item("1", "", "sacola") == ("1", "DESC:SACOLA")
def test_criar_produto_normaliza_nome(repo): # criar_produto(conn,"queijo mussarela fatiado 1kg",...) -> nome "QUEIJO MUSSARELA FATIADO 1KG"
def test_criar_produto_duplicado(repo):      # 2º criar com mesmo nome -> pytest.raises(ProdutoDuplicado); COUNT(*) == 1
def test_renomear_para_existente(repo):      # atualizar_produto(conn, b, nome=<nome de a>) -> ProdutoDuplicado; nome de b inalterado
def test_vincular_upsert_e_desvincular(repo_produtos)  # vincular 2x troca produto_id; desvincular remove
def test_ignorar_remove_vinculo_e_vincular_remove_ignorado(repo_produtos)
def test_restaurar(repo_produtos)
def test_excluir_produto_remove_vinculos(repo_produtos)  # COUNT(produto_vinculo) == 0
def test_reprocessar_nota_mantem_vinculo(repo_produtos)
    # vincular (zaf,"101"); repo.salvar_nota(<mesma nota "4"*44 de novo>); vínculo continua
```

- [ ] **Step 3: Rodar e ver falhar** — `.venv\Scripts\python -m pytest tests/test_produtos_vinculo.py -v` → FAIL (ImportError).

- [ ] **Step 4: Implementar** — tabelas exatamente como no spec §4 no fim de `SCHEMA`; `ProdutoDuplicado`; funções acima (capturar `sqlite3.IntegrityError` de `UNIQUE` → `ProdutoDuplicado`; cada escrita em `with conn:`).

- [ ] **Step 5: Rodar** `tests/test_produtos_vinculo.py` e a suíte inteira → PASS.

- [ ] **Step 6: Commit** — `git add nfg/db.py nfg/erros.py nfg/produtos.py tests/conftest.py tests/test_produtos_vinculo.py && git commit -m "feat(produtos): tabelas, catálogo e vínculos"`

---

### Task 2: Normalização de descrições

**Files:**
- Create: `nfg/produtos_texto.py`
- Test: `tests/test_produtos_normalizacao.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Assinatura: tipo: str; palavras: tuple[str, ...]; tokens: frozenset[str]; tamanho: tuple[Decimal, str] | None; venda: str`
  - `normalizar_unidade(unidade: str | None) -> str` — `UN|KG|PCT|CX|<outra maiúscula sem dígitos finais>`; None → `"UN"`.
  - `normalizar_produto(descricao: str, unidade: str | None) -> Assinatura` — algoritmo do spec §5.1 (passos 1–8, com a prioridade de tamanho).
  - `formatar_tamanho(tamanho: tuple[Decimal, str] | None) -> str | None`
  - `sugerir_nome(descricao: str, unidade: str | None) -> tuple[str, str, str | None, str]` — `(nome, tipo, tamanho, venda)`; nome = `" ".join(palavras)` + `" " + tamanho` se houver; sem palavras → nome = `normalizar_texto(descricao)`, tipo = nome.
  - Constantes `ABREVIACOES: dict[str, str]`, `SINONIMOS_TIPO: dict[str, str]`, `MARCAS: frozenset[str]`, `STOPWORDS: frozenset[str]`.

- [ ] **Step 1: Escrever os testes que falham**

```python
MUSS = {"QUEIJO", "MUSSARELA", "FATIADO"}

@pytest.mark.parametrize("desc,un", [("QJO MUSSARELA S.CLARA FAT 1KG", "UN"),
                                     ("QJO MUSSARELA TIROLEZ FAT 1KG", "UN"),
                                     ("QJO.MUSS.FAT.DALIA", "UND9")])
def test_tres_mussarelas_mesmo_tipo_e_tokens(desc, un):
    a = normalizar_produto(desc, un)
    assert a.tipo == "QUEIJO MUSSARELA" and a.tokens == MUSS and a.venda == "UN"

def test_tamanho_mussarela():
    assert normalizar_produto("QJO MUSSARELA S.CLARA FAT 1KG", "UN").tamanho == (Decimal(1000), "G")
    assert normalizar_produto("QJO.MUSS.FAT.DALIA", "UND9").tamanho is None

def test_parmesao_e_pao_de_queijo_tem_outro_tipo():
    assert normalizar_produto("QJO PARMESAO PRES RAL 100G", "UN").tipo == "QUEIJO PARMESAO"
    assert normalizar_produto("PAO QJO F.MINAS TRAD CG 820G", "UN").tipo == "PAO QUEIJO"

@pytest.mark.parametrize("desc,esperado", [
    ("COCA COLA 1,5L", (Decimal(1500), "ML")), ("VH CON TORO RESERVADO 750M", (Decimal(750), "ML")),
    ("PAO QJO F.MINAS TRAD CG 820G", (Decimal(820), "G")), ("OVO CAIP NATURALE C/20", (Decimal(20), "UN")),
    ("OVOS FILIPPSEN CAIPIRA C20", (Decimal(20), "UN")), ("P H NEVE L16", (Decimal(16), "UN")),
    ("ACHOC PO 30%", (Decimal(30), "%")), ("LIMP VDR JIMO AER400ML", (Decimal(400), "ML")),
])
def test_extrai_tamanho(desc, esperado)

def test_ovos_sinonimo_de_cabeca():
    assert normalizar_produto("OVOS FILIPPSEN CAIPIRA C20", "UN").tipo == "OVO CAIPIRA"
    assert normalizar_produto("OVO CAIP NATURALE C/20", "UN").tipo == "OVO CAIPIRA"

def test_com_sem_viram_palavras():
    assert {"COM", "GAS"} <= normalizar_produto("AGUA C/GAS 500ML", "UN").tokens

def test_tamanho_secundario_vira_palavra():   # "LEITE PO 400G 30%" -> tamanho (400,"G"), "30%" in tokens

@pytest.mark.parametrize("un,esperado", [("UND9","UN"),("UNID","UN"),("un","UN"),(None,"UN"),
    ("KG9","KG"),("kg","KG"),("PCT9","PCT"),("CXA1","CX"),("CAIXA","CX"),("CX","CX")])
def test_normalizar_unidade(un, esperado)

def test_granel_vende_por_kg():
    a = normalizar_produto("BANANA PRATA GRANEL", "KG")
    assert (a.tipo, a.tamanho, a.venda) == ("BANANA PRATA", None, "KG")
    assert normalizar_produto("CENOURA kg", "KG9").tipo == "CENOURA"

@pytest.mark.parametrize("t,s", [((Decimal(1000),"G"),"1KG"), ((Decimal(500),"G"),"500G"),
    ((Decimal(1500),"ML"),"1,5L"), ((Decimal(350),"ML"),"350ML"), ((Decimal(20),"UN"),"C/20"),
    ((Decimal(30),"%"),"30%"), (None, None)])
def test_formatar_tamanho(t, s)

def test_sugerir_nome():
    assert sugerir_nome("QJO MUSSARELA S.CLARA FAT 1KG", "UN") == (
        "QUEIJO MUSSARELA FATIADO 1KG", "QUEIJO MUSSARELA", "1KG", "UN")
    assert sugerir_nome("BANANA PRATA GRANEL", "KG") == ("BANANA PRATA", "BANANA PRATA", None, "KG")

@pytest.mark.parametrize("desc", ["*", "KG", "TIROLEZ", ""])
def test_descricao_sem_palavras_nao_quebra(desc):
    a = normalizar_produto(desc, "UN"); assert a.tipo == "" and a.tokens == frozenset()
    assert sugerir_nome(desc, "UN")[0] == normalizar_texto(desc)
```

- [ ] **Step 2: Rodar e ver falhar** — `pytest tests/test_produtos_normalizacao.py -v` → FAIL (ImportError).

- [ ] **Step 3: Implementar `nfg/produtos_texto.py`** seguindo o spec §5.1. Ordem: `normalizar_texto` → colar letra+ponto+palavra (`\b([A-Z])\.(?=[A-Z]{2})` → `\1`) → extrair tamanhos (peso/volume `(\d+(?:,\d+)?)\s?(KG|G|L|ML|M)\b` também colado a letras como `AER400ML`; embalagem `\bC/?(\d+)\b`, `\bL(\d+)`; percentual `(\d+)%`) → `C/`→`COM `, `S/`→`SEM ` → pontuação para espaço → `ABREVIACOES` por palavra → `SINONIMOS_TIPO` só na 1ª palavra → remover `MARCAS` e `STOPWORDS` → remover repetidas consecutivas. Dicionários iniciais: todas as abreviações e marcas citadas no spec §2/§5.1 e nos testes (incluir `SCLARA, TIROLEZ, DALIA, PRES, PRESIDENT, TUTTI, FMINAS, BVILLE, SBOYS, NATURALE, FILIPPSEN, JIMO, NEVE, CON, TORO`; `STOPWORDS` inclui `DE DA DO DAS DOS E AO A O EM PACOTE GRANEL KG UN`; `VDR→VIDRO`, `AER→AEROSOL`, `PO→PO`).

- [ ] **Step 4: Rodar** o arquivo e a suíte → PASS.

- [ ] **Step 5: Commit** — `git commit -m "feat(produtos): normalização de descrições"` (adicionar os 2 arquivos).

---

### Task 3: Pontuação e sugestões

**Files:**
- Modify: `nfg/produtos_texto.py`, `nfg/produtos.py`
- Test: `tests/test_produtos_sugestao.py`

**Interfaces:**
- Consumes: `Assinatura`, `normalizar_produto` (Task 2); `criar_produto`, `vincular` (Task 1).
- Produces:
  - `pontuar(item: Assinatura, produto: Assinatura, similares: Sequence[Assinatura] = ()) -> tuple[float, str] | None` (em `produtos_texto`) — `None` = veto.
  - `@dataclass(frozen=True) class Sugestao: produto_id: int; nome: str; score: float; motivo: str` (em `produtos`)
  - `sugerir(conn, descricao: str, unidade: str | None, n: int = 3) -> list[Sugestao]` (em `produtos`)

Regra (spec §5.2): veto se `item.tipo == ""`, 1ª palavra do tipo diferente, `venda` diferente, ou os dois tamanhos conhecidos e diferentes — sempre contra a assinatura do produto. Senão, para cada `s` em `[produto, *similares]`: `70 × |item.tokens ∩ s.tokens| / |item.tokens ∪ s.tokens|` + `20` se a 2ª palavra do tipo coincide; pega o máximo; `+10` se tamanho do item == tamanho do produto. `motivo` concatena com "; ": "mesmo tipo", "mesmo qualificador", "mesmo tamanho" / "tamanho não informado". `sugerir`: assinatura do produto = `normalizar_produto(f"{nome} {tamanho or ''}", venda)`; similares = descrições (mais recente por chave) dos itens vinculados; retorna `score > 0`, ordenado por (-score, nome), até `n`.

- [ ] **Step 1: Escrever os testes que falham**

```python
@pytest.fixture
def catalogo(repo):
    c = repo.conn
    ids = {k: criar_produto(c, *a) for k, a in {
        "muss": ("QUEIJO MUSSARELA FATIADO 1KG", "QUEIJO MUSSARELA", "1KG", "UN"),
        "prato": ("QUEIJO PRATO FATIADO 1KG", "QUEIJO PRATO", "1KG", "UN"),
        "parm": ("QUEIJO PARMESAO RALADO 100G", "QUEIJO PARMESAO", "100G", "UN"),
        "pao": ("PAO QUEIJO TRADICIONAL CONGELADO 820G", "PAO QUEIJO", "820G", "UN"),
        "ovo": ("OVO CAIPIRA C/20", "OVO CAIPIRA", "C/20", "UN"),
        "banana": ("BANANA PRATA", "BANANA PRATA", None, "KG")}.items()}
    return c, ids

@pytest.mark.parametrize("desc,un", [("QJO MUSSARELA S.CLARA FAT 1KG","UN"),
    ("QJO MUSSARELA TIROLEZ FAT 1KG","UN"), ("QJO.MUSS.FAT.DALIA","UND9")])
def test_mussarela_e_primeira_sugestao(catalogo, desc, un):
    c, ids = catalogo; assert sugerir(c, desc, un)[0].produto_id == ids["muss"]

@pytest.mark.parametrize("desc", ["QJO PARMESAO PRES RAL 100G", "PAO QJO F.MINAS TRAD CG 820G"])
def test_mussarela_nunca_sugerida(catalogo, desc):
    c, ids = catalogo; assert ids["muss"] not in [s.produto_id for s in sugerir(c, desc, "UN", n=10)]

def test_score_dalia(catalogo):
    c, ids = catalogo
    s = sugerir(c, "QJO.MUSS.FAT.DALIA", "UND9")[0]
    assert s.score == 90 and "tamanho não informado" in s.motivo
def test_score_mussarela_1kg_100(catalogo)            # "QJO MUSSARELA TIROLEZ FAT 1KG" -> 100
def test_prato_acima_de_mussarela(catalogo)            # "QJO PRATO S.CLARA FAT 1KG": [0] é prato; muss com score menor
def test_veto_embalagem(catalogo)                      # "OVO CAIP NATURALE C/30" não sugere ovo
def test_veto_venda(catalogo)                          # ("BANANA PRATA NATURALE ORG 800G","UN") não sugere banana
def test_descricao_vazia_sem_sugestoes(catalogo)       # sugerir(c, "*", "UN") == []
def test_similares_vinculados_ajudam():
    n = normalizar_produto
    item, prod = n("QJO MUSS FAT ESPECIAL", "UN"), n("QUEIJO MUSSARELA FATIADO 1KG", "UN")
    assert pontuar(item, prod)[0] == pytest.approx(72.5)                       # 70*3/4 + 20
    assert pontuar(item, prod, [n("QJO.MUSS.FAT.ESPECIAL.DALIA", "UND9")])[0] == 90
def test_sugerir_usa_descricoes_vinculadas(repo_produtos)
    # cria muss; vincula (atac,"6752"); sugerir(c, "QJO MUSS FAT", "UND9")[0].produto_id == muss
def test_pontuar_veto_retorna_none()   # pontuar(n("PAO QJO F.MINAS TRAD CG 820G","UN"), n("QUEIJO MUSSARELA FATIADO 1KG","UN")) is None
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** `pontuar`, `Sugestao`, `sugerir`.
- [ ] **Step 4: Rodar** o arquivo e a suíte → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(produtos): pontuação e sugestões"`

---

### Task 4: Fila de pendentes, consultas do catálogo e vínculo automático

**Files:**
- Modify: `nfg/produtos.py`
- Test: `tests/test_produtos_vinculo.py`

**Interfaces:**
- Consumes: `_VALIDA`, `_unificar_loja`, `_emissao`, `_vazio` de `nfg.analises`; `chave_item`, `vincular` (Task 1).
- Produces:
  - `_itens_chaveados(conn) -> DataFrame` — `[cnpj, codigo, loja, emissao, descricao, unidade, valor_unitario]` de notas válidas, `codigo` já via `chave_item`, `valor_unitario` float, `emissao` datetime. Base das Tasks 4–5.
  - `pendentes_df(conn) -> DataFrame` — `[cnpj, codigo, loja, descricao, unidade, ultimo_preco, ultima_data, compras]`, sem vínculo e não ignorados, ordenado por `compras` desc, depois `descricao`; `descricao`/`unidade`/`ultimo_preco` da compra mais recente.
  - `catalogo_df(conn) -> DataFrame` — `[id, nome, tipo, tamanho, venda, lojas, vinculos]` ordenado por nome (`lojas` = CNPJs distintos vinculados).
  - `vinculos_df(conn, produto_id) -> DataFrame` — `[cnpj, codigo, loja, descricao, origem]` (descrição mais recente).
  - `ignorados_df(conn) -> DataFrame` — `[cnpj, codigo, loja, descricao]`.
  - `vincular_automaticos(conn) -> int` — regras do spec §5.3; chave de descrição = `normalizar_texto` sem caracteres não alfanuméricos e espaços colapsados.

- [ ] **Step 1: Escrever os testes que falham**

```python
def test_pendentes_agrega_por_codigo(repo_produtos):
    df = pendentes_df(repo_produtos.conn).set_index(["cnpj", "codigo"])
    r = df.loc[(repo_produtos.zaf, "102")]
    assert r.compras == 2 and r.ultimo_preco == 51.90
    r = df.loc[(repo_produtos.atac, "6752")]          # nota cancelada não conta
    assert r.compras == 1 and r.ultimo_preco == 47.90 and r.unidade == "UND9"
    assert (repo_produtos.atac, "DESC:SACOLA") in df.index
def test_pendentes_exclui_vinculados_e_ignorados(repo_produtos)
def test_excluir_produto_devolve_a_fila(repo_produtos)   # vincula 101/102, exclui produto, ambos voltam em pendentes_df
def test_catalogo_e_vinculos_df(repo_produtos)          # muss vinculado a (zaf,101),(zaf2,101),(atac,6752): lojas == 3, vinculos == 3
def test_ignorados_df(repo_produtos)
def test_auto_mesma_raiz_de_cnpj(repo_produtos):
    c = repo_produtos.conn; p = criar_produto(c, "QUEIJO MUSSARELA FATIADO 1KG", "QUEIJO MUSSARELA", "1KG", "UN")
    vincular(c, repo_produtos.zaf, "101", p)
    assert vincular_automaticos(c) >= 1
    assert c.execute("SELECT origem FROM produto_vinculo WHERE cnpj=? AND codigo='101'",
                     (repo_produtos.zaf2,)).fetchone()[0] == "auto"
def test_auto_descricao_identica_normalizada(repo_produtos)
    # salva nota zaf com (1,"999","QJO MUSSARELA S.CLARA FAT 1KG *",...); após vincular 101 e rodar auto, (zaf,"999") vinculado
def test_auto_nao_liga_codigo_igual_de_outra_raiz(repo_produtos)
    # salva nota atac com (1,"101","AGUA MINERAL",...); (atac,"101") continua pendente
def test_auto_idempotente(repo_produtos)                # 2ª chamada retorna 0
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar** as funções (pandas sobre `_itens_chaveados` + leituras das tabelas novas; resultados vazios via `_vazio`).
- [ ] **Step 4: Rodar** o arquivo e a suíte → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(produtos): fila de pendentes e vínculo automático"`

---

### Task 5: Comparação de preços

**Files:**
- Modify: `nfg/produtos.py`
- Test: `tests/test_produtos_comparacao.py`

**Interfaces:**
- Consumes: `_itens_chaveados` (Task 4).
- Produces:
  - `comparar_produto(conn, produto_id: int) -> DataFrame` — `[cnpj, loja, ultimo_preco, ultima_data, descricao_original, dif_reais, dif_pct, mais_barato]`, uma linha por CNPJ, ordenado por `ultimo_preco`; `dif_*` contra o menor; `dif_pct` arredondado a 2 casas; `mais_barato` bool (empates: todos True).
  - `historico_produto(conn, produto_id) -> DataFrame` — `[emissao, loja, valor_unitario, descricao]` ordenado por emissão.
  - `visao_geral_df(conn) -> DataFrame` — `[produto_id, produto, venda, loja_mais_barata, menor_preco, maior_preco, dif_pct]` só produtos com 2+ CNPJs, ordenado por `dif_pct` desc.

- [ ] **Step 1: Escrever os testes que falham** (fixture local `vinculado` que devolve o próprio `repo_produtos` com atributos extras `muss`, `banana`, `parm` = ids; usar `c = vinculado.conn`, `muss = vinculado.muss`. Produto muss vinculado a (zaf,101),(zaf,102),(zaf2,101),(atac,6752); banana (venda KG) a (zaf,106),(atac,6753); produto "parm" vinculado a (zaf,103))

```python
def test_comparar_ultimo_preco_por_loja(vinculado):
    df = comparar_produto(c, muss)
    # zaf: último é 51.90 de 2026-09-20 (TIROLEZ); atac: 47.90 (cancelada de 10.00 ignorada); zaf2: 50.90
    assert list(df["ultimo_preco"]) == [47.90, 50.90, 51.90]
    df = df.set_index("cnpj"); r = vinculado   # r.zaf, r.zaf2, r.atac
    assert df.loc[r.atac, "mais_barato"] and not df.loc[r.zaf, "mais_barato"]
    assert df.loc[r.atac, "loja"] == "ATACADAO S.A."
    assert df.loc[r.zaf, "descricao_original"] == "QJO MUSSARELA TIROLEZ FAT 1KG"
    assert df.loc[r.zaf, "dif_reais"] == pytest.approx(4.00) and df.loc[r.zaf, "dif_pct"] == 8.35
def test_comparar_venda_kg(vinculado)            # banana: atac 5.49 mais barato que zaf 6.98
def test_historico_produto(vinculado)            # muss: 4 linhas válidas (52.90, 47.90, 51.90, 50.90 em ordem de data); sem 10.00
def test_visao_geral(vinculado)                  # contém muss (loja_mais_barata = atac, menor 47.90, maior 51.90, dif_pct 8.35) e banana; não contém parm (1 loja)
def test_produto_so_com_notas_canceladas(repo_produtos)
    # produto vinculado só a uma chave cujas notas são todas canceladas -> comparar_produto vazio (com as colunas), ausente de visao_geral_df
def test_produto_sem_vinculos(repo_produtos)     # comparar/historico vazios com as colunas certas
```

- [ ] **Step 2: Rodar e ver falhar.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: Rodar** o arquivo e a suíte → PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat(produtos): comparação de preços por loja"`

---

### Task 6: Página Produtos e integração com Importar

**Files:**
- Create: `pages/5_Produtos.py`
- Modify: `pages/1_Importar.py`, `tests/test_ui.py`

**Interfaces:**
- Consumes: tudo de `nfg/produtos.py` e `sugerir_nome` de `nfg/produtos_texto.py`.
- Produces (keys usadas nos testes): tabela de pendentes `tabela_pendentes`; botões `vincular_sug_0..2`, `vincular_outro` (com selectbox `outro_produto`), `criar_produto` (inputs `novo_nome`, `novo_tipo`, `novo_tamanho`, selectbox `novo_venda`), `ignorar`; selectbox `produto_comparar`; editor `editor_catalogo` + botão `salvar_catalogo`; tabela `tabela_catalogo` (seleção) + botões `desvincular_<i>`; botões `restaurar_<i>`.

Página conforme spec §6: cabeçalho igual a `4_Categorias.py` (sys.path, `set_page_config`, `abrir_repo()`, `avisar()` + replay de `_msgs`); `vincular_automaticos(conn)` ao abrir; `st.tabs(["Comparar", "A vincular", "Catálogo"])`. Usar widgets soltos (não `st.form`). Em Comparar: `st.success(f"Mais barato: {loja} — {formatar_brl(preco)}")` (sufixo `/kg` quando `venda == "KG"`), tabela e `px.line(historico, x="emissao", y="valor_unitario", color="loja", markers=True)`; produto em 1 loja → `st.info(f"Comprado só em {loja}")`; catálogo vazio → `st.info("Nenhum produto cadastrado...")`. Em A vincular: `st.caption(f"{n} itens a vincular")`. Após cada ação: `avisar(...)`, `st.session_state.pop("tabela_pendentes", None)`, `st.rerun()`. `ProdutoDuplicado` → `avisar("error", ...)`. Em `1_Importar.py`, após importar/coletar/reprocessar com sucesso: `vincular_automaticos(repo.conn)`; depois `k = len(pendentes_df(repo.conn))` e, se `k > 0`, `st.info(f"{k} itens aguardando vínculo em Produtos")`.

- [ ] **Step 1: Escrever os testes que falham** em `tests/test_ui.py`

```python
# adicionar "pages/5_Produtos.py" ao parametrize de test_pagina_carrega
PRODUTOS = str(RAIZ / "pages/5_Produtos.py")

def test_produtos_criar_e_vincular_pendente():
    at = AppTest.from_file(PRODUTOS, default_timeout=30).run()
    at.session_state["tabela_pendentes"] = {"selection": {"rows": [0], "columns": []}}
    at.run(); at.text_input(key="novo_nome").input("PRODUTO TESTE UI").run()
    at.button(key="criar_produto").click().run()
    # assert 1 produto "PRODUTO TESTE UI" no banco e 1 vínculo; at.success não vazio; sem exceção
def test_produtos_nome_duplicado_mostra_erro()      # cria via nfg.produtos antes; mesmo nome na UI -> at.error, 1 produto só
def test_produtos_ignorar()                          # seleciona linha 0, clica ignorar -> 1 linha em produto_ignorado
def test_produtos_vincular_sugestao()                # cria produto com nome sugerido do 1º pendente via sugerir_nome; seleciona; vincular_sug_0 -> vínculo gravado
def test_produtos_comparar_mostra_mais_barato():
    # via abrir_repo(): salvar nota atac com o mesmo código/descrição de um item Zaffari por preço menor,
    # criar produto, vincular as duas chaves; abrir página, selectbox produto_comparar -> produto;
    # assert any("Mais barato" in s.value and "ATACADAO" in s.value for s in at.success)
def test_produtos_sem_dados(tmp_path, monkeypatch)  # NFG_DATA_DIR vazio -> sem exceção, at.info presente
```

- [ ] **Step 2: Rodar e ver falhar** — `pytest tests/test_ui.py -v -k produtos` → FAIL.
- [ ] **Step 3: Implementar** `pages/5_Produtos.py` e o ajuste em `pages/1_Importar.py`.
- [ ] **Step 4: Rodar** a suíte inteira → PASS.
- [ ] **Step 5: Verificação manual** — copiar `data/nfg.db` para `data/nfg.backup-2026-10-04.db`; `.venv\Scripts\streamlit run app.py`; na página Produtos criar `QUEIJO MUSSARELA FATIADO 1KG` a partir de `QJO MUSSARELA S.CLARA FAT 1KG`, conferir que `QJO MUSSARELA TIROLEZ FAT 1KG` e `QJO.MUSS.FAT.DALIA` o têm como 1ª sugestão e que Comparar mostra Atacadão 47,90 como mais barato.
- [ ] **Step 6: Commit** — `git commit -m "feat(produtos): página Produtos e aviso na importação"`
