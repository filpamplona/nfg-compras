import pytest
import requests
import responses

from nfg.erros import BloqueioSefaz, ErroRede
from nfg.sefaz_client import URL_ETAPA1, URL_ETAPA2, SefazClient

CH = "43260993015006000547651210003414481604643989"


@responses.activate
def test_get_depois_post_com_form_correto():
    responses.get(URL_ETAPA1, body="form")
    responses.post(URL_ETAPA2, body="<html>Cartão</html>".encode("iso-8859-1"))
    html = SefazClient(sleep=lambda s: None).buscar(CH)
    assert "Cartão" in html
    assert [c.request.method for c in responses.calls] == ["GET", "POST"]
    assert f"chaveNFe={CH}" in responses.calls[0].request.url
    corpo = responses.calls[1].request.body
    assert responses.calls[1].request.headers["Referer"] == URL_ETAPA1
    assert f"chaveNFe={CH}" in corpo and "HML=false" in corpo and "Action=Avan%E7ar" in corpo


@responses.activate
def test_retry_em_5xx_e_desiste():
    responses.get(URL_ETAPA1, body="form")
    responses.post(URL_ETAPA2, status=503)
    with pytest.raises(ErroRede):
        SefazClient(sleep=lambda s: None).buscar(CH)
    assert sum(c.request.method == "POST" for c in responses.calls) == 3


@responses.activate
def test_retry_recupera():
    responses.get(URL_ETAPA1, body="form")
    responses.post(URL_ETAPA2, body=requests.ConnectionError())
    responses.post(URL_ETAPA2, body="<html>ok</html>")
    assert "ok" in SefazClient(sleep=lambda s: None).buscar(CH)


@pytest.mark.parametrize("status", [403, 429])
@responses.activate
def test_bloqueio(status):
    responses.get(URL_ETAPA1, body="form")
    responses.post(URL_ETAPA2, status=status)
    with pytest.raises(BloqueioSefaz):
        SefazClient(sleep=lambda s: None).buscar(CH)
    assert sum(c.request.method == "POST" for c in responses.calls) == 1


@responses.activate
def test_4xx_nao_retentavel_falha_sem_retry():
    responses.get(URL_ETAPA1, body="form")
    responses.post(URL_ETAPA2, status=404)
    with pytest.raises(ErroRede):
        SefazClient(sleep=lambda s: None).buscar(CH)
    assert sum(c.request.method == "POST" for c in responses.calls) == 1


@responses.activate
def test_backoffs_usados_entre_tentativas():
    responses.get(URL_ETAPA1, body="form")
    responses.post(URL_ETAPA2, status=503)
    dormidos = []
    with pytest.raises(ErroRede):
        SefazClient(sleep=dormidos.append).buscar(CH)
    assert dormidos == [2, 5]


@responses.activate
def test_bloqueio_na_etapa1():
    responses.get(URL_ETAPA1, status=429)
    with pytest.raises(BloqueioSefaz):
        SefazClient(sleep=lambda s: None).buscar(CH)


@responses.activate
def test_excecao_requests_nao_retentavel_vira_erro_rede():
    responses.get(URL_ETAPA1, body="form")
    responses.post(URL_ETAPA2, body=requests.TooManyRedirects())
    with pytest.raises(ErroRede):
        SefazClient(sleep=lambda s: None).buscar(CH)
    assert sum(c.request.method == "POST" for c in responses.calls) == 1


@responses.activate
def test_chunked_encoding_error_e_retentavel():
    responses.get(URL_ETAPA1, body="form")
    responses.post(URL_ETAPA2, body=requests.exceptions.ChunkedEncodingError())
    responses.post(URL_ETAPA2, body="<html>ok</html>")
    assert "ok" in SefazClient(sleep=lambda s: None).buscar(CH)
