from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).parent.parent


@pytest.fixture(autouse=True)
def dados(tmp_path, monkeypatch, nota_zaffari):
    monkeypatch.setenv("NFG_DATA_DIR", str(tmp_path))
    from nfg.config import abrir_repo
    abrir_repo().salvar_nota(nota_zaffari)


@pytest.mark.parametrize("arquivo", ["app.py", "pages/1_Importar.py", "pages/2_Notas.py",
                                     "pages/3_Análises.py", "pages/4_Categorias.py"])
def test_pagina_carrega(arquivo):
    at = AppTest.from_file(str(RAIZ / arquivo), default_timeout=30).run()
    assert not at.exception


def test_inicio_mostra_total():
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=30).run()
    assert any("382,47" in m.value for m in at.metric)


def test_inicio_sem_dados(tmp_path, monkeypatch):
    monkeypatch.setenv("NFG_DATA_DIR", str(tmp_path / "vazio"))
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=30).run()
    assert not at.exception and len(at.info) >= 1


def test_analises_sem_dados(tmp_path, monkeypatch):
    monkeypatch.setenv("NFG_DATA_DIR", str(tmp_path / "vazio"))
    at = AppTest.from_file(str(RAIZ / "pages/3_Análises.py"), default_timeout=30).run()
    assert not at.exception and any("Nenhuma nota" in i.value for i in at.info)


def test_regra_invalida_mostra_erro():
    at = AppTest.from_file(str(RAIZ / "pages/4_Categorias.py"), default_timeout=30).run()
    at.text_input(key="testar_padrao").input("(").run()
    assert not at.exception and at.error


CATEGORIAS = str(RAIZ / "pages/4_Categorias.py")


def _n_regras():
    from nfg.config import abrir_repo
    return abrir_repo().conn.execute("SELECT COUNT(*) FROM regras_categoria").fetchone()[0]


def test_salvar_regras_valida_e_invalida():
    antes = _n_regras()
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    at.session_state["editor_regras"] = {"edited_rows": {}, "deleted_rows": [], "added_rows": [
        {"padrao": "ZZZVALIDO", "categoria": "Bebidas", "prioridade": 5},
        {"padrao": "(", "categoria": "Bebidas", "prioridade": 5},
    ]}
    at.button(key="salvar_regras").click().run()
    assert not at.exception
    assert _n_regras() == antes + 1
    assert at.error
    # após o rerun o estado do editor foi limpo: novo Salvar não duplica
    at.button(key="salvar_regras").click().run()
    assert _n_regras() == antes + 1


def test_salvar_regras_limpa_estado_do_editor():
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    at.session_state["editor_regras"] = {"edited_rows": {}, "deleted_rows": [], "added_rows": [
        {"padrao": "ZZZNOVO", "categoria": "Bebidas", "prioridade": 5}]}
    at.button(key="salvar_regras").click().run()
    assert at.session_state["editor_regras"]["added_rows"] == []
    assert any("Regras salvas" in s.value for s in at.success)


def test_aplicar_categoria_manual():
    from nfg.analises import itens_df
    from nfg.categorias import SEM_CATEGORIA
    from nfg.config import abrir_repo
    conn = abrir_repo().conn
    with conn:
        conn.execute("DELETE FROM regras_categoria")  # deixa os itens sem categoria
    it = itens_df(conn)
    sem = it[(it["categoria"] == SEM_CATEGORIA) & it["codigo"].notna() & (it["codigo"] != "")]
    assert not sem.empty
    linha = (sem.groupby(["cnpj", "codigo", "descricao"], as_index=False)
                .agg(total=("valor_total", "sum")).sort_values("total", ascending=False).iloc[0])
    cat_id = conn.execute("SELECT id FROM categorias WHERE nome='Bebidas'").fetchone()[0]
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    at.session_state["editor_sem_categoria"] = {
        "edited_rows": {0: {"categoria": "Bebidas"}}, "deleted_rows": [], "added_rows": []}
    at.button(key="aplicar_manual").click().run()
    assert not at.exception
    row = conn.execute("SELECT categoria_id FROM categoria_manual WHERE cnpj=? AND codigo=?",
                       (linha["cnpj"], linha["codigo"])).fetchone()
    assert row is not None and row[0] == cat_id
    assert any("categorizados" in s.value for s in at.success)


