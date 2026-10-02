from __future__ import annotations

import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal


def parse_decimal_br(texto: str) -> Decimal:
    limpo = texto.replace("R$", "").replace("&nbsp;", "")
    limpo = re.sub(r"\s", "", limpo)  # \s cobre \xa0 em str
    return Decimal(limpo.replace(".", "").replace(",", "."))


def to_centavos(valor: Decimal) -> int:
    return int((Decimal(valor) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def from_centavos(c: int) -> Decimal:
    return Decimal(c) / 100


def normalizar_chave(texto: str) -> str:
    return re.sub(r"\D", "", texto)


def chave_valida(chave: str) -> bool:
    if len(chave) != 44 or not chave.isdigit():
        return False
    soma = 0
    for i, d in enumerate(reversed(chave[:43])):
        soma += int(d) * (2 + i % 8)
    resto = soma % 11
    dv = 0 if resto < 2 else 11 - resto
    return dv == int(chave[43])


def modelo_da_chave(chave: str) -> int:
    return int(chave[20:22])


def cnpj_da_chave(chave: str) -> str:
    return chave[6:20]


def normalizar_texto(texto: str) -> str:
    decomposto = unicodedata.normalize("NFKD", texto)
    sem_acento = "".join(c for c in decomposto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().upper()


def mascarar_cpf(texto: str) -> str:
    texto = re.sub(r"\d{3}\.\d{3}\.\d{3}-\d{2}", "000.000.000-00", texto)
    return re.sub(r"(CPF:)\s*\d{11}(?!\d)", r"\g<1> 00000000000", texto, flags=re.IGNORECASE)


def formatar_brl(valor: Decimal | float) -> str:
    q = Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    s = f"{q:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"
