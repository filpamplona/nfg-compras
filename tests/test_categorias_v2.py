from datetime import datetime
from decimal import Decimal

import pytest

from nfg.categorias import (
    MAX_PADRAO,
    Classificador,
    conflitos_df,
    criar_categoria,
    definir_manual,
    definir_por_descricao,
    definir_regra_loja,
    garantir_seed,
    listar_categorias,
    listar_por_descricao,
    listar_regras_loja,
    salvar_regra,
)
from nfg.models import Estabelecimento, Item, Nota


@pytest.fixture
def conn(repo):
    garantir_seed(repo.conn)
    return repo.conn


def _id(conn, nome):
    return conn.execute("SELECT id FROM categorias WHERE nome=?", (nome,)).fetchone()[0]


CASOS = [
    ("AGUA SANIT.Q.BOA", "Limpeza"),
    ("PIZZA ARTESANAL SABOR PICANHA LUCCA 750G", "Pizza"),
    ("MASSA OVOS PENA RENATA 500G", "Mercearia"),
    ("MAC.RENATA PARAF.OVO", "Mercearia"),
    ("BOLO SEVEN BOYS LARANJA 250G", "Padaria"),
    ("PAO ALHO S.MASSA 400G", "Padaria"),
    ("KITKAT AO LEITE 41,5G", "Doces/Snacks"),
    ("BIBS AO LEITE 40G NEUGEBAUER", "Doces/Snacks"),
    ("LING GRANBERG C/QUEIJO RESF 500G", "Carnes"),
    ("SAPON CREM RADIUM LIMAO 450ML", "Limpeza"),
    ("LARANJA PARA SUCO GRANEL", "Hortifruti"),
    ("VAGEM MACARRAO 370G", "Hortifruti"),
    ("FAR MACA PERUANA G.SAUDE 200G", "Mercearia"),
    ("LEITE COCO DUCOCO", "Mercearia"),
    ("OLEO COCO NATURALE S/SAB 200ML", "Mercearia"),
    ("QJO PRATO S.CLARA FAT 1KG", "Laticínios/Frios"),
    ("SH CLEAR MEN QUEDA 400ML", "Higiene"),
    ("SAB DOVE E.DOCE 90G C/6 L+P-", "Higiene"),
    ("KIT SAB.SENADOR", "Higiene"),
    ("P H NEVE T.SEDA DUPL L24P21 30M", "Higiene"),
    ("L ROUP LQ OMO C.RAP A.TOT 1,4L", "Limpeza"),
    ("LAV LOUCA PASTILHA JIMO 15G C/25", "Limpeza"),
    ("VH CON TORO RESERVADO C SAU 750M", "Bebidas"),
    ("F.MIG SUINO SEARA TEMP RESF", "Carnes"),
    ("CARVAO ACACIA NEGRA FOGONERO 5KG", "Casa/Utilidades"),
    ("DESRINITE 180MG 10 COMPRIMIDOS", "Farmácia"),
    ("10% OPCIONAL", "Serviços"),
    ("SALAME MILANO S.CLARA 100G", "Laticínios/Frios"),
    ("TAPIOCA ROCHA Z.GL 1KG", "Mercearia"),
    ("BROCOLIS 300G", "Hortifruti"),
    ("CAFE DO PONTO EXPORTACAO 500G", "Mercearia"),
    ("BANANA PRATA GRANEL", "Hortifruti"),
    ("PARAFUSO 3MM", "Sem categoria"),
]


@pytest.mark.parametrize("desc,cat", CASOS)
def test_seed_revisado(conn, desc, cat):
    assert Classificador(conn).categoria("1", "X", desc) == cat


def test_seed_categorias_ordem(conn):
    assert [c["nome"] for c in listar_categorias(conn)] == [
        "Doces/Snacks", "Bebidas", "Hortifruti", "Padaria", "Carnes", "Laticínios/Frios",
        "Mercearia", "Limpeza", "Higiene", "Outros", "Pizza", "Farmácia", "Casa/Utilidades",
        "Serviços"]
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2


