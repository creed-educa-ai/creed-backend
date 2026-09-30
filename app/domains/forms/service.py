"""Regra de negócio do domínio forms

Esta camada não conhece HTTP nem detalhes de ORM. É onde a lógica vive,
isolada e testável.

O formulário pertence a uma organização, e é aqui que mora a regra de quem age
em qual organização. `questions` (`check_organization`, P-033) e `responses`
(`check_same_organization`, P-031) a usam pela composição, em vez de repetir a
comparação.
"""

import uuid

from app.domains.forms.models import Form, FormStatus
from app.domains.forms.repository import FormRepository
from app.domains.forms.schemas import FormCreate
from app.shared.exceptions import ForbiddenError, NotFoundError

ADMIN = "admin"


class FormService:
    def __init__(self, repository: FormRepository) -> None:
        self.repository = repository

    async def create(
        self, request: FormCreate, *, role: str, organization_id: uuid.UUID
    ) -> Form:
        """`role` e `organization_id` são de quem pede, não do formulário."""
        self.check_organization(
            request.organization_id, role=role, organization_id=organization_id
        )

        form = Form(
            name=request.name,
            organization_id=request.organization_id,
            status=FormStatus.DRAFT,
        )
        return await self.repository.create(form)

    async def get(self, form_id: uuid.UUID) -> Form:
        """Só "existe?". Sem regra de acesso: é o que os outros domínios usam."""
        form = await self.repository.get_by_id(form_id)

        if form is None:
            raise NotFoundError(f"Formulário {form_id} não encontrado")

        return form

    async def get_for_user(
        self, form_id: uuid.UUID, *, role: str, organization_id: uuid.UUID
    ) -> Form:
        """O formulário, se quem pede pode vê-lo: 404 antes de 403."""
        form = await self.get(form_id)
        self.check_organization(
            form.organization_id, role=role, organization_id=organization_id
        )
        return form

    def check_organization(
        self,
        form_organization_id: uuid.UUID,
        *,
        role: str,
        organization_id: uuid.UUID,
    ) -> None:
        """Levanta `ForbiddenError` se quem pede não pode agir nessa organização.

        🟡 Premissa P-033 — o `admin` age em qualquer organização; `gestor` e
        `respondente`, só na do próprio vínculo. Confirmar na próxima reunião.
        """
        if role == ADMIN or form_organization_id == organization_id:
            return

        raise ForbiddenError("Sem acesso a formulário de outra organização")

    def check_same_organization(
        self, form_organization_id: uuid.UUID, *, organization_id: uuid.UUID
    ) -> None:
        """Como `check_organization`, mas sem exceção para o `admin`.

        É a regra de quem responde (P-031): a resposta sai com o vínculo do login,
        e o vínculo tem uma organização só, qualquer que seja o papel.
        """
        if form_organization_id != organization_id:
            raise ForbiddenError("Sem acesso a formulário de outra organização")
