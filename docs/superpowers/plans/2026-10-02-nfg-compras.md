# NFG Compras Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** App Streamlit local que importa o CSV do Nota Fiscal Gaúcha, baixa cada NFC-e na SEFAZ-RS pela chave, extrai itens para SQLite e mostra análises de compras mensais por produto, loja e categoria.

**Architecture:** Núcleo `nfg/` puro Python (sem Streamlit), testado com pytest/TDD: utilitários → parsers (CSV, HTML NFC-e, XML NF-e) → cliente HTTP → repositório SQLite → categorias → orquestração da coleta → análises (pandas). Páginas Streamlit finas em `app.py` e `pages/` chamam o núcleo.

**Tech Stack:** Python 3.11, streamlit, requests, beautifulsoup4 + lxml, pandas, plotly, openpyxl; dev: pytest, responses.

**Spec:** `docs/superpowers/specs/2026-10-02-nfg-compras-design.md` — leia antes de cada tarefa.

## Global Constraints

- Python 3.11 (ambiente Windows 11; rodar comandos a partir de `nfg-compras/`, com o venv `.venv` ativado).
- Todo código e identificadores de domínio em português (como no spec); mensagens de UI em português.
- `nfg/` nunca importa `streamlit`.
- Valores monetários de nota/item/pagamento: `Decimal` no Python; no banco, totais em centavos `INTEGER`, quantidade e valor unitário como `TEXT` decimal exato.
- Arredondamento para centavos: `ROUND_HALF_UP`.
- CPF nunca persistido em banco nem em disco (`mascarar_cpf` antes de salvar HTML).
- Consulta SEFAZ: GET `https://www.sefaz.rs.gov.br/ASP/AAE_ROOT/NFE/SAT-WEB-NFE-NFC_1.asp?chaveNFe=<chave>` e POST `https://www.sefaz.rs.gov.br/ASP/AAE_ROOT/NFE/SAT-WEB-NFE-NFC_2.asp` com `HML=false`, `chaveNFe=<chave>`, `Action=Avançar` (bytes iso-8859-1); resposta decodificada como iso-8859-1; timeout 20 s; backoffs (2, 5) s; pausa 1,5 s entre notas; máximo 3 tentativas por nota.
- Nunca contornar captcha/bloqueio: HTTP 403/429 ou "captcha" no HTML → `BloqueioSefaz` e o lote para.
- Análises só contam notas com `(tipo_operacao IS NULL OR tipo_operacao='Aquisição') AND (situacao_csv IS NULL OR situacao_csv='Normal')`.
- Testes que acessam a internet só com marcador `@pytest.mark.online` (excluídos por padrão).
- Commits terminam com `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **HTML bruto do servidor ≠ DOM capturado na fixture** (sem `<tbody>`, `&nbsp;`, iso-8859-1, espaços extras) — o parser deve extrair os mesmos dados. Teste em Task 3.
2. **Mesmo CSV importado duas vezes, ou CSVs de meses sobrepostos** — nenhuma duplicata e nota já `coletada` nunca volta a `pendente`. Teste em Task 6.
3. **SEFAZ responde 200 com página de outra nota/rejeição** — nunca gravar dados errados; chave divergente vira erro. Teste em Task 8.
4. **Usuário digita regex inválida numa regra de categoria** — erro amigável (`ValueError`), nada é gravado, a app não quebra. Teste em Task 7.
5. **CSV com BOM, linha em branco no final, ou nota com Situação "Cancelada"** — importa sem erro e a cancelada não entra nos totais. Testes em Task 2 e Task 9.

---

### Task 1: Scaffold, modelos, erros e utilitários

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `pytest.ini`, `nfg/__init__.py`, `nfg/models.py`, `nfg/erros.py`, `nfg/util.py`, `tests/__init__.py`, `tests/conftest.py`
- Test: `tests/test_util.py`

**Interfaces:**
- Produces (`nfg/models.py`, dataclasses):
  - `Estabelecimento(cnpj: str, razao_social: str, inscricao_estadual: str | None = None, endereco: str | None = None, municipio: str | None = None)`
  - `NotaResumo(chave: str, modelo: int, cnpj_emitente: str, nome_csv: str, municipio: str, numero: str, emissao: date, valor_total: Decimal, situacao: str, tipo_operacao: str)`
  - `Item(seq: int, codigo: str, descricao: str, quantidade: Decimal, unidade: str, valor_unitario: Decimal, valor_total: Decimal)`
  - `Pagamento(forma: str, valor: Decimal)`
  - `Nota(chave: str, modelo: int, emitente: Estabelecimento, numero: str, serie: str, emissao: datetime, protocolo: str | None, valor_total: Decimal, valor_descontos: Decimal, itens: list[Item], pagamentos: list[Pagamento])`
- Produces (`nfg/erros.py`): `ErroNFG(Exception)`; subclasses `ErroRede`, `NotaNaoEncontrada`, `LayoutDesconhecido`, `BloqueioSefaz`, `CSVInvalido`.
- Produces (`nfg/util.py`):
  - `parse_decimal_br(texto: str) -> Decimal` — remove `R$`, espaços e `&nbsp;`, `.` de milhar, `,`→`.`
  - `to_centavos(valor: Decimal) -> int`, `from_centavos(c: int) -> Decimal`
  - `normalizar_chave(texto: str) -> str` (só dígitos)
  - `chave_valida(chave: str) -> bool` (44 dígitos + DV módulo 11)
  - `modelo_da_chave(chave: str) -> int` (`int(chave[20:22])`), `cnpj_da_chave(chave: str) -> str` (`chave[6:20]`)
  - `normalizar_texto(texto: str) -> str` (maiúsculas, sem acento, espaços colapsados, strip)
  - `mascarar_cpf(texto: str) -> str` (`\d{3}\.\d{3}\.\d{3}-\d{2}` → `000.000.000-00`)
  - `formatar_brl(valor: Decimal | float) -> str` (`"R$ 1.234,56"`)

- [ ] **Step 1: Scaffold**

`requirements.txt`: `streamlit>=1.38`, `requests>=2.32`, `beautifulsoup4>=4.12`, `lxml>=5.0`, `pandas>=2.2`, `plotly>=5.22`, `openpyxl>=3.1`. `requirements-dev.txt`: `-r requirements.txt`, `pytest>=8`, `responses>=0.25`. `pytest.ini`: `testpaths = tests`, `markers = online: acessa a SEFAZ de verdade`, `addopts = -m "not online"`. `tests/conftest.py` define a fixture `fixtures_dir` → `Path(__file__).parent / "fixtures"`.
Run: `python -m venv .venv && .venv\Scripts\pip install -r requirements-dev.txt` → instala sem erro.

- [ ] **Step 2: Write failing tests `tests/test_util.py`**

```python
CHAVE_ZAFFARI = "43260993015006000547651210003414481604643989"
CHAVE_AMAZON  = "43260915436940001177550010445859151740147064"

