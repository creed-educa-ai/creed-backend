"""Regra de negócio do domínio forms

Esta camada não conhece HTTP nem detalhes de ORM. É onde a lógica vive,
isolada e testável.
"""

from app.domains.forms.repository import FormRepository


class FormService:
    def __init__(self, repository: FormRepository) -> None:
        self.repository = repository
