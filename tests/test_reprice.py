"""Tests for :class:`falaw.CostBasis` and :func:`falaw.reprice_plan` (falaw#60).

The bug these pin: a persisted plan's ``estimated_cost_usd`` is frozen, and
falaw 0.0.46 moved the LLM rate table tenfold *upward*, so a preview saved
before that change under-quotes the run it is used to price. The contract:

- a ``plan_*`` records **how** it priced a call, so the quote can be re-run;
- re-pricing is pure data — no network, no billing API, no cache peek;
- a call with no basis is reported as such and its cost cleared to *unknown*,
  never passed off as a current quote;
- stamping a basis moves **no** existing digest or serialized byte.

Hermetic throughout: the committed rate tables plus synthetic pricers. Nothing
here spends.
"""

from dataclasses import replace

import pytest

import falaw
from falaw import (
    CallPlan,
    CostBasis,
    Plan,
    Pricer,
    call_plan_from_dict,
    call_plan_to_dict,
    catalogue_cost_basis,
    llm_cost_basis,
    plan_from_dict,
    plan_hash,
    plan_to_dict,
    reprice_plan,
)
from falaw.llm_rates import CUSTOM_LLM_RATES_TABLE
from falaw.reprice import CATALOGUE_PRICER, DFLT_PRICERS, LLM_RATES_PRICER


def _unbased_call(prompt="a tiger"):
    """A call exactly as falaw built one *before* falaw#60 — no cost_basis."""
    return CallPlan(
        tool="generate_image",
        application="fal-ai/flux/dev",
        arguments={"prompt": prompt},
        output_kind="image",
        estimated_cost_usd=0.025,
    )


# ---------------------------------------------------------------------------
# The addition moves nothing that already existed
# ---------------------------------------------------------------------------


#: ``plan_hash`` of a single pre-falaw#60 call, computed before ``cost_basis``
#: existed. Pinned as a literal rather than recomputed: the point is that the
#: *bytes* have not moved, and a recomputed expectation would follow any drift
#: it is supposed to catch. A job manager (nw#27) dedups resumed renders on
#: this digest, so moving it silently re-runs work that was already paid for.
PINNED_UNBASED_PLAN_HASH = (
    "5aa9f7dd3beb391ac758a2e7fa1f818d1300474f40cb739b78e4c9f7b233504d"
)


def test_plan_hash_of_a_basis_free_plan_is_unmoved():
    assert plan_hash(Plan(calls=(_unbased_call(),))) == PINNED_UNBASED_PLAN_HASH


def test_a_basis_free_call_serializes_without_the_key():
    """Omit-when-unset: a plan with no basis writes the exact bytes it did
    before the field existed, so stored plans and cassettes still match."""
    d = call_plan_to_dict(_unbased_call())
    assert "cost_basis" not in d
    assert set(d) == {
        "tool",
        "application",
        "backend",
        "arguments",
        "output_kind",
        "estimated_cost_usd",
        "cache_status",
        "expected_duration_s",
        "metadata",
        "key_extra",
    }


def test_a_basis_does_not_change_the_hash_or_the_cache_key():
    """A basis says what a call *cost*, never what it *produces*, so it must
    appear in neither identity payload."""
    from falaw.canonical import cache_key_payload, plan_identity_payload

    stamped = replace(
        _unbased_call(), cost_basis=catalogue_cost_basis("fal-ai/flux/dev")
    )
    assert plan_hash(Plan(calls=(stamped,))) == PINNED_UNBASED_PLAN_HASH

    identity = plan_identity_payload(
        stamped.application, stamped.arguments, tool=stamped.tool
    )
    key = cache_key_payload(stamped.application, stamped.arguments)
    assert "cost_basis" not in identity
    assert "cost_basis" not in key


def test_a_dict_written_before_falaw60_still_parses():
    d = call_plan_to_dict(_unbased_call())
    assert call_plan_from_dict(d).cost_basis is None


# ---------------------------------------------------------------------------
# Serialization round-trips
# ---------------------------------------------------------------------------


def test_cost_basis_round_trips_through_the_wire_shape():
    call = falaw.plan_image_to_video("u", duration_s=6.0, consult_cache=False)
    assert call.cost_basis is not None
    plan = Plan(calls=(call,))
    assert plan_from_dict(plan_to_dict(plan)) == plan


