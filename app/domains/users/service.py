"""Regra de negócio do domínio users (ADR-002, secao 2.2).

Esta camada não conhece HTTP nem detalhes de ORM. É onde a lógica vive,
isolada e testável — o mesmo padrão que os dashboards usarão para o
cálculo dos 5 prismas (ADR-001, secao 4.1).

`users` conversa com `links` só pelo `LinkService`, injetado (spec da
CREED-32, "Abordagem técnica", item 8) — nunca com `LinkRepository` nem com
`Link` direto, que manteria o acoplamento na tabela e não no contrato do
domínio dono.

Com o Keycloak, a conversa é pela Admin API (`keycloak_admin`), chamada como o
`AuthenticationService` chama o `client.py`: as exceções de lá viram exceções de
domínio aqui, e o router traduz para status.
"""

import logging
import uuid
from dataclasses import dataclass

from app.domains.links.service import LinkService
from app.domains.organizacoes.service import OrganizationService
from app.domains.participants.service import ParticipantService
from app.domains.users.models import User
from app.domains.users.repository import UserRepository
from app.domains.users.schemas import MemberInvite, UserCreate
from app.external_services.keycloak import admin as keycloak_admin
from app.external_services.keycloak.client import KeycloakUnavailableError
from app.shared.enums import RecordStatus, Roles
from app.shared.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)

_CREATE_UNAVAILABLE = "Não foi possível criar o acesso agora. Tente de novo."
_DELETE_UNAVAILABLE = "Não foi possível remover o acesso agora. Tente de novo."
_INVITATION_UNAVAILABLE = "Não foi possível reenviar o convite agora. Tente de novo."
_RESET_EMAIL_UNAVAILABLE = (
    "Não foi possível enviar o e-mail de redefinição agora. Tente de novo."
)


@dataclass
class CreatedUser:
    """O que o router precisa para montar o `UserResponse` do cadastro.

    `role` e `organization_id` vêm do `Link` que o service já consultou
    para validar o cadastro — não faz sentido o router buscá-los de novo.
    """

    user: User
    role: str
    organization_id: uuid.UUID


@dataclass
class UserAccess:
    """O que a guarda e o login precisam saber sobre um login autenticado.

    `role` e `organization_id` são os do vínculo: `user` não guarda papel.
    """

    id: uuid.UUID
    email: str
    role: str
    link_id: uuid.UUID
    organization_id: uuid.UUID


