from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from decimal import Decimal, InvalidOperation

from nfg.erros import LayoutDesconhecido
from nfg.models import Estabelecimento, Item, Nota, Pagamento
from nfg.util import modelo_da_chave, normalizar_chave

NS = "{http://www.portalfiscal.inf.br/nfe}"

FORMAS_PAGAMENTO = {
    "01": "Dinheiro",
    "02": "Cheque",
    "03": "Cartão de Crédito",
    "04": "Cartão de Débito",
    "05": "Crédito Loja",
    "10": "Vale Alimentação",
    "11": "Vale Refeição",
    "15": "Boleto Bancário",
    "17": "PIX",
}


def _obrigatorio(no: ET.Element, caminho: str) -> ET.Element:
    achado = no.find(caminho)
    if achado is None:
        raise LayoutDesconhecido(f"Elemento ausente no XML da NF-e: {caminho}")
    return achado


def _texto(no: ET.Element, caminho: str) -> str:
    return (_obrigatorio(no, caminho).text or "").strip()


def _texto_opcional(no: ET.Element, caminho: str) -> str | None:
    achado = no.find(caminho)
    if achado is None or not (achado.text or "").strip():
        return None
    return achado.text.strip()


def _decimal(no: ET.Element, caminho: str) -> Decimal:
    return Decimal(_texto(no, caminho))


def parse(dados: bytes) -> Nota:
    try:
        raiz = ET.fromstring(dados)
    except ET.ParseError as e:
        raise LayoutDesconhecido(f"XML inválido: {e}") from e

    if raiz.tag == f"{NS}nfeProc":
        nfe = raiz.find(f"{NS}NFe")
    elif raiz.tag == f"{NS}NFe":
        nfe = raiz
    else:
        raise LayoutDesconhecido("O XML não é uma NF-e")
    if nfe is None:
        raise LayoutDesconhecido("Elemento NFe ausente")

    try:
        inf = _obrigatorio(nfe, f"{NS}infNFe")
        chave = normalizar_chave(inf.get("Id", ""))
        if len(chave) != 44:
            raise LayoutDesconhecido("Chave de acesso ausente ou inválida no XML")

        ide = _obrigatorio(inf, f"{NS}ide")
        emit = _obrigatorio(inf, f"{NS}emit")
        ender = emit.find(f"{NS}enderEmit")
        endereco = None
        municipio = None
        if ender is not None:
            partes = [_texto_opcional(ender, f"{NS}{t}") for t in ("xLgr", "nro", "xBairro", "xMun", "UF")]
            endereco = ", ".join(p for p in partes if p) or None
            municipio = _texto_opcional(ender, f"{NS}xMun")
        emitente = Estabelecimento(
            cnpj=_texto(emit, f"{NS}CNPJ"),
            razao_social=_texto(emit, f"{NS}xNome"),
            inscricao_estadual=_texto_opcional(emit, f"{NS}IE"),
            endereco=endereco,
            municipio=municipio,
        )

        emissao = datetime.fromisoformat(_texto(ide, f"{NS}dhEmi")).replace(tzinfo=None)

        itens = []
        for det in inf.findall(f"{NS}det"):
            prod = _obrigatorio(det, f"{NS}prod")
            itens.append(Item(
                seq=int(det.get("nItem")),
                codigo=_texto(prod, f"{NS}cProd"),
                descricao=_texto(prod, f"{NS}xProd"),
                quantidade=_decimal(prod, f"{NS}qCom"),
                unidade=_texto(prod, f"{NS}uCom"),
                valor_unitario=_decimal(prod, f"{NS}vUnCom"),
                valor_total=_decimal(prod, f"{NS}vProd"),
            ))

        icms = _obrigatorio(inf, f"{NS}total/{NS}ICMSTot")
        desc = _texto_opcional(icms, f"{NS}vDesc")
        pagamentos = [
            Pagamento(
                FORMAS_PAGAMENTO.get(_texto(dp, f"{NS}tPag"), "Outros"),
                _decimal(dp, f"{NS}vPag"),
            )
            for dp in inf.findall(f"{NS}pag/{NS}detPag")
        ]

        protocolo = _texto_opcional(raiz, f"{NS}protNFe/{NS}infProt/{NS}nProt")

        return Nota(
            chave=chave,
            modelo=modelo_da_chave(chave),
            emitente=emitente,
            numero=_texto(ide, f"{NS}nNF"),
            serie=_texto(ide, f"{NS}serie"),
            emissao=emissao,
            protocolo=protocolo,
            valor_total=_decimal(icms, f"{NS}vNF"),
            valor_descontos=Decimal(desc) if desc else Decimal("0"),
            itens=itens,
            pagamentos=pagamentos,
        )
    except (InvalidOperation, ValueError, TypeError) as e:
        raise LayoutDesconhecido(f"Valor inválido no XML da NF-e: {e}") from e
