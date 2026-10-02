from datetime import datetime
from decimal import Decimal

import pytest

from nfg.erros import LayoutDesconhecido
from nfg.models import Item, Pagamento
from nfg.nfe_xml_parser import parse


def test_nfe(fixtures_dir):
    n = parse((fixtures_dir / "nfe_exemplo.xml").read_bytes())
    assert n.chave == "43260915436940001177550010445859151740147064" and n.modelo == 55
    assert n.emitente.cnpj == "15436940001177" and n.emitente.municipio == "NOVA SANTA RITA"
    assert (n.numero, n.serie, n.protocolo) == ("44585915", "1", "143260000000001")
    assert n.emissao == datetime(2026, 9, 24, 10, 15, 0)            # hora local, sem tz
    assert n.itens[0] == Item(1, "B0TESTE001", "CABO USB-C 1M", Decimal("2.0000"), "UN", Decimal("15.4200000000"), Decimal("30.84"))
    assert (n.valor_total, n.valor_descontos) == (Decimal("60.84"), Decimal("0.00"))
    assert n.pagamentos == [Pagamento("Cartão de Crédito", Decimal("60.84"))]


def test_endereco_e_ie(fixtures_dir):
    n = parse((fixtures_dir / "nfe_exemplo.xml").read_bytes())
    assert n.emitente.endereco == "AV ANTONIO FRANCISCO DA SILVA, 1000, DISTRITO INDUSTRIAL, NOVA SANTA RITA, RS"
    assert n.emitente.inscricao_estadual == "0960000000"
    assert len(n.itens) == 2 and n.itens[1].seq == 2


def test_xml_invalido():
    with pytest.raises(LayoutDesconhecido):
        parse(b"<html>nada</html>")


def test_xml_malformado():
    with pytest.raises(LayoutDesconhecido):
        parse(b"<nfeProc><NFe>")