def test_categoria_duplicada_mostra_erro():
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    at.text_input[0].input("Bebidas")
    at.button[0].click().run()
    assert not at.exception and any("Já existe" in e.value for e in at.error)


def test_excluir_categoria_mostra_regras_removidas():
    from nfg.config import abrir_repo
    conn = abrir_repo().conn
    cat_id = conn.execute("SELECT id FROM categorias WHERE nome='Bebidas'").fetchone()[0]
    n = conn.execute("SELECT COUNT(*) FROM regras_categoria WHERE categoria_id=?", (cat_id,)).fetchone()[0]
    assert n > 0
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    at.selectbox(key="cat_excluir").select(cat_id).run()
    assert not at.exception
    assert any(f"{n} regra" in c.value for c in at.caption)
    assert any(f"{n} regra" in b.label for b in at.button)
    at.button(key="btn_excluir_categoria").click().run()
    assert conn.execute("SELECT COUNT(*) FROM regras_categoria WHERE categoria_id=?", (cat_id,)).fetchone()[0] == 0


def test_nota_sem_itens_mostra_dica():
    from nfg.config import abrir_repo
    from nfg.csv_import import ler
    repo = abrir_repo()
    repo.importar_resumos(ler((RAIZ / "tests/fixtures/relatorio_nfg.csv").read_bytes()).resumos)
    at = AppTest.from_file(str(RAIZ / "pages/2_Notas.py"), default_timeout=30).run()
    tabela = at.dataframe[0].value
    pos = int(tabela.index[tabela["Status"].str.contains("sem_itens")][0])
    at.session_state["tabela_notas"] = {"selection": {"rows": [pos], "columns": []}}
    at.run()
    assert not at.exception
    assert any("Anexe o XML" in i.value for i in at.info)


def test_nota_mostra_preco_unitario_em_brl():
    at = AppTest.from_file(str(RAIZ / "pages/2_Notas.py"), default_timeout=30).run()
    at.session_state["tabela_notas"] = {"selection": {"rows": [0], "columns": []}}
    at.run()
    assert not at.exception
    assert any("R$ " in str(v) for v in at.dataframe[1].value["Valor unit."])


def _conn():
    from nfg.config import abrir_repo
    return abrir_repo().conn


def _cat_id(conn, nome):
    return conn.execute("SELECT id FROM categorias WHERE nome=?", (nome,)).fetchone()[0]


def test_salvar_regra_de_estabelecimento():
    conn = _conn()
    cnpj, loja = conn.execute(
        "SELECT cnpj, COALESCE(razao_social, nome_csv, cnpj) FROM estabelecimentos").fetchone()
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    at.session_state["editor_regras_loja"] = {"edited_rows": {}, "deleted_rows": [], "added_rows": [
        {"loja": loja, "categoria": "Bebidas"}, {"loja": loja}]}
    at.button(key="salvar_regras_loja").click().run()
    assert not at.exception
    rows = conn.execute("SELECT cnpj, categoria_id FROM regras_loja").fetchall()
    assert [(r[0], r[1]) for r in rows] == [(cnpj, _cat_id(conn, "Bebidas"))]
    assert at.error  # linha incompleta
    at.session_state["editor_regras_loja"] = {"edited_rows": {}, "deleted_rows": [], "added_rows": []}
    at.button(key="salvar_regras_loja").click().run()
    assert any("Regras de estabelecimento salvas" in s.value for s in at.success)


def test_remover_regra_de_estabelecimento():
    from nfg.categorias import definir_regra_loja
    conn = _conn()
    cnpj = conn.execute("SELECT cnpj FROM estabelecimentos").fetchone()[0]
    definir_regra_loja(conn, cnpj, _cat_id(conn, "Bebidas"))
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    at.session_state["editor_regras_loja"] = {"edited_rows": {}, "deleted_rows": [0], "added_rows": []}
    at.button(key="salvar_regras_loja").click().run()
    assert not at.exception
    assert conn.execute("SELECT COUNT(*) FROM regras_loja").fetchone()[0] == 0


