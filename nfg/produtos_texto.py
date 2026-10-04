"""Normalização de descrições de itens para o agrupamento em produtos unificados.

Funções puras (sem banco). Ampliar os dicionários abaixo é a forma de melhorar as sugestões.
"""
import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

from nfg.util import normalizar_texto

ABREVIACOES: dict[str, str] = {
    "QJO": "QUEIJO",
    "MUSS": "MUSSARELA",
    "FAT": "FATIADO",
    "RAL": "RALADO",
    "LTE": "LEITE",
    "CHOC": "CHOCOLATE",
    "ACHOC": "ACHOCOLATADO",
    "BISC": "BISCOITO",
    "IOG": "IOGURTE",
    "CR": "CREME",
    "REFRIG": "REFRIGERANTE",
    "CG": "CONGELADO",
    "CONG": "CONGELADO",
    "PARB": "PARBOILIZADO",
    "CAIP": "CAIPIRA",
    "INT": "INTEGRAL",
    "TRAD": "TRADICIONAL",
    "VH": "VINHO",
    "VIN": "VINHO",
    "LIMP": "LIMPADOR",
    "VDR": "VIDRO",
    "AER": "AEROSOL",
    "PO": "PO",
    "DESC": "DESCARTAVEL",
    "SAB": "SABONETE",
    "DET": "DETERGENTE",
    "AMAC": "AMACIANTE",
    "MAC": "MACARRAO",
    "MARG": "MARGARINA",
    "PRESUNT": "PRESUNTO",
    "SALS": "SALSICHA",
    "LING": "LINGUICA",
    "FGO": "FRANGO",
    "BOV": "BOVINA",
    "SUIN": "SUINO",
    "TOM": "TOMATE",
    "BAT": "BATATA",
    "ARR": "ARROZ",
    "FEIJ": "FEIJAO",
    "AZ": "AZEITE",
    "AZEIT": "AZEITE",
    "NAT": "NATURAL",
    "DESN": "DESNATADO",
    "SEMI": "SEMIDESNATADO",
    "PAP": "PAPEL",
    "HIG": "HIGIENICO",
    "ESC": "ESCOVA",
    "DENT": "DENTAL",
    "CREM": "CREME",
    "EXT": "EXTRATO",
    "MOLH": "MOLHO",
}

SINONIMOS_TIPO: dict[str, str] = {
    "OVOS": "OVO",
    "KITKAT": "CHOCOLATE KIT KAT",
    "COCA": "REFRIGERANTE COCA",
    "PAOZINHO": "PAO",
    "PAES": "PAO",
    "QUEIJOS": "QUEIJO",
    "BANANAS": "BANANA",
    "LEITES": "LEITE",
    "BISCOITOS": "BISCOITO",
    "IOGURTES": "IOGURTE",
}

MARCAS: frozenset[str] = frozenset({
    "SCLARA", "TIROLEZ", "DALIA", "PRES", "PRESIDENT", "TUTTI", "FMINAS", "BVILLE", "SBOYS",
    "NATURALE", "FILIPPSEN", "JIMO", "NEVE", "CON", "TORO",
    "NESTLE", "DANONE", "PARMALAT", "ITAMBE", "ELEGE", "PIRACANITA", "QUATA", "CAMIL", "TIOJOAO",
    "LACTA", "GAROTO", "SADIA", "PERDIGAO", "SEARA", "ARISCO", "HEINZ", "BAUDUCCO", "OMO",
    "YPE", "DOVE", "COLGATE", "ZAFFARI", "MARCA",
})

STOPWORDS: frozenset[str] = frozenset({
    "DE", "DA", "DO", "DAS", "DOS", "E", "AO", "A", "O", "EM", "PACOTE", "GRANEL", "KG", "UN",
})

_UNIDADES: dict[str, str] = {
    "UN": "UN", "UND": "UN", "UNID": "UN", "UNI": "UN", "UNIDADE": "UN",
    "KG": "KG", "KGS": "KG", "QUILO": "KG",
    "PCT": "PCT", "PACOTE": "PCT",
    "CX": "CX", "CXA": "CX", "CAIXA": "CX",
}

