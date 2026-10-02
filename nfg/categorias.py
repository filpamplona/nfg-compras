from __future__ import annotations

import re
import sqlite3

import pandas as pd

from nfg.util import normalizar_texto

SEM_CATEGORIA = "Sem categoria"
# Limite de tamanho; regexes escritas pelo usuario alem disso sao confiaveis (sem protecao contra backtracking).
MAX_PADRAO = 1000
CNPJ_DIMED = "92665611007422"

_CATEGORIAS_SEED = [
    "Doces/Snacks", "Bebidas", "Hortifruti", "Padaria", "Carnes",
    "Laticínios/Frios", "Mercearia", "Limpeza", "Higiene", "Outros",
    "Pizza", "Farmácia", "Casa/Utilidades", "Serviços",
]

# Regras "comeca com" (padrao inicia com ^): decisivas, nao geram conflito.
_REGRAS_COMECA_COM = [
    ("Pizza", 5, r"^PIZZA\b"),
    ("Padaria", 5, r"^(PAO|PAES|PAOZINHO)\b"),
    ("Doces/Snacks", 5, r"^(CHOC|CHOCOLATE)\b"),
]

# (categoria, prioridade, padrao); desempate por ordem de insercao (id).
_REGRAS_SEED = _REGRAS_COMECA_COM + [
    ("Casa/Utilidades", 10, r"\b(CARVAO|SACOLA|SAC INST|ALCOOL GEL ACEND|FILTRO PAPEL)"),
    ("Limpeza", 10, r"\b(AGUA SANIT|SAPON|LAVA ROUPA|L ROUP|LAV LOUCA|DET\b|DET\.|DETERG|LIMP\b|LIMP\.|LIMPA\b|LIMPOL|DESENTUP|LUST\b|ALCOOL|PANO\b|ESP\b|ESPONJA|BOMBRIL|SCOTCH|SACO LIXO|VEJA\b|AJAX|DESINF|ALVEJ|AMACIANTE|SABAO|P TOALHA|PAPEL TOALHA)"),
    ("Pizza", 10, r"\bPIZZA\b"),
    ("Hortifruti", 10, r"\bPARA SUCO\b"),
    ("Serviços", 10, r"\b(OPCIONAL|TAXA|SERVICO)\b"),
    ("Farmácia", 12, r"\b(COMPRIMIDO|PASTILHA|XAROPE|GOTAS|\d+MG\b)"),
    ("Padaria", 15, r"\b(PAO|PAES|PAOZINHO|BOLO|BOLINHO|CUCA|SONHO)\b|\b(BROWNIE|TORRADA)"),
    ("Doces/Snacks", 20, r"\b(BISC|CHOC|BALA\b|SALGADINHO|TWIX|BOMBOM|SORVETE|SORB\b|WAFER|KITKAT|KIT KAT|BIBS\b|ALFAJOR|MARSHMAL|PE (DE )?MOCA|FONDANT|AMENDOIM|BARRA\b|BANAN\b)"),
    ("Higiene", 30, r"\b(SHAMPOO|SHAMP|SH\b|CONDIC|SABONETE|CREME DENTAL|ESCOVA|DESOD|DES\.|PAPEL HIG|P H\b|FIO DENT|ABSORV|ENXAGUANTE|LISTERINE)"),
    ("Higiene", 30, r"(?<!S/)\bSAB(\b|\.)"),
    ("Bebidas", 30, r"\b(REFRIG|COCA\b|SUCO|AGUA\b|AG MINERAL|CERVEJA|VINHO|VIN\.|VH\b|ENERG|RED BULL|CHA\b|POWERADE|QUENTAO|BEB\.|BEB\b|TACA\b)"),
    ("Hortifruti", 30, r"\bVAGEM\b"),
    ("Mercearia", 35, r"\b(MASSA|MACARRAO|MAC\.|FAR\b|FARINHA|LEITE COCO|ATUM|ACHOC|NESCAU|CAPP)"),
    ("Carnes", 40, r"\b(FILE\b|FILEZ|F\.MIG|CARNE|FRANGO|FGO\b|PATINHO|ALCATRA|COSTELA|LING\b|LING\.|LINGUICA|SALSICHAO|PICANHA|BIFE|S?COXA|PEIXE|SALMAO|TILAPIA|LOMBO|MAMINHA|ENTRECOT|HAMB\b|SUINO|BOVINO)"),
    ("Laticínios/Frios", 45, r"\b(QJO|QUEIJO|LEITE|IOG|MANTEIGA|REQUEIJAO|PRESUNTO|MUSSARELA|SALAME|MORT\b|MORT\.|MORTADELA|BACON|CR\.? ?LEITE|OVOS?\b)"),
    ("Hortifruti", 50, r"\b(BANANA|LARANJA|MACA\b|CEBOLA|TOMATE|BATATA|ALFACE|LIMAO|MAMAO|CENOURA|ALHO\b|UVA\b|MORANGO|ABACATE|KIWI|BROCOLIS|MELAO|BETERRABA|MORANGA|ABOBRINHA|ABOBORA|MANGA\b|BERGAMOTA|HF\.)"),
    ("Mercearia", 50, r"\b(CAFE\b|ARROZ|FEIJAO|ACUCAR|OLEO\b|AZEITE|MILHO|ERVILHA|MOLHO|SAL\b|CANELA|TEMPERO|AVEIA|TAPIOCA|PASSATA|CATCHUP|KETCHUP|MOSTARDA|OREGANO|PAPRICA|MEL\b|ERVA MATE|POLENTA|CASTANHA|ACAI)"),
    ("Hortifruti", 200, r"\bGRANEL\b"),
]