def test_ordem_de_decisao_completa(conn):
    cnpj, cod, desc = "111", "A", "SAB DOVE 90G"
    assert Classificador(conn).categoria(cnpj, cod, desc) == "Higiene"
    definir_regra_loja(conn, cnpj, _id(conn, "Outros"))
    assert Classificador(conn).categoria(cnpj, cod, desc) == "Outros"      # loja vence texto
    definir_por_descricao(conn, desc, _id(conn, "Bebidas"))
    assert Classificador(conn).categoria(cnpj, cod, desc) == "Bebidas"     # descricao vence loja
    definir_manual(conn, cnpj, cod, _id(conn, "Padaria"))
    assert Classificador(conn).categoria(cnpj, cod, desc) == "Padaria"     # manual vence descricao
    definir_manual(conn, cnpj, cod, None)
    assert Classificador(conn).categoria(cnpj, cod, desc) == "Bebidas"
    definir_por_descricao(conn, desc, None)
    assert Classificador(conn).categoria(cnpj, cod, desc) == "Outros"
    definir_regra_loja(conn, cnpj, None)
    assert Classificador(conn).categoria(cnpj, cod, desc) == "Higiene"
    assert Classificador(conn).categoria("1", "1", "PARAFUSO") == "Sem categoria"


def test_regra_de_loja_so_vale_para_a_loja(conn):
    definir_regra_loja(conn, "111", _id(conn, "Farmácia"))
    assert Classificador(conn).categoria("111", "A", "SHAMPOO X") == "Farmácia"
    assert Classificador(conn).categoria("222", "A", "SHAMPOO X") == "Higiene"
    definir_regra_loja(conn, "111", _id(conn, "Outros"))  # upsert
    assert Classificador(conn).categoria("111", "A", "SHAMPOO X") == "Outros"
    definir_manual(conn, "111", "A", _id(conn, "Padaria"))
    assert Classificador(conn).categoria("111", "A", "SHAMPOO X") == "Padaria"


def test_listar_regras_loja(conn):
    conn.execute("INSERT INTO estabelecimentos(cnpj, razao_social, nome_csv) VALUES ('111','Razao','csv')")
    conn.execute("INSERT INTO estabelecimentos(cnpj, nome_csv) VALUES ('222','so csv')")
    definir_regra_loja(conn, "111", _id(conn, "Outros"))
    definir_regra_loja(conn, "222", _id(conn, "Bebidas"))
    definir_regra_loja(conn, "333", _id(conn, "Pizza"))
    rows = {r["cnpj"]: r for r in listar_regras_loja(conn)}
    assert rows["111"]["loja"] == "Razao" and rows["111"]["categoria"] == "Outros"
    assert rows["222"]["loja"] == "so csv"
    assert rows["333"]["loja"] == "333" and rows["333"]["categoria_id"] == _id(conn, "Pizza")


def test_descricao_vale_em_outra_loja_e_normaliza(conn):
    definir_por_descricao(conn, "Café  do Ponto", _id(conn, "Outros"))
    clf = Classificador(conn)
    assert clf.categoria("1", "A", "CAFE DO PONTO") == "Outros"
    assert clf.categoria("2", "B", "café do ponto") == "Outros"
    assert conn.execute("SELECT descricao_norm FROM categoria_descricao").fetchone()[0] == "CAFE DO PONTO"
    definir_por_descricao(conn, "CAFE DO PONTO", _id(conn, "Bebidas"))  # upsert
    assert Classificador(conn).categoria("1", "A", "CAFE DO PONTO") == "Bebidas"
    definir_por_descricao(conn, "cafe do ponto", None)
    assert Classificador(conn).categoria("1", "A", "CAFE DO PONTO") == "Mercearia"


def test_casamentos(conn):
    clf = Classificador(conn)
    assert clf.casamentos("PIZZA ARTESANAL SABOR PICANHA") == ["Pizza", "Carnes"]
    assert clf.casamentos("PARAFUSO") == []
    assert clf.casamentos(None) == []


def _nota_conflito(repo, itens, cnpj="111", chave="1"):
    emit = Estabelecimento(cnpj, "LOJA X")
    repo.salvar_nota(Nota(chave=chave * 44, modelo=65, emitente=emit, numero="1", serie="1",
                          emissao=datetime(2026, 8, 1), protocolo=None, valor_total=Decimal(15),
                          valor_descontos=Decimal(0), itens=itens))


