import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from nfg.analises import itens_df
from nfg.categorias import (
    SEM_CATEGORIA, Classificador, conflitos_df, contar_casamentos, criar_categoria, definir_manual,
    definir_por_descricao, definir_regra_loja, excluir_categoria, excluir_regra, listar_categorias,
    listar_por_descricao, listar_regras, listar_regras_loja, salvar_regra,
)
from nfg.config import abrir_repo
from nfg.util import formatar_brl

st.set_page_config(page_title="Categorias — NFG Compras", page_icon="🧾", layout="wide")
repo = abrir_repo()
conn = repo.conn

st.title("Categorias")


def avisar(tipo: str, texto: str) -> None:
    st.session_state.setdefault("_msgs", []).append((tipo, texto))


for _tipo, _texto in st.session_state.pop("_msgs", []):
    getattr(st, _tipo)(_texto)

invalidas = Classificador(conn).regras_invalidas
if invalidas:
    st.warning("Regras com regex inválida (ignoradas na classificação): "
               + ", ".join(f"#{i}" for i in invalidas))

# ---------- Categorias ----------
st.subheader("Categorias")
nomes = {c["id"]: c["nome"] for c in listar_categorias(conn)}
nome_para_id = {v: k for k, v in nomes.items()}
c1, c2 = st.columns(2)
with c1:
    st.dataframe(pd.DataFrame({"Categoria": list(nomes.values())}), width="stretch", hide_index=True)
with c2:
    with st.form("nova_categoria", clear_on_submit=True):
        nova = st.text_input("Nova categoria")
        if st.form_submit_button("Criar") and nova.strip():
            try:
                criar_categoria(conn, nova.strip())
            except sqlite3.IntegrityError:
                st.error(f"Já existe uma categoria chamada \"{nova.strip()}\".")
            else:
                st.rerun()
    if nomes:
        excluir = st.selectbox("Excluir categoria", list(nomes), format_func=nomes.get, index=None,
                               placeholder="Escolha uma categoria", key="cat_excluir")
        n_regras = 0
        if excluir is not None:
            n_regras = conn.execute(
                "SELECT COUNT(*) FROM regras_categoria WHERE categoria_id = ?", (excluir,)).fetchone()[0]
            st.caption(f"Excluir \"{nomes[excluir]}\" também remove {n_regras} regra(s) e as "
                       "categorizações manuais dessa categoria.")
        rotulo = "Excluir categoria" if excluir is None else f"Excluir categoria (remove {n_regras} regra(s))"
        if excluir is not None and st.button(rotulo, key="btn_excluir_categoria"):
            try:
                excluir_categoria(conn, excluir)
            except Exception as e:
                st.error(f"Não foi possível excluir: {e}")
            else:
                st.rerun()

# ---------- Regras ----------
st.subheader("Regras")
regras = listar_regras(conn)
base = pd.DataFrame(
    [{"id": r["id"], "padrao": r["padrao"], "categoria": r["categoria"], "prioridade": r["prioridade"]}
     for r in regras],
    columns=["id", "padrao", "categoria", "prioridade"])
editado = st.data_editor(
    base, key="editor_regras", num_rows="dynamic", hide_index=True, width="stretch",
    column_order=["padrao", "categoria", "prioridade"],
    column_config={
        "padrao": st.column_config.TextColumn("Padrão (regex)", required=True),
        "categoria": st.column_config.SelectboxColumn("Categoria", options=list(nome_para_id), required=True),
        "prioridade": st.column_config.NumberColumn("Prioridade", min_value=0, step=1, default=100),
    })
