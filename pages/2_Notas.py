import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from nfg.analises import notas_df
from nfg.categorias import Classificador
from nfg.config import abrir_repo
from nfg.util import formatar_brl, from_centavos

st.set_page_config(page_title="NFG Compras", page_icon="🧾", layout="wide")
repo = abrir_repo()

ICONES = {"coletada": "✓ coletada", "pendente": "⏳ pendente", "erro": "⚠ erro", "sem_itens": "📎 sem_itens"}

st.title("Notas")
df = notas_df(repo.conn)
if df.empty:
    st.info("Nenhuma nota ainda. Vá em **Importar** para carregar o CSV.")
    st.stop()

df["status_ico"] = df["status"].map(ICONES).fillna(df["status"])
df["mes"] = df["mes"].fillna("—")
df["loja"] = df["loja"].fillna("(desconhecida)")

f1, f2, f3 = st.columns(3)
meses = f1.multiselect("Mês", sorted(df["mes"].unique(), reverse=True))
lojas = f2.multiselect("Loja", sorted(df["loja"].unique()))
status = f3.multiselect("Status", list(ICONES.values()))
if meses:
    df = df[df["mes"].isin(meses)]
if lojas:
    df = df[df["loja"].isin(lojas)]
if status:
    df = df[df["status_ico"].isin(status)]
df = df.sort_values("emissao", ascending=False).reset_index(drop=True)

tabela = pd.DataFrame({
    "Emissão": df["emissao"],
    "Loja": df["loja"],
    "Valor": df["valor_total"].map(formatar_brl),
    "Itens": df["num_itens"],
    "Status": df["status_ico"],
})
evento = st.dataframe(tabela, width="stretch", hide_index=True, key="tabela_notas",
                      on_select="rerun", selection_mode="single-row")

linhas = evento.selection.rows
if linhas:
    nota = df.iloc[linhas[0]]
    chave = nota["chave"]
    st.divider()
    st.subheader(f"{nota['loja']} — {formatar_brl(nota['valor_total'])}")
    st.caption(f"Chave {chave} · {nota['status_ico']}")
    if nota["aviso"]:
        st.warning(nota["aviso"])
    if nota["erro_msg"]:
        st.error(nota["erro_msg"])
    if nota["status"] in ("erro", "pendente") and st.button("Tentar novamente"):
        repo.reabrir(chave)
        st.rerun()

    itens = repo.itens_da_nota(chave)
    if not itens and nota["status"] == "sem_itens":
        st.info("Anexe o XML desta NF-e na página Importar para ver os itens.")
    if itens:
        cls = Classificador(repo.conn)
        cnpj = nota["cnpj"] or ""
        st.dataframe(pd.DataFrame([
            {"Seq": i["seq"], "Descrição": i["descricao"], "Qtd": i["quantidade"], "Un": i["unidade"],
             "Valor unit.": formatar_brl(Decimal(i["valor_unitario"])), "Total": formatar_brl(from_centavos(i["valor_total_centavos"])),
             "Categoria": cls.categoria(cnpj, i["codigo"] or "", i["descricao"])}
            for i in itens
        ]), width="stretch", hide_index=True)
    pags = repo.pagamentos_da_nota(chave)
    if pags:
        st.write("**Pagamentos**")
        st.dataframe(pd.DataFrame([
            {"Forma": p["forma"], "Valor": formatar_brl(from_centavos(p["valor_centavos"]))} for p in pags
        ]), hide_index=True)
