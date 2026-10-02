import io
from datetime import date

import pandas as pd
import pytest

from nfg.analises import (
    exportar_excel, gasto_mensal, gasto_mensal_por_categoria, gasto_por_categoria,
    gasto_por_loja, historico_preco, itens_df, meses_disponiveis, notas_df,
    ranking_produtos, resumo_mes,
)


def test_gasto_mensal_ignora_cancelada(repo_dados):
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


def test_filtro_fim_inclui_dia_inteiro(repo_dados):
    df = gasto_mensal(repo_dados.conn, inicio=date(2026, 8, 20), fim=date(2026, 8, 20))
    assert df.iloc[0]["total"] == pytest.approx(26.90)


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


def test_meses_e_notas_df(repo_dados):
    assert meses_disponiveis(repo_dados.conn) == ["2026-09", "2026-08"]
    n = notas_df(repo_dados.conn)
    assert len(n) == 4 and "num_itens" in n.columns


def test_exportar_excel(repo_dados):
    dados = exportar_excel({"Mensal": gasto_mensal(repo_dados.conn)})
    assert pd.read_excel(io.BytesIO(dados), sheet_name="Mensal").shape[0] == 2


def test_banco_vazio(repo):
    c = repo.conn
    for df in (notas_df(c), itens_df(c), gasto_mensal(c), gasto_mensal_por_categoria(c),
               gasto_por_loja(c), gasto_por_categoria(c), ranking_produtos(c), historico_preco(c, "x")):
        assert df.empty and len(df.columns) > 0
    assert meses_disponiveis(c) == []
    r = resumo_mes(c, "2026-09")
    assert r["total"] == 0 and r["compras"] == 0 and r["variacao_pct"] is None


def _nota_com_desconto(repo, nota_zaffari):
    from dataclasses import replace
    from decimal import Decimal

    n = replace(nota_zaffari, valor_total=Decimal("342.47"), valor_descontos=Decimal("40.00"))
    repo.salvar_nota(n)
    return n


def test_categorias_somam_gasto_mensal_com_desconto(repo, nota_zaffari):
    from nfg.categorias import garantir_seed

    garantir_seed(repo.conn)
    n = _nota_com_desconto(repo, nota_zaffari)
    mensal = gasto_mensal(repo.conn)["total"].sum()
    assert mensal == pytest.approx(342.47)
    assert gasto_por_categoria(repo.conn)["total"].sum() == pytest.approx(mensal, abs=0.005)
    assert gasto_mensal_por_categoria(repo.conn)["total"].sum() == pytest.approx(mensal, abs=0.005)
    it = itens_df(repo.conn)
    assert it["valor_total"].sum() == pytest.approx(float(n.valor_total), abs=0.0001)
    assert (it["valor_total"] * 100).round(6).map(lambda v: abs(v - round(v)) < 1e-6).all()
    # preço unitário permanece bruto
    assert sorted(it["valor_unitario"])[-1] == pytest.approx(float(max(i.valor_unitario for i in n.itens)))


def test_loja_unica_por_cnpj(repo, nota_zaffari):
    repo.salvar_nota(nota_zaffari)
    with repo.conn:
        repo.conn.execute("INSERT INTO estabelecimentos (cnpj, nome_csv) VALUES ('11111111000111', 'Nome CSV')"
                          " ON CONFLICT(cnpj) DO NOTHING")
        repo.conn.execute("UPDATE estabelecimentos SET nome_csv='Outro Nome' WHERE cnpj=?",
                          (nota_zaffari.emitente.cnpj,))
    assert set(notas_df(repo.conn)["loja"]) == {nota_zaffari.emitente.razao_social}
    assert set(itens_df(repo.conn)["loja"]) == {nota_zaffari.emitente.razao_social}
    assert list(gasto_por_loja(repo.conn)["loja"]) == [nota_zaffari.emitente.razao_social]


def test_loja_agrupa_por_cnpj_mesmo_com_nomes_diferentes(repo, nota_zaffari):
    from dataclasses import replace

    repo.salvar_nota(nota_zaffari)
    outra = replace(nota_zaffari, chave="9" * 44)
    repo.salvar_nota(outra)
    with repo.conn:  # a segunda nota sem razão social (loja só com nome_csv) não deve duplicar
        repo.conn.execute("UPDATE notas SET cnpj_emitente=? WHERE chave=?", (nota_zaffari.emitente.cnpj, "9" * 44))
    g = gasto_por_loja(repo.conn)
    assert len(g) == 1 and g.loc[0, "visitas"] == 2