if st.button("Salvar", type="primary", key="salvar_regras"):
    mantidos, erros = set(), 0
    for pos, linha in enumerate(editado.to_dict("records"), start=1):
        rid = None if pd.isna(linha.get("id")) else int(linha["id"])
        padrao, cat = linha.get("padrao"), linha.get("categoria")
        if rid is not None:
            mantidos.add(rid)
        if not isinstance(padrao, str) or not padrao.strip() or cat not in nome_para_id:
            if rid is not None:
                erros += 1
                avisar("error", f"Linha {pos}: padrão ou categoria ausente; regra não salva.")
            continue
        prio = 100 if pd.isna(linha.get("prioridade")) else int(linha["prioridade"])
        try:
            salvar_regra(conn, padrao, nome_para_id[cat], prio, rid)
        except ValueError as e:
            erros += 1
            avisar("error", f"Linha {pos} ({padrao[:40]}): {e}")
    for r in regras:
        if r["id"] not in mantidos:
            excluir_regra(conn, r["id"])
    if not erros:
        avisar("success", "Regras salvas.")
    st.session_state.pop("editor_regras", None)  # evita reaplicar o delta do editor
    st.rerun()

st.caption("Use ^ no início do padrão para 'começa com' (ex.: ^PIZZA). Regras 'começa com' são decisivas "
           "e não aparecem como conflito.")
st.text_input("Testar padrão", key="testar_padrao",
              help="Mostra quantos itens já coletados casam com a regex.")
teste = st.session_state.get("testar_padrao", "")
if teste:
    try:
        st.caption(f"{contar_casamentos(conn, teste)} itens casam com esse padrão.")
    except ValueError as e:
        st.error(str(e))

# ---------- Regras por estabelecimento ----------
st.subheader("Regras por estabelecimento")
st.caption("Vale para todos os itens comprados nesse estabelecimento, exceto correções manuais. "
           "Remover ou trocar a loja de uma linha remove a regra correspondente.")
lojas = {r["cnpj"]: r["nome"] for r in conn.execute(
    "SELECT cnpj, COALESCE(razao_social, nome_csv, cnpj) AS nome FROM estabelecimentos ORDER BY nome, cnpj")}
regras_loja = listar_regras_loja(conn)
for _r in regras_loja:
    lojas.setdefault(_r["cnpj"], _r["loja"])
_contagem = {}
for _n in lojas.values():
    _contagem[_n] = _contagem.get(_n, 0) + 1
rotulo_loja = {c: (n if _contagem[n] == 1 else f"{n} ({c})") for c, n in lojas.items()}
loja_para_cnpj = {v: k for k, v in rotulo_loja.items()}
base_loja = pd.DataFrame(
    [{"loja": rotulo_loja[r["cnpj"]], "categoria": r["categoria"]} for r in regras_loja],
    columns=["loja", "categoria"])
editado_loja = st.data_editor(
    base_loja, key="editor_regras_loja", num_rows="dynamic", hide_index=True, width="stretch",
    column_config={
        "loja": st.column_config.SelectboxColumn("Estabelecimento", options=list(loja_para_cnpj), required=True),
        "categoria": st.column_config.SelectboxColumn("Categoria", options=list(nome_para_id), required=True),
    })
if st.button("Salvar regras de estabelecimento", key="salvar_regras_loja"):
    propostas, erros = {}, 0
    for pos, linha in enumerate(editado_loja.to_dict("records"), start=1):
        loja, cat = linha.get("loja"), linha.get("categoria")
        loja_ok, cat_ok = loja in loja_para_cnpj, cat in nome_para_id
        if loja_ok and cat_ok:
            propostas.setdefault(loja_para_cnpj[loja], set()).add(nome_para_id[cat])
        elif loja_ok or cat_ok:
            erros += 1
            avisar("error", f"Linha {pos}: estabelecimento ou categoria ausente; regra não salva.")
    definidos, ambiguos = {}, set()
    for cnpj, cats in propostas.items():
        if len(cats) > 1:
            erros += 1
            ambiguos.add(cnpj)
            avisar("error", f"Estabelecimento '{rotulo_loja[cnpj]}' aparece em mais de uma linha com "
                            "categorias diferentes; nenhuma alteração feita para ele.")
        else:
            definidos[cnpj] = next(iter(cats))
    for cnpj, cat_id in definidos.items():
        definir_regra_loja(conn, cnpj, cat_id)
    presentes = set(editado_loja["loja"].dropna())  # linha incompleta não apaga a regra existente
    for r in regras_loja:
        if r["cnpj"] not in definidos and r["cnpj"] not in ambiguos                 and rotulo_loja[r["cnpj"]] not in presentes:
            definir_regra_loja(conn, r["cnpj"], None)
    avisar("success", "Demais regras salvas." if erros else "Regras de estabelecimento salvas.")
    st.session_state.pop("editor_regras_loja", None)
    st.rerun()