def test_loja_duplicada_com_categorias_diferentes():
    from nfg.categorias import definir_regra_loja
    conn = _conn()
    cnpj, loja = conn.execute(
        "SELECT cnpj, COALESCE(razao_social, nome_csv, cnpj) FROM estabelecimentos").fetchone()
    definir_regra_loja(conn, cnpj, _cat_id(conn, "Carnes"))
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    at.session_state["editor_regras_loja"] = {"edited_rows": {}, "deleted_rows": [], "added_rows": [
        {"loja": loja, "categoria": "Bebidas"}, {"loja": loja, "categoria": "Padaria"}]}
    at.button(key="salvar_regras_loja").click().run()
    assert not at.exception
    assert any("mais de uma linha" in e.value for e in at.error)
    rows = conn.execute("SELECT cnpj, categoria_id FROM regras_loja").fetchall()
    assert [(r[0], r[1]) for r in rows] == [(cnpj, _cat_id(conn, "Carnes"))]
    assert any("Demais regras salvas" in s.value for s in at.success)


def _primeiro_sem_categoria(conn):
    from nfg.analises import itens_df
    from nfg.categorias import SEM_CATEGORIA
    with conn:
        conn.execute("DELETE FROM regras_categoria")
    it = itens_df(conn)
    sem = it[it["categoria"] == SEM_CATEGORIA]
    return (sem.groupby(["cnpj", "codigo", "descricao"], as_index=False)
               .agg(total=("valor_total", "sum")).sort_values("total", ascending=False).iloc[0])


def test_aplicar_mesma_descricao():
    from nfg.util import normalizar_texto
    conn = _conn()
    linha = _primeiro_sem_categoria(conn)
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    at.session_state["editor_sem_categoria"] = {
        "edited_rows": {0: {"categoria": "Bebidas", "aplicar_a": "Mesma descrição (todas as lojas)"}},
        "deleted_rows": [], "added_rows": []}
    at.button(key="aplicar_manual").click().run()
    assert not at.exception
    assert any("0 produto(s) e 1 descrição(ões)" in s.value for s in at.success)
    row = conn.execute("SELECT descricao_norm, categoria_id FROM categoria_descricao").fetchall()
    assert [(r[0], r[1]) for r in row] == [(normalizar_texto(linha["descricao"]), _cat_id(conn, "Bebidas"))]
    assert conn.execute("SELECT COUNT(*) FROM categoria_manual").fetchone()[0] == 0


def test_aplicar_este_produto_por_padrao():
    conn = _conn()
    _primeiro_sem_categoria(conn)
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    at.session_state["editor_sem_categoria"] = {
        "edited_rows": {0: {"categoria": "Bebidas"}}, "deleted_rows": [], "added_rows": []}
    at.button(key="aplicar_manual").click().run()
    assert conn.execute("SELECT COUNT(*) FROM categoria_manual").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM categoria_descricao").fetchone()[0] == 0


def test_remover_correcao_por_descricao():
    from nfg.categorias import definir_por_descricao
    conn = _conn()
    definir_por_descricao(conn, "Produto Xis", _cat_id(conn, "Bebidas"))
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    assert not at.exception
    at.session_state["tabela_por_descricao"] = {"selection": {"rows": [0], "columns": []}}
    at.button(key="remover_por_descricao").click().run()
    assert not at.exception
    assert conn.execute("SELECT COUNT(*) FROM categoria_descricao").fetchone()[0] == 0


def test_correcoes_por_descricao_vazio():
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    assert any("Nenhuma correção por descrição." in c.value for c in at.caption)


def test_conflitos_sem_e_com():
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    assert not at.exception
    conn = _conn()
    with conn:
        conn.execute("DELETE FROM regras_categoria")
        conn.execute("INSERT INTO regras_categoria(padrao, categoria_id, prioridade) VALUES ('.', ?, 1)",
                     (_cat_id(conn, "Bebidas"),))
        conn.execute("INSERT INTO regras_categoria(padrao, categoria_id, prioridade) VALUES ('.', ?, 2)",
                     (_cat_id(conn, "Carnes"),))
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    assert not at.exception
    assert not any("Nenhum conflito" in c.value for c in at.caption)
    assert any("Altere a categoria ou marque Confirmar" in c.value for c in at.caption)


