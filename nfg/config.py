from __future__ import annotations

import os
from pathlib import Path

from nfg.categorias import garantir_seed, migrar
from nfg.db import Repositorio, conectar


def data_dir() -> Path:
    env = os.environ.get("NFG_DATA_DIR")
    d = Path(env) if env else Path(__file__).resolve().parent.parent / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def html_dir() -> Path:
    d = data_dir() / "html_bruto"
    d.mkdir(parents=True, exist_ok=True)
    return d


def abrir_repo() -> Repositorio:
    repo = Repositorio(conectar(data_dir() / "nfg.db"))
    garantir_seed(repo.conn)
    migrar(repo.conn)
    return repo
