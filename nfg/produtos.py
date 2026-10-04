from __future__ import annotations

import sqlite3

from nfg.erros import ProdutoDuplicado
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
            raise ProdutoDuplicado(nome) from e
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
