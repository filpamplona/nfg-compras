import os

import pytest

from nfg.nfce_parser import parse
from nfg.sefaz_client import SefazClient

# Chave de uma NFC-e real sua, informada por variável de ambiente para não
# publicar chaves reais no repositório (a página da SEFAZ mostra o CPF).
CHAVE = os.environ.get("NFG_CHAVE_ONLINE", "").replace(" ", "")


@pytest.mark.online
@pytest.mark.skipif(not CHAVE, reason="defina NFG_CHAVE_ONLINE com a chave de uma NFC-e real")
def test_consulta_real():
    nota = parse(SefazClient().buscar(CHAVE))
    assert nota.chave == CHAVE
    assert nota.itens and nota.valor_total > 0
