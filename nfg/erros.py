class ErroNFG(Exception):
    """Erro base do NFG Compras."""


class ErroRede(ErroNFG):
    pass


class NotaNaoEncontrada(ErroNFG):
    pass


class LayoutDesconhecido(ErroNFG):
    pass


class BloqueioSefaz(ErroNFG):
    pass


class CSVInvalido(ErroNFG):
    pass