def garantir_seed(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT COUNT(*) FROM categorias").fetchone()[0]:
        return
    with conn:
        ids = {}
        for nome in _CATEGORIAS_SEED:
            ids[nome] = conn.execute("INSERT INTO categorias(nome) VALUES (?)", (nome,)).lastrowid
        for nome, prio, padrao in _REGRAS_SEED:
            conn.execute(
                "INSERT INTO regras_categoria(padrao, categoria_id, prioridade) VALUES (?,?,?)",
                (padrao, ids[nome], prio),
            )
        conn.execute("PRAGMA user_version = 2")


def migrar(conn: sqlite3.Connection) -> None:
    """Migracoes v0 -> v1 (seed revisado) e v1 -> v2 (regras 'comeca com'). Idempotentes."""
    _migrar_v1(conn)
    _migrar_v2(conn)


def _migrar_v2(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 2:
        return
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN")
    try:
        ids = {r["nome"]: r["id"] for r in conn.execute("SELECT id, nome FROM categorias")}
        for nome, prio, padrao in _REGRAS_COMECA_COM:
            if nome in ids and not conn.execute(
                    "SELECT 1 FROM regras_categoria WHERE padrao=?", (padrao,)).fetchone():
                conn.execute(
                    "INSERT INTO regras_categoria(padrao, categoria_id, prioridade) VALUES (?,?,?)",
                    (padrao, ids[nome], prio))
        conn.execute("PRAGMA user_version = 2")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _migrar_v1(conn: sqlite3.Connection) -> None:
    if conn.execute("PRAGMA user_version").fetchone()[0] >= 1:
        return
    if conn.in_transaction:
        conn.commit()
    conn.execute("BEGIN")
    try:
        ids = {r["nome"]: r["id"] for r in conn.execute("SELECT id, nome FROM categorias")}
        if "Remédios" in ids:
            if "Farmácia" not in ids:
                conn.execute("UPDATE categorias SET nome='Farmácia' WHERE id=?", (ids["Remédios"],))
                ids["Farmácia"] = ids.pop("Remédios")
            else:
                antigo, novo = ids.pop("Remédios"), ids["Farmácia"]
                for tabela in ("categoria_manual", "regras_categoria", "regras_loja", "categoria_descricao"):
                    conn.execute(f"UPDATE {tabela} SET categoria_id=? WHERE categoria_id=?", (novo, antigo))
                conn.execute("DELETE FROM categorias WHERE id=?", (antigo,))
        for nome in _CATEGORIAS_SEED:
            if nome not in ids:
                ids[nome] = conn.execute("INSERT INTO categorias(nome) VALUES (?)", (nome,)).lastrowid
        conn.execute(
            "CREATE TABLE IF NOT EXISTS regras_categoria_backup ("
            "id INTEGER, padrao TEXT, categoria_nome TEXT, prioridade INTEGER)")
        if not conn.execute("SELECT COUNT(*) FROM regras_categoria_backup").fetchone()[0]:
            conn.execute(
                "INSERT INTO regras_categoria_backup(id, padrao, categoria_nome, prioridade) "
                "SELECT r.id, r.padrao, c.nome, r.prioridade FROM regras_categoria r "
                "JOIN categorias c ON c.id = r.categoria_id")
        conn.execute("DELETE FROM regras_categoria")
        for nome, prio, padrao in _REGRAS_SEED:
            conn.execute(
                "INSERT INTO regras_categoria(padrao, categoria_id, prioridade) VALUES (?,?,?)",
                (padrao, ids[nome], prio))
        if conn.execute("SELECT 1 FROM estabelecimentos WHERE cnpj=?", (CNPJ_DIMED,)).fetchone():
            conn.execute(
                "INSERT OR IGNORE INTO regras_loja(cnpj, categoria_id) VALUES (?,?)",
                (CNPJ_DIMED, ids["Farmácia"]))
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _compilar(padrao: str) -> re.Pattern:
    if len(padrao) > MAX_PADRAO:
        raise ValueError(f"Regex muito longa (máx. {MAX_PADRAO} caracteres)")
    try:
        return re.compile(padrao, re.IGNORECASE)
    except re.error as e:
        raise ValueError(f"Regex inválida: {padrao!r} ({e})") from e


class Classificador:
    def __init__(self, conn: sqlite3.Connection):
        self._regras = []
        self.regras_invalidas: list[int] = []
        for r in conn.execute(
            "SELECT r.id, r.padrao, c.nome AS categoria FROM regras_categoria r "
            "JOIN categorias c ON c.id = r.categoria_id ORDER BY r.prioridade, r.id"
        ):
            try:
                self._regras.append((re.compile(r["padrao"], re.IGNORECASE), r["categoria"], r["padrao"]))
            except re.error:
                self.regras_invalidas.append(r["id"])
        self._manual = {
            (r["cnpj"], r["codigo"]): r["categoria"]
            for r in conn.execute(
                "SELECT m.cnpj, m.codigo, c.nome AS categoria FROM categoria_manual m "
                "JOIN categorias c ON c.id = m.categoria_id"
            )
        }
        self._descricao = {
            r["descricao_norm"]: r["categoria"]
            for r in conn.execute(
                "SELECT d.descricao_norm, c.nome AS categoria FROM categoria_descricao d "
                "JOIN categorias c ON c.id = d.categoria_id"
            )
        }
        self._loja = {
            r["cnpj"]: r["categoria"]
            for r in conn.execute(
                "SELECT l.cnpj, c.nome AS categoria FROM regras_loja l "
                "JOIN categorias c ON c.id = l.categoria_id"
            )
        }

    def casamentos(self, descricao: str | None) -> list[str]:
        """Categorias distintas de todas as regras de texto que casam, em ordem de prioridade."""
        texto = normalizar_texto(descricao or "")
        out: list[str] = []
        for rx, nome, _ in self._regras:
            if nome not in out and rx.search(texto):
                out.append(nome)
        return out

    def regra_vencedora(self, descricao: str | None) -> tuple[str, str] | None:
        """(categoria, padrao) da primeira regra de texto que casa, ou None."""
        texto = normalizar_texto(descricao or "")
        for rx, nome, padrao in self._regras:
            if rx.search(texto):
                return nome, padrao
        return None

    def categoria(self, cnpj: str, codigo: str, descricao: str) -> str:
        manual = self._manual.get((cnpj, codigo))
        if manual:
            return manual
        texto = normalizar_texto(descricao or "")
        por_desc = self._descricao.get(texto)
        if por_desc:
            return por_desc
        loja = self._loja.get(cnpj)
        if loja:
            return loja
        for rx, nome, _ in self._regras:
            if rx.search(texto):
                return nome
        return SEM_CATEGORIA


def categorizar_df(conn: sqlite3.Connection, df: pd.DataFrame) -> pd.DataFrame:
    clf = Classificador(conn)
    out = df.copy()
    out["categoria"] = [
        clf.categoria(c, k, "" if pd.isna(d) else d)
        for c, k, d in zip(out["cnpj"], out["codigo"], out["descricao"])
    ]
    return out


def listar_categorias(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, nome FROM categorias ORDER BY id").fetchall()


def criar_categoria(conn: sqlite3.Connection, nome: str) -> int:
    with conn:
        return conn.execute("INSERT INTO categorias(nome) VALUES (?)", (nome,)).lastrowid


def excluir_categoria(conn: sqlite3.Connection, id: int) -> None:
    with conn:
        conn.execute("DELETE FROM categoria_manual WHERE categoria_id = ?", (id,))
        conn.execute("DELETE FROM categorias WHERE id = ?", (id,))


def listar_regras(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT r.id, r.padrao, r.categoria_id, r.prioridade, c.nome AS categoria "
        "FROM regras_categoria r JOIN categorias c ON c.id = r.categoria_id "
        "ORDER BY r.prioridade, r.id"
    ).fetchall()


def salvar_regra(conn: sqlite3.Connection, padrao: str, categoria_id: int,
                 prioridade: int = 100, id: int | None = None) -> int:
    _compilar(padrao)
    with conn:
        if id is None:
            return conn.execute(
                "INSERT INTO regras_categoria(padrao, categoria_id, prioridade) VALUES (?,?,?)",
                (padrao, categoria_id, prioridade),
            ).lastrowid
        conn.execute(
            "UPDATE regras_categoria SET padrao=?, categoria_id=?, prioridade=? WHERE id=?",
            (padrao, categoria_id, prioridade, id),
        )
        return id


def excluir_regra(conn: sqlite3.Connection, id: int) -> None:
    with conn:
        conn.execute("DELETE FROM regras_categoria WHERE id = ?", (id,))


def definir_manual(conn: sqlite3.Connection, cnpj: str, codigo: str, categoria_id: int | None) -> None:
    with conn:
        if categoria_id is None:
            conn.execute("DELETE FROM categoria_manual WHERE cnpj=? AND codigo=?", (cnpj, codigo))
        else:
            conn.execute(
                "INSERT INTO categoria_manual(cnpj, codigo, categoria_id) VALUES (?,?,?) "
                "ON CONFLICT(cnpj, codigo) DO UPDATE SET categoria_id=excluded.categoria_id",
                (cnpj, codigo, categoria_id),
            )


def contar_casamentos(conn: sqlite3.Connection, padrao: str) -> int:
    rx = _compilar(padrao)
    return sum(
        1 for r in conn.execute("SELECT descricao FROM itens")
        if rx.search(normalizar_texto(r["descricao"] or ""))
    )


def definir_por_descricao(conn: sqlite3.Connection, descricao: str, categoria_id: int | None) -> None:
    norm = normalizar_texto(descricao or "")
    with conn:
        if categoria_id is None:
            conn.execute("DELETE FROM categoria_descricao WHERE descricao_norm=?", (norm,))
        else:
            conn.execute(
                "INSERT INTO categoria_descricao(descricao_norm, categoria_id) VALUES (?,?) "
                "ON CONFLICT(descricao_norm) DO UPDATE SET categoria_id=excluded.categoria_id",
                (norm, categoria_id),
            )


def listar_por_descricao(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT d.descricao_norm, d.categoria_id, c.nome AS categoria "
        "FROM categoria_descricao d JOIN categorias c ON c.id = d.categoria_id "
        "ORDER BY d.descricao_norm"
    ).fetchall()


def listar_regras_loja(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT l.cnpj, COALESCE(e.razao_social, e.nome_csv, l.cnpj) AS loja, "
        "l.categoria_id, c.nome AS categoria "
        "FROM regras_loja l JOIN categorias c ON c.id = l.categoria_id "
        "LEFT JOIN estabelecimentos e ON e.cnpj = l.cnpj ORDER BY loja, l.cnpj"
    ).fetchall()


def definir_regra_loja(conn: sqlite3.Connection, cnpj: str, categoria_id: int | None) -> None:
    with conn:
        if categoria_id is None:
            conn.execute("DELETE FROM regras_loja WHERE cnpj=?", (cnpj,))
        else:
            conn.execute(
                "INSERT INTO regras_loja(cnpj, categoria_id) VALUES (?,?) "
                "ON CONFLICT(cnpj) DO UPDATE SET categoria_id=excluded.categoria_id",
                (cnpj, categoria_id),
            )


CONFLITOS_COLUNAS = ["cnpj", "loja", "codigo", "descricao", "vencedora", "outras"]


def conflitos_df(conn: sqlite3.Connection) -> pd.DataFrame:
    """Produtos cujas regras de texto casam com 2+ categorias distintas, ainda sem resolucao:
    exclui correcao manual, correcao por descricao e regra de texto decisiva (padrao com ^)."""
    clf = Classificador(conn)
    linhas = []
    for r in conn.execute(
        "SELECT DISTINCT n.cnpj_emitente AS cnpj, "
        "COALESCE(e.razao_social, e.nome_csv, n.cnpj_emitente) AS loja, "
        "i.codigo, i.descricao FROM itens i JOIN notas n ON n.chave = i.chave "
        "LEFT JOIN estabelecimentos e ON e.cnpj = n.cnpj_emitente "
        "ORDER BY loja, i.descricao, i.codigo"
    ):
        if (r["cnpj"], r["codigo"]) in clf._manual:
            continue
        if normalizar_texto(r["descricao"] or "") in clf._descricao:
            continue
        cats = clf.casamentos(r["descricao"])
        if len(cats) < 2:
            continue
        vence = clf.regra_vencedora(r["descricao"])
        if vence and vence[1].startswith("^"):
            continue
        vencedora = clf.categoria(r["cnpj"], r["codigo"], r["descricao"])
        linhas.append({
            "cnpj": r["cnpj"], "loja": r["loja"], "codigo": r["codigo"],
            "descricao": r["descricao"], "vencedora": vencedora,
            "outras": ", ".join(c for c in cats if c != vencedora),
        })
    return pd.DataFrame(linhas, columns=CONFLITOS_COLUNAS)
