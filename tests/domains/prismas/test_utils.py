"""Testes das funções puras de calculo dos Prismas Neuroinovadores."""

import pytest

from app.domains.prismas.utils import (
    NeuroinnovationPrism,
    calculate_all_prisms,
    calculate_neuroinnovation,
    calculate_prism,
    dimension_averages,
)
from app.shared.enums import Dimension
from app.shared.exceptions import ValidationError


def test_dimension_averages_groups_answers_by_dimension() -> None:
    assert dimension_averages([(Dimension.S2, 1), (Dimension.S2, 3)]) == {
        Dimension.S2: 2.0
    }


@pytest.mark.parametrize("value", [0, 6])
def test_dimension_averages_rejects_values_outside_likert_scale(value: int) -> None:
    with pytest.raises(ValidationError, match=f"S2.*{value}"):
        dimension_averages([(Dimension.S2, value)])


@pytest.mark.parametrize(
    ("prism", "averages", "expected"),
    [
        (
            NeuroinnovationPrism.PSYCHOLOGICAL_SAFETY,
            {Dimension.S6: 2.0, Dimension.S7: 4.0},
            3.0,
        ),
        (
            NeuroinnovationPrism.ADAPTIVE_LEADERSHIP,
            {Dimension.S7: 3.0, Dimension.S8: 5.0},
            4.0,
        ),
        (
            NeuroinnovationPrism.ENTREPRENEURIAL_CULTURE,
            {Dimension.S4: 1.0, Dimension.S6: 5.0},
            3.0,
        ),
        (
            NeuroinnovationPrism.COGNITIVE_ADAPTABILITY,
            {Dimension.S5A: 2.0, Dimension.S5B: 4.0},
            3.0,
        ),
    ],
)
def test_calculate_prism_returns_expected_composite_value(
    prism: NeuroinnovationPrism,
    averages: dict[Dimension, float],
    expected: float,
) -> None:
    assert calculate_prism(prism, averages) == expected


def test_calculate_neuroinnovation_averages_the_seven_dimensions() -> None:
    averages = {dimension: float(index) for index, dimension in enumerate(Dimension, 1)}

    assert calculate_neuroinnovation(averages) == 4.0


def test_neuroinnovation_averages_dimensions_instead_of_items() -> None:
    answers = [(Dimension.S2, 1)] * 9
    answers.extend((dimension, 5) for dimension in list(Dimension)[1:] for _ in range(1))

    averages = dimension_averages(answers)

    assert calculate_neuroinnovation(averages) == (1 + 5 * 6) / 7


def test_calculate_prism_rejects_neuroinnovation() -> None:
    with pytest.raises(ValueError, match="calculate_neuroinnovation"):
        calculate_prism(NeuroinnovationPrism.NEUROINNOVATION, {})


def test_neuroinnovation_requires_s2_while_composite_prisms_do_not() -> None:
    averages = dict.fromkeys(list(Dimension)[1:], 3.0)

    assert calculate_prism(NeuroinnovationPrism.PSYCHOLOGICAL_SAFETY, averages) == 3.0
    with pytest.raises(ValidationError, match="S2"):
        calculate_neuroinnovation(averages)


def test_composite_prism_requires_each_dimension_in_its_composition() -> None:
    with pytest.raises(ValidationError, match="S7"):
        calculate_prism(
            NeuroinnovationPrism.PSYCHOLOGICAL_SAFETY,
            {Dimension.S6: 3.0},
        )


def test_calculate_all_prisms_returns_all_five_keys() -> None:
    averages = dict.fromkeys(Dimension, 3.0)

    assert set(calculate_all_prisms(averages)) == set(NeuroinnovationPrism)
