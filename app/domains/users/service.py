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

A exclusão de membro (M-3, `MemberRemovalService`) também mora aqui, e não em
`links`, dono do vínculo: ela apaga o login, e `users` já depende de `links`. Em
`links`, o `LinkService` precisaria do `UserService`, e os dois services se
importariam um ao outro.

A exclusão de empresa (E-6, `OrganizationRemovalService`) mora aqui pelo mesmo
motivo: ela apaga cada membro pelo `MemberRemovalService`, e `users` já depende de
`organizacoes`. Em `organizacoes`, os dois domínios se importariam um ao outro.

A aprovação de empresa (E-3, `OrganizationApprovalService`) também: ela convida quem
cadastrou a empresa pelo `MemberService`, que é deste domínio.
"""

import logging
import uuid
from dataclasses import dataclass

from app.domains.dashboards.service import DashboardService
from app.domains.demographics.service import DemographicService
from app.domains.department.service import DepartmentService
from app.domains.documents.service import DocumentService
from app.domains.forms.service import FormService
from app.domains.insights.service import InsightService
from app.domains.links.service import LinkService
from app.domains.organizacoes.service import (
    OrganizationService,
    OrganizationWithDocument,
)
from app.domains.participants.service import ParticipantService
from app.domains.responses.service import FormResponseService
from app.domains.users.models import User
from app.domains.users.repository import UserRepository
from app.domains.users.schemas import MemberInvite, UserCreate
from app.external_services.keycloak import admin as keycloak_admin
from app.external_services.keycloak.client import KeycloakUnavailableError
from app.shared.enums import LinkType, RecordStatus, Roles
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
        keycloak_id = await self.delete_login(user)
        await self.remove_from_keycloak(keycloak_id)

    async def get_login_of_link(self, link_id: uuid.UUID) -> User | None:
        """O login do vínculo, ou `None` se o vínculo foi criado sem convite."""
        return await self.repository.get_by_link_id(link_id)

    async def delete_login(self, user: User) -> uuid.UUID:
        """Apaga o login só no banco e devolve o `keycloak_id`, para o realm depois.

        Separado de `remove_from_keycloak` porque quem apaga mais coisas no banco
        (a exclusão de membro, M-3) chama o Keycloak só no fim, pela mesma razão de
        `delete_user_service`.
        """
        keycloak_id = user.keycloak_id
        await self.repository.delete(user)
        return keycloak_id

    async def remove_from_keycloak(self, keycloak_id: uuid.UUID) -> None:
        """Apaga o usuário do realm. O 404 de lá é sucesso (`keycloak_admin`)."""
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


def _listed(keycloak_ids: list[uuid.UUID]) -> str:
    """Os ids como texto, prontos para copiar do log para o console do Keycloak."""
    return ", ".join(str(keycloak_id) for keycloak_id in keycloak_ids) or "nenhum"


class MemberRemovalService:
    """Exclui um membro de vez, com tudo o que é dele (M-3).

    Cada tabela é apagada pelo service do dono (ADR-0004, item 4): este service só
    decide quem pode e a ordem. A ordem é a das chaves estrangeiras, de quem aponta
    para quem é apontado, porque o banco recusa apagar uma linha que outra ainda
    referencia.
    """

    def __init__(
        self,
        users: UserService,
        links: LinkService,
        forms: FormService,
        responses: FormResponseService,
        insights: InsightService,
        dashboards: DashboardService,
        demographics: DemographicService,
        participants: ParticipantService,
    ) -> None:
        self.users = users
        self.links = links
        self.forms = forms
        self.responses = responses
        self.insights = insights
        self.dashboards = dashboards
        self.demographics = demographics
        self.participants = participants

    async def remove_member(
        self,
        organization_id: uuid.UUID,
        link_id: uuid.UUID,
        *,
        own_organization_id: uuid.UUID,
        own_link_id: uuid.UUID,
    ) -> None:
        """Confere quem pede e exclui o membro: banco e, por último, Keycloak.

        `own_organization_id` e `own_link_id` são de quem pede. A ordem de
        conferência é acesso (403), a si mesmo (409), vínculo (404). O 409 vem antes
        da busca porque o vínculo de quem pede sempre existe na própria organização.

        🟡 Premissa P-071 — o `gestor` exclui na própria organização, e o `admin`
        também só na própria, que é a da CREED (P-048), onde estão os mentorandos.
        É mais estreito que a P-066 da listagem e da troca de setor, em que o
        `admin` mexe em qualquer organização. O papel já foi conferido pela guarda.

        🟡 Premissa P-074 — qualquer vínculo da organização pode ser o alvo, outro
        `admin` ou `gestor` incluídos; a única recusa é a si mesmo. Confirmar na
        próxima reunião.
        """
        if organization_id != own_organization_id:
            raise ForbiddenError("Sem acesso aos membros desta organização")

        if link_id == own_link_id:
            raise ConflictError("Não é possível excluir o próprio acesso")

        keycloak_id = await self.delete_member_data(organization_id, link_id)
        if keycloak_id is not None:
            await self.remove_logins_from_keycloak([keycloak_id])

    async def delete_member_data(
        self, organization_id: uuid.UUID, link_id: uuid.UUID
    ) -> uuid.UUID | None:
        """Apaga no banco tudo o que é do membro e devolve o `keycloak_id` do login,
        ou `None` se ele não tinha login. Não chama o Keycloak nem confere acesso.
        Vínculo inexistente, ou de outra organização, é `NotFoundError`.

        Separado de `remove_member` para a exclusão de empresa (E-6) apagar cada
        membro assim e chamar o Keycloak uma vez só, no fim, com todos os logins.

        Saem as respostas, os questionários individuais, o login, o vínculo e, sem
        outro vínculo, o participante e o perfil demográfico.

        🟡 Premissa P-072 — saem também os insights e os dashboards das respostas
        apagadas e do login: o banco não deixa apagar o que eles referenciam. As
        perguntas ficam: são do instrumento, e não do questionário.
        """
        link = await self.links.get_member_link(organization_id, link_id)

        form_ids = await self.forms.list_individual_form_ids(link.id)
        response_ids = await self.responses.list_ids_for_member_removal(link.id, form_ids)
        login = await self.users.get_login_of_link(link.id)

        await self.insights.delete_for_form_responses(response_ids)
        await self.dashboards.delete_for_member_removal(
            response_ids, login.id if login is not None else None
        )
        await self.responses.delete_with_answers(response_ids)
        await self.forms.delete_individual_forms(form_ids)

        keycloak_id = await self.users.delete_login(login) if login is not None else None
        await self.links.delete_link(link)

        # A mesma pessoa em outra organização é outro vínculo do mesmo participante
        # ([C2]): ela continua existindo para lá.
        if not await self.links.participant_has_links(link.participant_id):
            await self.demographics.delete_for_participant(link.participant_id)
            await self.participants.delete_participant(link.participant_id)

        return keycloak_id

    async def remove_logins_from_keycloak(self, keycloak_ids: list[uuid.UUID]) -> None:
        """Apaga os logins do realm, depois de o banco já ter apagado tudo.

        🟡 Premissa P-073 — o Keycloak é chamado antes do commit, e não depois: se
        ele falhar, o 503 faz o `get_db` desfazer o banco, e repetir a exclusão
        resolve, porque o 404 do realm é sucesso. Commit primeiro deixaria logins
        no realm sem linha no banco, e reconvidar o e-mail daria 409 até a limpeza
        à mão. O que a M-3 e a E-6 pedem ("registrar o que sobrou") é o log abaixo.

        Banco e realm não têm transação comum, e sobra uma janela: o realm apaga e
        a resposta se perde (timeout), ou o commit falha depois. A pessoa fica no
        banco sem conseguir entrar até alguém repetir a exclusão. O log diz quem.
        """
        removed: list[uuid.UUID] = []
        for keycloak_id in keycloak_ids:
            try:
                await self.users.remove_from_keycloak(keycloak_id)
            except ServiceUnavailableError:
                logger.warning(
                    "Exclusão desfeita no banco com o Keycloak indisponível. Já "
                    "apagados no realm: %s. Talvez apagado (sem resposta): %s. Não "
                    "tentados: %s. Repetir a exclusão resolve.",
                    _listed(removed),
                    keycloak_id,
                    _listed(keycloak_ids[len(removed) + 1 :]),
                )
                raise
            removed.append(keycloak_id)


class OrganizationRemovalService:
    """Exclui uma empresa de vez, com todos os membros e tudo o que pende dela (E-6).

    É o `MemberRemovalService` um nível acima: cada tabela é apagada pelo service do
    dono (ADR-0004, item 4), e este service só decide quem pode e a ordem.
    """

    def __init__(
        self,
        members: MemberRemovalService,
        organizations: OrganizationService,
        links: LinkService,
        forms: FormService,
        responses: FormResponseService,
        insights: InsightService,
        dashboards: DashboardService,
        departments: DepartmentService,
        participants: ParticipantService,
        documents: DocumentService,
    ) -> None:
        self.members = members
        self.organizations = organizations
        self.links = links
        self.forms = forms
        self.responses = responses
        self.insights = insights
        self.dashboards = dashboards
        self.departments = departments
        self.participants = participants
        self.documents = documents

    async def remove_organization(
        self, organization_id: uuid.UUID, *, own_organization_id: uuid.UUID
    ) -> None:
        """Apaga a organização no banco e, por último, os logins dos membros no realm.

        `own_organization_id` é a organização de quem pede. O papel `admin` já foi
        conferido pela guarda da rota.

        A ordem é a das chaves estrangeiras, de quem aponta para quem é apontado,
        porque o banco recusa apagar uma linha que outra ainda referencia:

        1. cada membro, pelo `delete_member_data` da M-3, que devolve o login;
        2. os questionários que sobraram (os "para todos"): antes, as respostas que
           ainda apontam para eles, com os insights e os dashboards delas (as
           perguntas são do instrumento e ficam);
        3. os setores, para onde os vínculos apontavam;
        4. a organização;
        5. o documento dela, que é apontado pela organização e só sai depois dela;
        6. os logins no Keycloak, numa chamada só.

        🟡 Premissa P-079 — ninguém exclui a organização do próprio vínculo (409),
        conferido antes de qualquer consulta.

        🟡 Premissa P-080 — sai tudo o que pende da empresa e, no fim, o documento,
        se nenhum participante apontar para ele.

        🟡 Premissa P-078 — empresa pendente não tem membro nem questionário: para
        ela, isto apaga só a organização e o documento. É a rejeição do cadastro, e o
        mesmo documento pode se cadastrar de novo.

        O Keycloak é chamado sempre, mesmo com a lista vazia, e antes do commit,
        como na M-3 (P-073): se ele falhar, o 503 faz o `get_db` desfazer o banco
        inteiro, e repetir a exclusão resolve. Fica a mesma janela da M-3: o realm
        apaga e o commit falha depois, ou a resposta se perde. O log de
        `remove_logins_from_keycloak` diz quem já saiu do realm.
        """
        if organization_id == own_organization_id:
            raise ConflictError("Não é possível excluir a própria organização")

        # A guarda da rota só deixa passar o `admin`, que lê qualquer organização.
        organization = await self.organizations.get(
            organization_id,
            role=Roles.ADMIN.value,
            own_organization_id=own_organization_id,
        )

        keycloak_ids: list[uuid.UUID] = []
        for link_id in await self.links.list_organization_link_ids(organization_id):
            keycloak_id = await self.members.delete_member_data(organization_id, link_id)
            if keycloak_id is not None:
                keycloak_ids.append(keycloak_id)

        form_ids = await self.forms.list_organization_form_ids(organization_id)
        response_ids = await self.responses.list_ids_for_forms(form_ids)
        await self.insights.delete_for_form_responses(response_ids)
        # Sem login: os logins dos membros já saíram, com os dashboards deles.
        await self.dashboards.delete_for_member_removal(response_ids, None)
        await self.responses.delete_with_answers(response_ids)
        await self.forms.delete_organization_forms(form_ids)

        await self.departments.delete_for_organization(organization_id)

        document_id = organization.document_id
        await self.organizations.delete_organization(organization)

        if not await self.participants.document_in_use(document_id):
            await self.documents.delete_document(document_id)

        await self.members.remove_logins_from_keycloak(keycloak_ids)


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


class OrganizationApprovalService:
    """Aprova uma empresa pendente e convida quem a cadastrou como gestor (E-3).

    Compõe o `OrganizationService`, dono do status, e o `MemberService`, dono do
    convite. Não confere o papel: a guarda `admin` é da rota.
    """

    def __init__(
        self, organizations: OrganizationService, members: MemberService
    ) -> None:
        self.organizations = organizations
        self.members = members

    async def approve(
        self, organization_id: uuid.UUID, *, own_organization_id: uuid.UUID
    ) -> OrganizationWithDocument:
        """Ativa a empresa e manda o convite de gestor ao e-mail do cadastro.

        `own_organization_id` é a organização de quem pede, e só segue para o
        convite. Devolve a empresa já com o documento, pronta para a resposta: este
        domínio não importa o model `Organization`.

        A ordem é status antes do convite, e tudo na mesma transação da requisição.
        Assim, uma empresa que não está pendente para no `ConflictError` antes de
        criar qualquer coisa, e um convite que falha (e-mail com acesso, Keycloak ou
        SMTP fora do ar) faz o `get_db` desfazer a troca de status junto com o
        participante e o vínculo: a empresa continua pendente e pode ser aprovada de
        novo. O usuário do realm já é desfeito pelo `create_user_service` (D7).

        🟡 Premissa P-053 — o convite vai ao e-mail do cadastro, em nome do
        responsável (`contact_name`), com papel `gestor` e vínculo `emprego` (P-047).
        🟡 Premissa P-077 — e-mail que já tem acesso é o `ConflictError` do
        `create_user_service`, que sobe sem tratamento: a empresa continua pendente.
        🟡 Premissa P-079 — só `admin` aprova; por isso o convite sai com o papel
        `admin` de quem pede, que convida em qualquer organização.
        """
        organization = await self.organizations.activate_pending(organization_id)

        # Toda empresa pendente vem do cadastro público, que exige os dois campos.
        # Só uma criada pelo `POST /organizacoes` não os tem, e ela nasce ativa:
        # chegar aqui sem eles é banco editado à mão. Vira 409, que diz o motivo e
        # desfaz a troca de status, e não 500. O conteúdo já passou pelas regras do
        # `MemberInvite` no cadastro (P-082).
        if organization.email is None or organization.contact_name is None:
            raise ConflictError(
                f"A empresa {organization_id} não tem e-mail ou responsável para "
                "receber o convite"
            )

        # Antes do convite: depois do e-mail enviado, nada mais pode falhar (P-073).
        (approved,) = await self.organizations.with_documents([organization])

        await self.members.invite_member_service(
            organization.id,
            MemberInvite(
                name=organization.contact_name,
                email=organization.email,
                role=Roles.GESTOR,
                type=LinkType.EMPREGO,
            ),
            role=Roles.ADMIN.value,
            own_organization_id=own_organization_id,
        )
        return approved
