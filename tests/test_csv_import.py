from datetime import date
from decimal import Decimal

import pytest

from nfg.csv_import import ler
from nfg.erros import CSVInvalido


def test_le_csv_real(fixtures_dir):
    r = ler((fixtures_dir / "relatorio_nfg.csv").read_bytes())
    assert len(r.resumos) == 11 and r.invalidas == []
    z = r.resumos[0]
    assert z.chave == "43260993015006000547651210003414481604643989"
    assert (z.modelo, z.cnpj_emitente, z.nome_csv) == (65, "93015006000547", "Cia Zaffari Com E Ind")
    assert (z.numero, z.emissao, z.valor_total) == ("341448", date(2026, 9, 26), Decimal("382.47"))
    assert (z.municipio, z.situacao, z.tipo_operacao) == ("Porto Alegre", "Normal", "Aquisição")
    assert [x.modelo for x in r.resumos].count(55) == 1


def test_latin1_bom_e_linha_vazia(fixtures_dir):
    texto = (fixtures_dir / "relatorio_nfg.csv").read_text("utf-8")
    assert len(ler(texto.encode("latin-1")).resumos) == 11
    assert len(ler(b"\xef\xbb\xbf" + texto.encode("utf-8") + b"\r\n\r\n").resumos) == 11


def test_chave_invalida_vira_linha_invalida(fixtures_dir):
    texto = (fixtures_dir / "relatorio_nfg.csv").read_text("utf-8").replace("1604643989", "1604643980")
    r = ler(texto.encode("utf-8"))
    assert len(r.resumos) == 10 and r.invalidas[0][0] == 2 and "chave" in r.invalidas[0][1].lower()


def test_chave_nao_ascii_vira_linha_invalida(fixtures_dir):
    texto = (fixtures_dir / "relatorio_nfg.csv").read_text("utf-8").replace("1604643989", "160464398²")
    r = ler(texto.encode("utf-8"))
    assert len(r.resumos) == 10 and "chave" in r.invalidas[0][1].lower()


def test_sem_coluna_chave():
    with pytest.raises(CSVInvalido):
        ler('"a","b"\n"1","2"\n'.encode())


@pytest.mark.parametrize("velho,novo", [('"26/09/26","341448"', None), ("R$382,47", "abc")])
def test_data_ou_valor_ruim_vira_linha_invalida(fixtures_dir, velho, novo):
    texto = (fixtures_dir / "relatorio_nfg.csv").read_text("utf-8")
    if novo is None:
        texto = texto.replace('"26/09/26","341448"', '"99/99/99","341448"')
    else:
        texto = texto.replace(velho, novo)
    r = ler(texto.encode("utf-8"))
    assert len(r.resumos) == 10 and r.invalidas[0][0] == 2
    assert r.invalidas[0][1].startswith("dados inválidos")
