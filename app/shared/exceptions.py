"""Exceções de domínio, traduzidas para HTTP na borda (router).

Os services levantam estas exceções sem conhecer HTTP — a separação de
camadas do ADR-002 (secao 2.2) exige que o service não saiba o que é status code.
"""


class DomainError(Exception):
    """Base de todos os erros de domínio."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class NotFoundError(DomainError):
    """Recurso não encontrado. Traduzido para 404 no router."""


class ValidationError(DomainError):
    """Regra de negócio violada. Traduzido para 422 no router."""


class ConflictError(DomainError):
    """Conflito de estado (ex: duplicidade). Traduzido para 409 no router."""


class AuthenticationError(DomainError):
    """Login ou renovação de sessão falhou. Traduzido para 401 no router."""