# Prioridade do tamanho: peso/volume > embalagem > percentual.
_PRIORIDADE = {"PESO": 0, "EMB": 1, "PERC": 2}

_RE_COLAR_MARCA = re.compile(r"\b([A-Z])\.(?=[A-Z]{2})")
_RE_MULTIPACOTE = re.compile(r"(?<!\d)(?<!\d[.,])(\d+)\s?X\s?(\d+(?:[.,]\d+)?)\s?(KG|G|L|ML)\b")
_RE_PESO = re.compile(r"(?<!\d)(?<!\d[.,])(\d+(?:[.,]\d+)?)\s?(KG|G|L|ML|M)\b")
_RE_EMBALAGEM = re.compile(r"\bC/?(\d+)\b|\bL(\d+)\b")
_RE_PERCENTUAL = re.compile(r"(?<!\d)(?<!\d[.,])(\d+(?:[.,]\d+)?)\s?%")


@dataclass(frozen=True)
class Assinatura:
    tipo: str
    palavras: tuple[str, ...]
    tokens: frozenset[str]
    tamanho: tuple[Decimal, str] | None
    venda: str


def normalizar_unidade(unidade: str | None) -> str:
    if not unidade:
        return "UN"
    base = re.sub(r"\d+$", "", normalizar_texto(unidade))
    if not base:
        return "UN"
    return _UNIDADES.get(base, base)


def _decimal(texto: str) -> Decimal:
    return Decimal(texto.replace(",", "."))  # aceita "," e "." como separador


def _inteiro_se_possivel(valor: Decimal) -> Decimal:
    return Decimal(int(valor)) if valor == valor.to_integral_value() else valor


def _peso_volume(valor: Decimal, unidade: str) -> tuple[Decimal, str]:
    if unidade == "KG":
        return _inteiro_se_possivel(valor * 1000), "G"
    if unidade == "G":
        return _inteiro_se_possivel(valor), "G"
    if unidade == "L":
        return _inteiro_se_possivel(valor * 1000), "ML"
    return _inteiro_se_possivel(valor), "ML"  # ML e M (ML truncado)


def _extrair_tamanhos(texto: str) -> tuple[str, list[tuple[str, tuple[Decimal, str]]]]:
    """Remove os tamanhos do texto; devolve (texto, [(tipo, (valor, unidade))]) em ordem de aparição por tipo."""
    achados: list[tuple[str, tuple[Decimal, str]]] = []

    def multipacote(m):
        total = Decimal(m.group(1)) * _decimal(m.group(2))
        achados.append(("PESO", _peso_volume(total, m.group(3))))
        return " "

    def peso(m):
        achados.append(("PESO", _peso_volume(_decimal(m.group(1)), m.group(2))))
        return " "

    def embalagem(m):
        achados.append(("EMB", (Decimal(m.group(1) or m.group(2)), "UN")))
        return " "

    def percentual(m):
        achados.append(("PERC", (_inteiro_se_possivel(_decimal(m.group(1))), "%")))
        return " "

    texto = _RE_MULTIPACOTE.sub(multipacote, texto)
    texto = _RE_PESO.sub(peso, texto)
    texto = _RE_EMBALAGEM.sub(embalagem, texto)
    texto = _RE_PERCENTUAL.sub(percentual, texto)
    return texto, achados


def _numero(valor: Decimal) -> str:
    return format(_inteiro_se_possivel(valor.normalize() if valor != 0 else valor), "f").replace(".", ",")


def formatar_tamanho(tamanho: tuple[Decimal, str] | None) -> str | None:
    if tamanho is None:
        return None
    valor, unidade = tamanho
    if unidade in ("G", "ML") and valor >= 1000:
        return _numero(valor / 1000) + ("KG" if unidade == "G" else "L")
    if unidade == "UN":
        return f"C/{_numero(valor)}"
    return _numero(valor) + unidade