def test_the_quantity_hints_survive_serialization():
    """The whole point: ``duration_s`` never enters ``arguments``, so without
    the basis a persisted quantity-priced call cannot be re-quoted at all."""
    call = falaw.plan_image_to_video("u", duration_s=6.0, consult_cache=False)
    assert "duration_s" not in call.arguments
    # Seedance bills per video token: 1080p x 6 s x 24/1024 tokens per pixel-second.
    revived = plan_from_dict(plan_to_dict(Plan(calls=(call,)))).calls[0]
    assert revived.cost_basis.quantities == {"tokens": 291600}
    out = reprice_plan(Plan(calls=(revived,)))
    assert out.calls[0].status == "unchanged"
    assert out.calls[0].new_cost_usd == call.estimated_cost_usd


def test_unsupplied_hints_are_omitted_rather_than_written_as_null():
    """Absent is what the estimator actually saw — and what makes a
    quantity-priced record unpriceable, which is a fact worth preserving."""
    call = falaw.plan_image_to_video("u", consult_cache=False)
    assert call.cost_basis.quantities == {}
    assert call.estimated_cost_usd is None  # unknown, not free
    out = reprice_plan(Plan(calls=(call,)))
    assert out.calls[0].status == "unknown"
    assert out.plan.has_unknown_costs


# ---------------------------------------------------------------------------
# What plan_* stamps
# ---------------------------------------------------------------------------


def test_every_planner_stamps_a_basis():
    calls = (
        falaw.plan_generate_image("a tiger", consult_cache=False),
        falaw.plan_edit_image("u", "brighter", consult_cache=False),
        falaw.plan_generate_image_with_refs("a tiger", ["u"], consult_cache=False),
        falaw.plan_composite_character_in_environment("c", "e", consult_cache=False),
        falaw.plan_image_to_video("u", duration_s=6.0, consult_cache=False),
        falaw.plan_animate_face("u", "a", duration_s=6.0, consult_cache=False),
        falaw.plan_lipsync("v", "a", duration_s=6.0, consult_cache=False),
        falaw.plan_text_to_speech("hello", duration_s=3.0, consult_cache=False),
        falaw.plan_generate_audio("rain", duration_s=5.0, consult_cache=False),
        falaw.plan_llm_complete("hi", consult_cache=False),
    )
    for call in calls:
        assert call.cost_basis is not None, call.tool
        assert call.cost_basis.table_version, call.tool


def test_the_llm_basis_prices_the_routed_model_not_the_router():
    """``application`` is the router; the price belongs to what it routes to."""
    call = falaw.plan_llm_complete(
        "hi", model="anthropic/claude-sonnet-4.5", consult_cache=False
    )
    assert call.application == "fal-ai/any-llm"
    assert call.cost_basis.pricer == LLM_RATES_PRICER
    assert call.cost_basis.priced == "anthropic/claude-sonnet-4.5"


def _my_rates(per_call_usd=0.5):
    return {
        "anthropic/claude-sonnet-4.5": falaw.LlmRate(
            model="anthropic/claude-sonnet-4.5",
            tier="premium",
            per_call_usd=per_call_usd,
            date="2999-01-01",
        )
    }


def test_a_caller_supplied_rate_table_is_recorded_as_such():
    call = falaw.plan_llm_complete("hi", llm_rates=_my_rates(), consult_cache=False)
    assert call.estimated_cost_usd == 0.5
    assert call.cost_basis.table == CUSTOM_LLM_RATES_TABLE
    assert call.cost_basis.table_version == ""


def test_the_committed_table_never_requotes_a_caller_supplied_basis():
    """Two tables are two sets of books.

    A row priced at the caller's reconciled $0.50 must not come back as
    falaw's published $0.01 — that is a 50x *under-quote* wearing the clothes
    of a price drop, and it lands on exactly the caller the ``Pricer`` seam is
    advertised for.
    """
    call = falaw.plan_llm_complete("hi", llm_rates=_my_rates(), consult_cache=False)
    out = reprice_plan(Plan(calls=(call,)))

    (row,) = out.calls
    assert row.status == "unknown"
    assert row.new_cost_usd is None
    assert CUSTOM_LLM_RATES_TABLE in row.reason
    assert "falaw/data/llm_rates.json" in row.reason
    assert row.basis_changed
    assert out.plan.has_unknown_costs
    # And the refused call keeps the basis that actually priced it.
    assert out.plan.calls[0].cost_basis == call.cost_basis


