from decimal import Decimal

import pytest

from nfg.produtos_texto import (
    formatar_tamanho,
    normalizar_produto,
    normalizar_unidade,
    sugerir_nome,
)
from nfg.util import normalizar_texto

MUSS = {"QUEIJO", "MUSSARELA", "FATIADO"}


@pytest.mark.parametrize("desc,un", [("QJO MUSSARELA S.CLARA FAT 1KG", "UN"),
                                     ("QJO MUSSARELA TIROLEZ FAT 1KG", "UN"),
                                     ("QJO.MUSS.FAT.DALIA", "UND9")])
def test_tres_mussarelas_mesmo_tipo_e_tokens(desc, un):
    a = normalizar_produto(desc, un)
    assert a.tipo == "QUEIJO MUSSARELA" and a.tokens == MUSS and a.venda == "UN"


def test_tamanho_mussarela():
    assert normalizar_produto("QJO MUSSARELA S.CLARA FAT 1KG", "UN").tamanho == (Decimal(1000), "G")
    assert normalizar_produto("QJO.MUSS.FAT.DALIA", "UND9").tamanho is None


def test_parmesao_e_pao_de_queijo_tem_outro_tipo():
    assert normalizar_produto("QJO PARMESAO PRES RAL 100G", "UN").tipo == "QUEIJO PARMESAO"
    assert normalizar_produto("PAO QJO F.MINAS TRAD CG 820G", "UN").tipo == "PAO QUEIJO"


@pytest.mark.parametrize("desc,esperado", [
    ("COCA COLA 1,5L", (Decimal(1500), "ML")), ("VH CON TORO RESERVADO 750M", (Decimal(750), "ML")),
    ("PAO QJO F.MINAS TRAD CG 820G", (Decimal(820), "G")), ("OVO CAIP NATURALE C/20", (Decimal(20), "UN")),
    ("OVOS FILIPPSEN CAIPIRA C20", (Decimal(20), "UN")), ("P H NEVE L16", (Decimal(16), "UN")),
    ("ACHOC PO 30%", (Decimal(30), "%")), ("LIMP VDR JIMO AER400ML", (Decimal(400), "ML")),
])
def test_extrai_tamanho(desc, esperado):
    assert normalizar_produto(desc, "UN").tamanho == esperado


def test_ovos_sinonimo_de_cabeca():
    assert normalizar_produto("OVOS FILIPPSEN CAIPIRA C20", "UN").tipo == "OVO CAIPIRA"
    assert normalizar_produto("OVO CAIP NATURALE C/20", "UN").tipo == "OVO CAIPIRA"


def test_com_sem_viram_palavras():
    assert {"COM", "GAS"} <= normalizar_produto("AGUA C/GAS 500ML", "UN").tokens
    assert {"SEM", "LACTOSE"} <= normalizar_produto("LEITE S/LACTOSE 1L", "UN").tokens


def test_tamanho_secundario_vira_palavra():
    a = normalizar_produto("LEITE PO 400G 30%", "UN")
    assert a.tamanho == (Decimal(400), "G") and "30%" in a.tokens


def test_tamanho_igual_ao_escolhido_e_descartado():
    a = normalizar_produto("QUEIJO MUSSARELA FATIADO 1KG 1KG", "UN")
    assert a.tokens == {"QUEIJO", "MUSSARELA", "FATIADO"} and a.tamanho == (Decimal(1000), "G")
    a = normalizar_produto("OVO CAIPIRA C/20 C/20", "UN")
    assert a.tokens == {"OVO", "CAIPIRA"} and a.tamanho == (Decimal(20), "UN")


@pytest.mark.parametrize("desc,un", [("QJO MUSSARELA S.CLARA FAT 1KG", "UN"),
                                     ("LEITE PO 400G 30%", "UN"),
                                     ("OVO CAIP NATURALE C/20", "UN"),
                                     ("LEITE 1KG 500G", "UN"), ("LEITE 500G 1KG", "UN"),
                                     ("BANANA PRATA GRANEL", "KG")])
def test_nome_sugerido_faz_round_trip(desc, un):
    nome, _tipo, _tam, venda = sugerir_nome(desc, un)
    a, b = normalizar_produto(desc, un), normalizar_produto(nome, venda)
    assert (a.tipo, a.tokens, a.tamanho, a.venda) == (b.tipo, b.tokens, b.tamanho, b.venda)


@pytest.mark.parametrize("un,esperado", [("UND9", "UN"), ("UNID", "UN"), ("un", "UN"), (None, "UN"),
                                         ("KG9", "KG"), ("kg", "KG"), ("PCT9", "PCT"), ("CXA1", "CX"),
                                         ("CAIXA", "CX"), ("CX", "CX")])
def test_normalizar_unidade(un, esperado):
    assert normalizar_unidade(un) == esperado


def test_granel_vende_por_kg():
    a = normalizar_produto("BANANA PRATA GRANEL", "KG")
    assert (a.tipo, a.tamanho, a.venda) == ("BANANA PRATA", None, "KG")
    assert normalizar_produto("CENOURA kg", "KG9").tipo == "CENOURA"


@pytest.mark.parametrize("t,s", [((Decimal(1000), "G"), "1KG"), ((Decimal(500), "G"), "500G"),
                                 ((Decimal(1500), "ML"), "1,5L"), ((Decimal(350), "ML"), "350ML"),
                                 ((Decimal(20), "UN"), "C/20"), ((Decimal(30), "%"), "30%"),
                                 (None, None)])
def test_formatar_tamanho(t, s):
    assert formatar_tamanho(t) == s


def test_sugerir_nome():
    assert sugerir_nome("QJO MUSSARELA S.CLARA FAT 1KG", "UN") == (
        "QUEIJO MUSSARELA FATIADO 1KG", "QUEIJO MUSSARELA", "1KG", "UN")
    assert sugerir_nome("BANANA PRATA GRANEL", "KG") == ("BANANA PRATA", "BANANA PRATA", None, "KG")


@pytest.mark.parametrize("desc", ["*", "KG", "TIROLEZ", ""])
def test_descricao_sem_palavras_nao_quebra(desc):
    a = normalizar_produto(desc, "UN")
    assert a.tipo == "" and a.tokens == frozenset()
    assert sugerir_nome(desc, "UN")[0] == normalizar_texto(desc)


def test_decimal_com_ponto():
    a = normalizar_produto("COCA COLA 1.5L", "UN")
    assert a.tamanho == (Decimal(1500), "ML") and "1" not in a.tokens
    assert normalizar_produto("AGUA 0.5L", "UN").tamanho == (Decimal(500), "ML")


def test_ref_nao_vira_refrigerante():
    assert "REFRIGERANTE" not in normalizar_produto("ACUCAR REF UNIAO 1KG", "UN").palavras


def test_lt_so_vira_leite_no_inicio():
    assert "LEITE" not in normalizar_produto("CERV BRAHMA LT 350ML", "UN").palavras
    assert normalizar_produto("LT INTEGRAL PIRACANITA 1L", "UN").tipo.startswith("LEITE")


def test_barra_com_espaco_vira_com_sem():
    a = normalizar_produto("BISC C/ RECHEIO MORANGO 100G", "UN")
    assert a.tipo == "BISCOITO COM" and "C" not in a.palavras
    b = normalizar_produto("AMENDOIM S/ SAL 200G", "UN")
    assert "SEM" in b.palavras and "S" not in b.palavras
