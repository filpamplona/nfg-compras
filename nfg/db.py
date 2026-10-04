from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from nfg.models import Nota, NotaResumo
from nfg.util import to_centavos

SCHEMA = """
CREATE TABLE IF NOT EXISTS estabelecimentos (
  cnpj TEXT PRIMARY KEY,
  razao_social TEXT, nome_csv TEXT,
  inscricao_estadual TEXT, endereco TEXT, municipio TEXT
);
CREATE TABLE IF NOT EXISTS notas (
  chave TEXT PRIMARY KEY,
  modelo INTEGER NOT NULL,
  cnpj_emitente TEXT REFERENCES estabelecimentos(cnpj),
  numero TEXT, serie TEXT,
  emissao TEXT NOT NULL,
  valor_total_centavos INTEGER NOT NULL,
  valor_descontos_centavos INTEGER DEFAULT 0,
  protocolo TEXT,
  situacao_csv TEXT, tipo_operacao TEXT,
  status TEXT NOT NULL,
  erro_msg TEXT, aviso TEXT,
  tentativas INTEGER NOT NULL DEFAULT 0,
  importada_em TEXT, coletada_em TEXT
);
CREATE TABLE IF NOT EXISTS itens (
  id INTEGER PRIMARY KEY,
  chave TEXT NOT NULL REFERENCES notas(chave) ON DELETE CASCADE,
  seq INTEGER NOT NULL,
  codigo TEXT, descricao TEXT NOT NULL,
  quantidade TEXT NOT NULL, unidade TEXT,
  valor_unitario TEXT NOT NULL,
  valor_total_centavos INTEGER NOT NULL,
  UNIQUE (chave, seq)
);
CREATE TABLE IF NOT EXISTS pagamentos (
  id INTEGER PRIMARY KEY,
  chave TEXT NOT NULL REFERENCES notas(chave) ON DELETE CASCADE,
  forma TEXT NOT NULL, valor_centavos INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS categorias (id INTEGER PRIMARY KEY, nome TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS regras_categoria (
  id INTEGER PRIMARY KEY, padrao TEXT NOT NULL,
  categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
  prioridade INTEGER NOT NULL DEFAULT 100
);
CREATE TABLE IF NOT EXISTS categoria_manual (
  cnpj TEXT NOT NULL, codigo TEXT NOT NULL,
  categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE,
  PRIMARY KEY (cnpj, codigo)
);
CREATE TABLE IF NOT EXISTS regras_loja (
  cnpj TEXT PRIMARY KEY,
  categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS categoria_descricao (
  descricao_norm TEXT PRIMARY KEY,
  categoria_id INTEGER NOT NULL REFERENCES categorias(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS produtos (
  id INTEGER PRIMARY KEY,
  nome TEXT UNIQUE NOT NULL,
  tipo TEXT NOT NULL,
  tamanho TEXT,
  venda TEXT NOT NULL DEFAULT 'UN' CHECK (venda IN ('UN','KG'))
);
CREATE TABLE IF NOT EXISTS produto_vinculo (
  cnpj TEXT NOT NULL,
  codigo TEXT NOT NULL,
  produto_id INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
  origem TEXT NOT NULL CHECK (origem IN ('manual','auto')),
  PRIMARY KEY (cnpj, codigo)
);
CREATE TABLE IF NOT EXISTS produto_ignorado (
  cnpj TEXT NOT NULL,
  codigo TEXT NOT NULL,
  PRIMARY KEY (cnpj, codigo)
);
CREATE TABLE IF NOT EXISTS produto_rejeitado (
  cnpj TEXT NOT NULL,
  codigo TEXT NOT NULL,
  produto_id INTEGER NOT NULL REFERENCES produtos(id) ON DELETE CASCADE,
  PRIMARY KEY (cnpj, codigo, produto_id)
);
"""


