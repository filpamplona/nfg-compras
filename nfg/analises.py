from __future__ import annotations

import io
import sqlite3
from datetime import date
from typing import Literal

import pandas as pd

from nfg.categorias import categorizar_df
from nfg.util import normalizar_texto

_VALIDA = (
    "(n.tipo_operacao IS NULL OR n.tipo_operacao = 'Aquisição') "
    "AND (n.situacao_csv IS NULL OR n.situacao_csv = 'Normal')"
)

_COL_NOTAS = ["chave", "modelo", "emissao", "mes", "loja", "cnpj", "valor_total", "status",
              "aviso", "erro_msg", "situacao_csv", "tipo_operacao", "num_itens"]
_COL_ITENS = ["chave", "emissao", "mes", "loja", "cnpj", "seq", "codigo", "descricao",
              "descricao_norm", "quantidade", "unidade", "valor_unitario", "valor_total", "categoria"]


def _vazio(colunas: list[str]) -> pd.DataFrame:
    return pd.DataFrame({c: [] for c in colunas})


def _ratear_descontos(centavos: list[int], desconto: int) -> list[int]:
    """Reparte o desconto da nota entre os itens, proporcional ao valor (maior resto); soma exata."""
    total = sum(centavos)
    if desconto <= 0 or total <= 0:
        return list(centavos)
    desconto = min(desconto, total)
    base = [c * desconto // total for c in centavos]
    restos = sorted(range(len(centavos)), key=lambda k: (-(centavos[k] * desconto % total), k))
    for k in restos[: desconto - sum(base)]:
        base[k] += 1
    return [c - b for c, b in zip(centavos, base)]


def _unificar_loja(df: pd.DataFrame) -> pd.DataFrame:
    """Um único nome de loja por CNPJ (o primeiro não nulo, já com razão social preferida)."""
    if df.empty or "cnpj" not in df:
        return df
    nomes = df.dropna(subset=["loja"]).drop_duplicates("cnpj").set_index("cnpj")["loja"]
    df = df.copy()
    com_cnpj = df["cnpj"].notna()
    df.loc[com_cnpj, "loja"] = df.loc[com_cnpj, "cnpj"].map(nomes).fillna(df.loc[com_cnpj, "loja"])
    return df


def _emissao(serie: pd.Series) -> pd.Series:
    return pd.to_datetime(serie, format="ISO8601")


def _filtrar_periodo(df: pd.DataFrame, inicio: date | None, fim: date | None) -> pd.DataFrame:
    if inicio is not None:
        df = df[df["emissao"] >= pd.Timestamp(inicio)]
    if fim is not None:
        df = df[df["emissao"] < pd.Timestamp(fim) + pd.Timedelta(days=1)]
    return df


def notas_df(conn: sqlite3.Connection) -> pd.DataFrame:
    df = pd.read_sql_query(
        """SELECT n.chave, n.modelo, n.emissao, COALESCE(e.razao_social, e.nome_csv) AS loja,
                  n.cnpj_emitente AS cnpj, n.valor_total_centavos / 100.0 AS valor_total,
                  n.status, n.aviso, n.erro_msg, n.situacao_csv, n.tipo_operacao,
                  (SELECT COUNT(*) FROM itens i WHERE i.chave = n.chave) AS num_itens
           FROM notas n LEFT JOIN estabelecimentos e ON e.cnpj = n.cnpj_emitente
           ORDER BY n.emissao, n.chave""",
        conn,
    )
    if df.empty:
        return _vazio(_COL_NOTAS)
    df["emissao"] = _emissao(df["emissao"])
    df["mes"] = df["emissao"].dt.strftime("%Y-%m")
    return _unificar_loja(df)[_COL_NOTAS]


def _notas_validas(conn: sqlite3.Connection, inicio: date | None, fim: date | None) -> pd.DataFrame:
    df = pd.read_sql_query(
        f"""SELECT n.chave, n.emissao, COALESCE(e.razao_social, e.nome_csv) AS loja,
                   n.cnpj_emitente AS cnpj, n.valor_total_centavos / 100.0 AS valor_total
            FROM notas n LEFT JOIN estabelecimentos e ON e.cnpj = n.cnpj_emitente
            WHERE {_VALIDA}""",
        conn,
    )
    if df.empty:
        return df.assign(mes=pd.Series(dtype=str))
    df["emissao"] = _emissao(df["emissao"])
    df["mes"] = df["emissao"].dt.strftime("%Y-%m")
    return _unificar_loja(_filtrar_periodo(df, inicio, fim))


def itens_df(conn: sqlite3.Connection, inicio: date | None = None, fim: date | None = None) -> pd.DataFrame:
    df = pd.read_sql_query(
        f"""SELECT n.chave, n.emissao, COALESCE(e.razao_social, e.nome_csv) AS loja,
                   n.cnpj_emitente AS cnpj, i.seq, i.codigo, i.descricao, i.quantidade, i.unidade,
                   i.valor_unitario, i.valor_total_centavos AS centavos,
                   n.valor_descontos_centavos AS desconto
            FROM itens i JOIN notas n ON n.chave = i.chave
            LEFT JOIN estabelecimentos e ON e.cnpj = n.cnpj_emitente
            WHERE {_VALIDA}
            ORDER BY n.emissao, n.chave, i.seq""",
        conn,
    )
    if df.empty:
        return _vazio(_COL_ITENS)
    df["emissao"] = _emissao(df["emissao"])
    df = _filtrar_periodo(df, inicio, fim).copy()
    if df.empty:
        return _vazio(_COL_ITENS)
    # valor_total líquido: desconto da nota rateado entre os itens (soma por nota = valor pago)
    df["desconto"] = df["desconto"].fillna(0).astype(int)
    liquido = pd.Series(0, index=df.index, dtype="int64")
    for _, grupo in df.groupby("chave", sort=False):
        liquido.loc[grupo.index] = _ratear_descontos(
            grupo["centavos"].astype(int).tolist(), int(grupo["desconto"].iloc[0]))
    df["valor_total"] = liquido / 100.0
    df = _unificar_loja(df)
    df["mes"] = df["emissao"].dt.strftime("%Y-%m")
    df["descricao_norm"] = df["descricao"].map(normalizar_texto)
    df["quantidade"] = df["quantidade"].astype(float)
    df["valor_unitario"] = df["valor_unitario"].astype(float)
    df = categorizar_df(conn, df)
    return df[_COL_ITENS].reset_index(drop=True)


def gasto_mensal(conn: sqlite3.Connection, inicio: date | None = None, fim: date | None = None) -> pd.DataFrame:
    df = _notas_validas(conn, inicio, fim)
    if df.empty:
        return _vazio(["mes", "total", "compras", "ticket_medio"])
    g = df.groupby("mes", as_index=False).agg(total=("valor_total", "sum"), compras=("chave", "count"))
    g["ticket_medio"] = g["total"] / g["compras"]
    return g.sort_values("mes").reset_index(drop=True)


def gasto_mensal_por_categoria(conn: sqlite3.Connection, inicio: date | None = None,
                               fim: date | None = None) -> pd.DataFrame:
    df = itens_df(conn, inicio, fim)
    if df.empty:
        return _vazio(["mes", "categoria", "total"])
    g = df.groupby(["mes", "categoria"], as_index=False).agg(total=("valor_total", "sum"))
    return g.sort_values(["mes", "categoria"]).reset_index(drop=True)


def gasto_por_loja(conn: sqlite3.Connection, inicio: date | None = None, fim: date | None = None) -> pd.DataFrame:
    df = _notas_validas(conn, inicio, fim)
    if df.empty:
        return _vazio(["loja", "total", "visitas", "ticket_medio"])
    df = df.assign(_k=df["cnpj"].fillna(df["loja"]))
    g = df.groupby("_k", as_index=False).agg(
        loja=("loja", "first"), total=("valor_total", "sum"), visitas=("chave", "count")).drop(columns="_k")
    g["ticket_medio"] = g["total"] / g["visitas"]
    return g.sort_values("total", ascending=False).reset_index(drop=True)


def gasto_por_categoria(conn: sqlite3.Connection, inicio: date | None = None,
                        fim: date | None = None) -> pd.DataFrame:
    df = itens_df(conn, inicio, fim)
    if df.empty:
        return _vazio(["categoria", "total", "participacao"])
    g = df.groupby("categoria", as_index=False).agg(total=("valor_total", "sum"))
    soma = g["total"].sum()
    g["participacao"] = g["total"] / soma * 100 if soma else 0.0
    return g.sort_values("total", ascending=False).reset_index(drop=True)


def ranking_produtos(conn: sqlite3.Connection, inicio: date | None = None, fim: date | None = None,
                     por: Literal["valor", "frequencia"] = "valor", n: int = 20) -> pd.DataFrame:
    df = itens_df(conn, inicio, fim)
    if df.empty:
        return _vazio(["descricao_norm", "total", "compras", "quantidade"])
    g = df.groupby("descricao_norm", as_index=False).agg(
        total=("valor_total", "sum"), compras=("chave", "nunique"), quantidade=("quantidade", "sum"))
    chaves = ["compras", "total"] if por == "frequencia" else ["total"]
    return g.sort_values(chaves, ascending=False).head(n).reset_index(drop=True)


def historico_preco(conn: sqlite3.Connection, busca: str) -> pd.DataFrame:
    df = itens_df(conn)
    colunas = ["emissao", "loja", "descricao", "valor_unitario", "unidade"]
    palavras = normalizar_texto(busca).split()
    if df.empty or not palavras:
        return _vazio(colunas)
    mask = pd.Series(True, index=df.index)
    for p in palavras:
        mask &= df["descricao_norm"].str.contains(p, regex=False)
    return df[mask].sort_values("emissao", kind="stable")[colunas].reset_index(drop=True)


def meses_disponiveis(conn: sqlite3.Connection) -> list[str]:
    df = _notas_validas(conn, None, None)
    return sorted(df["mes"].unique().tolist(), reverse=True) if not df.empty else []


def _mes_anterior(mes: str) -> str:
    return str(pd.Period(mes, freq="M") - 1)


def resumo_mes(conn: sqlite3.Connection, mes: str) -> dict:
    mensal = gasto_mensal(conn).set_index("mes")
    total = float(mensal.loc[mes, "total"]) if mes in mensal.index else 0.0
    compras = int(mensal.loc[mes, "compras"]) if mes in mensal.index else 0
    anterior = _mes_anterior(mes)
    variacao = None
    if anterior in mensal.index and mensal.loc[anterior, "total"]:
        base = float(mensal.loc[anterior, "total"])
        variacao = (total - base) / base * 100
    pendentes = conn.execute(
        "SELECT COUNT(*) FROM notas WHERE status IN ('pendente', 'erro')").fetchone()[0]
    return {
        "total": total,
        "variacao_pct": variacao,
        "compras": compras,
        "ticket_medio": total / compras if compras else None,
        "pendentes": pendentes,
    }


def exportar_excel(planilhas: dict[str, pd.DataFrame]) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for nome, df in planilhas.items():
            df.to_excel(w, sheet_name=nome[:31], index=False)
    return buf.getvalue()
