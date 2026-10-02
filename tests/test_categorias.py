import pandas as pd
import pytest

from nfg.categorias import (
    Classificador,
    categorizar_df,
    contar_casamentos,
    criar_categoria,
    definir_manual,
    garantir_seed,
    listar_categorias,
    listar_regras,
    salvar_regra,
)


@pytest.fixture
def conn(repo):
    garantir_seed(repo.conn)
    return repo.conn


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
    definir_manual(conn, "93015006000547", "000000000001001609", None)
    assert Classificador(conn).categoria("93015006000547", "000000000001001609", "BANANA PRATA GRANEL") == "Hortifruti"


def test_prioridade(conn):
    pet = criar_categoria(conn, "Pet")
    salvar_regra(conn, r"\bBISC", pet, prioridade=10)
    assert Classificador(conn).categoria("1", "2", "BISC CACHORRO") == "Pet"


def test_regex_invalida(conn):
    n = len(listar_regras(conn))
    with pytest.raises(ValueError):
        salvar_regra(conn, "(", criar_categoria(conn, "X"))
    assert len(listar_regras(conn)) == n


def test_seed_idempotente(conn):
    garantir_seed(conn)
    assert len(listar_categorias(conn)) == 14


def test_contar_casamentos(repo, nota_zaffari):
    garantir_seed(repo.conn)
    repo.salvar_nota(nota_zaffari)
    assert contar_casamentos(repo.conn, r"\bBANANA") == 2
    with pytest.raises(ValueError):
        contar_casamentos(repo.conn, "(")


def test_categorizar_df(conn):
    df = pd.DataFrame([
        {"cnpj": "1", "codigo": "A", "descricao": "BANANA PRATA GRANEL"},
        {"cnpj": "1", "codigo": "B", "descricao": "PARAFUSO"},
        {"cnpj": "1", "codigo": "C", "descricao": None},
    ])
    out = categorizar_df(conn, df)
    assert list(out["categoria"]) == ["Hortifruti", "Sem categoria", "Sem categoria"]


def test_regra_invalida_no_banco(conn):
    cat = criar_categoria(conn, "Z")
    rid = conn.execute(
        "INSERT INTO regras_categoria(padrao, categoria_id, prioridade) VALUES ('(', ?, 1)", (cat,)
    ).lastrowid
    clf = Classificador(conn)
    assert clf.categoria("1", "2", "BANANA") == "Hortifruti"
    assert rid in clf.regras_invalidas


def test_padrao_longo(conn):
    n = len(listar_regras(conn))
    longo = "A" * 1001
    with pytest.raises(ValueError):
        salvar_regra(conn, longo, criar_categoria(conn, "Y"))
    assert len(listar_regras(conn)) == n
    with pytest.raises(ValueError):
        contar_casamentos(conn, longo)
