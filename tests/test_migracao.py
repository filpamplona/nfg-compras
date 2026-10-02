import pytest

from nfg import categorias as cat_mod
from nfg.categorias import garantir_seed, listar_regras, migrar
from nfg.db import conectar

DIMED = "92665611007422"
SEED_ANTIGO = ["Doces/Snacks", "Bebidas", "Hortifruti", "Padaria", "Carnes",
               "Laticínios/Frios", "Mercearia", "Limpeza", "Higiene", "Outros"]


@pytest.fixture
def antigo():
    c = conectar(":memory:")
    ids = {n: c.execute("INSERT INTO categorias(nome) VALUES (?)", (n,)).lastrowid
           for n in SEED_ANTIGO + ["Remédios"]}
    c.execute("INSERT INTO regras_categoria(padrao, categoria_id, prioridade) VALUES (?,?,?)",
              (r"\bBISC", ids["Doces/Snacks"], 40))
    c.execute("INSERT INTO regras_categoria(padrao, categoria_id, prioridade) VALUES (?,?,?)",
              (r"\bPIZZA", ids["Padaria"], 7))  # personalizada
    c.execute("INSERT INTO categoria_manual VALUES ('1','A',?)", (ids["Remédios"],))
    c.execute("INSERT INTO categoria_manual VALUES ('1','B',?)", (ids["Remédios"],))
    c.execute("INSERT INTO categoria_manual VALUES ('1','C',?)", (ids["Bebidas"],))
    c.execute("INSERT INTO estabelecimentos(cnpj, razao_social) VALUES (?, 'DIMED')", (DIMED,))
    c.commit()
    yield c
    c.close()


def _nomes(c):
    return [r[0] for r in c.execute("SELECT nome FROM categorias ORDER BY id")]


def _regras_seed():
    return [(n, p, pr) for n, pr, p in cat_mod._REGRAS_SEED]


def test_migrar_banco_antigo(antigo):
    c = antigo
    migrar(c)
    nomes = _nomes(c)
    assert "Farmácia" in nomes and "Remédios" not in nomes
    assert len(nomes) == 14
    manuais = {r["codigo"]: r["nome"] for r in c.execute(
        "SELECT m.codigo, c.nome FROM categoria_manual m JOIN categorias c ON c.id=m.categoria_id")}
    assert manuais == {"A": "Farmácia", "B": "Farmácia", "C": "Bebidas"}
    bk = {(r["padrao"], r["categoria_nome"], r["prioridade"]) for r in
          c.execute("SELECT * FROM regras_categoria_backup")}
    assert bk == {(r"\bBISC", "Doces/Snacks", 40), (r"\bPIZZA", "Padaria", 7)}
    atuais = [(r["categoria"], r["padrao"], r["prioridade"]) for r in listar_regras(c)]
    assert sorted(atuais) == sorted(_regras_seed())
    loja = c.execute("SELECT c.nome FROM regras_loja l JOIN categorias c ON c.id=l.categoria_id "
                     "WHERE l.cnpj=?", (DIMED,)).fetchone()
    assert loja[0] == "Farmácia"
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2


def test_migrar_idempotente(antigo):
    c = antigo
    migrar(c)
    n_regras = c.execute("SELECT COUNT(*) FROM regras_categoria").fetchone()[0]
    n_bk = c.execute("SELECT COUNT(*) FROM regras_categoria_backup").fetchone()[0]
    cat = c.execute("SELECT id FROM categorias WHERE nome='Outros'").fetchone()[0]
    c.execute("INSERT INTO regras_categoria(padrao, categoria_id, prioridade) VALUES ('ZZZUSER', ?, 1)", (cat,))
    c.commit()
    migrar(c)
    assert c.execute("SELECT COUNT(*) FROM regras_categoria").fetchone()[0] == n_regras + 1
    assert c.execute("SELECT 1 FROM regras_categoria WHERE padrao='ZZZUSER'").fetchone() is not None
    assert c.execute("SELECT COUNT(*) FROM regras_categoria_backup").fetchone()[0] == n_bk
    bk = {(r["padrao"], r["categoria_nome"], r["prioridade"]) for r in
          c.execute("SELECT * FROM regras_categoria_backup")}
    assert bk == {(r"\bBISC", "Doces/Snacks", 40), (r"\bPIZZA", "Padaria", 7)}