def test_parse_decimal_br():
    assert parse_decimal_br("R$382,47") == Decimal("382.47")
    assert parse_decimal_br("R$1.234,56") == Decimal("1234.56")
    assert parse_decimal_br(" 0,9399 ") == Decimal("0.9399")
    assert parse_decimal_br("21,8") == Decimal("21.8")
    assert parse_decimal_br("1\xa0234,00") == Decimal("1234.00")

def test_centavos_ida_e_volta():
    assert to_centavos(Decimal("382.47")) == 38247
    assert to_centavos(Decimal("0.005")) == 1           # ROUND_HALF_UP
    assert from_centavos(38247) == Decimal("382.47")

def test_chave():
    assert normalizar_chave("4326099301500600054765 1210003414481604643989") == CHAVE_ZAFFARI
    assert chave_valida(CHAVE_ZAFFARI) and chave_valida(CHAVE_AMAZON)
    assert not chave_valida(CHAVE_ZAFFARI[:-1] + "0")   # DV errado
    assert not chave_valida("123")
    assert modelo_da_chave(CHAVE_ZAFFARI) == 65 and modelo_da_chave(CHAVE_AMAZON) == 55
    assert cnpj_da_chave(CHAVE_ZAFFARI) == "93015006000547"

def test_normalizar_texto():
    assert normalizar_texto("  Café do   Ponto ") == "CAFE DO PONTO"

def test_mascarar_cpf():
    assert mascarar_cpf("CPF: 123.456.789-09") == "CPF: 000.000.000-00"

def test_formatar_brl():
    assert formatar_brl(Decimal("1234.5")) == "R$ 1.234,50"
```

DV módulo 11: sobre os 43 primeiros dígitos, da direita para a esquerda, pesos 2..9 ciclando; `resto = soma % 11`; `dv = 0 if resto < 2 else 11 - resto`.

- [ ] **Step 3: Run** `pytest tests/test_util.py -v` → FAIL (ImportError).
- [ ] **Step 4: Implement** `nfg/models.py`, `nfg/erros.py`, `nfg/util.py` com as assinaturas acima (`normalizar_texto` via `unicodedata.normalize("NFKD")` descartando combinantes).
- [ ] **Step 5: Run** `pytest -v` → PASS.
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: scaffold, modelos e utilitários"`

---

### Task 2: Importação do CSV do NFG

**Files:**
- Create: `nfg/csv_import.py`
- Test: `tests/test_csv_import.py` (usa `tests/fixtures/relatorio_nfg.csv`)

**Interfaces:**
- Consumes: `NotaResumo`, `CSVInvalido`, `util.*` (Task 1).
- Produces: `ResultadoCSV(resumos: list[NotaResumo], invalidas: list[tuple[int, str]])` (nº da linha do arquivo, motivo) e `ler(dados: bytes) -> ResultadoCSV`.

- [ ] **Step 1: Write failing tests**

```python
def test_le_csv_real(fixtures_dir):
    r = ler((fixtures_dir / "relatorio_nfg.csv").read_bytes())
    assert len(r.resumos) == 11 and r.invalidas == []
    z = r.resumos[0]
    assert z.chave == "43260993015006000547651210003414481604643989"
    assert (z.modelo, z.cnpj_emitente, z.nome_csv) == (65, "93015006000547", "Cia Zaffari Com E Ind")
    assert (z.numero, z.emissao, z.valor_total) == ("341448", date(2026, 9, 26), Decimal("382.47"))
    assert (z.municipio, z.situacao, z.tipo_operacao) == ("Porto Alegre", "Normal", "Aquisição")
    assert [x.modelo for x in r.resumos].count(55) == 1

def test_latin1_bom_e_linha_vazia(fixtures_dir):
    texto = (fixtures_dir / "relatorio_nfg.csv").read_text("utf-8")
    assert len(ler(texto.encode("latin-1")).resumos) == 11
    assert len(ler(b"\xef\xbb\xbf" + texto.encode("utf-8") + b"\r\n\r\n").resumos) == 11

def test_chave_invalida_vira_linha_invalida(fixtures_dir):
    texto = (fixtures_dir / "relatorio_nfg.csv").read_text("utf-8").replace("1604643989", "1604643980")
    r = ler(texto.encode("utf-8"))
    assert len(r.resumos) == 10 and r.invalidas[0][0] == 2 and "chave" in r.invalidas[0][1].lower()

def test_sem_coluna_chave():
    with pytest.raises(CSVInvalido):
        ler('"a","b"\n"1","2"\n'.encode())
```

- [ ] **Step 2: Run** `pytest tests/test_csv_import.py -v` → FAIL.
- [ ] **Step 3: Implement `ler`** — decodifica `utf-8-sig`, em `UnicodeDecodeError` usa `latin-1`; `csv.DictReader`; colunas por nome do cabeçalho (`Munic.`, `Razão Social`, `Emissão`, `Número`, `Chave de Acesso`, `Valor`, `Tipo Operação`, `Situação Docto`); ignora linhas totalmente vazias; data `%d/%m/%y`; `cnpj_emitente` e `modelo` vêm da chave.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: importação do CSV do NFG`

---

### Task 3: Parser do HTML da NFC-e

**Files:**
- Create: `nfg/nfce_parser.py`
- Test: `tests/test_nfce_parser.py` (usa `tests/fixtures/nfce_zaffari.html`)

**Interfaces:**
- Consumes: `Nota`, `Item`, `Pagamento`, `Estabelecimento`, erros, `util` (Task 1).
- Produces: `parse(html: str) -> Nota`; levanta `BloqueioSefaz`, `NotaNaoEncontrada(mensagem)`, `LayoutDesconhecido`.

- [ ] **Step 1: Write failing tests**

```python
@pytest.fixture
def html(fixtures_dir):
    return (fixtures_dir / "nfce_zaffari.html").read_text("utf-8")

def test_cabecalho(html):
    n = parse(html)
    assert n.chave == "43260993015006000547651210003414481604643989" and n.modelo == 65
    e = n.emitente
    assert (e.razao_social, e.cnpj, e.inscricao_estadual) == ("COMPANHIA ZAFFARI COMERCIO E INDUSTRIA", "93015006000547", "0963144057")
    assert e.endereco == "AV SERTÓRIO, 8000, SARANDI, PORTO ALEGRE, RS" and e.municipio == "PORTO ALEGRE"
    assert (n.numero, n.serie, n.protocolo) == ("341448", "121", "143260000000002")
    assert n.emissao == datetime(2026, 9, 26, 17, 35, 15)

