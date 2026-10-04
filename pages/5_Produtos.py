import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st

from nfg.config import abrir_repo
from nfg.erros import ProdutoDuplicado
from nfg.produtos import (
    atualizar_produto, catalogo_df, comparar_produto, criar_produto, desvincular, excluir_produto,
    historico_produto, ignorados_df, ignorar, pendentes_df, restaurar, sugerir, vincular,
    vincular_automaticos, vinculos_df, visao_geral_df,
)
from nfg.produtos_texto import sugerir_nome
from nfg.util import formatar_brl

st.set_page_config(page_title="Produtos — NFG Compras", page_icon="🧾", layout="wide")
repo = abrir_repo()
conn = repo.conn

st.title("Produtos")


def avisar(tipo: str, texto: str) -> None:
    st.session_state.setdefault("_msgs", []).append((tipo, texto))


def concluir(tipo: str, texto: str) -> None:
    avisar(tipo, texto)
    st.session_state.pop("tabela_pendentes", None)
    st.session_state.pop("_pendente_sel", None)
    st.rerun()


for _tipo, _texto in st.session_state.pop("_msgs", []):
    getattr(st, _tipo)(_texto)

vincular_automaticos(conn)
VENDAS = ["UN", "KG"]
tab_comparar, tab_pendentes, tab_catalogo = st.tabs(["Comparar", "A vincular", "Catálogo"])

# ---------- Comparar ----------
with tab_comparar:
    catalogo = catalogo_df(conn)
    if catalogo.empty:
        st.info("Nenhum produto cadastrado. Crie produtos na aba \"A vincular\".")
    else:
        nomes = dict(zip(catalogo["id"], catalogo["nome"]))
        vendas = dict(zip(catalogo["id"], catalogo["venda"]))
        visao = visao_geral_df(conn)
        if not visao.empty:
            st.subheader("Maiores diferenças entre lojas")
            st.dataframe(pd.DataFrame({
                "Produto": visao["produto"], "Loja mais barata": visao["loja_mais_barata"],
                "Menor preço": visao["menor_preco"].map(formatar_brl),
                "Maior preço": visao["maior_preco"].map(formatar_brl),
                "Diferença (%)": visao["dif_pct"].map(lambda x: f"{x:.1f}%"),
            }), width="stretch", hide_index=True)
        pid = st.selectbox("Produto", list(nomes), format_func=nomes.get, index=None,
                           placeholder="Escolha um produto", key="produto_comparar")
        if pid is not None:
            comp = comparar_produto(conn, pid)
            sufixo = "/kg" if vendas[pid] == "KG" else ""
            if comp.empty:
                st.info("Este produto ainda não tem compras vinculadas.")
            else:
                if len(comp) == 1:
                    st.info(f"Comprado só em {comp['loja'].iloc[0]}")
                else:
                    melhor = comp.iloc[0]
                    st.success(f"Mais barato: {melhor['loja']} — {formatar_brl(melhor['ultimo_preco'])}{sufixo}")
                st.dataframe(pd.DataFrame({
                    "Loja": comp["loja"], "Último preço (R$/kg)" if sufixo else "Último preço": comp["ultimo_preco"].map(formatar_brl),
                    "Data": comp["ultima_data"], "Descrição na loja": comp["descricao_original"],
                    "Diferença (R$)": comp["dif_reais"].map(formatar_brl),
                    "Diferença (%)": comp["dif_pct"].map(lambda x: f"{x:.1f}%"),
                    "Mais barato": comp["mais_barato"].map({True: "Sim", False: ""}),
                }), width="stretch", hide_index=True)
                hist = historico_produto(conn, pid)
                st.plotly_chart(px.line(hist, x="emissao", y="valor_unitario", color="loja", markers=True,
                                        labels={"emissao": "Data", "valor_unitario": "Preço unitário (R$)",
                                                "loja": "Loja"}), width="stretch")

