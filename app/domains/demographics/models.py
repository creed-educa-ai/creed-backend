"""Models SQLAlchemy do domínio demographics.

Perfil demográfico do participante (CREED-40), no contrato do
`demographicsSchema.ts` do front. É da **pessoa**, não do login: um participante
tem no máximo um perfil.

Origem étnica e religião aceitam mais de uma opção e moram em tabelas filhas, no
mesmo formato de `insight_prismas`. Apagar o perfil apaga as opções marcadas.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Gender(enum.Enum):
    """Gênero (`genero` no front)."""

    FEMININO = "feminino"
    MASCULINO = "masculino"
    NAO_BINARIO = "nao_binario"
    PREFIRO_NAO_INFORMAR = "prefiro_nao_informar"


class AgeRange(enum.Enum):
    """Faixa etária (`faixaEtaria` no front).

    O banco grava o nome do membro, e nome Python não começa com dígito: daí o
    prefixo `AGE_`.
    """

    AGE_18_25 = "18_25"
    AGE_26_35 = "26_35"
    AGE_36_45 = "36_45"
    AGE_46_55 = "46_55"
    AGE_56_65 = "56_65"
    AGE_65_MAIS = "65_mais"
    PREFIRO_NAO_INFORMAR = "prefiro_nao_informar"


class Ethnicity(enum.Enum):
    """Origem étnica (`origemEtnica` no front)."""

    AFRICANA_AFRODESCENDENTE = "africana_afrodescendente"
    INDIGENA_AMERINDIA = "indigena_amerindia"
    EUROPEIA = "europeia"
    ASIATICA = "asiatica"
    ARABE_MEDIO_ORIENTE = "arabe_medio_oriente"
    LATINO_AMERICANA = "latino_americana"
    ROMANI_CIGANA = "romani_cigana"
    MULTIPLA_HIBRIDA = "multipla_hibrida"
    PREFIRO_NAO_RESPONDER = "prefiro_nao_responder"


class Religion(enum.Enum):
    """Religião (`religiao` no front)."""

    CRISTA = "crista"
    JUDAICA = "judaica"
    ISLAMICA = "islamica"
    MATRIZ_AFRICANA = "matriz_africana"
    ESPIRITISMO = "espiritismo"
    BUDISMO = "budismo"
    SEM_RELIGIAO = "sem_religiao"
    OUTRA = "outra"
    PREFIRO_NAO_RESPONDER = "prefiro_nao_responder"


class Nationality(enum.Enum):
    """Nacionalidade (`nacionalidade` no front)."""

    BRASILEIRA = "brasileira"
    PORTUGUESA = "portuguesa"
    OUTRA = "outra"


class BrazilState(enum.Enum):
    """UF de quem é brasileiro (`estadoBrasil` no front)."""

    AC = "AC"
    AL = "AL"
    AP = "AP"
    AM = "AM"
    BA = "BA"
    CE = "CE"
    DF = "DF"
    ES = "ES"
    GO = "GO"
    MA = "MA"
    MT = "MT"
    MS = "MS"
    MG = "MG"
    PA = "PA"
    PB = "PB"
    PR = "PR"
    PE = "PE"
    PI = "PI"
    RJ = "RJ"
    RN = "RN"
    RS = "RS"
    RO = "RO"
    RR = "RR"
    SC = "SC"
    SP = "SP"
    SE = "SE"
    TO = "TO"


class PortugalRegion(enum.Enum):
    """Região de quem é português (`regiaoPortugal` no front)."""

    NORTE = "norte"
    CENTRO = "centro"
    AREA_METROPOLITANA_LISBOA = "area_metropolitana_lisboa"
    ALENTEJO = "alentejo"
    ALGARVE = "algarve"
    ACORES = "acores"
    MADEIRA = "madeira"


class Demographic(Base):
    __tablename__ = "demographics"
    # Os checks espelham o `normalizeDemographics` do front: campo que depende da
    # nacionalidade só fica preenchido com a nacionalidade dele. O banco grava o
    # NOME do membro ('BRASILEIRA'), não o valor. `IS NOT DISTINCT FROM`, e não
    # `=`, porque CHECK que dá NULL passa: com `=`, estado preenchido e
    # nacionalidade vazia entrariam.
    __table_args__ = (
        UniqueConstraint("participant_id", name="uq_demographics_participant_id"),
        CheckConstraint(
            "brazil_state IS NULL OR nationality IS NOT DISTINCT FROM 'BRASILEIRA'",
            name="ck_demographics_brazil_state_requires_brasileira",
        ),
        CheckConstraint(
            "portugal_region IS NULL OR nationality IS NOT DISTINCT FROM 'PORTUGUESA'",
            name="ck_demographics_portugal_region_requires_portuguesa",
        ),
        CheckConstraint(
            "other_nationality IS NULL OR nationality IS NOT DISTINCT FROM 'OUTRA'",
            name="ck_demographics_other_nationality_requires_outra",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    # A constraint única lá em cima faz o 1:1 e já cria o índice. FK por nome de
    # tabela: importar o model de `participants` furaria a fronteira de domínio.
    participant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "participants.id",
            name="fk_demographics_participant_id_participants",
        ),
        nullable=False,
    )

    gender: Mapped[Gender | None] = mapped_column(
        Enum(Gender, name="gender"), nullable=True
    )
    age_range: Mapped[AgeRange | None] = mapped_column(
        Enum(AgeRange, name="agerange"), nullable=True
    )
    nationality: Mapped[Nationality | None] = mapped_column(
        Enum(Nationality, name="nationality"), nullable=True
    )
    brazil_state: Mapped[BrazilState | None] = mapped_column(
        Enum(BrazilState, name="brazilstate"), nullable=True
    )
    portugal_region: Mapped[PortugalRegion | None] = mapped_column(
        Enum(PortugalRegion, name="portugalregion"), nullable=True
    )
    other_nationality: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class DemographicEthnicity(Base):
    __tablename__ = "demographic_ethnicities"

    demographic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "demographics.id",
            name="fk_demographic_ethnicities_demographic_id_demographics",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    ethnicity: Mapped[Ethnicity] = mapped_column(
        Enum(Ethnicity, name="ethnicity"), primary_key=True
    )


class DemographicReligion(Base):
    __tablename__ = "demographic_religions"

    demographic_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "demographics.id",
            name="fk_demographic_religions_demographic_id_demographics",
            ondelete="CASCADE",
        ),
        primary_key=True,
    )
    religion: Mapped[Religion] = mapped_column(
        Enum(Religion, name="religion"), primary_key=True
    )
