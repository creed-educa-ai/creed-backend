"""Testes de app/shared/enums.py"""

from app.shared.enums import Dimension


def test_dimension_contains_matrix_dimensions_in_order() -> None:
    assert list(Dimension) == [
        Dimension.S2,
        Dimension.S4,
        Dimension.S5A,
        Dimension.S5B,
        Dimension.S6,
        Dimension.S7,
        Dimension.S8,
    ]


def test_dimension_names_match_values() -> None:
    assert all(dimension.name == dimension.value for dimension in Dimension)