def conectar(caminho: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(caminho), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn


def _agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Repositorio:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def importar_resumos(self, resumos: list[NotaResumo]) -> dict[str, int]:
        novas = existentes = nfe = 0
        agora = _agora()
        with self.conn:
            for r in resumos:
                if r.modelo == 55:
                    nfe += 1
                self.conn.execute(
                    """INSERT INTO estabelecimentos (cnpj, nome_csv, municipio) VALUES (?,?,?)
                       ON CONFLICT(cnpj) DO UPDATE SET
                         nome_csv = COALESCE(estabelecimentos.nome_csv, excluded.nome_csv),
                         municipio = COALESCE(estabelecimentos.municipio, excluded.municipio)""",
                    (r.cnpj_emitente, r.nome_csv, r.municipio),
                )
                existia = self.conn.execute(
                    "SELECT 1 FROM notas WHERE chave = ?", (r.chave,)).fetchone() is not None
                self.conn.execute(
                    """INSERT INTO notas (chave, modelo, cnpj_emitente, numero, emissao,
                         valor_total_centavos, situacao_csv, tipo_operacao, status, importada_em)
                       VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(chave) DO UPDATE SET
                         situacao_csv = excluded.situacao_csv,
                         tipo_operacao = excluded.tipo_operacao""",
                    (
                        r.chave, r.modelo, r.cnpj_emitente, r.numero, r.emissao.isoformat(),
                        to_centavos(r.valor_total), r.situacao, r.tipo_operacao,
                        "pendente" if r.modelo == 65 else "sem_itens", agora,
                    ),
                )
                if existia:
                    existentes += 1
                else:
                    novas += 1
        return {"novas": novas, "existentes": existentes, "nfe": nfe}

    def pendentes(self, max_tentativas: int = 3) -> list[str]:
        rows = self.conn.execute(
            """SELECT chave FROM notas
               WHERE modelo = 65 AND (status = 'pendente' OR (status = 'erro' AND tentativas < ?))
                 AND (tipo_operacao IS NULL OR tipo_operacao = 'Aquisição')
                 AND (situacao_csv IS NULL OR situacao_csv = 'Normal')
               ORDER BY emissao, chave""",
            (max_tentativas,),
        ).fetchall()
        return [r["chave"] for r in rows]

    def salvar_nota(self, nota: Nota, aviso: str | None = None) -> None:
        e = nota.emitente
        with self.conn:
            self.conn.execute(
                """INSERT INTO estabelecimentos (cnpj, razao_social, inscricao_estadual, endereco, municipio)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(cnpj) DO UPDATE SET
                     razao_social = excluded.razao_social,
                     inscricao_estadual = excluded.inscricao_estadual,
                     endereco = excluded.endereco,
                     municipio = COALESCE(excluded.municipio, estabelecimentos.municipio)""",
                (e.cnpj, e.razao_social, e.inscricao_estadual, e.endereco, e.municipio),
            )
            agora = _agora()
            self.conn.execute(
                """INSERT INTO notas (chave, modelo, cnpj_emitente, numero, serie, emissao,
                     valor_total_centavos, valor_descontos_centavos, protocolo, status,
                     erro_msg, aviso, importada_em, coletada_em)
                   VALUES (?,?,?,?,?,?,?,?,?, 'coletada', NULL, ?, ?, ?)
                   ON CONFLICT(chave) DO UPDATE SET
                     modelo = excluded.modelo,
                     cnpj_emitente = excluded.cnpj_emitente,
                     numero = excluded.numero,
                     serie = excluded.serie,
                     emissao = excluded.emissao,
                     valor_total_centavos = excluded.valor_total_centavos,
                     valor_descontos_centavos = excluded.valor_descontos_centavos,
                     protocolo = excluded.protocolo,
                     status = 'coletada',
                     erro_msg = NULL,
                     aviso = excluded.aviso,
                     coletada_em = excluded.coletada_em""",
                (
                    nota.chave, nota.modelo, e.cnpj, nota.numero, nota.serie,
                    nota.emissao.isoformat(timespec="seconds"),
                    to_centavos(nota.valor_total), to_centavos(nota.valor_descontos),
                    nota.protocolo, aviso, agora, agora,
                ),
            )
            self.conn.execute("DELETE FROM itens WHERE chave = ?", (nota.chave,))
            self.conn.execute("DELETE FROM pagamentos WHERE chave = ?", (nota.chave,))
            self.conn.executemany(
                """INSERT INTO itens (chave, seq, codigo, descricao, quantidade, unidade,
                     valor_unitario, valor_total_centavos) VALUES (?,?,?,?,?,?,?,?)""",
                [
                    (nota.chave, i.seq, i.codigo, i.descricao, str(i.quantidade), i.unidade,
                     str(i.valor_unitario), to_centavos(i.valor_total))
                    for i in nota.itens
                ],
            )
            self.conn.executemany(
                "INSERT INTO pagamentos (chave, forma, valor_centavos) VALUES (?,?,?)",
                [(nota.chave, p.forma, to_centavos(p.valor)) for p in nota.pagamentos],
            )

    def registrar_erro(self, chave: str, mensagem: str, definitivo: bool) -> None:
        with self.conn:
            self.conn.execute(
                """UPDATE notas SET status = 'erro', erro_msg = ?,
                     tentativas = CASE WHEN ? THEN 3 ELSE tentativas + 1 END
                   WHERE chave = ?""",
                (mensagem, 1 if definitivo else 0, chave),
            )

    def reabrir(self, chave: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE notas SET status = 'pendente', tentativas = 0, erro_msg = NULL WHERE chave = ?",
                (chave,),
            )

    def contagem_status(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT status, COUNT(*) AS n FROM notas GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    def itens_da_nota(self, chave: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM itens WHERE chave = ? ORDER BY seq", (chave,)).fetchall()

    def pagamentos_da_nota(self, chave: str) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM pagamentos WHERE chave = ? ORDER BY id", (chave,)).fetchall()