def test_itens(html):
    n = parse(html)
    assert len(n.itens) == 18
    assert n.itens[0] == Item(1, "000000000001069007", "FILE PTO FGO NAT DESF CG 400G", Decimal("1"), "UN", Decimal("21.8"), Decimal("21.80"))
    assert (n.itens[5].quantidade, n.itens[5].unidade) == (Decimal("0.9399"), "KG")
    assert [i.descricao for i in n.itens[14:16]] == ["BANANA PRATA GRANEL"] * 2
    assert sum(i.valor_total for i in n.itens) == Decimal("382.47")

def test_totais_e_pagamento(html):
    n = parse(html)
    assert (n.valor_total, n.valor_descontos) == (Decimal("382.47"), Decimal("0.00"))
    assert n.pagamentos == [Pagamento("Cartão de Crédito", Decimal("382.47"))]
    assert "000.000.000-00" not in repr(n)

def test_html_bruto_do_servidor(html):               # Review Focus 1
    bruto = re.sub(r"</?tbody>", "", html).replace("382,47</td>", "382,47&nbsp;</td>")
    bruto = bruto.replace("<td", "\n  <td").encode("iso-8859-1").decode("iso-8859-1")
    assert parse(bruto) == parse(html)

def test_rejeicao():
    with pytest.raises(NotaNaoEncontrada):
        parse("<html><body><div id='nfce'>NFC-e não encontrada na base de dados da SEFAZ</div></body></html>")

def test_layout_desconhecido():
    with pytest.raises(LayoutDesconhecido):
        parse("<html><body><p>Bem-vindo</p></body></html>")

def test_captcha():
    with pytest.raises(BloqueioSefaz):
        parse("<html><body><div class='g-recaptcha'></div></body></html>")
```

- [ ] **Step 2: Run** `pytest tests/test_nfce_parser.py -v` → FAIL.
- [ ] **Step 3: Implement `parse`** com `BeautifulSoup(html, "lxml")`, seguindo os seletores do spec §2. Ordem: "captcha" no HTML (case-insensitive) → `BloqueioSefaz`; sem `table.NFCCabecalho` → se o texto contém `não encontrad`, `inexistente`, `rejei`, `inválid` ou `erro` → `NotaNaoEncontrada(texto[:200])`, senão `LayoutDesconhecido`. Cabeçalho via regex sobre o texto normalizado de espaços (`NFC-e nº:\s*(\d+)\s*Série:\s*(\d+)\s*Data de Emissão:\s*(\S+ \S+)`, `Protocolo de Autorização:\s*(\d+)`, `CNPJ:\s*([\d./-]+)`, `Inscrição Estadual:\s*(\S+)`). Chave = dígitos do `td` logo após "CHAVE DE ACESSO". Endereço: partes separadas por vírgula, cada uma com espaços colapsados, unidas por `", "`; município = penúltima parte. Itens: `tr[id^="Item"]`, `seq` = posição (1-based). Faltando campo obrigatório → `LayoutDesconhecido`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: parser do HTML da NFC-e`

---

### Task 4: Parser do XML da NF-e

**Files:**
- Create: `nfg/nfe_xml_parser.py`, `tests/fixtures/nfe_exemplo.xml`
- Test: `tests/test_nfe_xml_parser.py`

**Interfaces:**
- Consumes: modelos, erros, `util` (Task 1).
- Produces: `parse(dados: bytes) -> Nota`; `LayoutDesconhecido` para XML inválido ou que não é NF-e.

- [ ] **Step 1: Criar fixture sintética** `nfe_exemplo.xml`: raiz `nfeProc` (namespace `http://www.portalfiscal.inf.br/nfe`) contendo `NFe/infNFe Id="NFe43260915436940001177550010445859151740147064"`; `ide`: `nNF=44585915`, `serie=1`, `dhEmi=2026-09-24T10:15:00-03:00`; `emit`: `CNPJ=15436940001177`, `xNome=AMAZON SERVICOS DE VAREJO DO BRASIL LTDA.`, `IE=0960000000`, `enderEmit` (`xLgr=AV ANTONIO FRANCISCO DA SILVA`, `nro=1000`, `xBairro=DISTRITO INDUSTRIAL`, `xMun=NOVA SANTA RITA`, `UF=RS`); `det nItem=1` `prod`: `cProd=B0TESTE001`, `xProd=CABO USB-C 1M`, `qCom=2.0000`, `uCom=UN`, `vUnCom=15.4200000000`, `vProd=30.84`; `det nItem=2`: `B0TESTE002`, `LAMPADA LED 9W`, `1.0000`, `UN`, `30.0000000000`, `30.00`; `total/ICMSTot`: `vNF=60.84`, `vDesc=0.00`; `pag/detPag`: `tPag=03`, `vPag=60.84`; `protNFe/infProt/nProt=143260000000001`. Dados fictícios.
- [ ] **Step 2: Write failing tests**

```python
def test_nfe(fixtures_dir):
    n = parse((fixtures_dir / "nfe_exemplo.xml").read_bytes())
    assert n.chave == "43260915436940001177550010445859151740147064" and n.modelo == 55
    assert n.emitente.cnpj == "15436940001177" and n.emitente.municipio == "NOVA SANTA RITA"
    assert (n.numero, n.serie, n.protocolo) == ("44585915", "1", "143260000000001")
    assert n.emissao == datetime(2026, 9, 24, 10, 15, 0)            # hora local, sem tz
    assert n.itens[0] == Item(1, "B0TESTE001", "CABO USB-C 1M", Decimal("2.0000"), "UN", Decimal("15.4200000000"), Decimal("30.84"))
    assert (n.valor_total, n.valor_descontos) == (Decimal("60.84"), Decimal("0.00"))
    assert n.pagamentos == [Pagamento("Cartão de Crédito", Decimal("60.84"))]

def test_xml_invalido():
    with pytest.raises(LayoutDesconhecido):
        parse(b"<html>nada</html>")
```

- [ ] **Step 3: Run** → FAIL.
- [ ] **Step 4: Implement** com `xml.etree.ElementTree` e o namespace; aceita raiz `nfeProc` ou `NFe`. Mapa `tPag`: `01` Dinheiro, `02` Cheque, `03` Cartão de Crédito, `04` Cartão de Débito, `05` Crédito Loja, `10` Vale Alimentação, `11` Vale Refeição, `15` Boleto Bancário, `17` PIX, outros → `Outros`. Endereço = `xLgr, nro, xBairro, xMun, UF`.
- [ ] **Step 5: Run** → PASS. **Step 6: Commit** `feat: parser do XML da NF-e`

---

### Task 5: Cliente HTTP da SEFAZ

**Files:**
- Create: `nfg/sefaz_client.py`
- Test: `tests/test_sefaz_client.py`

