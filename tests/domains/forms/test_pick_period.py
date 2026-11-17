"""Testes de `pick_period`: qual período vale para um membro (P-068).

Função pura: sem banco e sem relógio. O `now` é fixo, e cada `Form` é montado à mão
com as datas relativas a ele.
"""

import uuid
from datetime import UTC, datetime, timedelta

from app.domains.forms.models import Form, FormStatus
from app.domains.forms.schemas import PeriodStatus
from app.domains.forms.service import period_status, pick_period

NOW = datetime(2026, 11, 9, 12, tzinfo=UTC)
DAY = timedelta(days=1)
ORG = uuid.uuid4()
MEMBER = uuid.uuid4()
OTHER_MEMBER = uuid.uuid4()


def period(
    opens_in: timedelta | None,
    closes_in: timedelta | None,
    link_id: uuid.UUID | None = None,
) -> Form:
    """Período com datas relativas a `NOW`. `link_id` nulo é "para todos"."""
    return Form(
        id=uuid.uuid4(),
        name="Plasticidade Humana",
        organization_id=ORG,
        status=FormStatus.DRAFT,
        opens_at=None if opens_in is None else NOW + opens_in,
        closes_at=None if closes_in is None else NOW + closes_in,
        link_id=link_id,
        created_at=NOW - 30 * DAY,
    )


def picked(periods: list[Form]) -> Form | None:
    """O formulário escolhido para `MEMBER` em `NOW`, ou `None`."""
    result = pick_period(periods, MEMBER, NOW)
    return None if result is None else result.form


def test_open_wins_over_scheduled() -> None:
    open_now = period(-DAY, DAY)
    scheduled = period(DAY, 2 * DAY)

    assert picked([scheduled, open_now]) is open_now


def test_individual_open_wins_over_everyone_open_even_if_it_opened_earlier() -> None:
    individual = period(-3 * DAY, DAY, link_id=MEMBER)
    everyone = period(-DAY, DAY)

    assert picked([everyone, individual]) is individual


def test_between_two_open_for_everyone_the_last_opened_wins() -> None:
    older = period(-3 * DAY, DAY)
    newer = period(-DAY, DAY)

    assert picked([older, newer]) is newer


def test_only_scheduled_returns_the_one_that_opens_first() -> None:
    later = period(5 * DAY, 6 * DAY)
    sooner = period(DAY, 2 * DAY)

    assert picked([later, sooner]) is sooner


def test_only_past_returns_the_last_one_that_closed() -> None:
    old = period(-10 * DAY, -8 * DAY)
    recent = period(-5 * DAY, -DAY)

    assert picked([old, recent]) is recent


def test_scheduled_wins_over_past() -> None:
    past = period(-5 * DAY, -DAY)
    scheduled = period(DAY, 2 * DAY)

    assert picked([past, scheduled]) is scheduled


def test_individual_period_of_another_member_is_ignored() -> None:
    of_someone_else = period(-DAY, DAY, link_id=OTHER_MEMBER)
    scheduled_for_everyone = period(DAY, 2 * DAY)

    assert picked([of_someone_else, scheduled_for_everyone]) is (scheduled_for_everyone)
    assert picked([of_someone_else]) is None


def test_form_without_dates_is_not_a_period() -> None:
    no_dates = period(None, None)
    only_opens = period(-DAY, None)

    assert picked([no_dates, only_opens]) is None


def test_empty_list_returns_none() -> None:
    assert picked([]) is None


def test_window_edges_open_at_opens_at_and_closed_at_closes_at() -> None:
    opens_now = period(timedelta(0), DAY)
    closes_now = period(-DAY, timedelta(0))

    assert period_status(opens_now, NOW) is PeriodStatus.OPEN
    assert period_status(closes_now, NOW) is PeriodStatus.PAST
    assert picked([closes_now, opens_now]) is opens_now


def test_dated_period_carries_the_dates_of_the_form() -> None:
    open_now = period(-DAY, DAY)

    result = pick_period([open_now], MEMBER, NOW)

    assert result is not None
    assert result.opens_at == NOW - DAY
    assert result.closes_at == NOW + DAY
    assert result.status is PeriodStatus.OPEN