def test_migrar_remedios_com_farmacia_existente(antigo):
    c = antigo
    fid = c.execute("INSERT INTO categorias(nome) VALUES ('Farmácia')").lastrowid
    rid = c.execute("SELECT id FROM categorias WHERE nome='Remédios'").fetchone()[0]
    c.execute("INSERT INTO regras_loja VALUES ('9', ?)", (rid,))
    c.execute("INSERT INTO categoria_descricao VALUES ('XPTO', ?)", (rid,))
    c.commit()
    migrar(c)
    assert "Remédios" not in _nomes(c)
    assert c.execute("SELECT categoria_id FROM regras_loja WHERE cnpj='9'").fetchone()[0] == fid
    assert c.execute("SELECT categoria_id FROM categoria_descricao").fetchone()[0] == fid
    assert c.execute("SELECT COUNT(*) FROM categoria_manual WHERE categoria_id=?", (fid,)).fetchone()[0] == 2
    assert _nomes(c).count("Farmácia") == 1


def test_migrar_preserva_regra_loja_existente_dimed(antigo):
    c = antigo
    oid = c.execute("SELECT id FROM categorias WHERE nome='Outros'").fetchone()[0]
    c.execute("INSERT INTO regras_loja VALUES (?, ?)", (DIMED, oid))
    c.commit()
    migrar(c)
    assert c.execute("SELECT categoria_id FROM regras_loja WHERE cnpj=?", (DIMED,)).fetchone()[0] == oid


def test_migrar_sem_dimed_nem_remedios():
    c = conectar(":memory:")
    migrar(c)  # banco vazio, user_version 0
    assert c.execute("SELECT COUNT(*) FROM regras_loja").fetchone()[0] == 0
    assert len(_nomes(c)) == 14
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2


def test_migrar_atomica(antigo, monkeypatch):
    c = antigo
    monkeypatch.setattr(cat_mod, "_REGRAS_SEED", [("Categoria Inexistente", 1, "x")])
    with pytest.raises(KeyError):
        migrar(c)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 0
    assert "Remédios" in _nomes(c)
    assert len(_nomes(c)) == 11
    assert c.execute("SELECT COUNT(*) FROM regras_categoria").fetchone()[0] == 2


def test_banco_novo_nao_migra():
    c = conectar(":memory:")
    garantir_seed(c)
    assert len(_nomes(c)) == 14
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2
    antes = c.execute("SELECT COUNT(*) FROM regras_categoria").fetchone()[0]
    migrar(c)
    assert c.execute("SELECT COUNT(*) FROM regras_categoria").fetchone()[0] == antes
    assert c.execute("SELECT name FROM sqlite_master WHERE name='regras_categoria_backup'").fetchone() is None


COMECA_COM = [(r"^PIZZA\b", "Pizza"), (r"^(PAO|PAES|PAOZINHO)\b", "Padaria"),
              (r"^(CHOC|CHOCOLATE)\b", "Doces/Snacks")]


def _contagem_comeca_com(c):
    return {p: c.execute("SELECT COUNT(*) FROM regras_categoria WHERE padrao=?", (p,)).fetchone()[0]
            for p, _ in COMECA_COM}


def test_migrar_v1_para_v2(antigo):
    c = antigo
    migrar(c)
    with c:
        for p, _ in COMECA_COM:
            c.execute("DELETE FROM regras_categoria WHERE padrao=?", (p,))
        c.execute("PRAGMA user_version = 1")
    assert _contagem_comeca_com(c) == {p: 0 for p, _ in COMECA_COM}
    migrar(c)
    assert _contagem_comeca_com(c) == {p: 1 for p, _ in COMECA_COM}
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2
    for p, nome in COMECA_COM:
        r = c.execute("SELECT c.nome, r.prioridade FROM regras_categoria r JOIN categorias c "
                      "ON c.id=r.categoria_id WHERE r.padrao=?", (p,)).fetchone()
        assert (r[0], r[1]) == (nome, 5)
    migrar(c)
    assert _contagem_comeca_com(c) == {p: 1 for p, _ in COMECA_COM}


def test_migrar_v1_para_v2_nao_duplica_regra_existente(antigo):
    c = antigo
    migrar(c)
    with c:
        c.execute("DELETE FROM regras_categoria WHERE padrao=?", (COMECA_COM[0][0],))
        c.execute("PRAGMA user_version = 1")
    migrar(c)
    assert _contagem_comeca_com(c) == {p: 1 for p, _ in COMECA_COM}


def test_migrar_v0_resulta_regras_uma_vez(antigo):
    migrar(antigo)
    assert _contagem_comeca_com(antigo) == {p: 1 for p, _ in COMECA_COM}
    assert antigo.execute("PRAGMA user_version").fetchone()[0] == 2


def test_banco_novo_tem_regras_comeca_com():
    c = conectar(":memory:")
    garantir_seed(c)
    assert _contagem_comeca_com(c) == {p: 1 for p, _ in COMECA_COM}
