"""Schemas Pydantic do domínio organizacoes.

Separados por direção (ADR-0004): entrada e saída não se contaminam.
"""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.domains.organizacoes.models import Organization, OrganizationStatus
from app.shared.enums import RecordStatus
from app.shared.validators import sem_caractere_de_controle

# `[0-9]`, e não `\d`: no Python, `\d` aceita dígito de qualquer escrita (o um de
# largura cheia, U+FF11, por exemplo), e o mesmo número escrito de dois jeitos
# escaparia da constraint única de `documents`.
CPF_OR_CNPJ_DIGITS = re.compile(r"[0-9]{11}|[0-9]{14}")


class OrganizationCreate(BaseModel):
    """Payload de cadastro. O documento precisa já existir."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    address: str = Field(min_length=1, max_length=255)
    document_id: uuid.UUID

    @field_validator("name", "address")
    @classmethod
    def _sem_caractere_de_controle(cls, valor: str) -> str:
        return sem_caractere_de_controle(valor)


class OrganizationUpdate(BaseModel):
    """Payload do PATCH: todo campo é opcional, e só o que vier é alterado.

    `document_id` fica de fora: trocar o documento de uma organização não está no
    contrato da CREED-38.

    `status` é `RecordStatus`, e não `OrganizationStatus`, de propósito: o PATCH não
    aceita `pending` (422). Tirar uma empresa de `pending` também não é do PATCH:
    o service recusa (409), porque ela só sai desse estado aprovada ou rejeitada.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, min_length=1, max_length=255)
    status: RecordStatus | None = None

    @field_validator("name", "address", "status")
    @classmethod
    def _nulo_nao_apaga(cls, valor: object) -> object:
        """Recusa `null` enviado: os três campos são obrigatórios no banco.

        Sem isto, `{"name": null}` chegava ao service como "alterar para None" e o
        banco recusava no `flush()`, com 500. Para manter o valor, omite-se o campo.
        O validador só roda no que veio no corpo, não no default.
        """
        if valor is None:
            raise ValueError("não pode ser nulo; omita o campo para mantê-lo")
        return valor

    @field_validator("name", "address")
    @classmethod
    def _sem_caractere_de_controle(cls, valor: str | None) -> str | None:
        return None if valor is None else sem_caractere_de_controle(valor)


