import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from nfg.analises import (
    exportar_excel, gasto_mensal, gasto_mensal_por_categoria, gasto_por_categoria,
    gasto_por_loja, historico_preco, itens_df, notas_df, ranking_produtos,
)
from nfg.config import abrir_repo

st.set_page_config(page_title="Análises — NFG Compras", page_icon="🧾", layout="wide")
repo = abrir_repo()
conn = repo.conn

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

st.title("Análises")
todas = notas_df(conn)
if todas.empty:
    st.info("Nenhuma nota coletada ainda. Vá em Importar.")
    st.stop()

emissoes = todas["emissao"].dropna()
periodo = st.date_input(
    "Período", value=(emissoes.min().date(), emissoes.max().date()), format="DD/MM/YYYY")
inicio = fim = None
if isinstance(periodo, (tuple, list)) and len(periodo) == 2:
    inicio, fim = periodo


def baixar(df: pd.DataFrame, nome: str) -> None:
    c1, c2, _ = st.columns([1, 1, 4])
    csv = df.to_csv(index=False, sep=";", decimal=",").encode("utf-8-sig")
    c1.download_button("Baixar CSV", csv, file_name=f"{nome}.csv", mime="text/csv", key=f"csv_{nome}")
    c2.download_button("Baixar Excel", exportar_excel({nome: df}), file_name=f"{nome}.xlsx",
                       mime=XLSX, key=f"xlsx_{nome}")


def sem_dados() -> None:
    st.info("Sem dados no período selecionado.")


abas = st.tabs(["Mensal", "Por loja", "Por categoria", "Ranking de produtos", "Histórico de preço"])

with abas[0]:
    mensal = gasto_mensal(conn, inicio, fim)
    if mensal.empty:
        sem_dados()
    else:
        por_cat = gasto_mensal_por_categoria(conn, inicio, fim)
        if not por_cat.empty:
            st.plotly_chart(px.bar(por_cat, x="mes", y="total", color="categoria",
                                   labels={"mes": "Mês", "total": "Total (R$)", "categoria": "Categoria"}),
                            width="stretch")
        st.dataframe(mensal, width="stretch", hide_index=True)
        baixar(mensal, "mensal")

with abas[1]:
    lojas = gasto_por_loja(conn, inicio, fim)
    if lojas.empty:
        sem_dados()
    else:
        st.plotly_chart(px.bar(lojas.sort_values("total"), x="total", y="loja", orientation="h",
                               labels={"total": "Total (R$)", "loja": "Loja"}), width="stretch")
        st.dataframe(lojas, width="stretch", hide_index=True)
        baixar(lojas, "por_loja")

with abas[2]:
    cats = gasto_por_categoria(conn, inicio, fim)
    if cats.empty:
        sem_dados()
    else:
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.pie(cats, names="categoria", values="total", hole=0.5), width="stretch")
        por_cat = gasto_mensal_por_categoria(conn, inicio, fim)
        c2.plotly_chart(px.line(por_cat, x="mes", y="total", color="categoria", markers=True,
                                labels={"mes": "Mês", "total": "Total (R$)", "categoria": "Categoria"}),
                        width="stretch")
        st.dataframe(cats, width="stretch", hide_index=True)
        baixar(cats, "por_categoria")

with abas[3]:
    c1, c2 = st.columns(2)
    modo = c1.radio("Ordenar por", ["valor", "frequencia"], horizontal=True,
                    format_func=lambda m: "Valor gasto" if m == "valor" else "Frequência")
    n = c2.number_input("Quantos produtos", min_value=1, max_value=200, value=20, step=1)
    rank = ranking_produtos(conn, inicio, fim, por=modo, n=int(n))
    if rank.empty:
        sem_dados()
    else:
        y = "total" if modo == "valor" else "compras"
        st.plotly_chart(px.bar(rank.iloc[::-1], x=y, y="descricao_norm", orientation="h",
                               labels={"total": "Total (R$)", "compras": "Compras",
                                       "descricao_norm": "Produto"}), width="stretch")
        st.dataframe(rank, width="stretch", hide_index=True)
        baixar(rank, "ranking_produtos")

with abas[4]:
    busca = st.text_input("Buscar produto", key="busca_preco", placeholder="ex.: leite")
    if busca.strip():
        hist = historico_preco(conn, busca)
        if hist.empty:
            st.info("Nenhum item encontrado para essa busca.")
        else:
            st.plotly_chart(px.line(hist, x="emissao", y="valor_unitario", color="loja", markers=True,
                                    hover_data=["descricao", "unidade"],
                                    labels={"emissao": "Data", "valor_unitario": "Valor unitário (R$)",
                                            "loja": "Loja"}), width="stretch")
            st.dataframe(hist, width="stretch", hide_index=True)
            baixar(hist, "historico_preco")
    else:
        st.caption("Digite parte do nome de um produto para ver a evolução do preço.")

st.divider()
st.download_button(
    "Exportação completa (.xlsx)",
    exportar_excel({"Notas": notas_df(conn), "Itens": itens_df(conn)}),
    file_name="nfg_compras.xlsx", mime=XLSX, key="export_completo")
