"""Parser do HTML da consulta pública de NFC-e (SEFAZ-RS, XSLT 1.10)."""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup, Tag

from nfg.erros import BloqueioSefaz, LayoutDesconhecido, NotaNaoEncontrada
from nfg.models import Estabelecimento, Item, Nota, Pagamento
from nfg.util import modelo_da_chave, normalizar_chave, parse_decimal_br

_MARCAS_REJEICAO = ("não encontrad", "inexistente", "rejei", "inválid")


def _espacos(texto: str) -> str:
    return re.sub(r"\s+", " ", texto.replace("\xa0", " ")).strip()


def _busca(padrao: str, texto: str, campo: str) -> re.Match[str]:
    m = re.search(padrao, texto)
    if not m:
        raise LayoutDesconhecido(f"Campo não encontrado no HTML da NFC-e: {campo}")
    return m


def _decimal(texto: str, campo: str) -> Decimal:
    try:
        return parse_decimal_br(texto)
    except (InvalidOperation, ValueError) as exc:
        raise LayoutDesconhecido(f"Valor inválido em {campo}: {texto!r}") from exc


def _celula_valor_opcional(soup: BeautifulSoup, rotulo: str) -> str | None:
    for td in soup.find_all("td"):
        if _espacos(td.get_text()).lower().startswith(rotulo.lower()):
            prox = td.find_next_sibling("td")
            if prox is not None:
                return prox.get_text()
    return None


def _celula_valor(soup: BeautifulSoup, rotulo: str) -> str:
    texto = _celula_valor_opcional(soup, rotulo)
    if texto is None:
        raise LayoutDesconhecido(f"Campo não encontrado no HTML da NFC-e: {rotulo}")
    return texto


def _emitente(cab: Tag, soup: BeautifulSoup) -> Estabelecimento:
    nome = cab.select_one("td.NFCCabecalho_SubTitulo")
    subs = cab.select("td.NFCCabecalho_SubTitulo1")
    if nome is None or len(subs) < 1:
        raise LayoutDesconhecido("Cabeçalho do emitente ausente")
    razao = _espacos(nome.get_text())
    ident = _espacos(subs[0].get_text())
    cnpj = re.sub(r"\D", "", _busca(r"CNPJ:\s*([\d./-]+)", ident, "CNPJ").group(1))
    ie = _busca(r"Inscri\S*\s*Estadual:\s*(\S+)", ident, "Inscrição Estadual").group(1)
    tabela_end = soup.select("table.NFCCabecalho td.NFCCabecalho_SubTitulo1")
    endereco = municipio = None
    if len(tabela_end) >= 2:
        partes = [_espacos(p) for p in tabela_end[1].get_text().split(",")]
        partes = [p for p in partes if p]
        if partes:
            endereco = ", ".join(partes)
            if len(partes) >= 2:
                municipio = partes[-2]
    return Estabelecimento(cnpj=cnpj, razao_social=razao, inscricao_estadual=ie,
                           endereco=endereco, municipio=municipio)


def _chave(soup: BeautifulSoup) -> str:
    for td in soup.find_all("td"):
        if _espacos(td.get_text()).upper() == "CHAVE DE ACESSO":
            prox = td.find_next("td")
            chave = normalizar_chave(prox.get_text()) if prox is not None else ""
            if len(chave) == 44:
                return chave
    raise LayoutDesconhecido("Chave de acesso não encontrada")


def _itens(soup: BeautifulSoup) -> list[Item]:
    itens = []
    for seq, tr in enumerate(soup.select('tr[id^="Item"]'), start=1):
        tds = tr.select("td.NFCDetalhe_Item")
        if len(tds) != 6:
            raise LayoutDesconhecido(f"Item {seq} com {len(tds)} colunas (esperado 6)")
        c = [_espacos(td.get_text()) for td in tds]
        itens.append(Item(
            seq=seq, codigo=c[0], descricao=c[1],
            quantidade=_decimal(c[2], f"quantidade do item {seq}"), unidade=c[3],
            valor_unitario=_decimal(c[4], f"valor unitário do item {seq}"),
            valor_total=_decimal(c[5], f"valor total do item {seq}"),
        ))
    if not itens:
        raise LayoutDesconhecido("Nenhum item encontrado")
    return itens


def _pagamentos(soup: BeautifulSoup) -> list[Pagamento]:
    for td in soup.find_all("td"):
        if _espacos(td.get_text()).upper() == "FORMA PAGAMENTO":
            pagamentos = []
            for tr in td.find_parent("tr").find_next_siblings("tr"):
                tds = tr.find_all("td", recursive=False)
                if len(tds) >= 2 and not _espacos(tds[0].get_text()).lower().startswith("troco"):
                    pagamentos.append(Pagamento(
                        _espacos(tds[0].get_text()),
                        _decimal(tds[1].get_text(), "valor do pagamento")))
            return pagamentos
    raise LayoutDesconhecido("Seção FORMA PAGAMENTO não encontrada")


def parse(html: str) -> Nota:
    soup = BeautifulSoup(html, "lxml")
    cab = soup.select_one("table.NFCCabecalho")
    if cab is None:
        if "captcha" in html.lower():
            raise BloqueioSefaz("SEFAZ pediu captcha; consulta bloqueada")
        texto = _espacos(soup.get_text())
        if any(m in texto.lower() for m in _MARCAS_REJEICAO):
            raise NotaNaoEncontrada(texto[:200])
        raise LayoutDesconhecido("Tabela de cabeçalho da NFC-e ausente")

    texto = _espacos(soup.get_text())
    m = _busca(r"NFC-e\s*n\S*:\s*(\d+)\s*S\S*rie:\s*(\d+)\s*Data de Emiss\S*o:\s*(\S+ \S+)",
               texto, "número/série/emissão")
    numero, serie, emissao_txt = m.groups()
    try:
        emissao = datetime.strptime(emissao_txt, "%d/%m/%Y %H:%M:%S")
    except ValueError as exc:
        raise LayoutDesconhecido(f"Data de emissão inválida: {emissao_txt!r}") from exc
    pm = re.search(r"Protocolo de Autoriza\S*o:\s*(\d+)", texto)
    chave = _chave(soup)

    txt_descontos = _celula_valor_opcional(soup, "Valor descontos R$")
    descontos = _decimal(txt_descontos, "valor descontos") if txt_descontos is not None else Decimal("0")
    txt_pago = _celula_valor_opcional(soup, "Valor a pagar R$")
    if txt_pago is not None:
        pago = _decimal(txt_pago, "valor a pagar")
    else:
        # "Valor total R$" é o bruto; o valor pago é total - descontos
        pago = _decimal(_celula_valor(soup, "Valor total R$"), "valor total") - descontos

    return Nota(
        chave=chave,
        modelo=modelo_da_chave(chave),
        emitente=_emitente(cab, soup),
        numero=numero,
        serie=serie,
        emissao=emissao,
        protocolo=pm.group(1) if pm else None,
        valor_total=pago,
        valor_descontos=descontos,
        itens=_itens(soup),
        pagamentos=_pagamentos(soup),
    )
