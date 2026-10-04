from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from nfg.analises import _VALIDA
from nfg.erros import ProdutoDuplicado
from nfg.produtos_texto import normalizar_produto, pontuar
from nfg.util import normalizar_texto

_CAMPOS = {"nome", "tipo", "tamanho", "venda"}


def chave_item(cnpj: str, codigo: str | None, descricao: str) -> tuple[str, str]:
    if codigo:
        return (cnpj, codigo)
    return (cnpj, "DESC:" + normalizar_texto(descricao))


def criar_produto(conn: sqlite3.Connection, nome: str, tipo: str, tamanho: str | None, venda: str) -> int:
    try:
        with conn:
            return conn.execute(
                "INSERT INTO produtos(nome, tipo, tamanho, venda) VALUES (?,?,?,?)",
                (normalizar_texto(nome), tipo, tamanho, venda),
            ).lastrowid
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e).upper():
            raise ProdutoDuplicado(normalizar_texto(nome)) from e
        raise


def atualizar_produto(conn: sqlite3.Connection, produto_id: int, **campos) -> None:
    invalidos = set(campos) - _CAMPOS
    if invalidos:
        raise ValueError(f"campos invalidos: {sorted(invalidos)}")
    if not campos:
        return
    if "nome" in campos:
        campos["nome"] = normalizar_texto(campos["nome"])
    sets = ", ".join(f"{k} = ?" for k in campos)
    try:
        with conn:
            conn.execute(f"UPDATE produtos SET {sets} WHERE id = ?", (*campos.values(), produto_id))
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e).upper():
            raise ProdutoDuplicado(campos.get("nome", "")) from e
        raise


def excluir_produto(conn: sqlite3.Connection, produto_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM produto_vinculo WHERE produto_id = ?", (produto_id,))
        conn.execute("DELETE FROM produtos WHERE id = ?", (produto_id,))


def vincular(conn: sqlite3.Connection, cnpj: str, codigo: str, produto_id: int, origem: str = "manual") -> None:
    with conn:
        conn.execute("DELETE FROM produto_ignorado WHERE cnpj = ? AND codigo = ?", (cnpj, codigo))
        conn.execute(
            """INSERT INTO produto_vinculo(cnpj, codigo, produto_id, origem) VALUES (?,?,?,?)
               ON CONFLICT(cnpj, codigo) DO UPDATE SET
                 produto_id = excluded.produto_id, origem = excluded.origem""",
            (cnpj, codigo, produto_id, origem),
        )


def desvincular(conn: sqlite3.Connection, cnpj: str, codigo: str) -> None:
    with conn:
        conn.execute("DELETE FROM produto_vinculo WHERE cnpj = ? AND codigo = ?", (cnpj, codigo))


def ignorar(conn: sqlite3.Connection, cnpj: str, codigo: str) -> None:
    with conn:
        conn.execute("DELETE FROM produto_vinculo WHERE cnpj = ? AND codigo = ?", (cnpj, codigo))
        conn.execute("INSERT OR IGNORE INTO produto_ignorado(cnpj, codigo) VALUES (?,?)", (cnpj, codigo))


def restaurar(conn: sqlite3.Connection, cnpj: str, codigo: str) -> None:
    with conn:
        conn.execute("DELETE FROM produto_ignorado WHERE cnpj = ? AND codigo = ?", (cnpj, codigo))


@dataclass(frozen=True)
class Sugestao:
    produto_id: int
    nome: str
    score: float
    motivo: str


def _descricoes_vinculadas(conn: sqlite3.Connection) -> dict[int, list[tuple[str, str | None]]]:
    """Descrição mais recente (e unidade) de cada item vinculado, agrupada por produto."""
    vinculos = {(r[0], r[1]): r[2] for r in conn.execute("SELECT cnpj, codigo, produto_id FROM produto_vinculo")}
    if not vinculos:
        return {}
    recentes: dict[tuple[str, str], tuple[tuple, str, str | None]] = {}
    linhas = conn.execute(
        f"""SELECT n.cnpj_emitente, i.codigo, i.descricao, i.unidade, n.emissao, n.chave, i.seq
            FROM itens i JOIN notas n ON n.chave = i.chave
            WHERE {_VALIDA}"""
    )
    for cnpj, codigo, descricao, unidade, emissao, chave, seq in linhas:
        k = chave_item(cnpj, codigo, descricao)
        if k not in vinculos:
            continue
        ordem = (emissao, chave, seq)
        if k not in recentes or ordem > recentes[k][0]:
            recentes[k] = (ordem, descricao, unidade)
    por_produto: dict[int, list[tuple[str, str | None]]] = {}
    for k, (_, descricao, unidade) in recentes.items():
        por_produto.setdefault(vinculos[k], []).append((descricao, unidade))
    return por_produto


def sugerir(conn: sqlite3.Connection, descricao: str, unidade: str | None, n: int = 3) -> list[Sugestao]:
    item = normalizar_produto(descricao, unidade)
    if not item.tipo:
        return []
    similares = _descricoes_vinculadas(conn)
    sugestoes = []
    for pid, nome, tamanho, venda in conn.execute("SELECT id, nome, tamanho, venda FROM produtos"):
        produto = normalizar_produto(f"{nome} {tamanho or ''}", venda)
        sims = [normalizar_produto(d, u) for d, u in similares.get(pid, [])]
        resultado = pontuar(item, produto, sims)
        if resultado and resultado[0] > 0:
            sugestoes.append(Sugestao(pid, nome, resultado[0], resultado[1]))
    sugestoes.sort(key=lambda s: (-s.score, s.nome))
    return sugestoes[:n]