def _salvar_conflitos_extra():
    from datetime import datetime
    from decimal import Decimal
    from nfg.config import abrir_repo
    from nfg.models import Estabelecimento, Item, Nota
    itens = [Item(i, cod, desc, Decimal(1), "UN", Decimal(5), Decimal(5)) for i, (cod, desc) in enumerate(
        [("S1", "SUCO NATURALE LARANJA INT 1L"), ("S2", "SUCO NATURALE UVA INT 1L")], start=1)]
    repo = abrir_repo()
    repo.salvar_nota(Nota(chave="7" * 44, modelo=65, emitente=Estabelecimento("111", "LOJA X"), numero="1",
                          serie="1", emissao=datetime(2026, 8, 1), protocolo=None, valor_total=Decimal(10),
                          valor_descontos=Decimal(0), itens=itens))
    return repo.conn


def _linha_conflito(conn, descricao):
    from nfg.categorias import conflitos_df
    df = conflitos_df(conn).reset_index(drop=True)
    pos = int(df.index[df["descricao"] == descricao][0])
    return pos, df.iloc[pos]


def test_conflitos_confirmar_grava_manual_e_some():
    conn = _salvar_conflitos_extra()
    pos, linha = _linha_conflito(conn, "SUCO NATURALE LARANJA INT 1L")
    assert linha["vencedora"] == "Bebidas"
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    assert not at.exception
    at.session_state["editor_conflitos"] = {
        "edited_rows": {pos: {"confirmar": True}}, "deleted_rows": [], "added_rows": []}
    at.button(key="salvar_conflitos").click().run()
    assert not at.exception
    row = conn.execute("SELECT categoria_id FROM categoria_manual WHERE cnpj='111' AND codigo='S1'").fetchone()
    assert row[0] == _cat_id(conn, "Bebidas")
    assert conn.execute("SELECT COUNT(*) FROM categoria_manual").fetchone()[0] == 1
    assert any("1 conflito(s) resolvido(s)." in s.value for s in at.success)
    from nfg.categorias import conflitos_df
    assert "SUCO NATURALE LARANJA INT 1L" not in set(conflitos_df(conn)["descricao"])


def test_conflitos_mudar_categoria_mesma_descricao():
    from nfg.util import normalizar_texto
    conn = _salvar_conflitos_extra()
    pos, _ = _linha_conflito(conn, "SUCO NATURALE UVA INT 1L")
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    at.session_state["editor_conflitos"] = {
        "edited_rows": {pos: {"categoria": "Hortifruti", "aplicar_a": "Mesma descrição (todas as lojas)"}},
        "deleted_rows": [], "added_rows": []}
    at.button(key="salvar_conflitos").click().run()
    assert not at.exception
    rows = conn.execute("SELECT descricao_norm, categoria_id FROM categoria_descricao").fetchall()
    assert [(r[0], r[1]) for r in rows] == [(normalizar_texto("SUCO NATURALE UVA INT 1L"), _cat_id(conn, "Hortifruti"))]
    assert conn.execute("SELECT COUNT(*) FROM categoria_manual").fetchone()[0] == 0


def test_conflitos_salvar_sem_mudancas():
    conn = _salvar_conflitos_extra()
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    at.button(key="salvar_conflitos").click().run()
    assert not at.exception
    assert any("Nada a salvar." in i.value for i in at.info)
    assert conn.execute("SELECT COUNT(*) FROM categoria_manual").fetchone()[0] == 0


def test_conflitos_lista_mudou_nao_grava_em_outro_produto():
    from nfg.categorias import definir_manual
    conn = _salvar_conflitos_extra()
    pos, _ = _linha_conflito(conn, "SUCO NATURALE LARANJA INT 1L")
    at = AppTest.from_file(CATEGORIAS, default_timeout=30).run()
    definir_manual(conn, "111", "S1", _cat_id(conn, "Bebidas"))  # a lista desloca apos o render
    at.session_state["editor_conflitos"] = {
        "edited_rows": {pos: {"confirmar": True}}, "deleted_rows": [], "added_rows": []}
    at.button(key="salvar_conflitos").click().run()
    assert not at.exception
    assert any("Lista de conflitos mudou" in w.value for w in at.warning)
    rows = conn.execute("SELECT codigo FROM categoria_manual").fetchall()
    assert [r[0] for r in rows] == ["S1"]
