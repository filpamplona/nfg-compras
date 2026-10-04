from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

import pandas as pd

from nfg.analises import _VALIDA, _emissao, _unificar_loja, _vazio
from nfg.erros import ProdutoDuplicado
from nfg.produtos_texto import normalizar_produto, normalizar_unidade, pontuar
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
        conn.execute("DELETE FROM produto_rejeitado WHERE produto_id = ?", (produto_id,))
        conn.execute("DELETE FROM produtos WHERE id = ?", (produto_id,))


def vincular(conn: sqlite3.Connection, cnpj: str, codigo: str, produto_id: int, origem: str = "manual") -> None:
    with conn:
        conn.execute("DELETE FROM produto_ignorado WHERE cnpj = ? AND codigo = ?", (cnpj, codigo))
        if origem == "manual":
            conn.execute("DELETE FROM produto_rejeitado WHERE cnpj = ? AND codigo = ? AND produto_id = ?",
                         (cnpj, codigo, produto_id))
        conn.execute(
            """INSERT INTO produto_vinculo(cnpj, codigo, produto_id, origem) VALUES (?,?,?,?)
               ON CONFLICT(cnpj, codigo) DO UPDATE SET
                 produto_id = excluded.produto_id, origem = excluded.origem""",
            (cnpj, codigo, produto_id, origem),
        )


def desvincular(conn: sqlite3.Connection, cnpj: str, codigo: str) -> None:
    with conn:
        conn.execute(
            """INSERT OR IGNORE INTO produto_rejeitado(cnpj, codigo, produto_id)
               SELECT cnpj, codigo, produto_id FROM produto_vinculo WHERE cnpj = ? AND codigo = ?""",
            (cnpj, codigo),
        )
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


_COL_ITENS_CHAVEADOS = ["cnpj", "codigo", "loja", "emissao", "descricao", "unidade", "valor_unitario"]


def _itens_chaveados(conn: sqlite3.Connection) -> pd.DataFrame:
    """Itens de notas válidas com `codigo` já na chave de vínculo, ordenados do mais antigo ao mais recente."""
    linhas = conn.execute(
        f"""SELECT n.cnpj_emitente, i.codigo, COALESCE(e.razao_social, e.nome_csv), n.emissao,
                   i.descricao, i.unidade, i.valor_unitario
            FROM itens i JOIN notas n ON n.chave = i.chave
            LEFT JOIN estabelecimentos e ON e.cnpj = n.cnpj_emitente
            WHERE {_VALIDA}
            ORDER BY n.emissao, n.chave, i.seq"""
    ).fetchall()
    if not linhas:
        return _vazio(_COL_ITENS_CHAVEADOS)
    linhas = [(cnpj, chave_item(cnpj, codigo, descricao)[1], loja, emissao, descricao, unidade, vu)
              for cnpj, codigo, loja, emissao, descricao, unidade, vu in linhas]
    df = pd.DataFrame(linhas, columns=_COL_ITENS_CHAVEADOS)
    df["emissao"] = _emissao(df["emissao"])
    df["valor_unitario"] = df["valor_unitario"].astype(float)
    return _unificar_loja(df)


def _recentes(conn: sqlite3.Connection) -> pd.DataFrame:
    """Última linha (compra mais recente) de cada (cnpj, codigo), com a contagem de compras."""
    itens = _itens_chaveados(conn)
    if itens.empty:
        return itens.assign(compras=pd.Series(dtype=int))
    compras = itens.groupby(["cnpj", "codigo"]).size().rename("compras")
    ultimo = itens.drop_duplicates(["cnpj", "codigo"], keep="last")
    return ultimo.merge(compras, on=["cnpj", "codigo"])


def _descricoes_vinculadas(conn: sqlite3.Connection) -> dict[int, list[tuple[str, str | None]]]:
    """Descrição mais recente (e unidade) de cada item vinculado, agrupada por produto."""
    vinculos = {(r[0], r[1]): r[2] for r in conn.execute("SELECT cnpj, codigo, produto_id FROM produto_vinculo")}
    if not vinculos:
        return {}
    por_produto: dict[int, list[tuple[str, str | None]]] = {}
    for r in _recentes(conn).itertuples(index=False):
        pid = vinculos.get((r.cnpj, r.codigo))
        if pid is not None:
            por_produto.setdefault(pid, []).append((r.descricao, r.unidade))
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


def _pares(conn: sqlite3.Connection, tabela: str) -> set[tuple[str, str]]:
    return {(r[0], r[1]) for r in conn.execute(f"SELECT cnpj, codigo FROM {tabela}")}


