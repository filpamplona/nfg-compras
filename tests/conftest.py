from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from nfg.models import Estabelecimento, Item, Nota


def nota(chave, emit, emissao, total, itens):
    return Nota(chave=chave, modelo=65, emitente=emit, numero="1", serie="1", emissao=emissao,
                protocolo=None, valor_total=Decimal(total), valor_descontos=Decimal("0"), itens=itens)


def item(seq, cod, desc, qtd, un, vu):
    q, v = Decimal(qtd), Decimal(vu)
    return Item(seq, cod, desc, q, un, v, q * v)


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
    from nfg.categorias import garantir_seed

    garantir_seed(repo.conn)
    repo.salvar_nota(nota_zaffari)
    atacadao = Estabelecimento("75315333008860", "ATACADAO S.A.")
    zaffari = nota_zaffari.emitente

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


@pytest.fixture
def repo_produtos(repo_dados, nota_zaffari):
    repo = repo_dados
    zaf = nota_zaffari.emitente
    zaf2 = Estabelecimento(zaf.cnpj[:8] + "002590", "CIA ZAFFARI FILIAL")
    atac = Estabelecimento("75315333008860", "ATACADAO S.A.")
    repo.zaf, repo.zaf2, repo.atac = zaf.cnpj, zaf2.cnpj, atac.cnpj
    repo.salvar_nota(nota("4" * 44, zaf, datetime(2026, 9, 1, 10, 0), "199.56", [
        item(1, "101", "QJO MUSSARELA S.CLARA FAT 1KG", "1", "UN", "52.90"),
        item(2, "102", "QJO MUSSARELA TIROLEZ FAT 1KG", "1", "UN", "48.90"),
        item(3, "103", "QJO PARMESAO PRES RAL 100G", "1", "UN", "12.98"),
        item(4, "104", "PAO QJO F.MINAS TRAD CG 820G", "1", "UN", "28.90"),
        item(5, "105", "QJO PRATO S.CLARA FAT 1KG", "1", "UN", "52.90"),
        item(6, "106", "BANANA PRATA GRANEL", "1.5", "KG", "6.98"),
    ]))
    repo.salvar_nota(nota("5" * 44, atac, datetime(2026, 9, 5, 10, 0), "58.38", [
        item(1, "6752", "QJO.MUSS.FAT.DALIA", "1", "UND9", "47.90"),
        item(2, "6753", "BANANA PRATA", "2", "KG9", "5.49"),
        item(3, None, "SACOLA", "1", "UN", "0.10"),
    ]))
    repo.salvar_nota(nota("6" * 44, zaf, datetime(2026, 9, 20, 10, 0), "51.90", [
        item(1, "102", "QJO MUSSARELA TIROLEZ FAT 1KG", "1", "UN", "51.90"),
    ]))
    repo.salvar_nota(nota("7" * 44, zaf2, datetime(2026, 9, 22, 10, 0), "50.90", [
        item(1, "101", "QJO MUSSARELA S.CLARA FAT 1KG", "1", "UN", "50.90"),
    ]))
    repo.salvar_nota(nota("8" * 44, atac, datetime(2026, 9, 25, 10, 0), "10.00", [
        item(1, "6752", "QJO.MUSS.FAT.DALIA", "1", "UND9", "10.00"),
    ]))
    with repo.conn:
        repo.conn.execute("UPDATE notas SET situacao_csv='Cancelada' WHERE chave = ?", ("8" * 44,))
    return repo