# ---------- A vincular ----------
with tab_pendentes:
    pend = pendentes_df(conn)
    st.caption(f"{len(pend)} itens a vincular")
    if pend.empty:
        st.session_state.pop("_pendente_sel", None)
        st.info("Nenhum item aguardando vínculo.")
    else:
        evento = st.dataframe(
            pd.DataFrame({
                "Loja": pend["loja"], "Descrição": pend["descricao"], "Un.": pend["unidade"],
                "Último preço": pend["ultimo_preco"].map(formatar_brl),
                "Última compra": pend["ultima_data"], "Compras": pend["compras"],
            }),
            key="tabela_pendentes", hide_index=True, width="stretch",
            on_select="rerun", selection_mode="single-row")
        sel = evento.selection.rows
        if not sel or sel[0] >= len(pend):
            st.session_state.pop("_pendente_sel", None)  # widgets do formulario deixam de existir
            st.caption("Selecione um item para vinculá-lo a um produto.")
        else:
            item = pend.iloc[sel[0]]
            cnpj, codigo = item["cnpj"], item["codigo"]
            st.markdown(f"**{item['descricao']}** — {item['loja']}")
            ident = (cnpj, codigo)
            if st.session_state.get("_pendente_sel") != ident:
                nome, tipo, tamanho, venda = sugerir_nome(item["descricao"], item["unidade"])
                st.session_state["novo_nome"] = nome
                st.session_state["novo_tipo"] = tipo
                st.session_state["novo_tamanho"] = tamanho or ""
                st.session_state["novo_venda"] = venda
                st.session_state["_pendente_sel"] = ident

            sugestoes = sugerir(conn, item["descricao"], item["unidade"], n=3)
            st.markdown("**Vincular a um produto existente**")
            if not sugestoes:
                st.caption("Sem sugestões.")
            for i, s in enumerate(sugestoes):
                if st.button(f"{s.nome} — {s.score:.0f} pts ({s.motivo})", key=f"vincular_sug_{i}"):
                    vincular(conn, cnpj, codigo, s.produto_id)
                    concluir("success", f"Vinculado a \"{s.nome}\".")
            cat = catalogo_df(conn)
            if not cat.empty:
                nomes_cat = dict(zip(cat["id"], cat["nome"]))
                outro = st.selectbox("Outro produto", list(nomes_cat), format_func=nomes_cat.get,
                                     index=None, placeholder="Escolha um produto", key="outro_produto")
                if st.button("Vincular ao produto escolhido", key="vincular_outro", disabled=outro is None):
                    vincular(conn, cnpj, codigo, outro)
                    concluir("success", f"Vinculado a \"{nomes_cat[outro]}\".")

            st.markdown("**Criar produto novo**")
            c1, c2, c3, c4 = st.columns(4)
            c1.text_input("Nome", key="novo_nome")
            c2.text_input("Tipo", key="novo_tipo")
            c3.text_input("Tamanho", key="novo_tamanho")
            c4.selectbox("Venda", VENDAS, key="novo_venda")
            b1, b2 = st.columns(2)
            if b1.button("Criar produto e vincular", type="primary", key="criar_produto"):
                nome_novo = st.session_state["novo_nome"].strip()
                if not nome_novo:
                    st.error("Informe o nome do produto.")
                else:
                    try:
                        pid_novo = criar_produto(conn, nome_novo, st.session_state["novo_tipo"].strip(),
                                                 st.session_state["novo_tamanho"].strip() or None,
                                                 st.session_state["novo_venda"])
                    except ProdutoDuplicado as e:
                        st.error(str(e))
                    else:
                        vincular(conn, cnpj, codigo, pid_novo)
                        concluir("success", f"Produto \"{nome_novo}\" criado e vinculado.")
            if b2.button("Ignorar este item", key="ignorar"):
                ignorar(conn, cnpj, codigo)
                concluir("success", "Item ignorado.")

    ign = ignorados_df(conn)
    if not ign.empty:
        with st.expander(f"Ignorados ({len(ign)})"):
            for i, r in ign.iterrows():
                c1, c2 = st.columns([4, 1])
                c1.write(f"{r['descricao']} — {r['loja']}")
                if c2.button("Restaurar", key=f"restaurar_{i}"):
                    restaurar(conn, r["cnpj"], r["codigo"])
                    concluir("success", "Item restaurado.")

