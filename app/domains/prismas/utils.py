"""Calcula os cinco Prismas Neuroinovadores da Matriz CREED.

As quatro pontas compostas sao calculadas pelas formulas SP = (S6 + S7) / 2,
LA = (S7 + S8) / 2, CE = (S4 + S6) / 2 e AC = (S5A + S5B) / 2.
NP = (S2 + S4 + S5A + S5B + S6 + S7 + S8) / 7. Essa formula calcula a
media das sete medias de dimensao, e nao a media dos itens individuais.
"""

import enum
from collections.abc import Iterable, Mapping

from app.shared.enums import Dimension
from app.shared.exceptions import ValidationError


class NeuroinnovationPrism(enum.Enum):
    """Prismas Neuroinovadores da Matriz CREED."""

    PSYCHOLOGICAL_SAFETY = "SP"
    ADAPTIVE_LEADERSHIP = "LA"
    ENTREPRENEURIAL_CULTURE = "CE"
    COGNITIVE_ADAPTABILITY = "AC"
    NEUROINNOVATION = "NP"


PRISM_COMPOSITION: dict[NeuroinnovationPrism, tuple[Dimension, ...]] = {
    NeuroinnovationPrism.PSYCHOLOGICAL_SAFETY: (Dimension.S6, Dimension.S7),
    NeuroinnovationPrism.ADAPTIVE_LEADERSHIP: (Dimension.S7, Dimension.S8),
    NeuroinnovationPrism.ENTREPRENEURIAL_CULTURE: (Dimension.S4, Dimension.S6),
    NeuroinnovationPrism.COGNITIVE_ADAPTABILITY: (Dimension.S5A, Dimension.S5B),
}

_ALL_DIMENSIONS = tuple(Dimension)


def dimension_averages(
    answers: Iterable[tuple[Dimension, int | float]],
) -> dict[Dimension, float]:
    """Agrupa respostas por dimensao e devolve a media de cada dimensao."""
    totals: dict[Dimension, float] = {}
    counts: dict[Dimension, int] = {}

    for dimension, value in answers:
        if not 1 <= value <= 5:
            raise ValidationError(
                f"Dimensao {dimension.value} recebeu valor {value}; esperado entre 1 e 5"
            )
        totals[dimension] = totals.get(dimension, 0.0) + value
        counts[dimension] = counts.get(dimension, 0) + 1

    return {dimension: totals[dimension] / counts[dimension] for dimension in totals}


def calculate_prism(
    prism: NeuroinnovationPrism,
    averages: dict[Dimension, float],
) -> float:
    """Calcula uma das quatro pontas compostas a partir das medias."""
    if prism is NeuroinnovationPrism.NEUROINNOVATION:
        raise ValueError(
            "Use calculate_neuroinnovation para calcular o prisma NEUROINNOVATION"
        )

    dimensions = PRISM_COMPOSITION[prism]
    _require_dimensions(averages, dimensions)
    return sum(averages[dimension] for dimension in dimensions) / len(dimensions)


def calculate_neuroinnovation(averages: dict[Dimension, float]) -> float:
    """Calcula NP como a media das medias das sete dimensoes."""
    _require_dimensions(averages, _ALL_DIMENSIONS)
    return sum(averages[dimension] for dimension in _ALL_DIMENSIONS) / len(
        _ALL_DIMENSIONS
    )


def calculate_all_prisms(
    averages: dict[Dimension, float],
) -> dict[NeuroinnovationPrism, float]:
    """Calcula as quatro pontas compostas e a ponta NP."""
    return {
        **{prism: calculate_prism(prism, averages) for prism in PRISM_COMPOSITION},
        NeuroinnovationPrism.NEUROINNOVATION: calculate_neuroinnovation(averages),
    }


def _require_dimensions(
    averages: Mapping[Dimension, float],
    dimensions: Iterable[Dimension],
) -> None:
    missing = [dimension for dimension in dimensions if dimension not in averages]
    if missing:
        names = ", ".join(dimension.value for dimension in missing)
        raise ValidationError(f"Dimensoes sem resposta: {names}")