class UserService:
    def __init__(self, repository: UserRepository, links: LinkService) -> None:
        self.repository = repository
        self.links = links

    async def get_active_user_access_by_email(self, email: str) -> UserAccess | None:
        """O que a guarda e o login usam para saber quem está logado.

        `None` cobre usuário inexistente, inativo, e `link_id` que o
        `LinkService` não encontra — a guarda e o login tratam os três como
        "sem acesso" (401), sem distinguir. Usuário sem `link_id` não existe:
        a coluna é `NOT NULL`.
        """
        user = await self.repository.get_user_by_email(email)

        if user is None or user.status is not RecordStatus.ACTIVE:
            return None

        link = await self.links.get_link_by_id_service(user.link_id)
        if link is None:
            return None

        return UserAccess(
            id=user.id,
            email=user.email,
            role=link.role.value,
            link_id=user.link_id,
            organization_id=link.organization_id,
        )

    async def create_user_service(self, request: UserCreate) -> CreatedUser:
        """Cria o acesso no banco e no Keycloak e manda o convite. Tudo ou nada (D7).

        A ordem importa. O que só depende do banco é conferido antes de tocar no
        Keycloak, para um 409 ou 404 não deixar rastro no realm. O e-mail sai por
        último, quando o INSERT já passou pelo flush: convite enviado é acesso que
        existe. Se algo falha depois de o usuário existir no realm, ele é apagado lá
        e o erro segue até o `get_db`, que desfaz o banco. Não há commit aqui: quem
        fecha a transação é a requisição (CREED-364).
        """
        # O Keycloak guarda o e-mail em minúsculas, e o login acha o usuário do banco
        # pelo e-mail do token. Gravado como veio ("Pessoa@..."), o acesso nasceria
        # sem conseguir entrar nunca.
        email = request.email.lower()

        already_exists = await self.repository.get_user_by_email(email)

        if already_exists is not None:
            raise ConflictError(f"Já existe usuário com o e-mail {email}")

        link = await self.links.get_link_by_id_service(request.link_id)
        if link is None:
            raise NotFoundError(f"Vínculo {request.link_id} não encontrado")

        link_in_use = await self.repository.get_by_link_id(request.link_id)
        if link_in_use is not None:
            raise ConflictError(f"Vínculo {request.link_id} já está em uso")

        try:
            keycloak_id = await keycloak_admin.create_user(email)
        except keycloak_admin.KeycloakConflictError as exc:
            # O e-mail não está no banco, mas está no realm: um acesso criado à mão,
            # ou um que sobrou de uma falha. Não é reaproveitado (spec, D7).
            raise ConflictError(f"Já existe acesso com o e-mail {email}") from exc
        except KeycloakUnavailableError as exc:
            # Sem o id, não há o que desfazer. Num timeout de leitura, o realm pode ter
            # criado o usuário mesmo assim: ele sobra lá, e a nova tentativa dá 409 até
            # a limpeza manual, como na compensação que falha.
            raise ServiceUnavailableError(_CREATE_UNAVAILABLE) from exc

        try:
            # O papel do token é a cópia do papel do vínculo (decisão D4): a guarda
            # compara os dois a cada requisição.
            await keycloak_admin.assign_realm_role(keycloak_id, link.role.value)

            # `status` é decisão de produto (P-013), então mora aqui e não no model
            # — ADR-0004: "se muda quando o produto muda de ideia, é service". O
            # default do model é só a rede para quem construir um User por outro
            # caminho; em conflito, esta linha é a que vale.
            user = User(
                keycloak_id=keycloak_id,
                name=request.name,
                email=email,
                status=RecordStatus.ACTIVE,
                link_id=request.link_id,
            )
            created = await self.repository.create(user)

            await keycloak_admin.send_update_password_email(keycloak_id)
        except KeycloakUnavailableError as exc:
            await self._remove_from_keycloak_after_failure(keycloak_id)
            raise ServiceUnavailableError(_CREATE_UNAVAILABLE) from exc
        except Exception:
            # Amplo de propósito: qualquer falha depois de o usuário existir no realm
            # tem que desfazê-lo lá, senão o e-mail fica preso em 409. Na prática, é o
            # INSERT que o banco recusa no flush. Nada é engolido: o `raise` devolve o
            # erro original, o mesmo de antes de o Keycloak entrar aqui.
            await self._remove_from_keycloak_after_failure(keycloak_id)
            raise

        return CreatedUser(
            user=created, role=link.role.value, organization_id=link.organization_id
        )

    async def _remove_from_keycloak_after_failure(self, keycloak_id: uuid.UUID) -> None:
        """Desfaz o usuário do realm. Falhar aqui não troca o erro que trouxe até aqui.

        Se o Keycloak cair entre a criação e esta chamada, o usuário fica no realm
        sem linha no banco, e o e-mail dele passa a dar 409. O log é o que permite
        apagá-lo à mão.
        """
        try:
            await keycloak_admin.delete_user(keycloak_id)
        except KeycloakUnavailableError:
            logger.error(
                "Usuário %s ficou no Keycloak sem linha no banco; apague-o no console",
                keycloak_id,
            )

    async def delete_user_service(self, user_id: uuid.UUID) -> None:
        user = await self.repository.get_by_id(user_id)

        if user is None:
            raise NotFoundError(f"Usuário {user_id} não encontrado")

        # Banco primeiro, Keycloak depois. O delete do banco só vira definitivo no
        # commit, ao fim da requisição: se o Keycloak falhar, o erro faz o `get_db`
        # desfazer o delete, e o usuário continua no banco. Num timeout em que o realm
        # já apagou, ele sai só de lá; repetir a remoção resolve, porque o 404 do realm
        # é sucesso. Na ordem contrária, um flush que falhasse deixaria uma linha no
        # banco apontando para um usuário que o realm já apagou.
        keycloak_id = user.keycloak_id
        await self.repository.delete(user)

        try:
            await keycloak_admin.delete_user(keycloak_id)
        except KeycloakUnavailableError as exc:
            raise ServiceUnavailableError(_DELETE_UNAVAILABLE) from exc

    async def resend_invitation_service(
        self, user_id: uuid.UUID, *, role: str, own_organization_id: uuid.UUID
    ) -> None:
        """Manda de novo o e-mail do convite.

        `role` e `own_organization_id` são de quem pede. É o mesmo e-mail do convite e
        da redefinição de senha: para quem já definiu a senha, o link vira uma
        redefinição, e isso é aceito (spec, D10).
        """
        user = await self.repository.get_by_id(user_id)
        not_found_message = f"Usuário {user_id} não encontrado"

        if user is None:
            raise NotFoundError(not_found_message)

        # 🟡 Premissa P-045 — o gestor reenvia só para quem é da organização dele.
        # Usuário de outra organização é 404, como o inexistente, e com a mesma
        # mensagem: dizer "existe, mas não é seu" vaza cadastro alheio (decisão 4 do
        # contrato da CREED-23). A organização é a do vínculo do usuário.
        # 🟡 Premissa P-058 — o reenvio não olha o papel nem o status do acesso.
        if role != Roles.ADMIN.value:
            link = await self.links.get_link_by_id_service(user.link_id)
            if link is None or link.organization_id != own_organization_id:
                raise NotFoundError(not_found_message)

        try:
            await keycloak_admin.send_update_password_email(user.keycloak_id)
        except KeycloakUnavailableError as exc:
            raise ServiceUnavailableError(_INVITATION_UNAVAILABLE) from exc

    async def send_password_reset_service(self, email: str) -> None:
        """Manda o e-mail de redefinição de senha, se o e-mail tem acesso ativo.

        Para e-mail sem acesso, ou de acesso inativo, não manda nada e não levanta
        erro: a resposta da rota (status, corpo e cabeçalhos) é a mesma para qualquer
        e-mail válido. O tempo de resposta não é: com acesso, o service chama o
        Keycloak e o SMTP; sem acesso, só consulta o banco. Por isso não é a regra do
        login, que chama o Keycloak nos dois caminhos. O risco de enumeração pelo
        tempo foi aceito pelo responsável técnico em 2026-10-29; a mitigação futura é
        mandar o e-mail fora da requisição.
        """
        # O e-mail chega como a pessoa digitou ("Pessoa@..."), e o banco o guarda em
        # minúsculas desde o cadastro. A comparação do repository é exata.
        user = await self.repository.get_user_by_email(email.lower())

        if user is None or user.status is not RecordStatus.ACTIVE:
            return

        try:
            await keycloak_admin.send_update_password_email(user.keycloak_id)
        except KeycloakUnavailableError as exc:
            # Só acontece para e-mail com acesso, e só enquanto o Keycloak ou o SMTP
            # estão fora: nessa janela o 503 revela o cadastro, e a spec aceita isso
            # (Riscos). Fora dela, a resposta não revela; o tempo, sim (docstring).
            raise ServiceUnavailableError(_RESET_EMAIL_UNAVAILABLE) from exc


