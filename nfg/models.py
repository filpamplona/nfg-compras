from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal


@dataclass
class Estabelecimento:
    cnpj: str
    razao_social: str
    inscricao_estadual: str | None = None
    endereco: str | None = None
    municipio: str | None = None


@dataclass
class NotaResumo:
    chave: str
    modelo: int
    cnpj_emitente: str
    nome_csv: str
    municipio: str
    numero: str
    emissao: date
    valor_total: Decimal
    situacao: str
    tipo_operacao: str


@dataclass
class Item:
    seq: int
    codigo: str
    descricao: str
    quantidade: Decimal
    unidade: str
    valor_unitario: Decimal
    valor_total: Decimal


@dataclass
class Pagamento:
    forma: str
    valor: Decimal


@dataclass
class Nota:
    chave: str
    modelo: int
    emitente: Estabelecimento
    numero: str
    serie: str
    emissao: datetime
    protocolo: str | None
    valor_total: Decimal
    valor_descontos: Decimal
    itens: list[Item] = field(default_factory=list)
    pagamentos: list[Pagamento] = field(default_factory=list)