def pendentes_df(conn: sqlite3.Connection) -> pd.DataFrame:
    colunas = ["cnpj", "codigo", "loja", "descricao", "unidade", "ultimo_preco", "ultima_data", "compras"]
    df = _recentes(conn)
    if df.empty:
        return _vazio(colunas)
    fora = _pares(conn, "produto_vinculo") | _pares(conn, "produto_ignorado")
    df = df[[(c, k) not in fora for c, k in zip(df["cnpj"], df["codigo"])]]
    df = df.rename(columns={"valor_unitario": "ultimo_preco", "emissao": "ultima_data"})
    df = df.sort_values(["compras", "descricao"], ascending=[False, True], kind="stable")
    return df[colunas].reset_index(drop=True)


def catalogo_df(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """SELECT p.id, p.nome, p.tipo, p.tamanho, p.venda,
                  COUNT(DISTINCT v.cnpj) AS lojas, COUNT(v.codigo) AS vinculos
           FROM produtos p LEFT JOIN produto_vinculo v ON v.produto_id = p.id
           GROUP BY p.id ORDER BY p.nome""",
        conn,
    )


def _com_descricao(conn: sqlite3.Connection, pares: list[tuple]) -> pd.DataFrame:
    """Anexa loja e descrição mais recente a linhas (cnpj, codigo, *extras)."""
    recentes = _recentes(conn)[["cnpj", "codigo", "loja", "descricao"]]
    df = pd.DataFrame(pares, columns=["cnpj", "codigo", *(["origem"] if pares and len(pares[0]) > 2 else [])])
    return df.merge(recentes, on=["cnpj", "codigo"], how="left")


def vinculos_df(conn: sqlite3.Connection, produto_id: int) -> pd.DataFrame:
    colunas = ["cnpj", "codigo", "loja", "descricao", "origem"]
    pares = conn.execute(
        "SELECT cnpj, codigo, origem FROM produto_vinculo WHERE produto_id = ?", (produto_id,)
    ).fetchall()
    if not pares:
        return _vazio(colunas)
    return _com_descricao(conn, pares)[colunas].sort_values(["loja", "descricao"]).reset_index(drop=True)


def ignorados_df(conn: sqlite3.Connection) -> pd.DataFrame:
    colunas = ["cnpj", "codigo", "loja", "descricao"]
    pares = conn.execute("SELECT cnpj, codigo FROM produto_ignorado").fetchall()
    if not pares:
        return _vazio(colunas)
    return _com_descricao(conn, pares)[colunas].sort_values(["loja", "descricao"]).reset_index(drop=True)


def _chave_descricao(descricao: str) -> str:
    return " ".join(re.sub(r"[^A-Z0-9 ]", "", normalizar_texto(descricao).upper()).split())


def _unico(candidatos: set[int]) -> int | None:
    return next(iter(candidatos)) if len(candidatos) == 1 else None


def vincular_automaticos(conn: sqlite3.Connection) -> int:
    """Liga pendentes por mesmo código na mesma raiz de CNPJ ou descrição idêntica normalizada."""
    recentes = _recentes(conn)
    if recentes.empty:
        return 0
    desc = {(r.cnpj, r.codigo): r.descricao for r in recentes.itertuples(index=False)}
    unidades = {(r.cnpj, r.codigo): r.unidade for r in recentes.itertuples(index=False)}
    vendas = {r[0]: r[1] for r in conn.execute("SELECT id, venda FROM produtos")}
    total = 0
    while True:
        vinculos = {(r[0], r[1]): r[2] for r in conn.execute("SELECT cnpj, codigo, produto_id FROM produto_vinculo")}
        ignorados = _pares(conn, "produto_ignorado")
        rejeitados = {(r[0], r[1], r[2]) for r in conn.execute("SELECT cnpj, codigo, produto_id FROM produto_rejeitado")}
        por_codigo: dict[tuple[str, str], set[tuple[str, int]]] = {}
        por_desc: dict[str, set[int]] = {}
        for (cnpj, codigo), pid in vinculos.items():
            por_codigo.setdefault((cnpj[:8], codigo), set()).add((cnpj, pid))
            if (cnpj, codigo) in desc:
                por_desc.setdefault(_chave_descricao(desc[(cnpj, codigo)]), set()).add(pid)
        novos = []
        for (cnpj, codigo), descricao in desc.items():
            if (cnpj, codigo) in vinculos or (cnpj, codigo) in ignorados:
                continue
            cands = {p for c, p in por_codigo.get((cnpj[:8], codigo), ()) if c != cnpj}
            cands = {p for p in cands if (cnpj, codigo, p) not in rejeitados}
            if cands:
                pid = _unico(cands)  # ambíguo: pula a chave, sem cair na regra 2
            else:
                venda = "KG" if normalizar_unidade(unidades[(cnpj, codigo)]) == "KG" else "UN"
                por_desc_ok = {p for p in por_desc.get(_chave_descricao(descricao), set())
                               if (cnpj, codigo, p) not in rejeitados and vendas.get(p) == venda}
                pid = _unico(por_desc_ok)
            if pid is not None:
                novos.append((cnpj, codigo, pid))
        if not novos:
            return total
        for cnpj, codigo, pid in novos:
            vincular(conn, cnpj, codigo, pid, origem="auto")
        total += len(novos)


