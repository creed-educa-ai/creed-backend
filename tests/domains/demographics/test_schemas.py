"""Testes dos schemas do domínio demographics.

Os payloads entram por `model_validate` com os `value` do front, como chegam no
corpo da requisição.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.domains.demographics.models import (
    AgeRange,
    BrazilState,
    Demographic,
    Ethnicity,
    Gender,
    Nationality,
    PortugalRegion,
    Religion,
)
from app.domains.demographics.schemas import DemographicCreate, DemographicResponse

DEPENDENT_FIELDS = {
    "brazil_state": "SP",
    "portugal_region": "norte",
    "other_nationality": "argentina",
}


def test_create_takes_only_what_the_client_sends() -> None:
    """`id`, `participant_id` e as datas não vêm do corpo."""
    assert set(DemographicCreate.model_fields) == {
        "gender",
        "age_range",
        "ethnicities",
        "religions",
        "nationality",
        "brazil_state",
        "portugal_region",
        "other_nationality",
    }


def test_response_returns_the_profile_with_identity_and_dates() -> None:
    assert set(DemographicResponse.model_fields) == set(
        DemographicCreate.model_fields
    ) | {"id", "participant_id", "created_at", "updated_at"}


def test_empty_payload_is_accepted() -> None:
    data = DemographicCreate.model_validate({})

    assert data.gender is None
    assert data.age_range is None
    assert data.nationality is None
    assert data.ethnicities == []
    assert data.religions == []


def test_frontend_values_become_enum_members() -> None:
    data = DemographicCreate.model_validate(
        {
            "gender": "nao_binario",
            "age_range": "18_25",
            "ethnicities": ["indigena_amerindia", "multipla_hibrida"],
            "religions": ["matriz_africana"],
            "nationality": "portuguesa",
            "portugal_region": "area_metropolitana_lisboa",
        }
    )

    assert data.gender is Gender.NAO_BINARIO
    assert data.age_range is AgeRange.AGE_18_25
    assert data.ethnicities == [Ethnicity.INDIGENA_AMERINDIA, Ethnicity.MULTIPLA_HIBRIDA]
    assert data.religions == [Religion.MATRIZ_AFRICANA]
    assert data.nationality is Nationality.PORTUGUESA
    assert data.portugal_region is PortugalRegion.AREA_METROPOLITANA_LISBOA


@pytest.mark.parametrize(
    "payload",
    [
        {"gender": "outro"},
        {"age_range": "AGE_18_25"},
        {"age_range": "66_mais"},
        {"ethnicities": ["nordica"]},
        {"religions": ["ateia"]},
        {"nationality": "espanhola"},
        {"nationality": "brasileira", "brazil_state": "XX"},
        {"nationality": "portuguesa", "portugal_region": "lisboa"},
    ],
)
def test_value_outside_the_enum_is_rejected(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DemographicCreate.model_validate(payload)


@pytest.mark.parametrize(
    ("nationality", "kept"),
    [
        ("brasileira", "brazil_state"),
        ("portuguesa", "portugal_region"),
        ("outra", "other_nationality"),
        (None, None),
    ],
)
def test_fields_of_other_nationalities_are_cleared(
    nationality: str | None, kept: str | None
) -> None:
    data = DemographicCreate.model_validate(
        {"nationality": nationality, **DEPENDENT_FIELDS}
    )

    for field in DEPENDENT_FIELDS:
        if field == kept:
            assert getattr(data, field) is not None
        else:
            assert getattr(data, field) is None, f"{field} deveria ter sido zerado"


def test_matching_dependent_field_keeps_its_value() -> None:
    data = DemographicCreate.model_validate(
        {"nationality": "brasileira", "brazil_state": "RS"}
    )

    assert data.brazil_state is BrazilState.RS


@pytest.mark.parametrize(
    "payload",
    [
        {"ethnicities": ["europeia", "asiatica", "europeia"]},
        {"religions": ["crista", "crista"]},
    ],
)
def test_repeated_option_is_rejected(payload: dict[str, Any]) -> None:
    with pytest.raises(ValidationError, match="Não pode repetir opção"):
        DemographicCreate.model_validate(payload)


def test_prefer_not_to_answer_can_come_with_other_options() -> None:
    """🟡 Premissa: sem exclusividade entre "prefiro não responder" e o resto."""
    data = DemographicCreate.model_validate(
        {"religions": ["crista", "prefiro_nao_responder"]}
    )

    assert data.religions == [Religion.CRISTA, Religion.PREFIRO_NAO_RESPONDER]


def test_other_nationality_is_stripped() -> None:
    data = DemographicCreate.model_validate(
        {"nationality": "outra", "other_nationality": "  argentina  "}
    )

    assert data.other_nationality == "argentina"


def test_blank_other_nationality_becomes_empty() -> None:
    data = DemographicCreate.model_validate(
        {"nationality": "outra", "other_nationality": "   "}
    )

    assert data.other_nationality is None


@pytest.mark.parametrize("nationality", ["brasileira", "portuguesa", "outra", None])
def test_empty_other_nationality_from_the_frontend_becomes_none(
    nationality: str | None,
) -> None:
    """O front manda `nacionalidadeOutra: ''` quando o campo não se aplica."""
    data = DemographicCreate.model_validate(
        {"nationality": nationality, "other_nationality": ""}
    )

    assert data.other_nationality is None


def test_other_nationality_accepts_100_characters_after_strip() -> None:
    data = DemographicCreate.model_validate(
        {"nationality": "outra", "other_nationality": f"  {'a' * 100}  "}
    )

    assert data.other_nationality == "a" * 100


def test_other_nationality_over_100_characters_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DemographicCreate.model_validate(
            {"nationality": "outra", "other_nationality": "a" * 101}
        )


def test_invalid_state_is_rejected_even_if_it_would_be_cleared() -> None:
    """Valor inválido é recusado antes da normalização, mesmo num campo que a
    nacionalidade zeraria."""
    with pytest.raises(ValidationError) as error:
        DemographicCreate.model_validate(
            {"nationality": "portuguesa", "brazil_state": "XX"}
        )

    assert [err["loc"] for err in error.value.errors()] == [("brazil_state",)]


def test_long_other_nationality_is_rejected_even_if_it_would_be_cleared() -> None:
    with pytest.raises(ValidationError) as error:
        DemographicCreate.model_validate(
            {"nationality": "brasileira", "other_nationality": "a" * 101}
        )

    assert [err["loc"] for err in error.value.errors()] == [("other_nationality",)]


@pytest.mark.parametrize("control_character", ["\x00", "\n", "\t"])
def test_other_nationality_with_control_character_is_rejected(
    control_character: str,
) -> None:
    """No meio do texto: na ponta, `\\n` e `\\t` já saem no strip."""
    with pytest.raises(ValidationError, match="caracteres de controle"):
        DemographicCreate.model_validate(
            {
                "nationality": "outra",
                "other_nationality": f"arg{control_character}entina",
            }
        )


def test_de_model_builds_the_response_from_the_model_and_the_options() -> None:
    demographic = Demographic(
        id=uuid.uuid4(),
        participant_id=uuid.uuid4(),
        gender=Gender.FEMININO,
        age_range=AgeRange.AGE_65_MAIS,
        nationality=Nationality.BRASILEIRA,
        brazil_state=BrazilState.RS,
        portugal_region=None,
        other_nationality=None,
        created_at=datetime(2026, 10, 18, tzinfo=UTC),
        updated_at=None,
    )

    response = DemographicResponse.de_model(
        demographic,
        ethnicities=[Ethnicity.EUROPEIA, Ethnicity.LATINO_AMERICANA],
        religions=[Religion.SEM_RELIGIAO],
    )

    assert response.id == demographic.id
    assert response.participant_id == demographic.participant_id
    assert response.gender is Gender.FEMININO
    assert response.age_range is AgeRange.AGE_65_MAIS
    assert response.nationality is Nationality.BRASILEIRA
    assert response.brazil_state is BrazilState.RS
    assert response.portugal_region is None
    assert response.other_nationality is None
    assert response.ethnicities == [Ethnicity.EUROPEIA, Ethnicity.LATINO_AMERICANA]
    assert response.religions == [Religion.SEM_RELIGIAO]
    assert response.created_at == demographic.created_at
    assert response.updated_at is None


def test_response_cannot_be_validated_straight_from_the_model() -> None:
    """O model não tem as listas: `model_validate` direto falha em vez de devolver
    `[]` calado. A saída tem que passar por `de_model()`."""
    demographic = Demographic(
        id=uuid.uuid4(),
        participant_id=uuid.uuid4(),
        created_at=datetime(2026, 10, 18, tzinfo=UTC),
    )

    with pytest.raises(ValidationError) as error:
        DemographicResponse.model_validate(demographic)

    assert {err["loc"] for err in error.value.errors()} == {
        ("ethnicities",),
        ("religions",),
    }


def test_response_schema_requires_every_field() -> None:
    schema = DemographicResponse.model_json_schema(mode="serialization")

    assert set(schema["required"]) == set(DemographicResponse.model_fields)


def test_response_serializes_the_frontend_values() -> None:
    demographic = Demographic(
        id=uuid.uuid4(),
        participant_id=uuid.uuid4(),
        age_range=AgeRange.AGE_18_25,
        created_at=datetime(2026, 10, 18, tzinfo=UTC),
    )

    body = DemographicResponse.de_model(
        demographic, ethnicities=[Ethnicity.ASIATICA], religions=[]
    ).model_dump(mode="json")

    assert body["age_range"] == "18_25"
    assert body["ethnicities"] == ["asiatica"]
