import re
from datetime import datetime
from decimal import Decimal

import pytest

from nfg.erros import BloqueioSefaz, LayoutDesconhecido, NotaNaoEncontrada
from nfg.models import Item, Pagamento
from nfg.nfce_parser import parse


@pytest.fixture
def html(fixtures_dir):
    return (fixtures_dir / "nfce_zaffari.html").read_text("utf-8")


def test_cabecalho(html):
    n = parse(html)
    assert n.chave == "43260993015006000547651210003414481604643989" and n.modelo == 65
    e = n.emitente
    assert (e.razao_social, e.cnpj, e.inscricao_estadual) == ("COMPANHIA ZAFFARI COMERCIO E INDUSTRIA", "93015006000547", "0963144057")
    assert e.endereco == "AV SERTÓRIO, 8000, SARANDI, PORTO ALEGRE, RS" and e.municipio == "PORTO ALEGRE"
    assert (n.numero, n.serie, n.protocolo) == ("341448", "121", "143260000000002")
    assert n.emissao == datetime(2026, 9, 26, 17, 35, 15)


def test_itens(html):
    n = parse(html)
    assert len(n.itens) == 18
    assert n.itens[0] == Item(1, "000000000001069007", "FILE PTO FGO NAT DESF CG 400G", Decimal("1"), "UN", Decimal("21.8"), Decimal("21.80"))
    assert (n.itens[5].quantidade, n.itens[5].unidade) == (Decimal("0.9399"), "KG")
    assert [i.descricao for i in n.itens[14:16]] == ["BANANA PRATA GRANEL"] * 2
    assert sum(i.valor_total for i in n.itens) == Decimal("382.47")


def test_totais_e_pagamento(html):
    n = parse(html)
    assert (n.valor_total, n.valor_descontos) == (Decimal("382.47"), Decimal("0.00"))
    assert n.pagamentos == [Pagamento("Cartão de Crédito", Decimal("382.47"))]
    assert "000.000.000-00" not in repr(n)


def test_html_bruto_do_servidor(html):               # Review Focus 1
    bruto = re.sub(r"</?tbody>", "", html).replace("382,47</td>", "382,47&nbsp;</td>")
    bruto = bruto.replace("<td", "\n  <td").encode("iso-8859-1").decode("iso-8859-1")
    assert parse(bruto) == parse(html)


def test_rejeicao():
    with pytest.raises(NotaNaoEncontrada):
        parse("<html><body><div id='nfce'>NFC-e não encontrada na base de dados da SEFAZ</div></body></html>")


def test_layout_desconhecido():
    with pytest.raises(LayoutDesconhecido):
        parse("<html><body><p>Bem-vindo</p></body></html>")


def test_captcha():
    with pytest.raises(BloqueioSefaz):
        parse("<html><body><div class='g-recaptcha'></div></body></html>")


def test_erro_transitorio_nao_e_nota_inexistente():
    with pytest.raises(LayoutDesconhecido):
        parse("<html><body>Erro interno no servidor. Tente novamente.</body></html>")


def test_script_captcha_em_pagina_valida(html):
    h = html.replace("</body>", '<script src="https://www.google.com/recaptcha/api.js"></script></body>')
    assert len(parse(h).itens) == 18


def test_troco_nao_e_pagamento(html):
    linha = '<tr><td class="NFCDetalhe_Item">Troco R$</td><td class="NFCDetalhe_Item">0,00</td></tr>'
    h = html.replace("</tbody></table>\n                </td>\n              </tr>\n              <tr>\n                <td class=\"borda-pontilhada-botton NFCDetalhe_Item \"", linha + "</tbody></table>\n                </td>\n              </tr>\n              <tr>\n                <td class=\"borda-pontilhada-botton NFCDetalhe_Item \"")
    assert h != html
    assert parse(h).pagamentos == parse(html).pagamentos


def test_desconto_valor_total_e_valor_pago(html):
    from nfg.coleta import validar_totais
    h = html.replace("<td class=\"NFCDetalhe_Item\" align=\"right\" style=\"width: 70px;\">0,00</td>",
                     "<td class=\"NFCDetalhe_Item\" align=\"right\" style=\"width: 70px;\">40,00</td>", 1)
    h = h.replace("Cartão de Crédito</td>\n                      <td class=\"NFCDetalhe_Item\" align=\"right\" style=\"width: 70px;\">382,47",
                  "Cartão de Crédito</td>\n                      <td class=\"NFCDetalhe_Item\" align=\"right\" style=\"width: 70px;\">342,47")
    assert h != html
    n = parse(h)
    assert n.valor_total == Decimal("342.47") and n.valor_descontos == Decimal("40.00")
    assert n.pagamentos[0].valor == Decimal("342.47")
    assert validar_totais(n) is None


def _com_valor_a_pagar(html, valor):
    linha = ('<tr><td class="NFCDetalhe_Item" align="left">Valor a pagar R$</td>'
             f'<td class="NFCDetalhe_Item" align="right">{valor}</td></tr>')
    h = re.sub(r"(<tr>\s*<td[^>]*>FORMA PAGAMENTO)", lambda m: linha + m.group(1), html, count=1)
    assert h != html
    return h


def test_sem_linha_de_descontos_vale_zero(html):
    h = re.sub(r"<tr>\s*<td[^>]*>Valor descontos R\$</td>\s*<td[^>]*>[^<]*</td>\s*</tr>", "", html)
    assert h != html
    n = parse(h)
    assert n.valor_descontos == Decimal("0") and n.valor_total == Decimal("382.47")


def test_valor_a_pagar_presente_prevalece(html):
    assert parse(_com_valor_a_pagar(html, "300,00")).valor_total == Decimal("300.00")


def test_valor_a_pagar_malformado_levanta(html):
    with pytest.raises(LayoutDesconhecido):
        parse(_com_valor_a_pagar(html, "abc"))