_COL_COMPARAR = ["cnpj", "loja", "ultimo_preco", "ultima_data", "descricao_original",
                 "dif_reais", "dif_pct", "mais_barato"]
_COL_HISTORICO = ["emissao", "loja", "valor_unitario", "descricao"]
_COL_VISAO = ["produto_id", "produto", "venda", "loja_mais_barata", "menor_preco", "maior_preco", "dif_pct"]


def _rotular_lojas(df: pd.DataFrame) -> pd.DataFrame:
    """Lojas (CNPJs) distintas com o mesmo nome ganham o sufixo ` (filial)` (dígitos 9-12 do CNPJ)."""
    if df.empty:
        return df
    por_nome = df.drop_duplicates("cnpj").groupby("loja")["cnpj"].nunique()
    repetidos = set(por_nome[por_nome > 1].index)
    if not repetidos:
        return df
    df = df.copy()
    mascara = df["loja"].isin(repetidos)
    df.loc[mascara, "loja"] = df.loc[mascara, "loja"] + " (" + df.loc[mascara, "cnpj"].str[8:12] + ")"
    return df


def _itens_do_produto(conn: sqlite3.Connection, produto_id: int | None = None) -> pd.DataFrame:
    """Itens válidos vinculados a produtos (todos, ou só `produto_id`), com a coluna produto_id."""
    filtro, params = ("WHERE produto_id = ?", (produto_id,)) if produto_id is not None else ("", ())
    vinculos = pd.DataFrame(
        conn.execute(f"SELECT cnpj, codigo, produto_id FROM produto_vinculo {filtro}", params).fetchall(),
        columns=["cnpj", "codigo", "produto_id"],
    )
    itens = _itens_chaveados(conn)
    if vinculos.empty or itens.empty:
        return _vazio(["produto_id", *_COL_ITENS_CHAVEADOS])
    return _rotular_lojas(itens.merge(vinculos, on=["cnpj", "codigo"], how="inner"))


def _ultimo_por_loja(itens: pd.DataFrame) -> pd.DataFrame:
    """Linha mais recente de cada (produto_id, cnpj); `itens` já vem do mais antigo ao mais novo."""
    return itens.sort_values("emissao", kind="stable").drop_duplicates(["produto_id", "cnpj"], keep="last")


def _comparar(ultimos: pd.DataFrame) -> pd.DataFrame:
    df = ultimos.rename(columns={"valor_unitario": "ultimo_preco", "emissao": "ultima_data",
                                 "descricao": "descricao_original"}).copy()
    menor = df["ultimo_preco"].min()
    df["dif_reais"] = (df["ultimo_preco"] - menor).round(2)
    df["dif_pct"] = ((df["ultimo_preco"] - menor) / menor * 100).round(2)
    df["mais_barato"] = df["ultimo_preco"] == menor
    return df.sort_values(["ultimo_preco", "loja"], kind="stable")[_COL_COMPARAR].reset_index(drop=True)


def comparar_produto(conn: sqlite3.Connection, produto_id: int) -> pd.DataFrame:
    itens = _itens_do_produto(conn, produto_id)
    if itens.empty:
        return _vazio(_COL_COMPARAR)
    return _comparar(_ultimo_por_loja(itens))


def historico_produto(conn: sqlite3.Connection, produto_id: int) -> pd.DataFrame:
    itens = _itens_do_produto(conn, produto_id)
    if itens.empty:
        return _vazio(_COL_HISTORICO)
    itens = itens.sort_values("emissao", kind="stable")
    return itens[["emissao", "loja", "valor_unitario", "descricao"]].reset_index(drop=True)


def visao_geral_df(conn: sqlite3.Connection) -> pd.DataFrame:
    itens = _itens_do_produto(conn)
    if itens.empty:
        return _vazio(_COL_VISAO)
    ultimos = _ultimo_por_loja(itens)
    produtos = {r[0]: (r[1], r[2]) for r in conn.execute("SELECT id, nome, venda FROM produtos")}
    linhas = []
    for pid, grupo in ultimos.groupby("produto_id"):
        if len(grupo) < 2 or pid not in produtos:
            continue
        comp = _comparar(grupo)
        menor, maior = comp["ultimo_preco"].min(), comp["ultimo_preco"].max()
        linhas.append((pid, produtos[pid][0], produtos[pid][1], comp["loja"].iloc[0], menor, maior,
                       round((maior - menor) / menor * 100, 2)))
    if not linhas:
        return _vazio(_COL_VISAO)
    df = pd.DataFrame(linhas, columns=_COL_VISAO)
    return df.sort_values(["dif_pct", "produto"], ascending=[False, True], kind="stable").reset_index(drop=True)
