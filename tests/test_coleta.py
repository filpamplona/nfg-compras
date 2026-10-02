from dataclasses import replace
from decimal import Decimal

from nfg.coleta import anexar_xml, coletar, reprocessar_html, validar_totais
from nfg.erros import BloqueioSefaz, ErroRede

Z = "43260993015006000547651210003414481604643989"


class ClienteFalso:
    def __init__(self, respostas):
        self.respostas = respostas

    def buscar(self, chave):
        r = self.respostas[chave]
        if isinstance(r, Exception):
            raise r
        return r


def test_lote_misto(repo_csv, html_zaffari, tmp_path):
    z = Z
    outras = [c for c in repo_csv.pendentes() if c != z]
    respostas = {z: html_zaffari, outras[0]: ErroRede("timeout"),
                 outras[1]: "<html><body>NFC-e não encontrada</body></html>"}
    respostas |= {c: "<html><body><p>x</p></body></html>" for c in outras[2:]}
    eventos, pausas = [], []
    r = coletar(repo_csv, ClienteFalso(respostas), tmp_path, eventos.append, sleep=pausas.append)
    assert (r.coletadas, r.erros, r.interrompido) == (1, 9, False)
    assert len(eventos) == 10 and len(pausas) == 9
    assert any(e.ok and "18 itens" in e.mensagem for e in eventos)
    assert (tmp_path / f"{z}.html").exists()
    assert "000.000.000-00" in (tmp_path / f"{z}.html").read_text("utf-8")
    assert outras[0] in repo_csv.pendentes() and outras[1] not in repo_csv.pendentes()
    tent = lambda c: repo_csv.conn.execute("select tentativas from notas where chave=?", (c,)).fetchone()[0]
    assert tent(outras[0]) == 1 and tent(outras[1]) == 3 and tent(outras[2]) == 1


def test_bloqueio_interrompe(repo_csv, tmp_path):
    respostas = {c: BloqueioSefaz("403") for c in repo_csv.pendentes()}
    chamadas, pausas = [], []

    class Cont(ClienteFalso):
        def buscar(self, chave):
            chamadas.append(chave)
            return super().buscar(chave)

    primeira = repo_csv.pendentes()[0]
    r = coletar(repo_csv, Cont(respostas), tmp_path, sleep=pausas.append)
    assert r.interrompido and r.erros == 1 and "403" in r.motivo
    assert chamadas == [primeira] and pausas == []
    assert primeira in repo_csv.pendentes()
    row = repo_csv.conn.execute("select status, tentativas from notas where chave=?", (primeira,)).fetchone()
    assert (row[0], row[1]) == ("pendente", 0)


def test_chave_divergente_nao_grava(repo_csv, html_zaffari, tmp_path):
    outra = [c for c in repo_csv.pendentes() if c != Z][0]
    coletar(repo_csv, ClienteFalso({c: html_zaffari for c in repo_csv.pendentes()}), tmp_path,
            sleep=lambda s: None)
    assert repo_csv.conn.execute("select status from notas where chave=?", (outra,)).fetchone()[0] == "erro"
    assert not (tmp_path / f"{outra}.html").exists()


def test_reprocessar(repo_csv, html_zaffari, tmp_path):
    (tmp_path / f"{Z}.html").write_text(html_zaffari, "utf-8")
    assert reprocessar_html(repo_csv, tmp_path).coletadas == 1


def test_anexar_xml_completa_nfe(repo_csv, fixtures_dir):
    nota = anexar_xml(repo_csv, (fixtures_dir / "nfe_exemplo.xml").read_bytes())
    row = repo_csv.conn.execute("select status from notas where chave=?", (nota.chave,)).fetchone()
    assert row[0] == "coletada" and len(repo_csv.itens_da_nota(nota.chave)) == 2


def test_validar_totais(nota_zaffari):
    assert validar_totais(nota_zaffari) is None
    assert "soma" in validar_totais(replace(nota_zaffari, valor_total=Decimal("400.00"))).lower()


def test_reprocessar_nao_rebaixa_coletada(repo, nota_zaffari, tmp_path):
    repo.salvar_nota(nota_zaffari)
    (tmp_path / f"{nota_zaffari.chave}.html").write_text("<html>lixo</html>", "utf-8")
    r = reprocessar_html(repo, tmp_path)
    assert r.erros == 1 and r.coletadas == 0
    assert repo.conn.execute("select status from notas where chave=?", (nota_zaffari.chave,)).fetchone()[0] == "coletada"


def test_soma_divergente_salva_com_aviso(repo_csv, html_zaffari, tmp_path):
    html = html_zaffari.replace('width: 70px;">382,47', 'width: 70px;">400,00', 1)
    assert html != html_zaffari
    r = coletar(repo_csv, ClienteFalso({c: html for c in repo_csv.pendentes()}), tmp_path, sleep=lambda s: None)
    assert r.coletadas == 1
    row = repo_csv.conn.execute("select status, aviso from notas where chave=?", (Z,)).fetchone()
    assert row[0] == "coletada" and row[1]


def test_validar_totais_ignora_nfe(nota_zaffari):
    nfe = replace(nota_zaffari, modelo=55, valor_total=Decimal("999.00"))
    assert validar_totais(nfe) is None