class OrganizationSignUp(BaseModel):
    """Payload do cadastro público (`POST /organizations/sign-up`), sem login.

    Sem endereço: a tela não pede, e a organização nasce com "[A informar]"
    (P-075, no service). O documento chega como a pessoa digitou e sai daqui só
    com os dígitos; o tipo (CPF ou CNPJ) quem deduz é o `DocumentService`.

    O e-mail vai como a pessoa digitou, como no `PasswordResetRequest`; quem grava
    em minúsculas é o service.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [
                {
                    "name": "Empresa Exemplo",
                    "document": "12.345.678/0001-90",
                    "email": "gestora@empresa.com.br",
                    "contact_name": "Gestora Exemplo",
                    "phone": "51 99999-0000",
                }
            ]
        },
    )

    name: str = Field(
        min_length=1,
        max_length=200,
        description="Nome da empresa.",
        examples=["Empresa Exemplo"],
    )
    document: str = Field(
        min_length=1,
        max_length=100,
        description=(
            "CPF ou CNPJ, com ou sem pontuação. Fica só com letras e números, e o "
            "resultado precisa ter 11 dígitos (CPF) ou 14 (CNPJ)."
        ),
        examples=["12.345.678/0001-90"],
    )
    email: EmailStr = Field(
        description="E-mail da empresa, que recebe o acesso de gestor na aprovação.",
        examples=["gestora@empresa.com.br"],
    )
    # 🟡 Premissa P-082 — de 2 a 200, a regra do `UserBase.name`: o convite da
    # aprovação usa este nome, e com 1 caractere ele quebraria lá.
    contact_name: str = Field(
        min_length=2,
        max_length=200,
        description="Nome completo de quem faz o cadastro.",
        examples=["Gestora Exemplo"],
    )
    phone: str = Field(
        min_length=1,
        max_length=30,
        description="Telefone de contato, em texto livre.",
        examples=["51 99999-0000"],
    )

    @field_validator("name", "contact_name", "phone")
    @classmethod
    def _sem_caractere_de_controle(cls, valor: str) -> str:
        return sem_caractere_de_controle(valor)

    @field_validator("document")
    @classmethod
    def _so_os_digitos_de_cpf_ou_cnpj(cls, valor: str) -> str:
        """🟡 Premissa P-076 — guarda só letras e números; 11 ou 14 dígitos.

        Tira tudo o que não é letra nem número, o mesmo critério do `signUpSchema`
        do front: pontuação, espaço, `_` e tab saem. Letra que sobrar reprova, porque
        CPF e CNPJ são só dígitos. Sem dígito verificador.
        """
        limpo = "".join(letra for letra in valor if letra.isalnum())
        if not CPF_OR_CNPJ_DIGITS.fullmatch(limpo):
            raise ValueError("O documento precisa ter 11 dígitos (CPF) ou 14 (CNPJ)")
        return limpo


class OrganizationDocument(BaseModel):
    """O documento da organização, como a tela da administradora mostra."""

    type: str = Field(description="Tipo do documento: `cpf`, `cnpj`, `nipc`...")
    value: str = Field(description="Número do documento, como está guardado.")


class OrganizationResponse(BaseModel):
    """Representação de saída de uma organização."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": "5a1e9c3b-2f7d-4b8a-9e6c-0d4f1b2a3c5e",
                    "name": "Organização Exemplo",
                    "address": "Av. Ipiranga, 6681, Porto Alegre - RS",
                    "document_id": "3b2f8c1a-6d4e-4f7a-9c5b-1e0d2a8f6b94",
                    "status": "pending",
                    "email": "gestora@empresa.com.br",
                    "contact_name": "Gestora Exemplo",
                    "phone": "51 99999-0000",
                    "document": {"type": "cnpj", "value": "12345678000190"},
                    "created_at": "2026-10-15T14:30:00Z",
                    "updated_at": None,
                }
            ]
        },
    )

    id: uuid.UUID = Field(description="Identificador da organização na plataforma.")
    name: str = Field(description="Nome da organização.")
    address: str = Field(description="Endereço, em texto livre (P-021).")
    document_id: uuid.UUID = Field(description="Documento da organização.")
    status: OrganizationStatus = Field(
        description=(
            "Estado do cadastro. `pending` é a empresa que se cadastrou e ainda não "
            "foi aprovada."
        )
    )
    email: str | None = Field(
        description="E-mail informado no cadastro; nulo se a organização não o tem."
    )
    contact_name: str | None = Field(
        description="Nome do responsável informado no cadastro; nulo se não há."
    )
    phone: str | None = Field(
        description="Telefone informado no cadastro; nulo se não há."
    )
    document: OrganizationDocument = Field(
        description="Tipo e número do documento apontado por `document_id`."
    )
    created_at: datetime = Field(description="Data e hora do cadastro.")
    updated_at: datetime | None = Field(
        description="Data e hora da última alteração; nulo se nunca foi alterada."
    )

    @classmethod
    def de_model(
        cls, organization: Organization, document_type: str, document_value: str
    ) -> "OrganizationResponse":
        """Monta a saída a partir do model e do documento dele.

        O documento não vem de `organization`: mora em `documents`, e quem o lê é o
        `OrganizationService.with_documents`. Este schema não importa o service, que
        já importa este arquivo.
        """
        return cls(
            id=organization.id,
            name=organization.name,
            address=organization.address,
            document_id=organization.document_id,
            status=organization.status,
            email=organization.email,
            contact_name=organization.contact_name,
            phone=organization.phone,
            document=OrganizationDocument(type=document_type, value=document_value),
            created_at=organization.created_at,
            updated_at=organization.updated_at,
        )
