import pytest

from nfg.produtos import (
    comparar_produto, criar_produto, historico_produto, vincular, visao_geral_df,
)

COL_COMPARAR = ["cnpj", "loja", "ultimo_preco", "ultima_data", "descricao_original",
                "dif_reais", "dif_pct", "mais_barato"]
COL_HISTORICO = ["emissao", "loja", "valor_unitario", "descricao"]
COL_VISAO = ["produto_id", "produto", "venda", "loja_mais_barata", "menor_preco", "maior_preco", "dif_pct"]


@pytest.fixture
def vinculado(repo_produtos):
    r = repo_produtos
    c = r.conn
    r.muss = criar_produto(c, "Queijo Mussarela", "queijo mussarela", "1kg", "UN")
    r.banana = criar_produto(c, "Banana Prata", "banana prata", None, "KG")
    r.parm = criar_produto(c, "Queijo Parmesao", "queijo parmesao", "100g", "UN")
    for cnpj, cod in [(r.zaf, "101"), (r.zaf, "102"), (r.zaf2, "101"), (r.atac, "6752")]:
        vincular(c, cnpj, cod, r.muss)
    vincular(c, r.zaf, "106", r.banana)
    vincular(c, r.atac, "6753", r.banana)
    vincular(c, r.zaf, "103", r.parm)
    return r


def test_comparar_ultimo_preco_por_loja(vinculado):
    c, muss = vinculado.conn, vinculado.muss
    df = comparar_produto(c, muss)
    assert list(df.columns) == COL_COMPARAR
    assert list(df["ultimo_preco"]) == [47.90, 50.90, 51.90]
    df = df.set_index("cnpj")
    r = vinculado
    assert df.loc[r.atac, "mais_barato"] and not df.loc[r.zaf, "mais_barato"]
    assert df.loc[r.atac, "loja"] == "ATACADAO S.A."
    assert df.loc[r.zaf, "descricao_original"] == "QJO MUSSARELA TIROLEZ FAT 1KG"
    assert df.loc[r.zaf, "dif_reais"] == pytest.approx(4.00) and df.loc[r.zaf, "dif_pct"] == 8.35


def test_comparar_venda_kg(vinculado):
    df = comparar_produto(vinculado.conn, vinculado.banana).set_index("cnpj")
    assert df.loc[vinculado.atac, "ultimo_preco"] == 5.49 and df.loc[vinculado.atac, "mais_barato"]
    assert df.loc[vinculado.zaf, "ultimo_preco"] == 6.98 and not df.loc[vinculado.zaf, "mais_barato"]


def test_comparar_uma_loja_e_a_mais_barata(vinculado):
    c = vinculado.conn
    df = comparar_produto(c, vinculado.parm)
    assert len(df) == 1 and bool(df["mais_barato"].iloc[0]) and df["dif_reais"].iloc[0] == 0


def test_historico_produto(vinculado):
    df = historico_produto(vinculado.conn, vinculado.muss)
    assert list(df.columns) == COL_HISTORICO
    assert list(df["valor_unitario"]) == [52.90, 48.90, 47.90, 51.90, 50.90]  # 5 linhas validas; sem 10.00 cancelado


def test_visao_geral(vinculado):
    df = visao_geral_df(vinculado.conn)
    assert list(df.columns) == COL_VISAO
    assert vinculado.parm not in set(df["produto_id"])
    m = df.set_index("produto_id").loc[vinculado.muss]
    assert m["loja_mais_barata"] == "ATACADAO S.A."
    assert m["menor_preco"] == 47.90 and m["maior_preco"] == 51.90 and m["dif_pct"] == 8.35
    assert vinculado.banana in set(df["produto_id"])
    assert list(df["dif_pct"]) == sorted(df["dif_pct"], reverse=True)


def test_produto_so_com_notas_canceladas(repo_produtos):
    r = repo_produtos
    pid = criar_produto(r.conn, "Fantasma", "fantasma", None, "UN")
    vincular(r.conn, r.atac, "6752", pid)
    r.conn.execute("UPDATE notas SET situacao_csv='Cancelada' WHERE chave = ?", ("5" * 44,))
    comp = comparar_produto(r.conn, pid)
    assert comp.empty and list(comp.columns) == COL_COMPARAR
    assert pid not in set(visao_geral_df(r.conn)["produto_id"])


def test_produto_sem_vinculos(repo_produtos):
    pid = criar_produto(repo_produtos.conn, "Nada", "nada", None, "UN")
    comp = comparar_produto(repo_produtos.conn, pid)
    hist = historico_produto(repo_produtos.conn, pid)
    assert comp.empty and list(comp.columns) == COL_COMPARAR
    assert hist.empty and list(hist.columns) == COL_HISTORICO
