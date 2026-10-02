import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from nfg import csv_import
from nfg.coleta import anexar_xml, coletar, reprocessar_html
from nfg.config import abrir_repo, html_dir
from nfg.erros import CSVInvalido, ErroNFG, LayoutDesconhecido
from nfg.sefaz_client import SefazClient
from nfg.util import formatar_brl

st.set_page_config(page_title="NFG Compras", page_icon="🧾", layout="wide")
repo = abrir_repo()

st.title("Importar")

# --- CSV ---
st.subheader("1. Relatório CSV da Nota Fiscal Gaúcha")
arquivo = st.file_uploader("Arquivo CSV", type=["csv"], key="csv")
if arquivo is not None:
    try:
        res = csv_import.ler(arquivo.getvalue())
    except CSVInvalido as e:
        st.error(f"CSV inválido: {e}")
    else:
        previa = pd.DataFrame([
            {"Emissão": r.emissao, "Loja": r.nome_csv, "Valor": formatar_brl(r.valor_total),
             "Modelo": r.modelo, "Situação": r.situacao, "Chave": r.chave}
            for r in res.resumos
        ])
        st.dataframe(previa, width="stretch", hide_index=True)
        if res.invalidas:
            st.warning(f"{len(res.invalidas)} linhas inválidas")
            for linha, motivo in res.invalidas:
                st.write(f"Linha {linha}: {motivo}")
        if st.button("Importar", type="primary"):
            r = repo.importar_resumos(res.resumos)
            st.success(f"{r['novas']} novas, {r['existentes']} já existentes, "
                       f"{r['nfe']} NF-e aguardando XML, {len(res.invalidas)} inválidas")

# --- XML ---
st.subheader("2. XML de NF-e (modelo 55)")
xmls = st.file_uploader("Arquivos XML", type=["xml"], accept_multiple_files=True, key="xml")
if xmls and st.button("Anexar XMLs"):
    for f in xmls:
        try:
            nota = anexar_xml(repo, f.getvalue())
            st.success(f"{f.name}: nota {nota.chave} anexada")
        except LayoutDesconhecido as e:
            st.error(f"{f.name}: não foi possível ler este XML ({e}).")
        except ErroNFG as e:
            st.error(f"{f.name}: {e}")

# --- Coleta ---
st.subheader("3. Coleta na SEFAZ")
n_pend = len(repo.pendentes())
if st.button(f"Baixar notas pendentes ({n_pend})", disabled=n_pend == 0, type="primary"):
    barra = st.progress(0.0)
    with st.status("Baixando notas...", expanded=True) as status:
        def on_progress(p):
            barra.progress(p.i / p.total if p.total else 1.0)
            st.write(f"{'✓' if p.ok else '⚠'} {p.i}/{p.total} {p.chave}: {p.mensagem}")

        lote = coletar(repo, SefazClient(), html_dir(), on_progress=on_progress)
        status.update(label="Coleta finalizada", state="error" if lote.interrompido else "complete")
    if lote.interrompido:
        st.error(f"Coleta interrompida: {lote.motivo}. Tente mais tarde.")
    else:
        st.success(f"{lote.coletadas} notas coletadas, {lote.erros} com erro.")

if st.button("Reprocessar HTMLs salvos"):
    lote = reprocessar_html(repo, html_dir())
    st.success(f"{lote.coletadas} reprocessadas, {lote.erros} com erro.")