# ---------- Sem categoria ----------
st.subheader("Itens sem categoria")
APLICAR_PRODUTO = "Este produto"
APLICAR_DESCRICAO = "Mesma descrição (todas as lojas)"
itens = itens_df(conn)
sem = itens[itens["categoria"] == SEM_CATEGORIA]
# "Este produto" exige (cnpj, codigo); "Mesma descrição" só exige descrição
total_sem = len(sem)
sem = sem[sem["descricao"].notna() & (sem["descricao"] != "")]
if total_sem > len(sem):
    st.caption(f"{total_sem - len(sem)} itens sem categoria não aparecem aqui por não terem descrição.")
if sem.empty:
    st.info("Nenhum item sem categoria.")
else:
    agr = (sem.groupby(["cnpj", "codigo", "descricao"], as_index=False, dropna=False)
              .agg(total=("valor_total", "sum")).sort_values("total", ascending=False)
              .reset_index(drop=True))
    tabela = pd.DataFrame({
        "cnpj": agr["cnpj"], "codigo": agr["codigo"], "descricao": agr["descricao"],
        "total": agr["total"].map(formatar_brl),
        "categoria": pd.Series([None] * len(agr), dtype=object),
        "aplicar_a": pd.Series([APLICAR_PRODUTO] * len(agr), dtype=object),
    })
    ed = st.data_editor(
        tabela, key="editor_sem_categoria", hide_index=True, width="stretch",
        disabled=["cnpj", "codigo", "descricao", "total"],
        column_config={
            "cnpj": "CNPJ", "codigo": "Código", "descricao": "Descrição", "total": "Total gasto",
            "categoria": st.column_config.SelectboxColumn("Categoria", options=list(nome_para_id)),
            "aplicar_a": st.column_config.SelectboxColumn(
                "Aplicar a", options=[APLICAR_PRODUTO, APLICAR_DESCRICAO], default=APLICAR_PRODUTO),
        })
    if st.button("Aplicar", key="aplicar_manual"):
        n_prod = n_desc = 0
        for linha in ed.to_dict("records"):
            if linha["categoria"] not in nome_para_id:
                continue
            cat_id = nome_para_id[linha["categoria"]]
            if linha.get("aplicar_a") == APLICAR_DESCRICAO:
                definir_por_descricao(conn, linha["descricao"], cat_id)
                n_desc += 1
            elif pd.isna(linha["cnpj"]) or pd.isna(linha["codigo"]) or linha["codigo"] == "":
                avisar("error", f"\"{linha['descricao']}\": sem CNPJ ou código; use \"{APLICAR_DESCRICAO}\".")
                continue
            else:
                definir_manual(conn, linha["cnpj"], linha["codigo"], cat_id)
                n_prod += 1
        avisar("success", f"{n_prod} produto(s) e {n_desc} descrição(ões) categorizados.")
        st.session_state.pop("editor_sem_categoria", None)
        st.rerun()

# ---------- Correções por descrição ----------
st.subheader("Correções por descrição")
por_desc = listar_por_descricao(conn)
if not por_desc:
    st.caption("Nenhuma correção por descrição.")
else:
    evento = st.dataframe(
        pd.DataFrame({"Descrição": [r["descricao_norm"] for r in por_desc],
                      "Categoria": [r["categoria"] for r in por_desc]}),
        key="tabela_por_descricao", hide_index=True, width="stretch",
        on_select="rerun", selection_mode="multi-row")
    if st.button("Remover selecionadas", key="remover_por_descricao"):
        sel = evento.selection.rows
        for pos in sel:
            definir_por_descricao(conn, por_desc[pos]["descricao_norm"], None)
        avisar("success", f"{len(sel)} correções removidas.")
        st.session_state.pop("tabela_por_descricao", None)
        st.rerun()