def test_a_pricer_naming_the_same_table_does_requote_it():
    """The escape hatch the refusal points at: bring your own books."""
    call = falaw.plan_llm_complete("hi", llm_rates=_my_rates(), consult_cache=False)
    mine = Pricer(
        quote=lambda basis: falaw.llm_ceiling_usd(
            basis.priced, rates=_my_rates(0.75), **basis.quantities
        ),
        table=CUSTOM_LLM_RATES_TABLE,
        version=lambda: "2026-09",
    )
    (row,) = reprice_plan(
        Plan(calls=(call,)), pricers={**DFLT_PRICERS, LLM_RATES_PRICER: mine}
    ).calls
    assert row.status == "changed"
    assert (row.old_cost_usd, row.new_cost_usd) == (0.5, 0.75)
    assert row.call.cost_basis.table_version == "2026-09"


def test_a_basis_naming_no_table_is_not_assumed_to_be_falaws():
    """An unstated book is an unknown book, not the committed one."""
    call = replace(
        _unbased_call(),
        cost_basis=CostBasis(pricer=CATALOGUE_PRICER, priced="fal-ai/flux/dev"),
    )
    (row,) = reprice_plan(Plan(calls=(call,))).calls
    assert row.status == "unknown"
    assert "unnamed table" in row.reason


# ---------------------------------------------------------------------------
# reprice_plan: the four statuses
# ---------------------------------------------------------------------------


def test_repricing_against_an_unmoved_table_changes_nothing():
    plan = Plan(
        calls=(
            falaw.plan_generate_image("a tiger", consult_cache=False),
            falaw.plan_llm_complete("hi", consult_cache=False),
        )
    )
    out = reprice_plan(plan)
    assert [c.status for c in out] == ["unchanged", "unchanged"]
    assert out.known_delta_usd == 0.0
    assert out.changed == ()
    assert out.unpriced == ()
    assert out.plan.total_cost_usd == plan.total_cost_usd


def test_a_moved_rate_table_shows_up_as_a_changed_call():
    """The falaw 0.0.46 scenario: the table re-quotes upward and the saved
    plan's frozen figure is exposed as stale rather than trusted."""
    plan = Plan(calls=(falaw.plan_llm_complete("hi", consult_cache=False),))
    old = plan.calls[0].estimated_cost_usd

    tenfold = Pricer(
        quote=lambda basis: old * 10,
        table="falaw/data/llm_rates.json",
        version=lambda: "moved",
    )
    out = reprice_plan(plan, pricers={**DFLT_PRICERS, LLM_RATES_PRICER: tenfold})

    (row,) = out.calls
    assert row.status == "changed"
    assert (row.old_cost_usd, row.new_cost_usd) == (old, old * 10)
    assert row.delta_usd == pytest.approx(old * 9)
    assert out.known_delta_usd == pytest.approx(old * 9)
    assert row.basis_changed  # the *table* moved, not just the number
    assert out.plan.calls[0].cost_basis.table_version == "moved"


def _repriced_at(factor=None, *, delta=None):
    """One image call re-quoted through a synthetic pricer, and its diff row."""
    plan = Plan(calls=(falaw.plan_generate_image("a tiger", consult_cache=False),))
    old = plan.calls[0].estimated_cost_usd
    new = old + delta if delta is not None else old * factor
    moved = Pricer(
        quote=lambda basis: new,
        table="falaw/data/models.json",
        version=lambda: "moved",
    )
    out = reprice_plan(plan, pricers={**DFLT_PRICERS, CATALOGUE_PRICER: moved})
    return old, new, out


def test_a_price_drop_is_reported_as_a_drop_not_as_unchanged():
    """A re-quote must be able to move *down*. Clamping to the old figure
    would over-quote every cheapened model — and hide the drop from an audit."""
    old, new, out = _repriced_at(0.5)
    (row,) = out.calls
    assert row.status == "changed"
    assert row.new_cost_usd == new < old
    assert row.delta_usd == pytest.approx(-old / 2)
    assert out.known_delta_usd == pytest.approx(-old / 2)


def test_a_sub_cent_move_is_still_a_move():
    """No epsilon anywhere: a 1e-9 change across 200 calls is real money, and
    a tolerance is how a slow repricing goes unnoticed for a quarter."""
    _, new, out = _repriced_at(delta=1e-9)
    (row,) = out.calls
    assert row.status == "changed"
    assert row.new_cost_usd == new
    assert row.delta_usd == pytest.approx(1e-9)


def test_a_call_with_no_basis_is_never_passed_off_as_current():
    plan = Plan(calls=(_unbased_call(),))
    out = reprice_plan(plan)

    (row,) = out.calls
    assert row.status == "no_basis"
    assert row.old_cost_usd == 0.025
    assert row.new_cost_usd is None
    assert row.delta_usd is None
    assert not row.basis_changed
    assert "no cost_basis" in row.reason
    # Cleared to unknown, which is what forces approval downstream.
    assert out.plan.calls[0].estimated_cost_usd is None
    assert out.plan.has_unknown_costs
    assert out.plan.unknown_call_count == 1
    assert out.unpriced == (row,)


