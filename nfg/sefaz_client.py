"""Cliente HTTP da consulta pública de NFC-e da SEFAZ-RS."""
import time
from typing import Callable

import requests

from nfg.erros import BloqueioSefaz, ErroRede

URL_ETAPA1 = "https://www.sefaz.rs.gov.br/ASP/AAE_ROOT/NFE/SAT-WEB-NFE-NFC_1.asp"
URL_ETAPA2 = "https://www.sefaz.rs.gov.br/ASP/AAE_ROOT/NFE/SAT-WEB-NFE-NFC_2.asp"
USER_AGENT = "NFG-Compras/1.0 (uso pessoal)"


class _Tentar(Exception):
    """Falha transitória: vale a pena tentar de novo."""


class SefazClient:
    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: float = 20,
        backoffs: tuple[float, ...] = (2, 5),
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.timeout = timeout
        self.backoffs = backoffs
        self._sleep = sleep

    def buscar(self, chave: str) -> str:
        total = 1 + len(self.backoffs)
        ultimo: Exception | None = None
        for i in range(total):
            try:
                return self._tentar(chave)
            except _Tentar as e:
                ultimo = e
                if i < len(self.backoffs):
                    self._sleep(self.backoffs[i])
        raise ErroRede(f"Falha ao consultar a SEFAZ após {total} tentativas: {ultimo}") from ultimo

    def _checar(self, resp: requests.Response) -> None:
        if resp.status_code in (403, 429):
            raise BloqueioSefaz(f"SEFAZ bloqueou a consulta (HTTP {resp.status_code})")
        if resp.status_code >= 500:
            raise _Tentar(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise ErroRede(f"SEFAZ respondeu HTTP {resp.status_code}")

    def _tentar(self, chave: str) -> str:
        try:
            r1 = self.session.get(URL_ETAPA1, params={"chaveNFe": chave}, timeout=self.timeout)
            self._checar(r1)
            r2 = self.session.post(
                URL_ETAPA2,
                data={
                    "HML": "false",
                    "chaveNFe": chave,
                    "Action": "Avançar".encode("iso-8859-1"),
                },
                headers={"Referer": URL_ETAPA1},
                timeout=self.timeout,
            )
            self._checar(r2)
        except (
            requests.ConnectionError,
            requests.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ) as e:
            raise _Tentar(str(e)) from e
        except requests.RequestException as e:
            raise ErroRede(f"Erro na requisição à SEFAZ: {e}") from e
        return r2.content.decode("iso-8859-1")
