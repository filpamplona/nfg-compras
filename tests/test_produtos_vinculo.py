import sqlite3

import pytest

from nfg.db import SCHEMA, conectar
from nfg.erros import ProdutoDuplicado
from nfg.produtos import (
    atualizar_produto, chave_item, criar_produto, desvincular, excluir_produto,
    ignorar, restaurar, vincular,
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