**Interfaces:**
- Consumes: `ErroRede`, `BloqueioSefaz` (Task 1).
- Produces: constantes `URL_ETAPA1`, `URL_ETAPA2`; `class SefazClient(session: requests.Session | None = None, timeout: float = 20, backoffs: tuple[float, ...] = (2, 5), sleep: Callable[[float], None] = time.sleep)` com `buscar(chave: str) -> str`.

- [ ] **Step 1: Write failing tests** (com `responses`, `sleep=lambda s: None`)

```python
CH = "43260993015006000547651210003414481604643989"

@responses.activate
def test_get_depois_post_com_form_correto():
    responses.get(URL_ETAPA1, body="form")
    responses.post(URL_ETAPA2, body="<html>Cartão</html>".encode("iso-8859-1"))
    html = SefazClient(sleep=lambda s: None).buscar(CH)
    assert "Cartão" in html
    assert [c.request.method for c in responses.calls] == ["GET", "POST"]
    assert f"chaveNFe={CH}" in responses.calls[0].request.url
    corpo = responses.calls[1].request.body
    assert f"chaveNFe={CH}" in corpo and "HML=false" in corpo and "Action=Avan%E7ar" in corpo

@responses.activate
def test_retry_em_5xx_e_desiste():
    responses.get(URL_ETAPA1, body="form")
    responses.post(URL_ETAPA2, status=503)
    with pytest.raises(ErroRede):
        SefazClient(sleep=lambda s: None).buscar(CH)
    assert sum(c.request.method == "POST" for c in responses.calls) == 3

@responses.activate
def test_retry_recupera():
    responses.get(URL_ETAPA1, body="form")
    responses.post(URL_ETAPA2, body=requests.ConnectionError())
    responses.post(URL_ETAPA2, body="<html>ok</html>")
    assert "ok" in SefazClient(sleep=lambda s: None).buscar(CH)

@pytest.mark.parametrize("status", [403, 429])
@responses.activate
def test_bloqueio(status):
    responses.get(URL_ETAPA1, body="form")
    responses.post(URL_ETAPA2, status=status)
    with pytest.raises(BloqueioSefaz):
        SefazClient(sleep=lambda s: None).buscar(CH)
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — cada tentativa faz GET etapa 1 + POST etapa 2 (`data={"HML": "false", "chaveNFe": chave, "Action": "Avançar".encode("iso-8859-1")}`, header `Referer: URL_ETAPA1`); `ConnectionError`/`Timeout`/status ≥ 500 → dorme `backoffs[i]` e tenta de novo, esgotou → `ErroRede`; 403/429 → `BloqueioSefaz` imediato; retorna `resp.content.decode("iso-8859-1")`. Header `User-Agent` identificando o app (`NFG-Compras/1.0 (uso pessoal)`).
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat: cliente HTTP da SEFAZ`

---

### Task 6: Banco SQLite e repositório

**Files:**
- Create: `nfg/db.py`, `nfg/config.py`
- Test: `tests/test_db.py`; adicionar a `tests/conftest.py` as fixtures `repo` (Repositorio em `:memory:`) e `nota_zaffari` (`nfce_parser.parse` da fixture)

**Interfaces:**
- Consumes: modelos, `util` (Task 1); `nfce_parser.parse` só nos testes.
- Produces (`nfg/db.py`):
  - `conectar(caminho: str | Path) -> sqlite3.Connection` — `row_factory=sqlite3.Row`, `PRAGMA foreign_keys=ON`, cria o schema exato do spec §4 (`CREATE TABLE IF NOT EXISTS`), `check_same_thread=False`.
  - `class Repositorio(conn)` com atributo `conn` e métodos:
    - `importar_resumos(resumos: list[NotaResumo]) -> dict[str, int]` → chaves `novas`, `existentes`, `nfe`
    - `pendentes(max_tentativas: int = 3) -> list[str]` (modelo 65 e (`pendente` ou (`erro` e `tentativas < max`))), ordem de emissão
    - `salvar_nota(nota: Nota, aviso: str | None = None) -> None`
    - `registrar_erro(chave: str, mensagem: str, definitivo: bool) -> None`
    - `contagem_status() -> dict[str, int]`
    - `itens_da_nota(chave: str) -> list[sqlite3.Row]`, `pagamentos_da_nota(chave: str) -> list[sqlite3.Row]`
- Produces (`nfg/config.py`): `data_dir() -> Path` (env `NFG_DATA_DIR` ou `<projeto>/data`, cria se faltar), `html_dir() -> Path` (`data_dir()/"html_bruto"`), `abrir_repo() -> Repositorio` (conecta em `data_dir()/"nfg.db"` e chama `categorias.garantir_seed`; essa chamada entra na Task 7).

- [ ] **Step 1: Write failing tests**

```python
def test_importar_e_idempotencia(repo, fixtures_dir):             # Review Focus 2
    resumos = ler((fixtures_dir / "relatorio_nfg.csv").read_bytes()).resumos
    assert repo.importar_resumos(resumos) == {"novas": 11, "existentes": 0, "nfe": 1}
    assert repo.importar_resumos(resumos) == {"novas": 0, "existentes": 11, "nfe": 1}
    assert repo.contagem_status() == {"pendente": 10, "sem_itens": 1}
    assert len(repo.pendentes()) == 10

def test_salvar_nota_e_nao_rebaixar(repo, fixtures_dir, nota_zaffari):
    resumos = ler((fixtures_dir / "relatorio_nfg.csv").read_bytes()).resumos
    repo.importar_resumos(resumos)
    repo.salvar_nota(nota_zaffari)
    repo.importar_resumos(resumos)
    row = repo.conn.execute("select * from notas where chave=?", (nota_zaffari.chave,)).fetchone()
    assert row["status"] == "coletada" and row["valor_total_centavos"] == 38247
    assert row["emissao"] == "2026-09-26T17:35:15"
    itens = repo.itens_da_nota(nota_zaffari.chave)
    assert len(itens) == 18 and itens[5]["quantidade"] == "0.9399" and itens[0]["valor_unitario"] == "21.8"
    assert repo.pagamentos_da_nota(nota_zaffari.chave)[0]["valor_centavos"] == 38247
    assert repo.conn.execute("select razao_social from estabelecimentos where cnpj='93015006000547'").fetchone()[0] == "COMPANHIA ZAFFARI COMERCIO E INDUSTRIA"

def test_salvar_duas_vezes_substitui_itens(repo, nota_zaffari):
    repo.salvar_nota(nota_zaffari); repo.salvar_nota(nota_zaffari)   # nota fora do CSV também é criada
    assert len(repo.itens_da_nota(nota_zaffari.chave)) == 18

def test_registrar_erro(repo, fixtures_dir):
    repo.importar_resumos(ler((fixtures_dir / "relatorio_nfg.csv").read_bytes()).resumos)
    a, b = repo.pendentes()[:2]
    repo.registrar_erro(a, "timeout", definitivo=False)
    repo.registrar_erro(b, "não encontrada", definitivo=True)
    assert a in repo.pendentes() and b not in repo.pendentes()

def test_cascade(repo, nota_zaffari):
    repo.salvar_nota(nota_zaffari)
    repo.conn.execute("delete from notas")
    assert repo.conn.execute("select count(*) from itens").fetchone()[0] == 0
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — `importar_resumos` faz `INSERT ... ON CONFLICT(chave) DO NOTHING` em `notas` (status `pendente`/`sem_itens`, `emissao` = data ISO) e `INSERT OR IGNORE` em `estabelecimentos` (cnpj, `nome_csv`, município); `salvar_nota` usa `with conn:` para um upsert de estabelecimento (preenche `razao_social`/IE/endereço sem apagar `nome_csv`), upsert da nota (status `coletada`, `erro_msg=NULL`, `aviso`, `coletada_em`), `DELETE` + `INSERT` de itens e pagamentos; quantidade e valor unitário gravados com `str(Decimal)`. `registrar_erro`: `status='erro'`, `erro_msg`, `tentativas = 3 if definitivo else tentativas + 1`.
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat: banco SQLite e repositório`

