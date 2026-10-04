import pytest

from nfg.produtos import criar_produto, sugerir, vincular
from nfg.produtos_texto import normalizar_produto, pontuar


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


@pytest.mark.parametrize("desc,un", [("QJO MUSSARELA S.CLARA FAT 1KG", "UN"),
                                     ("QJO MUSSARELA TIROLEZ FAT 1KG", "UN"), ("QJO.MUSS.FAT.DALIA", "UND9")])
def test_mussarela_e_primeira_sugestao(catalogo, desc, un):
    c, ids = catalogo
    assert sugerir(c, desc, un)[0].produto_id == ids["muss"]


@pytest.mark.parametrize("desc", ["QJO PARMESAO PRES RAL 100G", "PAO QJO F.MINAS TRAD CG 820G"])
def test_mussarela_nunca_sugerida(catalogo, desc):
    c, ids = catalogo
    assert ids["muss"] not in [s.produto_id for s in sugerir(c, desc, "UN", n=10)]


def test_score_dalia(catalogo):
    c, ids = catalogo
    s = sugerir(c, "QJO.MUSS.FAT.DALIA", "UND9")[0]
    assert s.score == 90 and "tamanho não informado" in s.motivo


def test_score_mussarela_1kg_100(catalogo):
    c, ids = catalogo
    s = sugerir(c, "QJO MUSSARELA TIROLEZ FAT 1KG", "UN")[0]
    assert s.produto_id == ids["muss"] and s.score == 100 and "mesmo tamanho" in s.motivo


def test_prato_acima_de_mussarela(catalogo):
    c, ids = catalogo
    sugestoes = sugerir(c, "QJO PRATO S.CLARA FAT 1KG", "UN", n=10)
    assert sugestoes[0].produto_id == ids["prato"]
    muss = next(s for s in sugestoes if s.produto_id == ids["muss"])
    assert muss.score < sugestoes[0].score


def test_veto_embalagem(catalogo):
    c, ids = catalogo
    assert ids["ovo"] not in [s.produto_id for s in sugerir(c, "OVO CAIP NATURALE C/30", "UN", n=10)]


def test_veto_venda(catalogo):
    c, ids = catalogo
    assert ids["banana"] not in [s.produto_id for s in sugerir(c, "BANANA PRATA NATURALE ORG 800G", "UN", n=10)]


def test_descricao_vazia_sem_sugestoes(catalogo):
    c, ids = catalogo
    assert sugerir(c, "*", "UN") == []


def test_similares_vinculados_ajudam():
    n = normalizar_produto
    item, prod = n("QJO MUSS FAT ESPECIAL", "UN"), n("QUEIJO MUSSARELA FATIADO 1KG", "UN")
    assert pontuar(item, prod)[0] == pytest.approx(72.5)  # 70*3/4 + 20
    assert pontuar(item, prod, [n("QJO.MUSS.FAT.ESPECIAL.DALIA", "UND9")])[0] == 90


def test_sugerir_usa_descricoes_vinculadas(repo_produtos):
    c = repo_produtos.conn
    muss = criar_produto(c, "QUEIJO MUSSARELA FATIADO 1KG", "QUEIJO MUSSARELA", "1KG", "UN")
    vincular(c, repo_produtos.atac, "6752", muss)
    assert sugerir(c, "QJO MUSS FAT", "UND9")[0].produto_id == muss


def test_pontuar_veto_retorna_none():
    n = normalizar_produto
    assert pontuar(n("PAO QJO F.MINAS TRAD CG 820G", "UN"), n("QUEIJO MUSSARELA FATIADO 1KG", "UN")) is None