class MemberService:
    """O convite de membro: participante, vínculo e acesso numa chamada (D8).

    Segunda classe deste arquivo, como o `QuestionOptionService`, e não métodos no
    `UserService`: a guarda de toda rota protegida monta o `UserService`, e ele
    passaria a montar participante e organização a cada requisição.

    Compõe os donos pelo service de cada um. O `users` não monta `ParticipantCreate`
    nem `LinkCreate`: quem monta são `create_member_participant` e
    `create_member_link`, nos domínios donos (`tests/test_arquitetura.py`).
    """

    def __init__(
        self,
        users: UserService,
        participants: ParticipantService,
        links: LinkService,
        organizations: OrganizationService,
    ) -> None:
        self.users = users
        self.participants = participants
        self.links = links
        self.organizations = organizations

    async def invite_member_service(
        self,
        organization_id: uuid.UUID,
        request: MemberInvite,
        *,
        role: str,
        own_organization_id: uuid.UUID,
    ) -> CreatedUser:
        """Cria participante, vínculo e acesso, e manda o convite. Tudo ou nada.

        `role` e `own_organization_id` são de quem pede. Participante e vínculo são
        gravados (flush) antes do acesso, porque o acesso precisa do id do vínculo.
        Se o acesso falha (e-mail repetido, Keycloak ou SMTP fora do ar), o erro sobe
        até o `get_db`, que desfaz os dois junto com o resto da requisição. A
        compensação no Keycloak já é do `create_user_service` (D7).
        """
        # Organização alheia é 403 antes de 404, para não revelar quais existem
        # (P-033). Quem compara é o dono da organização.
        # 🟡 Premissa P-057 — organização inativa também recebe convite.
        await self.organizations.get(
            organization_id, role=role, own_organization_id=own_organization_id
        )

        # 🟡 Premissa P-045 — o gestor convida só como gestor ou respondente.
        if role != Roles.ADMIN.value and request.role is Roles.ADMIN:
            raise ForbiddenError("Só o admin convida com o papel admin")

        participant = await self.participants.create_member_participant(request.name)
        link = await self.links.create_member_link(
            organization_id, participant.id, request.role, request.type
        )

        # O e-mail vai como veio: quem compara e grava em minúsculas é o
        # `create_user_service`.
        return await self.users.create_user_service(
            UserCreate(name=request.name, email=request.email, link_id=link.id)
        )
