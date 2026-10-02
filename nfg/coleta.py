from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Callable

from nfg import nfce_parser, nfe_xml_parser
from nfg.db import Repositorio
from nfg.erros import BloqueioSefaz, ErroNFG, LayoutDesconhecido, NotaNaoEncontrada
from nfg.models import Nota
from nfg.util import formatar_brl, mascarar_cpf

TOLERANCIA = Decimal("0.01")


@dataclass
class Progresso:
    i: int
    total: int
    chave: str
    ok: bool
    mensagem: str


@dataclass
class ResultadoLote:
    coletadas: int
    erros: int
    interrompido: bool
    motivo: str | None


def validar_totais(nota: Nota) -> str | None:
    if nota.modelo != 65:  # vNF da NF-e inclui frete, seguro, IPI etc.; só NFC-e é conferível
        return None
    soma = sum((i.valor_total for i in nota.itens), Decimal("0"))
    esperado = soma - nota.valor_descontos
    if abs(esperado - nota.valor_total) > TOLERANCIA:
        return (
            f"Soma dos itens ({formatar_brl(soma)}) menos descontos "
            f"({formatar_brl(nota.valor_descontos)}) difere do total ({formatar_brl(nota.valor_total)})"
        )
    return None


def _mensagem_ok(nota: Nota) -> str:
    return (
        f"✓ {nota.emitente.razao_social} {nota.emissao:%d/%m} — {len(nota.itens)} itens"
        f" — {formatar_brl(nota.valor_total)}"
    )


def _mensagem_erro(chave: str, e: ErroNFG) -> str:
    return f"⚠ {chave[-8:]} — {type(e).__name__}: {e}"


def _parse_e_salvar(repo: Repositorio, chave: str, html: str, arquivo: Path | None = None) -> Nota:
    nota = nfce_parser.parse(html)
    if nota.chave != chave:
        if arquivo is not None:
            arquivo.unlink(missing_ok=True)
        raise LayoutDesconhecido("chave divergente")
    repo.salvar_nota(nota, validar_totais(nota))
    return nota


def coletar(
    repo: Repositorio,
    cliente,
    dir_html: Path,
    on_progress: Callable[[Progresso], None] = lambda p: None,
    pausa: float = 1.5,
    sleep: Callable[[float], None] = time.sleep,
) -> ResultadoLote:
    dir_html = Path(dir_html)
    dir_html.mkdir(parents=True, exist_ok=True)
    chaves = repo.pendentes()
    total = len(chaves)
    coletadas = erros = 0
    for i, chave in enumerate(chaves, start=1):
        if i > 1:
            sleep(pausa)
        try:
            html = mascarar_cpf(cliente.buscar(chave))
            arquivo = dir_html / f"{chave}.html"
            arquivo.write_text(html, encoding="utf-8")
            nota = _parse_e_salvar(repo, chave, html, arquivo)
        except BloqueioSefaz as e:
            erros += 1
            msg = _mensagem_erro(chave, e)
            on_progress(Progresso(i, total, chave, False, msg))
            return ResultadoLote(coletadas, erros, True, str(e))
        except ErroNFG as e:
            erros += 1
            repo.registrar_erro(chave, str(e), definitivo=isinstance(e, NotaNaoEncontrada))
            on_progress(Progresso(i, total, chave, False, _mensagem_erro(chave, e)))
        else:
            coletadas += 1
            on_progress(Progresso(i, total, chave, True, _mensagem_ok(nota)))
    return ResultadoLote(coletadas, erros, False, None)


def reprocessar_html(repo: Repositorio, dir_html: Path) -> ResultadoLote:
    coletadas = erros = 0
    for arq in sorted(Path(dir_html).glob("*.html")):
        chave = arq.stem
        try:
            _parse_e_salvar(repo, chave, arq.read_text(encoding="utf-8"))
            coletadas += 1
        except ErroNFG:
            erros += 1  # reprocessamento nunca grava erro no banco
    return ResultadoLote(coletadas, erros, False, None)


def anexar_xml(repo: Repositorio, dados: bytes) -> Nota:
    nota = nfe_xml_parser.parse(dados)
    repo.salvar_nota(nota, validar_totais(nota))
    return nota
