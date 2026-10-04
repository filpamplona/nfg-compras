import sqlite3
from datetime import datetime

import pytest

from nfg.db import SCHEMA, conectar
from nfg.erros import ProdutoDuplicado
from nfg.models import Estabelecimento
from nfg.produtos import (
    atualizar_produto, chave_item, criar_produto, desvincular, excluir_produto,
    ignorar, restaurar, vincular,
    catalogo_df, ignorados_df, pendentes_df, vinculos_df, vincular_automaticos,
)
from tests.conftest import item, nota


def _n(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]


def test_banco_antigo_ganha_tabelas_e_user_version_segue(tmp_path):
    caminho = tmp_path / "nfg.db"
    antigo = SCHEMA[:SCHEMA.index("CREATE TABLE IF NOT EXISTS produtos")]
    c = sqlite3.connect(str(caminho))
    c.executescript(antigo)
    c.execute("PRAGMA user_version = 2")
    c.commit()
    antes = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "produtos" not in antes
    c.close()
    conn = conectar(caminho)
    tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"produtos", "produto_vinculo", "produto_ignorado"} <= tabelas
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 2
    conn.close()


def test_chave_item_com_e_sem_codigo():
    assert chave_item("1", "101", "X") == ("1", "101")
    assert chave_item("1", None, "Sacola  ") == ("1", "DESC:SACOLA")
    assert chave_item("1", "", "sacola") == ("1", "DESC:SACOLA")


def test_criar_produto_normaliza_nome(repo):
    pid = criar_produto(repo.conn, "queijo mussarela fatiado 1kg", "QUEIJO MUSSARELA", "1KG", "UN")
    assert _n(repo.conn, "SELECT nome FROM produtos WHERE id=?", pid) == "QUEIJO MUSSARELA FATIADO 1KG"


def test_criar_produto_duplicado(repo):
    criar_produto(repo.conn, "Banana Prata", "BANANA", None, "KG")
    with pytest.raises(ProdutoDuplicado):
        criar_produto(repo.conn, "banana prata", "BANANA", None, "KG")
    assert _n(repo.conn, "SELECT COUNT(*) FROM produtos") == 1


def test_renomear_para_existente(repo):
    a = criar_produto(repo.conn, "A", "A", None, "UN")
    b = criar_produto(repo.conn, "B", "B", None, "UN")
    with pytest.raises(ProdutoDuplicado):
        atualizar_produto(repo.conn, b, nome="a")
    assert _n(repo.conn, "SELECT nome FROM produtos WHERE id=?", b) == "B"
    atualizar_produto(repo.conn, a, tipo="X", tamanho="1KG")
    assert _n(repo.conn, "SELECT tipo FROM produtos WHERE id=?", a) == "X"


def test_vincular_upsert_e_desvincular(repo_produtos):
    c, z = repo_produtos.conn, repo_produtos.zaf
    a = criar_produto(c, "A", "A", None, "UN")
    b = criar_produto(c, "B", "B", None, "UN")
    vincular(c, z, "101", a)
    vincular(c, z, "101", b, origem="auto")
    assert _n(c, "SELECT COUNT(*) FROM produto_vinculo") == 1
    assert _n(c, "SELECT produto_id FROM produto_vinculo WHERE cnpj=? AND codigo='101'", z) == b
    assert _n(c, "SELECT origem FROM produto_vinculo") == "auto"
    desvincular(c, z, "101")
    assert _n(c, "SELECT COUNT(*) FROM produto_vinculo") == 0


def test_ignorar_remove_vinculo_e_vincular_remove_ignorado(repo_produtos):
    c, z = repo_produtos.conn, repo_produtos.zaf
    a = criar_produto(c, "A", "A", None, "UN")
    vincular(c, z, "101", a)
    ignorar(c, z, "101")
    assert _n(c, "SELECT COUNT(*) FROM produto_vinculo") == 0
    assert _n(c, "SELECT COUNT(*) FROM produto_ignorado") == 1
    vincular(c, z, "101", a)
    assert _n(c, "SELECT COUNT(*) FROM produto_ignorado") == 0
    assert _n(c, "SELECT COUNT(*) FROM produto_vinculo") == 1


def test_restaurar(repo_produtos):
    c, z = repo_produtos.conn, repo_produtos.zaf
    ignorar(c, z, "101")
    restaurar(c, z, "101")
    assert _n(c, "SELECT COUNT(*) FROM produto_ignorado") == 0


def test_excluir_produto_remove_vinculos(repo_produtos):
    c = repo_produtos.conn
    a = criar_produto(c, "A", "A", None, "UN")
    vincular(c, repo_produtos.zaf, "101", a)
    vincular(c, repo_produtos.atac, "6752", a)
    excluir_produto(c, a)
    assert _n(c, "SELECT COUNT(*) FROM produto_vinculo") == 0
    assert _n(c, "SELECT COUNT(*) FROM produtos") == 0


def test_reprocessar_nota_mantem_vinculo(repo_produtos):
    from datetime import datetime
    c, z = repo_produtos.conn, repo_produtos.zaf
    a = criar_produto(c, "A", "A", None, "UN")
    vincular(c, z, "101", a)
    emit = c.execute("SELECT cnpj, razao_social FROM estabelecimentos WHERE cnpj=?", (z,)).fetchone()
    from nfg.models import Estabelecimento
    repo_produtos.salvar_nota(nota("4" * 44, Estabelecimento(emit[0], emit[1]), datetime(2026, 9, 1, 10, 0), "52.90", [
        item(1, "101", "QJO MUSSARELA S.CLARA FAT 1KG", "1", "UN", "52.90"),
    ]))
    assert _n(c, "SELECT COUNT(*) FROM produto_vinculo WHERE cnpj=? AND codigo='101'", z) == 1


