from pathlib import Path

import pytest


@pytest.fixture
def fixtures_dir() -> Path:
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def repo():
    from nfg.db import Repositorio, conectar

    r = Repositorio(conectar(":memory:"))
    yield r
    r.conn.close()


@pytest.fixture
def nota_zaffari(fixtures_dir):
    from nfg import nfce_parser

    return nfce_parser.parse((fixtures_dir / "nfce_zaffari.html").read_text(encoding="utf-8"))


@pytest.fixture
def repo_csv(repo, fixtures_dir):
    from nfg import csv_import

    repo.importar_resumos(csv_import.ler((fixtures_dir / "relatorio_nfg.csv").read_bytes()).resumos)
    return repo


@pytest.fixture
def html_zaffari(fixtures_dir) -> str:
    return (fixtures_dir / "nfce_zaffari.html").read_text(encoding="utf-8")


@pytest.fixture
def repo_dados(repo, nota_zaffari):
    from datetime import datetime
    from decimal import Decimal

    from nfg.categorias import garantir_seed
    from nfg.models import Estabelecimento, Item, Nota

    garantir_seed(repo.conn)
    repo.salvar_nota(nota_zaffari)
    atacadao = Estabelecimento("75315333008860", "ATACADAO S.A.")
    zaffari = nota_zaffari.emitente

    def nota(chave, emit, emissao, total, itens):
        return Nota(chave=chave, modelo=65, emitente=emit, numero="1", serie="1", emissao=emissao,
                    protocolo=None, valor_total=Decimal(total), valor_descontos=Decimal("0"), itens=itens)

    def item(seq, cod, desc, qtd, un, vu):
        q, v = Decimal(qtd), Decimal(vu)
        return Item(seq, cod, desc, q, un, v, q * v)

    repo.salvar_nota(nota("1" * 44, atacadao, datetime(2026, 8, 10, 10, 0), "43.00", [
        item(1, "1", "ARROZ TIO JOAO 5KG", "1", "UN", "25.00"),
        item(2, "2", "COCA COLA 2L", "2", "UN", "9.00"),
    ]))
    repo.salvar_nota(nota("2" * 44, zaffari, datetime(2026, 8, 20, 18, 0), "26.90", [
        item(1, "3", "CAFE DO PONTO EXPORTACAO 500G", "1", "UN", "26.90"),
    ]))
    repo.salvar_nota(nota("3" * 44, atacadao, datetime(2026, 8, 15, 12, 0), "999.00", []))
    with repo.conn:
        repo.conn.execute("UPDATE notas SET situacao_csv='Cancelada' WHERE chave = ?", ("3" * 44,))
    return repo
