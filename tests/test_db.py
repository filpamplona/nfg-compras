import pytest

from nfg.csv_import import ler


def _resumos(fixtures_dir):
    return ler((fixtures_dir / "relatorio_nfg.csv").read_bytes()).resumos


def test_importar_e_idempotencia(repo, fixtures_dir):
    resumos = _resumos(fixtures_dir)
    assert repo.importar_resumos(resumos) == {"novas": 11, "existentes": 0, "nfe": 1}
    assert repo.importar_resumos(resumos) == {"novas": 0, "existentes": 11, "nfe": 1}
    assert repo.contagem_status() == {"pendente": 10, "sem_itens": 1}
    assert len(repo.pendentes()) == 10


def test_salvar_nota_e_nao_rebaixar(repo, fixtures_dir, nota_zaffari):
    resumos = _resumos(fixtures_dir)
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


def test_salvar_preserva_situacao_e_nome_csv(repo, fixtures_dir, nota_zaffari):
    repo.importar_resumos(_resumos(fixtures_dir))
    antes = repo.conn.execute("select situacao_csv, tipo_operacao from notas where chave=?", (nota_zaffari.chave,)).fetchone()
    repo.salvar_nota(nota_zaffari)
    depois = repo.conn.execute("select situacao_csv, tipo_operacao from notas where chave=?", (nota_zaffari.chave,)).fetchone()
    assert tuple(antes) == tuple(depois) and antes[0] is not None
    est = repo.conn.execute("select nome_csv from estabelecimentos where cnpj='93015006000547'").fetchone()
    assert est[0]


def test_salvar_duas_vezes_substitui_itens(repo, nota_zaffari):
    repo.salvar_nota(nota_zaffari)
    repo.salvar_nota(nota_zaffari)
    assert len(repo.itens_da_nota(nota_zaffari.chave)) == 18
    row = repo.conn.execute("select situacao_csv from notas").fetchone()
    assert row[0] is None


def test_registrar_erro(repo, fixtures_dir):
    repo.importar_resumos(_resumos(fixtures_dir))
    a, b = repo.pendentes()[:2]
    repo.registrar_erro(a, "timeout", definitivo=False)
    repo.registrar_erro(b, "não encontrada", definitivo=True)
    assert a in repo.pendentes() and b not in repo.pendentes()


def test_cascade(repo, nota_zaffari):
    repo.salvar_nota(nota_zaffari)
    repo.conn.execute("delete from notas")
    assert repo.conn.execute("select count(*) from itens").fetchone()[0] == 0


def test_reabrir(repo, fixtures_dir):
    repo.importar_resumos(_resumos(fixtures_dir))
    chave = repo.pendentes()[0]
    repo.registrar_erro(chave, "falhou", definitivo=True)
    assert chave not in repo.pendentes()
    repo.reabrir(chave)
    assert chave in repo.pendentes()
    row = repo.conn.execute("select status, tentativas, erro_msg from notas where chave=?", (chave,)).fetchone()
    assert tuple(row) == ("pendente", 0, None)


def test_xml_antes_do_csv_preenche_situacao(repo, fixtures_dir, nota_zaffari):
    repo.salvar_nota(nota_zaffari)
    assert repo.conn.execute("select situacao_csv from notas where chave=?", (nota_zaffari.chave,)).fetchone()[0] is None
    r = repo.importar_resumos(_resumos(fixtures_dir))
    assert r["existentes"] == 1
    row = repo.conn.execute("select situacao_csv, tipo_operacao, status from notas where chave=?",
                            (nota_zaffari.chave,)).fetchone()
    assert tuple(row) == ("Normal", "Aquisição", "coletada")
    assert repo.conn.execute("select nome_csv from estabelecimentos where cnpj=?",
                             (nota_zaffari.emitente.cnpj,)).fetchone()[0]


def test_reimport_cancelada_exclui_das_analises(repo, fixtures_dir, nota_zaffari):
    from dataclasses import replace

    from nfg.analises import gasto_mensal

    repo.salvar_nota(nota_zaffari)
    resumos = _resumos(fixtures_dir)
    repo.importar_resumos(resumos)
    antes = gasto_mensal(repo.conn)["total"].sum()
    canceladas = [replace(r, situacao="Cancelada") if r.chave == nota_zaffari.chave else r for r in resumos]
    repo.importar_resumos(canceladas)
    assert antes - gasto_mensal(repo.conn)["total"].sum() == pytest.approx(382.47)
    assert repo.conn.execute("select status from notas where chave=?", (nota_zaffari.chave,)).fetchone()[0] == "coletada"


def test_pendentes_ignora_canceladas_e_nao_aquisicao(repo, fixtures_dir):
    repo.importar_resumos(_resumos(fixtures_dir))
    antes = set(repo.pendentes())
    alvo, outra = sorted(antes)[:2]
    with repo.conn:
        repo.conn.execute("UPDATE notas SET situacao_csv='Cancelada' WHERE chave=?", (alvo,))
        repo.conn.execute("UPDATE notas SET tipo_operacao='Devolução' WHERE chave=?", (outra,))
    assert set(repo.pendentes()) == antes - {alvo, outra}