# ---------- Catálogo ----------
with tab_catalogo:
    cat = catalogo_df(conn)
    if cat.empty:
        st.info("Nenhum produto cadastrado.")
    else:
        st.caption("Edite nome, tipo, tamanho ou venda; remover uma linha exclui o produto e seus vínculos.")
        base = cat[["id", "nome", "tipo", "tamanho", "venda"]].copy()
        editado = st.data_editor(
            base, key="editor_catalogo", num_rows="dynamic", hide_index=True, width="stretch",
            column_order=["nome", "tipo", "tamanho", "venda"],
            column_config={
                "nome": st.column_config.TextColumn("Nome", required=True),
                "tipo": st.column_config.TextColumn("Tipo"),
                "tamanho": st.column_config.TextColumn("Tamanho"),
                "venda": st.column_config.SelectboxColumn("Venda", options=VENDAS, default="UN"),
            })
        if st.button("Salvar catálogo", type="primary", key="salvar_catalogo"):
            originais = {int(r["id"]): r for r in base.to_dict("records")}
            mantidos, alterados, criados, erros = set(), 0, 0, 0
            for linha in editado.to_dict("records"):
                rid = None if pd.isna(linha.get("id")) else int(linha["id"])
                nome = linha.get("nome")
                tamanho = linha.get("tamanho")
                tamanho = None if pd.isna(tamanho) or not str(tamanho).strip() else str(tamanho).strip()
                tipo = "" if pd.isna(linha.get("tipo")) else str(linha["tipo"]).strip()
                venda = linha.get("venda") if linha.get("venda") in VENDAS else "UN"
                if rid is not None:
                    mantidos.add(rid)
                if not isinstance(nome, str) or not nome.strip():
                    if rid is not None:
                        erros += 1
                        avisar("error", "Produto sem nome; linha não salva.")
                    continue
                try:
                    if rid is None:
                        criar_produto(conn, nome, tipo, tamanho, venda)
                        criados += 1
                    else:
                        o = originais.get(rid, {})
                        o_tam = o.get("tamanho")
                        o_tam = None if o_tam is None or pd.isna(o_tam) else o_tam
                        if (nome.strip(), tipo, tamanho, venda) != (o.get("nome"), o.get("tipo"), o_tam, o.get("venda")):
                            atualizar_produto(conn, rid, nome=nome, tipo=tipo, tamanho=tamanho, venda=venda)
                            alterados += 1
                except ProdutoDuplicado as e:
                    erros += 1
                    avisar("error", str(e))
            if erros:
                # nao exclui nem limpa o editor: o usuario corrige e salva de novo
                st.warning(f"{alterados} alterado(s) e {criados} criado(s) salvos; "
                           f"{erros} linha(s) com erro. Nenhuma exclusão foi aplicada.")
                for _t, _m in st.session_state.pop("_msgs", []):
                    getattr(st, _t)(_m)
            else:
                removidos = [rid for rid in originais if rid not in mantidos]
                for rid in removidos:
                    excluir_produto(conn, rid)
                avisar("success", f"Catálogo salvo: {alterados} alterado(s), {criados} criado(s), "
                                  f"{len(removidos)} removido(s).")
                st.session_state.pop("editor_catalogo", None)
                st.session_state.pop("tabela_catalogo", None)
                st.rerun()

        st.subheader("Vínculos")
        ev_cat = st.dataframe(
            pd.DataFrame({"Produto": cat["nome"], "Tipo": cat["tipo"], "Tamanho": cat["tamanho"],
                          "Venda": cat["venda"], "Lojas": cat["lojas"], "Vínculos": cat["vinculos"]}),
            key="tabela_catalogo", hide_index=True, width="stretch",
            on_select="rerun", selection_mode="single-row")
        sel_cat = ev_cat.selection.rows
        if sel_cat and sel_cat[0] < len(cat):
            pid_sel = int(cat["id"].iloc[sel_cat[0]])
            vin = vinculos_df(conn, pid_sel)
            if vin.empty:
                st.caption("Este produto não tem vínculos.")
            for i, r in vin.iterrows():
                c1, c2 = st.columns([4, 1])
                c1.write(f"{r['descricao']} — {r['loja']} ({r['origem']})")
                if c2.button("Desvincular", key=f"desvincular_{i}"):
                    desvincular(conn, r["cnpj"], r["codigo"])
                    avisar("success", "Vínculo removido.")
                    st.session_state.pop("tabela_pendentes", None)
                    st.session_state.pop("_pendente_sel", None)
                    st.rerun()