def _assinar(descricao: str, unidade: str | None) -> tuple[Assinatura, tuple[str, ...], list[str]]:
    """Devolve (assinatura, palavras regulares, palavras de tamanho secundário)."""
    texto = normalizar_texto(descricao or "")
    texto = _RE_COLAR_MARCA.sub(r"\1", texto)
    texto, achados = _extrair_tamanhos(texto)

    escolhido = None
    if achados:
        escolhido = min(achados, key=lambda a: _PRIORIDADE[a[0]])[1]  # min é estável: 1º de cada prioridade
    secundarios = []
    for _, tam in achados:
        if tam != escolhido and (palavra := formatar_tamanho(tam)) not in secundarios:
            secundarios.append(palavra)

    texto = re.sub(r"\bC/\s*(?=[A-Z])", "COM ", texto)
    texto = re.sub(r"\bS/\s*(?=[A-Z])", "SEM ", texto)
    texto = re.sub(r"[^A-Z0-9]+", " ", texto)

    # "LT" é leite só como primeira palavra ("LT INTEGRAL"); no fim é lata ("CERV X LT 350ML")
    palavras = [("LEITE" if p == "LT" and i == 0 else ABREVIACOES.get(p, p)) for i, p in enumerate(texto.split())]
    palavras = [p for p in palavras if p not in MARCAS and p not in STOPWORDS]
    if palavras and palavras[0] in SINONIMOS_TIPO:
        palavras[:1] = SINONIMOS_TIPO[palavras[0]].split()
    sem_repetidas: list[str] = []
    for p in palavras:
        if not sem_repetidas or sem_repetidas[-1] != p:
            sem_repetidas.append(p)

    tipo = " ".join(sem_repetidas[:2])
    secundarios = [s for s in secundarios if s not in sem_repetidas]
    finais = tuple(sem_repetidas) + tuple(secundarios)
    venda = "KG" if normalizar_unidade(unidade) == "KG" else "UN"
    return Assinatura(tipo, finais, frozenset(finais), escolhido, venda), tuple(sem_repetidas), secundarios


def normalizar_produto(descricao: str, unidade: str | None) -> Assinatura:
    return _assinar(descricao, unidade)[0]


def sugerir_nome(descricao: str, unidade: str | None) -> tuple[str, str, str | None, str]:
    """Devolve (nome, tipo, tamanho, venda) sugeridos para um produto novo."""
    a, regulares, secundarios = _assinar(descricao, unidade)
    tamanho = formatar_tamanho(a.tamanho)
    if not a.palavras:
        nome = normalizar_texto(descricao or "")
        return nome, nome, tamanho, a.venda
    # tamanho escolhido antes dos secundários, para que renormalizar o nome o escolha de novo
    nome = " ".join((*regulares, *([tamanho] if tamanho else []), *secundarios))
    return nome, a.tipo, tamanho, a.venda


def pontuar(item: Assinatura, produto: Assinatura, similares: Sequence[Assinatura] = ()) -> tuple[float, str] | None:
    """Pontua (0-100) a compatibilidade item x produto; None = veto."""
    if not item.tipo or not produto.tipo:
        return None
    palavras_item, palavras_produto = item.tipo.split(), produto.tipo.split()
    if palavras_item[0] != palavras_produto[0] or item.venda != produto.venda:
        return None
    if item.tamanho and produto.tamanho and item.tamanho != produto.tamanho:
        return None

    def jaccard(s: Assinatura) -> float:
        uniao = item.tokens | s.tokens
        return 70 * len(item.tokens & s.tokens) / len(uniao) if uniao else 0.0

    score = max(jaccard(s) for s in (produto, *similares))
    motivos = ["mesmo tipo"]
    if len(palavras_item) > 1 and len(palavras_produto) > 1 and palavras_item[1] == palavras_produto[1]:
        score += 20
        motivos.append("mesmo qualificador")
    if item.tamanho and item.tamanho == produto.tamanho:
        score += 10
        motivos.append("mesmo tamanho")
    else:
        motivos.append("tamanho não informado")
    return round(score, 2), "; ".join(motivos)