---

### Task 7: Categorias

**Files:**
- Create: `nfg/categorias.py`
- Modify: `nfg/config.py` (`abrir_repo` chama `garantir_seed`)
- Test: `tests/test_categorias.py`

**Interfaces:**
- Consumes: `Repositorio`/`conectar` (Task 6), `normalizar_texto` (Task 1).
- Produces:
  - `garantir_seed(conn) -> None` (insere categorias e regras padrão só se `categorias` estiver vazia)
  - `class Classificador(conn)` com `categoria(cnpj: str, codigo: str, descricao: str) -> str`
  - `categorizar_df(conn, df: pd.DataFrame) -> pd.DataFrame` (precisa das colunas `cnpj`, `codigo`, `descricao`; acrescenta `categoria`)
  - CRUD: `listar_categorias(conn) -> list[Row]`, `criar_categoria(conn, nome: str) -> int`, `excluir_categoria(conn, id: int)`, `listar_regras(conn) -> list[Row]` (com `categoria` = nome), `salvar_regra(conn, padrao: str, categoria_id: int, prioridade: int = 100, id: int | None = None) -> int` (`ValueError` se a regex for inválida), `excluir_regra(conn, id: int)`, `definir_manual(conn, cnpj: str, codigo: str, categoria_id: int | None)` (`None` remove), `contar_casamentos(conn, padrao: str) -> int`
  - constante `SEM_CATEGORIA = "Sem categoria"`

Seed (`padrão`, categoria, prioridade). Regex `re.IGNORECASE` aplicada a `normalizar_texto(descricao)`:

| Categoria | Padrão | Prio |
|---|---|---|
| Doces/Snacks | `\b(BISC\|CHOC\|BALA\b\|SALGADINHO\|TWIX\|BOMBOM\|SORVETE\|WAFER)` | 40 |
| Bebidas | `\b(REFRIG\|COCA\b\|SUCO\|AGUA\b\|CERVEJA\|VINHO\|ENERG\|RED BULL\|CHA\b)` | 40 |
| Hortifruti | `\b(BANANA\|LARANJA\|MACA\b\|CEBOLA\|TOMATE\|BATATA\|ALFACE\|LIMAO\|MAMAO\|CENOURA\|ALHO\b\|UVA\b\|MORANGO\|ABACATE)` | 50 |
| Padaria | `\b(PAO\b\|PAES\b\|BROWNIE\|BOLO\b\|CUCA\b\|TORRADA\|SONHO\b)` | 50 |
| Carnes | `\b(FILE\b\|CARNE\|FRANGO\|PATINHO\|ALCATRA\|COSTELA\|LINGUICA\|PICANHA\|BIFE\|COXA\|PEIXE\|SALMAO\|TILAPIA)` | 50 |
| Laticínios/Frios | `\b(LEITE\|QUEIJO\|IOG\|MANTEIGA\|REQUEIJAO\|PRESUNTO\|MUSSARELA\|OVO\b\|OVOS\b)` | 50 |
| Mercearia | `\b(CAFE\b\|ARROZ\|FEIJAO\|MASSA\|MACARRAO\|FARINHA\|ACUCAR\|OLEO\b\|AZEITE\|MILHO\|ERVILHA\|MOLHO\|SAL\b\|CANELA\|TEMPERO\|AVEIA)` | 50 |
| Limpeza | `\b(DETERG\|SABAO\|AMACIANTE\|DESINF\|ALVEJ\|ESPONJA\|LIMPADOR\|SACO LIXO\|PAPEL TOALHA)` | 50 |
| Higiene | `\b(SHAMPOO\|CONDIC\|SABONETE\|CREME DENTAL\|ESCOVA\|DESOD\|PAPEL HIG\|FIO DENTAL\|ABSORV)` | 50 |
| Hortifruti | `\bGRANEL\b` | 200 |
| Outros | (sem regra) | — |

Empate de prioridade → menor `id` primeiro (ordem de inserção da tabela).

- [ ] **Step 1: Write failing tests**

```python
@pytest.fixture
def conn(repo):
    garantir_seed(repo.conn); return repo.conn

@pytest.mark.parametrize("desc,cat", [
    ("BANANA PRATA GRANEL", "Hortifruti"), ("PAO CACETINHO *", "Padaria"),
    ("FILE PTO FGO NAT DESF CG 400G", "Carnes"), ("CAFE DO PONTO EXPORTACAO 500G", "Mercearia"),
    ("ENERG RED BULL 473ML", "Bebidas"), ("BISC ANELU AMANT GOIABA 350G", "Doces/Snacks"),
    ("OVO CAIP G LIVR FILIPPSEN C/20", "Laticínios/Frios"), ("MACA TURMA DA MONICA 1KG", "Hortifruti"),
    ("CEBOLA BRANCA GRANEL", "Hortifruti"), ("PARAFUSO 3MM", "Sem categoria"),
])
def test_regras_seed(conn, desc, cat):
    assert Classificador(conn).categoria("93015006000547", "X", desc) == cat

def test_manual_vence_regra(conn):
    outros = next(c["id"] for c in listar_categorias(conn) if c["nome"] == "Outros")
    definir_manual(conn, "93015006000547", "000000000001001609", outros)
    assert Classificador(conn).categoria("93015006000547", "000000000001001609", "BANANA PRATA GRANEL") == "Outros"
    assert Classificador(conn).categoria("11111111111111", "000000000001001609", "BANANA PRATA GRANEL") == "Hortifruti"

def test_prioridade(conn):
    pet = criar_categoria(conn, "Pet")
    salvar_regra(conn, r"\bBISC", pet, prioridade=10)
    assert Classificador(conn).categoria("1", "2", "BISC CACHORRO") == "Pet"

def test_regex_invalida(conn):                                   # Review Focus 4
    n = len(listar_regras(conn))
    with pytest.raises(ValueError):
        salvar_regra(conn, "(", criar_categoria(conn, "X"))
    assert len(listar_regras(conn)) == n

def test_seed_idempotente(conn):
    garantir_seed(conn)
    assert len(listar_categorias(conn)) == 10
```

