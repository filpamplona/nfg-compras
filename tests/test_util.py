from decimal import Decimal

from nfg.util import (
    cnpj_da_chave,
    chave_valida,
    formatar_brl,
    from_centavos,
    mascarar_cpf,
    modelo_da_chave,
    normalizar_chave,
    normalizar_texto,
    parse_decimal_br,
    to_centavos,
)

CHAVE_ZAFFARI = "43260993015006000547651210003414481604643989"
CHAVE_AMAZON = "43260915436940001177550010445859151740147064"


def test_parse_decimal_br():
    assert parse_decimal_br("R$382,47") == Decimal("382.47")
    assert parse_decimal_br("R$1.234,56") == Decimal("1234.56")
    assert parse_decimal_br(" 0,9399 ") == Decimal("0.9399")
    assert parse_decimal_br("21,8") == Decimal("21.8")
    assert parse_decimal_br("1\xa0234,00") == Decimal("1234.00")


def test_centavos_ida_e_volta():
    assert to_centavos(Decimal("382.47")) == 38247
    assert to_centavos(Decimal("0.005")) == 1  # ROUND_HALF_UP
    assert from_centavos(38247) == Decimal("382.47")


def test_chave():
    assert normalizar_chave("4326099301500600054765 1210003414481604643989") == CHAVE_ZAFFARI
    assert chave_valida(CHAVE_ZAFFARI) and chave_valida(CHAVE_AMAZON)
    assert not chave_valida(CHAVE_ZAFFARI[:-1] + "0")  # DV errado
    assert not chave_valida("123")
    assert modelo_da_chave(CHAVE_ZAFFARI) == 65 and modelo_da_chave(CHAVE_AMAZON) == 55
    assert cnpj_da_chave(CHAVE_ZAFFARI) == "93015006000547"


def test_normalizar_texto():
    assert normalizar_texto("  Café do   Ponto ") == "CAFE DO PONTO"


def test_mascarar_cpf():
    assert mascarar_cpf("CPF: 123.456.789-09") == "CPF: 000.000.000-00"


def test_mascarar_cpf_sem_formatacao():
    assert mascarar_cpf("CPF: 12345678909") == "CPF: 00000000000"
    assert mascarar_cpf("cpf:12345678909 fim") == "cpf: 00000000000 fim"
    assert mascarar_cpf("Chave 43260993015006000547651210003414481604643989") ==         "Chave 43260993015006000547651210003414481604643989"


def test_formatar_brl():
    assert formatar_brl(Decimal("1234.5")) == "R$ 1.234,50"