# ---------- Conflitos ----------
st.subheader("Conflitos")
conflitos = conflitos_df(conn)
if conflitos.empty:
    st.caption("Nenhum conflito entre regras.")
else:
    st.caption("Altere a categoria ou marque Confirmar para manter a atual. Itens resolvidos saem da lista.")
    _ident = [tuple(x) for x in conflitos[["cnpj", "codigo", "descricao"]].astype(str).values]
    if st.session_state.get("_conflitos_ident") not in (None, _ident):
        pend = st.session_state.get("editor_conflitos") or {}
        if pend.get("edited_rows"):
            # edicoes feitas sobre outra versao da lista (indices por posicao): descartar
            st.session_state.pop("editor_conflitos", None)
            st.warning("Lista de conflitos mudou; recarregue e tente de novo.")
    st.session_state["_conflitos_ident"] = _ident
    tabela_conf = pd.DataFrame({
        "cnpj": conflitos["cnpj"], "codigo": conflitos["codigo"], "vencedora": conflitos["vencedora"],
        "loja": conflitos["loja"], "descricao": conflitos["descricao"],
        "categoria": conflitos["vencedora"], "outras": conflitos["outras"],
        "aplicar_a": pd.Series([APLICAR_PRODUTO] * len(conflitos), dtype=object, index=conflitos.index),
        "confirmar": pd.Series([False] * len(conflitos), dtype=bool, index=conflitos.index),
    }).reset_index(drop=True)
    ed_conf = st.data_editor(
        tabela_conf, key="editor_conflitos", hide_index=True, width="stretch",
        disabled=["loja", "descricao", "outras"],
        column_order=["loja", "descricao", "categoria", "outras", "aplicar_a", "confirmar"],
        column_config={
            "loja": "Loja", "descricao": "Descrição", "outras": "Outras categorias que casam",
            "categoria": st.column_config.SelectboxColumn("Categoria", options=list(nome_para_id)),
            "aplicar_a": st.column_config.SelectboxColumn(
                "Aplicar a", options=[APLICAR_PRODUTO, APLICAR_DESCRICAO], default=APLICAR_PRODUTO),
            "confirmar": st.column_config.CheckboxColumn("Confirmar", default=False),
        })
    if st.button("Salvar conflitos", key="salvar_conflitos"):
        n = sinalizadas = 0
        atuais = {(str(a), str(b), str(c)) for a, b, c in
                  conflitos[["cnpj", "codigo", "descricao"]].itertuples(index=False)}
        for linha in ed_conf.to_dict("records"):
            orig = linha
            cat = linha.get("categoria")
            if cat not in nome_para_id or not (cat != orig["vencedora"] or bool(linha.get("confirmar"))):
                continue
            sinalizadas += 1
            if (str(orig["cnpj"]), str(orig["codigo"]), str(orig["descricao"])) not in atuais:
                st.warning("Lista de conflitos mudou; recarregue e tente de novo.")
                continue
            cat_id = nome_para_id[cat]
            if linha.get("aplicar_a") == APLICAR_DESCRICAO:
                definir_por_descricao(conn, orig["descricao"], cat_id)
            elif pd.isna(orig["cnpj"]) or pd.isna(orig["codigo"]) or orig["codigo"] == "":
                st.error(f"\"{orig['descricao']}\": sem CNPJ ou código; use \"{APLICAR_DESCRICAO}\".")
                continue
            else:
                definir_manual(conn, orig["cnpj"], orig["codigo"], cat_id)
            n += 1
        if n:
            avisar("success", f"{n} conflito(s) resolvido(s).")
            st.session_state.pop("editor_conflitos", None)
            st.rerun()
        elif not sinalizadas:
            st.info("Nada a salvar.")
