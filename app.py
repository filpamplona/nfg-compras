import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from nfg.analises import gasto_mensal, meses_disponiveis, resumo_mes
from nfg.config import abrir_repo
from nfg.util import formatar_brl

st.set_page_config(page_title="NFG Compras", page_icon="🧾", layout="wide")
repo = abrir_repo()

st.title("🧾 NFG Compras")

meses = meses_disponiveis(repo.conn)
if not meses:
    st.info("Ainda não há notas com dados. Vá em **Importar** para carregar o CSV da Nota Fiscal Gaúcha.")
    st.stop()

mes = st.selectbox("Mês", meses, index=0)
r = resumo_mes(repo.conn, mes)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total do mês", formatar_brl(r["total"]),
          delta=None if r["variacao_pct"] is None else f"{r['variacao_pct']:+.1f}%".replace(".", ","))
c2.metric("Compras", r["compras"])
c3.metric("Ticket médio", formatar_brl(r["ticket_medio"]) if r["ticket_medio"] is not None else "—")
c4.metric("Notas pendentes/erro", r["pendentes"])

st.subheader("Últimos 12 meses")
mensal = gasto_mensal(repo.conn).tail(12)
st.bar_chart(mensal.set_index("mes")["total"])
