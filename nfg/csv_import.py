from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import datetime
from decimal import InvalidOperation

from nfg.erros import CSVInvalido
from nfg.models import NotaResumo
from nfg.util import (
    chave_valida,
    cnpj_da_chave,
    modelo_da_chave,
    normalizar_chave,
    parse_decimal_br,
)

COL_MUNICIPIO = "Munic."
COL_NOME = "Razão Social"
COL_EMISSAO = "Emissão"
COL_NUMERO = "Número"
COL_CHAVE = "Chave de Acesso"
COL_VALOR = "Valor"
COL_TIPO = "Tipo Operação"
COL_SITUACAO = "Situação Docto"


@dataclass
class ResultadoCSV:
    resumos: list[NotaResumo] = field(default_factory=list)
    invalidas: list[tuple[int, str]] = field(default_factory=list)


def _decodificar(dados: bytes) -> str:
    try:
        return dados.decode("utf-8-sig")
    except UnicodeDecodeError:
        return dados.decode("latin-1")


def ler(dados: bytes) -> ResultadoCSV:
    texto = _decodificar(dados)
    leitor = csv.DictReader(io.StringIO(texto, newline=""))
    campos = [(c or "").strip() for c in (leitor.fieldnames or [])]
    if COL_CHAVE not in campos:
        raise CSVInvalido(f"Coluna '{COL_CHAVE}' não encontrada no CSV.")
    leitor.fieldnames = campos

    resultado = ResultadoCSV()
    for linha in leitor:
        numero_linha = leitor.line_num
        if not any((v or "").strip() for v in linha.values() if isinstance(v, str) or v is None):
            continue
        chave = normalizar_chave(linha.get(COL_CHAVE) or "")
        if not chave.isascii() or not chave_valida(chave):
            resultado.invalidas.append((numero_linha, "chave de acesso inválida"))
            continue
        try:
            emissao = datetime.strptime((linha.get(COL_EMISSAO) or "").strip(), "%d/%m/%y").date()
            valor_total = parse_decimal_br(linha.get(COL_VALOR) or "")
        except (ValueError, InvalidOperation) as e:
            resultado.invalidas.append((numero_linha, f"dados inválidos: {e}"))
            continue
        resultado.resumos.append(
            NotaResumo(
                chave=chave,
                modelo=modelo_da_chave(chave),
                cnpj_emitente=cnpj_da_chave(chave),
                nome_csv=(linha.get(COL_NOME) or "").strip(),
                municipio=(linha.get(COL_MUNICIPIO) or "").strip(),
                numero=(linha.get(COL_NUMERO) or "").strip(),
                emissao=emissao,
                valor_total=valor_total,
                situacao=(linha.get(COL_SITUACAO) or "").strip(),
                tipo_operacao=(linha.get(COL_TIPO) or "").strip(),
            )
        )
    return resultado