def test_an_unregistered_pricer_reprices_to_unknown_not_to_the_old_number():
    call = replace(
        _unbased_call(),
        cost_basis=CostBasis(pricer="from-the-future", priced="fal-ai/flux/dev"),
    )
    (row,) = reprice_plan(Plan(calls=(call,))).calls
    assert row.status == "unknown"
    assert row.new_cost_usd is None
    assert "from-the-future" in row.reason


def test_a_model_that_left_the_catalogue_reprices_to_unknown():
    call = replace(
        _unbased_call(),
        cost_basis=catalogue_cost_basis("fal-ai/retired-last-tuesday"),
    )
    (row,) = reprice_plan(Plan(calls=(call,))).calls
    assert row.status == "unknown"
    assert row.new_cost_usd is None
    assert "KeyError" in row.reason


def test_one_unpriceable_call_does_not_abort_the_rest_of_the_plan():
    """A 200-call plan must not lose 199 re-quotes to one stale row."""
    good = falaw.plan_generate_image("a tiger", consult_cache=False)
    bad = replace(good, cost_basis=catalogue_cost_basis("fal-ai/gone"))
    out = reprice_plan(Plan(calls=(bad, good, bad)))
    assert [c.status for c in out] == ["unknown", "unchanged", "unknown"]
    assert out.plan.calls[1].estimated_cost_usd == good.estimated_cost_usd


# ---------------------------------------------------------------------------
# What reprice_plan does *not* do
# ---------------------------------------------------------------------------


def test_repricing_leaves_the_input_plan_untouched():
    plan = Plan(calls=(falaw.plan_generate_image("a tiger", consult_cache=False),))
    before = plan_to_dict(plan)
    reprice_plan(plan)
    assert plan_to_dict(plan) == before


def test_repricing_is_structurally_identity_preserving():
    plan = Plan(
        calls=(
            falaw.plan_generate_image("a tiger", consult_cache=False),
            falaw.plan_image_to_video("u", duration_s=6.0, consult_cache=False),
        )
    )
    out = reprice_plan(plan)
    assert plan_hash(out.plan) == plan_hash(plan)
    assert [c.arguments for c in out.plan] == [c.arguments for c in plan]


def test_repricing_carries_cache_status_through_untouched():
    """A re-quote answers "what would this cost", not "is it still cached" —
    peeking here would make a cache hit read as a price drop."""
    call = replace(
        falaw.plan_generate_image("a tiger", consult_cache=False),
        cache_status="hit",
    )
    out = reprice_plan(Plan(calls=(call,)))
    assert out.plan.calls[0].cache_status == "hit"
    assert out.plan.total_cost_usd == 0.0  # a hit still bills nothing


def test_repricing_makes_no_network_call(no_outbound_network):
    """The autouse guard records any non-loopback connection; asking for it by
    name here says the refusal is the assertion, not a side effect."""
    plan = Plan(calls=(falaw.plan_llm_complete("hi", consult_cache=False),))
    reprice_plan(plan)
    assert list(no_outbound_network) == []


# ---------------------------------------------------------------------------
# The basis helpers
# ---------------------------------------------------------------------------


def test_catalogue_basis_drops_unsupplied_quantities():
    basis = catalogue_cost_basis("fal-ai/flux/dev", seconds=None, tokens=12)
    assert basis.quantities == {"tokens": 12}
    assert basis.pricer == CATALOGUE_PRICER
    assert basis.table == "falaw/data/models.json"


def test_llm_basis_drops_unsupplied_quantities():
    basis = llm_cost_basis("openai/gpt-4o", input_tokens=None)
    assert basis.quantities == {}


def test_the_repriced_basis_is_stamped_with_todays_table_version():
    stale = replace(
        falaw.plan_generate_image("a tiger", consult_cache=False).cost_basis,
        table_version="from-a-year-ago",
    )
    call = replace(
        falaw.plan_generate_image("a tiger", consult_cache=False), cost_basis=stale
    )
    (row,) = reprice_plan(Plan(calls=(call,))).calls
    assert row.basis_changed
    assert row.call.cost_basis.table_version == falaw.registry.models_table_version()


def test_exported_from_package_root():
    assert falaw.reprice_plan is reprice_plan
    assert falaw.CostBasis is CostBasis