Também: `test_contar_casamentos` (com `nota_zaffari` salva, `contar_casamentos(conn, r"\bBANANA") == 2`) e `test_categorizar_df` (DataFrame de 2 linhas → coluna `categoria` correta).

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — `Classificador` carrega regras (compiladas, ordenadas por `prioridade, id`) e o dict manual uma vez no `__init__`.
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat: categorias por regras e ajuste manual`

---

### Task 8: Orquestração da coleta

**Files:**
- Create: `nfg/coleta.py`
- Test: `tests/test_coleta.py`

**Interfaces:**
- Consumes: `Repositorio` (Task 6), `nfce_parser.parse` (Task 3), `nfe_xml_parser.parse` (Task 4), erros e `mascarar_cpf`/`formatar_brl` (Task 1); cliente com `buscar(chave) -> str` (Task 5).
- Produces:
  - `Progresso(i: int, total: int, chave: str, ok: bool, mensagem: str)`, `ResultadoLote(coletadas: int, erros: int, interrompido: bool, motivo: str | None)`
  - `validar_totais(nota: Nota) -> str | None` (aviso se `|Σ itens − descontos − total| > 0,01`)
  - `coletar(repo, cliente, dir_html: Path, on_progress: Callable[[Progresso], None] = lambda p: None, pausa: float = 1.5, sleep: Callable[[float], None] = time.sleep) -> ResultadoLote`
  - `reprocessar_html(repo, dir_html: Path) -> ResultadoLote`
  - `anexar_xml(repo, dados: bytes) -> Nota`

- [ ] **Step 1: Write failing tests** — `ClienteFalso(respostas: dict[str, str | Exception])` cuja `buscar` devolve o HTML ou levanta a exceção; o repo é criado a partir do CSV real.

```python
def test_lote_misto(repo_csv, html_zaffari, tmp_path):
    z = "43260993015006000547651210003414481604643989"
    outras = [c for c in repo_csv.pendentes() if c != z]
    respostas = {z: html_zaffari, outras[0]: ErroRede("timeout"),
                 outras[1]: "<html><body>NFC-e não encontrada</body></html>"}
    respostas |= {c: "<html><body><p>x</p></body></html>" for c in outras[2:]}
    eventos, pausas = [], []
    r = coletar(repo_csv, ClienteFalso(respostas), tmp_path, eventos.append, sleep=pausas.append)
    assert (r.coletadas, r.erros, r.interrompido) == (1, 9, False)
    assert len(eventos) == 10 and len(pausas) == 9
    assert any(e.ok and "18 itens" in e.mensagem for e in eventos)
    assert (tmp_path / f"{z}.html").exists()
    assert "000.000.000-00" in (tmp_path / f"{z}.html").read_text("utf-8")
    assert outras[0] in repo_csv.pendentes() and outras[1] not in repo_csv.pendentes()

def test_bloqueio_interrompe(repo_csv, tmp_path):
    respostas = {c: BloqueioSefaz("403") for c in repo_csv.pendentes()}
    r = coletar(repo_csv, ClienteFalso(respostas), tmp_path, sleep=lambda s: None)
    assert r.interrompido and r.erros == 1 and "403" in r.motivo

def test_chave_divergente_nao_grava(repo_csv, html_zaffari, tmp_path):   # Review Focus 3
    outra = [c for c in repo_csv.pendentes() if c != "43260993015006000547651210003414481604643989"][0]
    coletar(repo_csv, ClienteFalso({c: html_zaffari for c in repo_csv.pendentes()}), tmp_path, sleep=lambda s: None)
    assert repo_csv.conn.execute("select status from notas where chave=?", (outra,)).fetchone()[0] == "erro"

def test_reprocessar(repo_csv, html_zaffari, tmp_path):
    (tmp_path / "43260993015006000547651210003414481604643989.html").write_text(html_zaffari, "utf-8")
    assert reprocessar_html(repo_csv, tmp_path).coletadas == 1

def test_anexar_xml_completa_nfe(repo_csv, fixtures_dir):
    nota = anexar_xml(repo_csv, (fixtures_dir / "nfe_exemplo.xml").read_bytes())
    row = repo_csv.conn.execute("select status from notas where chave=?", (nota.chave,)).fetchone()
    assert row[0] == "coletada" and len(repo_csv.itens_da_nota(nota.chave)) == 2

def test_validar_totais(nota_zaffari):
    assert validar_totais(nota_zaffari) is None
    assert "soma" in validar_totais(replace(nota_zaffari, valor_total=Decimal("400.00"))).lower()
```

(Fixtures `repo_csv` e `html_zaffari` entram em `tests/conftest.py`.)

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement `coletar`** — para cada chave de `repo.pendentes()`: `buscar` → `mascarar_cpf` → grava `dir_html/<chave>.html` (utf-8) → `parse` → se `nota.chave != chave` → `LayoutDesconhecido("chave divergente")` → `repo.salvar_nota(nota, validar_totais(nota))`. `ErroRede`/`LayoutDesconhecido` → `registrar_erro(definitivo=False)`; `NotaNaoEncontrada` → `definitivo=True`; `BloqueioSefaz` → `registrar_erro(definitivo=False)`, emite progresso e retorna `interrompido=True`, `motivo=str(e)`. Mensagem de sucesso: `f"✓ {razao_social} {dd/mm} — {n} itens — {formatar_brl(total)}"`; de erro: `f"⚠ {chave[-8:]} — {tipo}: {msg}"`. `sleep(pausa)` entre notas, nunca após a última. `reprocessar_html` aplica `parse` + `salvar_nota` a cada `*.html` (o nome do arquivo é a chave), sem rede e sem pausa.
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat: orquestração da coleta`

---

### Task 9: Análises

**Files:**
- Create: `nfg/analises.py`
- Test: `tests/test_analises.py`; adicionar a `tests/conftest.py` a fixture `repo_dados`