def _muss(repo):
    return criar_produto(repo.conn, "QUEIJO MUSSARELA FATIADO 1KG", "QUEIJO MUSSARELA", "1KG", "UN")


def test_pendentes_agrega_por_codigo(repo_produtos):
    df = pendentes_df(repo_produtos.conn).set_index(["cnpj", "codigo"])
    r = df.loc[(repo_produtos.zaf, "102")]
    assert r.compras == 2 and r.ultimo_preco == 51.90
    r = df.loc[(repo_produtos.atac, "6752")]  # nota cancelada nao conta
    assert r.compras == 1 and r.ultimo_preco == 47.90 and r.unidade == "UND9"
    assert (repo_produtos.atac, "DESC:SACOLA") in df.index


def test_pendentes_exclui_vinculados_e_ignorados(repo_produtos):
    c = repo_produtos.conn
    vincular(c, repo_produtos.zaf, "101", _muss(repo_produtos))
    ignorar(c, repo_produtos.zaf, "106")
    chaves = set(pendentes_df(c)[["cnpj", "codigo"]].itertuples(index=False, name=None))
    assert (repo_produtos.zaf, "101") not in chaves
    assert (repo_produtos.zaf, "106") not in chaves
    assert (repo_produtos.zaf, "102") in chaves


def test_excluir_produto_devolve_a_fila(repo_produtos):
    c = repo_produtos.conn
    p = _muss(repo_produtos)
    vincular(c, repo_produtos.zaf, "101", p)
    vincular(c, repo_produtos.zaf, "102", p)
    excluir_produto(c, p)
    chaves = set(pendentes_df(c)[["cnpj", "codigo"]].itertuples(index=False, name=None))
    assert {(repo_produtos.zaf, "101"), (repo_produtos.zaf, "102")} <= chaves


def test_catalogo_e_vinculos_df(repo_produtos):
    c = repo_produtos.conn
    p = _muss(repo_produtos)
    for cnpj, cod in [(repo_produtos.zaf, "101"), (repo_produtos.zaf2, "101"), (repo_produtos.atac, "6752")]:
        vincular(c, cnpj, cod, p)
    cat = catalogo_df(c)
    assert list(cat.columns) == ["id", "nome", "tipo", "tamanho", "venda", "lojas", "vinculos"]
    r = cat.iloc[0]
    assert r.id == p and r.lojas == 3 and r.vinculos == 3
    v = vinculos_df(c, p)
    assert list(v.columns) == ["cnpj", "codigo", "loja", "descricao", "origem"]
    assert len(v) == 3
    assert v.set_index(["cnpj", "codigo"]).loc[(repo_produtos.atac, "6752"), "descricao"] == "QJO.MUSS.FAT.DALIA"


def test_ignorados_df(repo_produtos):
    c = repo_produtos.conn
    ignorar(c, repo_produtos.zaf, "106")
    df = ignorados_df(c)
    assert list(df.columns) == ["cnpj", "codigo", "loja", "descricao"]
    assert len(df) == 1 and df.iloc[0].descricao == "BANANA PRATA GRANEL"


def test_auto_mesma_raiz_de_cnpj(repo_produtos):
    c = repo_produtos.conn
    p = _muss(repo_produtos)
    vincular(c, repo_produtos.zaf, "101", p)
    assert vincular_automaticos(c) >= 1
    assert c.execute("SELECT origem FROM produto_vinculo WHERE cnpj=? AND codigo='101'",
                     (repo_produtos.zaf2,)).fetchone()[0] == "auto"


def test_auto_descricao_identica_normalizada(repo_produtos):
    c = repo_produtos.conn
    repo_produtos.salvar_nota(nota("9" * 44, Estabelecimento(repo_produtos.zaf, 'CIA ZAFFARI'), datetime(2026, 9, 28, 10, 0), "50.00", [
        item(1, "999", "QJO MUSSARELA S.CLARA FAT 1KG *", "1", "UN", "50.00")]))
    vincular(c, repo_produtos.zaf, "101", _muss(repo_produtos))
    vincular_automaticos(c)
    assert c.execute("SELECT origem FROM produto_vinculo WHERE cnpj=? AND codigo='999'",
                     (repo_produtos.zaf,)).fetchone()[0] == "auto"


def test_auto_nao_liga_codigo_igual_de_outra_raiz(repo_produtos):
    c = repo_produtos.conn
    repo_produtos.salvar_nota(nota("a" * 44, Estabelecimento(repo_produtos.atac, 'ATACADAO S.A.'), datetime(2026, 9, 28, 10, 0), "3.00", [
        item(1, "101", "AGUA MINERAL", "1", "UN", "3.00")]))
    vincular(c, repo_produtos.zaf, "101", _muss(repo_produtos))
    vincular_automaticos(c)
    chaves = set(pendentes_df(c)[["cnpj", "codigo"]].itertuples(index=False, name=None))
    assert (repo_produtos.atac, "101") in chaves


def test_auto_idempotente(repo_produtos):
    c = repo_produtos.conn
    vincular(c, repo_produtos.zaf, "101", _muss(repo_produtos))
    assert vincular_automaticos(c) >= 1
    assert vincular_automaticos(c) == 0