def _item(seq, cod, desc):
    return Item(seq, cod, desc, Decimal(1), "UN", Decimal(5), Decimal(5))


def test_conflitos_df(repo):
    garantir_seed(repo.conn)
    colunas = ["cnpj", "loja", "codigo", "descricao", "vencedora", "outras"]
    vazio = conflitos_df(repo.conn)
    assert list(vazio.columns) == colunas and vazio.empty

    _nota_conflito(repo, [_item(1, "P1", "SUCO NATURALE LARANJA INT 1L"), _item(2, "P2", "BANANA PRATA")])
    df = conflitos_df(repo.conn)
    assert len(df) == 1
    r = df.iloc[0]
    assert (r["cnpj"], r["loja"], r["codigo"]) == ("111", "LOJA X", "P1")
    assert r["vencedora"] == "Bebidas" and r["outras"] == "Hortifruti"


def test_conflitos_df_exclui_decisiva_manual_e_descricao(repo):
    garantir_seed(repo.conn)
    _nota_conflito(repo, [
        _item(1, "P1", "PIZZA DI PAOLO LOMBO 760G"),
        _item(2, "P2", "SUCO NATURALE LARANJA INT 1L"),
        _item(3, "P3", "SUCO NATURALE UVA INT 1L"),
    ])
    assert list(conflitos_df(repo.conn)["codigo"]) == ["P2", "P3"]  # pizza (^PIZZA) e decisiva
    definir_manual(repo.conn, "111", "P2", _id(repo.conn, "Hortifruti"))
    assert list(conflitos_df(repo.conn)["codigo"]) == ["P3"]
    definir_por_descricao(repo.conn, "suco naturale uva int 1l", _id(repo.conn, "Bebidas"))
    assert conflitos_df(repo.conn).empty


def test_conflitos_df_mantem_item_com_regra_de_loja(repo):
    garantir_seed(repo.conn)
    _nota_conflito(repo, [_item(1, "P1", "SUCO NATURALE LARANJA INT 1L")])
    definir_regra_loja(repo.conn, "111", _id(repo.conn, "Outros"))
    r = conflitos_df(repo.conn).iloc[0]
    assert r["vencedora"] == "Outros" and r["outras"] == "Bebidas, Hortifruti"


@pytest.mark.parametrize("desc,cat", [
    ("PIZZA DI PAOLO LOMBO 760G", "Pizza"),
    ("PIZZA ARTESANAL 1/2 CARNE DE PANELA E 1/2 MILHO COM BACON LUCCA 580G", "Pizza"),
    ("PAO HAMB PULLMAN", "Padaria"),
    ("PAO QUEIJO F.MINAS", "Padaria"),
    ("CHOC.HERSHEYS LEITE", "Doces/Snacks"),
    ("CHOC HERSHEYS AO LEITE 82G", "Doces/Snacks"),
    ("CHOCOLATE KINDER BUENO 43G AO LEITE C2", "Doces/Snacks"),
])
def test_regras_comeca_com(conn, desc, cat):
    assert Classificador(conn).categoria("1", "X", desc) == cat


def test_regra_vencedora(conn):
    clf = Classificador(conn)
    assert clf.regra_vencedora("PIZZA DI PAOLO LOMBO") == ("Pizza", r"^PIZZA\b")
    assert clf.regra_vencedora("PARAFUSO") is None


def test_max_padrao(conn):
    assert MAX_PADRAO == 1000
    cat = criar_categoria(conn, "Q")
    with pytest.raises(ValueError):
        salvar_regra(conn, "A" * 1001, cat)
    salvar_regra(conn, "A" * 1000, cat)


def test_listar_por_descricao(conn):
    assert listar_por_descricao(conn) == []
    definir_por_descricao(conn, "Café  do Ponto", _id(conn, "Outros"))
    (r,) = listar_por_descricao(conn)
    assert r["descricao_norm"] == "CAFE DO PONTO"
    assert r["categoria_id"] == _id(conn, "Outros") and r["categoria"] == "Outros"