**Interfaces:**
- Consumes: `Repositorio` (Task 6), `categorizar_df`/`garantir_seed` (Task 7), `normalizar_texto` (Task 1).
- Produces (todos com `conn` e, onde indicado, `inicio: date | None = None, fim: date | None = None`; valores em `float`):
  - `notas_df(conn) -> DataFrame[chave, modelo, emissao, mes, loja, cnpj, valor_total, status, aviso, erro_msg, situacao_csv, tipo_operacao, num_itens]` — todas as notas; `loja = coalesce(razao_social, nome_csv)`; `mes = "YYYY-MM"`
  - `itens_df(conn, inicio, fim) -> DataFrame[chave, emissao, mes, loja, cnpj, seq, codigo, descricao, descricao_norm, quantidade, unidade, valor_unitario, valor_total, categoria]` (só notas válidas)
  - `gasto_mensal(conn, inicio, fim) -> DataFrame[mes, total, compras, ticket_medio]`
  - `gasto_mensal_por_categoria(conn, inicio, fim) -> DataFrame[mes, categoria, total]`
  - `gasto_por_loja(conn, inicio, fim) -> DataFrame[loja, total, visitas, ticket_medio]` (ordem decrescente de total)
  - `gasto_por_categoria(conn, inicio, fim) -> DataFrame[categoria, total, participacao]` (participação em %)
  - `ranking_produtos(conn, inicio, fim, por: Literal["valor", "frequencia"] = "valor", n: int = 20) -> DataFrame[descricao_norm, total, compras, quantidade]` (`compras` = nº de notas distintas; "frequencia" ordena por `compras`, desempate por `total`)
  - `historico_preco(conn, busca: str) -> DataFrame[emissao, loja, descricao, valor_unitario, unidade]` (todas as palavras de `normalizar_texto(busca)` contidas em `descricao_norm`; ordem cronológica)
  - `resumo_mes(conn, mes: str) -> dict` com `total`, `variacao_pct` (`None` sem mês anterior), `compras`, `ticket_medio`, `pendentes` (pendente + erro)
  - `meses_disponiveis(conn) -> list[str]` (decrescente)
  - `exportar_excel(planilhas: dict[str, DataFrame]) -> bytes`

`repo_dados`: seed + `nota_zaffari` (set/2026) + duas notas sintéticas salvas com `salvar_nota`: chave `"1"*44`, Atacadão (`75315333008860`, `ATACADAO S.A.`), 2026-08-10 10:00, itens `ARROZ TIO JOAO 5KG` 1 UN 25.00 e `COCA COLA 2L` 2 UN 9.00 → 18.00, total 43.00; chave `"2"*44`, Zaffari, 2026-08-20 18:00, item `CAFE DO PONTO EXPORTACAO 500G` 1 UN 26.90, total 26.90; e uma quarta nota, chave `"3"*44`, Atacadão, 2026-08-15, total 999.00, sem itens, com `situacao_csv='Cancelada'` (via `UPDATE` após salvar).

- [ ] **Step 1: Write failing tests**

```python
def test_gasto_mensal_ignora_cancelada(repo_dados):              # Review Focus 5
    df = gasto_mensal(repo_dados.conn).set_index("mes")
    assert df.loc["2026-08", "total"] == pytest.approx(69.90) and df.loc["2026-08", "compras"] == 2
    assert df.loc["2026-08", "ticket_medio"] == pytest.approx(34.95)
    assert df.loc["2026-09", "total"] == pytest.approx(382.47)

def test_por_loja(repo_dados):
    df = gasto_por_loja(repo_dados.conn)
    assert list(df["loja"]) == ["COMPANHIA ZAFFARI COMERCIO E INDUSTRIA", "ATACADAO S.A."]
    assert df.iloc[0]["total"] == pytest.approx(409.37) and df.iloc[0]["visitas"] == 2

def test_por_categoria(repo_dados):
    df = gasto_por_categoria(repo_dados.conn).set_index("categoria")
    assert df["total"].sum() == pytest.approx(452.37)
    assert df.loc["Bebidas", "total"] == pytest.approx(36.49)
    assert df["participacao"].sum() == pytest.approx(100)

def test_filtro_periodo(repo_dados):
    df = gasto_mensal(repo_dados.conn, inicio=date(2026, 9, 1), fim=date(2026, 9, 30))
    assert list(df["mes"]) == ["2026-09"]

def test_historico_preco(repo_dados):
    df = historico_preco(repo_dados.conn, "café do ponto")
    assert list(df["valor_unitario"]) == pytest.approx([26.90, 28.90])

def test_ranking(repo_dados):
    df = ranking_produtos(repo_dados.conn, por="frequencia", n=1)
    assert df.iloc[0]["descricao_norm"] == "CAFE DO PONTO EXPORTACAO 500G" and df.iloc[0]["compras"] == 2
    assert ranking_produtos(repo_dados.conn, por="valor", n=1).iloc[0]["descricao_norm"] == "CAFE DO PONTO EXPORTACAO 500G"

def test_resumo_mes(repo_dados):
    r = resumo_mes(repo_dados.conn, "2026-09")
    assert r["total"] == pytest.approx(382.47) and r["variacao_pct"] == pytest.approx(447.17, abs=0.01)
    assert resumo_mes(repo_dados.conn, "2026-08")["variacao_pct"] is None

def test_exportar_excel(repo_dados):
    dados = exportar_excel({"Mensal": gasto_mensal(repo_dados.conn)})
    assert pd.read_excel(io.BytesIO(dados), sheet_name="Mensal").shape[0] == 2
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** — SQL → `pd.read_sql_query`; centavos ÷ 100; `quantidade`/`valor_unitario` via `float`; `descricao_norm` com `normalizar_texto`; categorias via `categorizar_df`. Totais mensais e por loja usam `notas.valor_total_centavos` (inclui NF-e sem itens); por categoria e ranking usam itens. `exportar_excel` usa `pd.ExcelWriter(engine="openpyxl")` num `BytesIO`.
- [ ] **Step 4: Run** → PASS. **Step 5: Commit** `feat: análises`

---

### Task 10: UI — Início, Importar, Notas

**Files:**
- Create: `app.py`, `pages/1_Importar.py`, `pages/2_Notas.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: `config.abrir_repo/html_dir` (Tasks 6 e 7), `csv_import.ler` (Task 2), `coleta.coletar/reprocessar_html/anexar_xml` (Task 8), `SefazClient` (Task 5), `analises.resumo_mes/meses_disponiveis/gasto_mensal/notas_df` (Task 9), `Classificador` (Task 7), `formatar_brl` (Task 1).

