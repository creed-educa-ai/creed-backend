"""Falhas do N8N que quem chama o client precisa distinguir (CREED-803).

Uma só por enquanto: para o worker da CREED-804, todo erro de entrega significa a
mesma coisa (nova tentativa com espera). A segunda exceção nasce quando alguém
precisar tratar um caso diferente (playbook `integrar-servico-externo.md`, passo 3).
"""

from app.shared.exceptions import ServiceUnavailableError


class N8NUnavailableError(ServiceUnavailableError):
    """O N8N não recebeu o pedido: fora do ar, lento demais ou respondeu com erro.

    A mensagem vai para o log e para o `last_error` do insight, nunca para a tela.
    """