Telas conforme o spec §6. Cada página abre o repositório no início do script (`repo = abrir_repo()`). Na coleta, o botão "Baixar notas pendentes (N)" fica desabilitado quando N = 0; `st.progress` + `st.status` com o log de cada `Progresso`; ao terminar, `st.success` ou, se interrompido, `st.error(f"Coleta interrompida: {motivo}. Tente mais tarde.")`. A importação mostra a prévia (`st.dataframe` dos resumos), um botão "Importar" e o resultado `"{novas} novas, {existentes} já existentes, {nfe} NF-e aguardando XML, {invalidas} inválidas"`; as linhas inválidas são listadas. O upload de XML aceita vários arquivos e mostra o resultado por arquivo, com o erro amigável em `LayoutDesconhecido`. Na tela Notas, o status aparece com os ícones ✓ coletada, ⏳ pendente, ⚠ erro e 📎 sem_itens; a seleção usa `st.dataframe(on_select="rerun", selection_mode="single-row")`, e o detalhe mostra os itens com categoria, os pagamentos, o aviso/erro e o botão "Tentar novamente" (zera `tentativas`, volta a `pendente`). Para isso, adicionar `Repositorio.reabrir(chave: str) -> None` em `nfg/db.py` com um teste em `tests/test_db.py`.

- [ ] **Step 1: Write failing smoke tests**

```python
@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch, nota_zaffari):
    monkeypatch.setenv("NFG_DATA_DIR", str(tmp_path))
    from nfg.config import abrir_repo
    abrir_repo().salvar_nota(nota_zaffari)

@pytest.mark.parametrize("arquivo", ["app.py", "pages/1_Importar.py", "pages/2_Notas.py"])
def test_pagina_carrega(arquivo):
    at = AppTest.from_file(str(RAIZ / arquivo), default_timeout=30).run()   # RAIZ = Path(__file__).parent.parent
    assert not at.exception

def test_inicio_mostra_total():
    at = AppTest.from_file(str(RAIZ / "app.py")).run()
    assert any("382,47" in m.value for m in at.metric)
```

Mais `test_reabrir` em `tests/test_db.py`: depois de `registrar_erro(definitivo=True)` + `reabrir`, a chave volta a `pendentes()`.

- [ ] **Step 2: Run** `pytest tests/test_ui.py tests/test_db.py -v` → FAIL.
- [ ] **Step 3: Implement** as três páginas e `reabrir`. `st.set_page_config(page_title="NFG Compras", page_icon="🧾", layout="wide")` em cada página.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Manual** `streamlit run app.py`: importar `tests/fixtures/relatorio_nfg.csv` → mensagem "11 novas…"; a tela Notas lista 11 notas.
- [ ] **Step 6: Commit** `feat: UI início, importação e notas`

---

### Task 11: UI — Análises e Categorias

**Files:**
- Create: `pages/3_Análises.py`, `pages/4_Categorias.py`
- Modify: `tests/test_ui.py`

**Interfaces:**
- Consumes: todas as funções de `analises` (Task 9) e o CRUD de `categorias` (Task 7).

Análises: filtro de período global (`st.date_input` com intervalo; padrão = tudo) e 5 abas conforme o spec §6. Gráficos Plotly: barras empilhadas por categoria (Mensal), barras horizontais (Por loja), rosca + linhas mensais (Por categoria), barras (Ranking, com seletor valor/frequência e N), linha por loja (Histórico de preço, com `st.text_input` de busca). Cada aba tem `st.download_button` "Baixar CSV" (`df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")`) e "Baixar Excel" (`exportar_excel`). No rodapé, "Exportação completa (.xlsx)" com as planilhas Notas (`notas_df`) e Itens (`itens_df`). Sem dados → `st.info("Nenhuma nota coletada ainda. Vá em Importar.")`.

Categorias: tabela de categorias com criar/excluir; regras em `st.data_editor` (padrão, categoria, prioridade) com botão "Salvar", em que `ValueError` vira `st.error` e as demais regras continuam salvas; campo "Testar padrão" (`st.text_input(key="testar_padrao")`) mostra `contar_casamentos`; regex inválida → `st.error` (`contar_casamentos` também levanta `ValueError` para regex inválida). Lista "Sem categoria": itens agrupados por (cnpj, codigo, descricao) com total gasto, ordem decrescente, em `st.data_editor` com coluna `SelectboxColumn` de categoria → "Aplicar" chama `definir_manual`.

- [ ] **Step 1: Write failing smoke tests** — incluir `"pages/3_Análises.py"` e `"pages/4_Categorias.py"` no parametrize, e mais:

```python
def test_analises_sem_dados(tmp_path, monkeypatch):
    monkeypatch.setenv("NFG_DATA_DIR", str(tmp_path / "vazio"))
    at = AppTest.from_file(str(RAIZ / "pages/3_Análises.py")).run()
    assert not at.exception and any("Nenhuma nota" in i.value for i in at.info)

def test_regra_invalida_mostra_erro():
    at = AppTest.from_file(str(RAIZ / "pages/4_Categorias.py")).run()
    at.text_input(key="testar_padrao").input("(").run()
    assert not at.exception and at.error
```

(A fixture autouse da Task 10 usa `tmp_path` direto; em `test_analises_sem_dados` o `monkeypatch.setenv` posterior vence.)

- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** `pytest -v` → toda a suíte PASS.
- [ ] **Step 5: Commit** `feat: UI análises e categorias`

---

### Task 12: Teste online, README e verificação ponta a ponta

**Files:**
- Create: `tests/test_online.py`, `README.md`

- [ ] **Step 1: Teste online**

```python
@pytest.mark.online
def test_consulta_real_zaffari():
    nota = parse(SefazClient().buscar("43260993015006000547651210003414481604643989"))
    assert len(nota.itens) == 18 and nota.valor_total == Decimal("382.47")
```

Run: `pytest -m online -v` → PASS. Esse teste valida o Review Focus 1 contra o servidor real. Se falhar por diferença de HTML, salvar a resposta (com o CPF mascarado) como nova fixture, ajustar o parser e adicionar o caso aos testes da Task 3.

- [ ] **Step 2: README.md** em português: o que é, instalação (`python -m venv .venv`, `pip install -r requirements.txt`), `streamlit run app.py`, fluxo (exportar CSV no NFG → Importar → Baixar pendentes → anexar XML das NF-e → Análises), onde ficam os dados (`data/`), limitações (NF-e só com XML; a SEFAZ pode bloquear e o app para; o CPF não é armazenado), testes (`pytest`, `pytest -m online`).
- [ ] **Step 3: Verificação ponta a ponta** — com `NFG_DATA_DIR` num diretório temporário, `streamlit run app.py`: importar o CSV real → baixar pendentes (10 NFC-e, cerca de 15 s) → todas `coletada` ou com erro explicado → a nota Zaffari de 26/09 tem 18 itens que batem com o PDF → Início mostra setembro/2026 → Análises mostra gasto por loja e por categoria. Registrar o resultado.
- [ ] **Step 4: Run** `pytest -v` → PASS. **Step 5: Commit** `docs: README e teste online`
