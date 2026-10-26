"""The terms ledger and its plan-time check (falaw#16)."""

from __future__ import annotations

import inspect

import pytest

import falaw
from falaw import FalTermsViolation, TermsContext
from falaw.operations import _plan
from falaw.terms import (
    ModelTerms,
    check_terms,
    get_terms,
    load_terms,
    third_party_tenancy_ok,
    unreviewed_models,
)

SELF_HOSTED, HOSTED = "comfyui", "fal"


def _row(**kw) -> ModelTerms:
    base = dict(
        model_id="m",
        backend="b",
        license_binds_us="no",
        commercial_use="allowed",
        third_party_tenancy="allowed",
        c2pa_compatible="yes",
    )
    return ModelTerms(**{**base, **kw})


def _ledger(*rows: ModelTerms):
    return {(r.model_id, r.backend): r for r in rows}


# ── the key is (model, backend): same weights, different legal position ─────


def test_flux_dev_hosted_and_self_hosted_differ():
    ctx = TermsContext(third_party=True)
    check_terms("fal-ai/flux/dev", SELF_HOSTED, None)  # no context: unchecked
    with pytest.raises(FalTermsViolation, match="forbidden") as err:
        check_terms("fal-ai/flux/dev", SELF_HOSTED, ctx)
    assert err.value.model_id == "fal-ai/flux/dev"
    assert err.value.backend == SELF_HOSTED
    assert "huggingface.co/black-forest-labs/FLUX.1-dev" in str(err.value)


def test_schnell_self_hosted_is_cleared_for_third_parties():
    check_terms("fal-ai/flux/schnell", SELF_HOSTED, TermsContext(third_party=True))


# ── fail closed ─────────────────────────────────────────────────────────────


def test_a_model_nobody_reviewed_is_refused_not_waved_through():
    with pytest.raises(FalTermsViolation, match="no terms row"):
        check_terms("nobody/reviewed-this", HOSTED, TermsContext(), ledger={})


@pytest.mark.parametrize(
    ("field", "context"),
    [
        ("license_binds_us", TermsContext(commercial=False)),
        ("commercial_use", TermsContext()),
        ("third_party_tenancy", TermsContext(commercial=False, third_party=True)),
        ("c2pa_compatible", TermsContext(commercial=False, c2pa=True)),
    ],
)
def test_unknown_refuses_when_it_matters(field, context):
    unknown = _row(**{field: "unknown"})
    with pytest.raises(FalTermsViolation, match="unknown"):
        check_terms("m", "b", context, ledger=_ledger(unknown))


def test_unknown_is_ignored_when_the_job_does_not_need_it():
    row = _row(third_party_tenancy="unknown", c2pa_compatible="unknown")
    check_terms("m", "b", TermsContext(), ledger=_ledger(row))


def test_ideogram_cannot_flow_through_c2pa_provenance():
    ctx = TermsContext(commercial=False, c2pa=True)
    with pytest.raises(FalTermsViolation, match="entirely human generated"):
        check_terms("fal-ai/ideogram/v3", HOSTED, ctx)


def test_no_context_checks_nothing_even_for_unreviewed_models():
    check_terms("nobody/reviewed-this", HOSTED, None)


# ── the routing-visible projection ──────────────────────────────────────────


def test_third_party_tenancy_ok_is_conservative():
    assert third_party_tenancy_ok("fal-ai/flux/schnell", SELF_HOSTED)
    assert not third_party_tenancy_ok("fal-ai/flux/dev", SELF_HOSTED)
    assert not third_party_tenancy_ok("fal-ai/flux/schnell", HOSTED)  # unreviewed
    assert not third_party_tenancy_ok("nobody/reviewed-this", HOSTED)


# ── the ledger as data ──────────────────────────────────────────────────────


def test_ledger_rows_are_valid_and_unique():
    ledger = load_terms()
    assert ledger  # parsed, vocab-checked by ModelTerms.__post_init__
    assert all(row.observed_on and row.source_url for row in ledger.values())


def test_a_bad_vocabulary_value_is_refused_at_load():
    with pytest.raises(ValueError, match="commercial_use"):
        _row(commercial_use="maybe")


def test_every_ledger_hosted_row_names_a_catalogue_model():
    ids = {m.id for m in falaw.list_models()}
    stray = {m for (m, b) in load_terms() if b == HOSTED and m not in ids}
    assert not stray


def test_unreviewed_models_lists_the_rest_of_the_catalogue():
    todo = unreviewed_models()
    assert "fal-ai/flux/dev" not in todo  # has a hosted row
    assert "fal-ai/veo3" in todo
    assert get_terms("fal-ai/veo3", HOSTED) is None


# ── plan-time wiring ────────────────────────────────────────────────────────


def test_plan_refuses_before_any_call_and_default_is_unchanged():
    plan = falaw.plan_generate_image("a cat", model_id="fal-ai/flux/schnell")
    assert plan.application == "fal-ai/flux/schnell"
    with pytest.raises(FalTermsViolation):  # fal-hosted schnell: tenancy unreviewed
        falaw.plan_generate_image(
            "a cat",
            model_id="fal-ai/flux/schnell",
            terms_context=TermsContext(third_party=True),
        )


def test_commercial_hosted_schnell_is_cleared():
    falaw.plan_generate_image(
        "a cat", model_id="fal-ai/flux/schnell", terms_context=TermsContext()
    )


def test_every_plan_function_accepts_terms_context():
    missing = [
        name
        for name, fn in inspect.getmembers(_plan, inspect.isfunction)
        if name.startswith(("plan_", "_plan_"))
        and fn.__module__ == _plan.__name__
        and "terms_context" not in inspect.signature(fn).parameters
    ]
    assert not missing


# ── review regressions ──────────────────────────────────────────────────────

_REFUSE_ALL = TermsContext(third_party=True)


def test_execution_checks_every_call_whatever_its_backend_before_running_any():
    from falaw import CallPlan, Plan, execute_plan

    ok = CallPlan(
        tool="t",
        application="fal-ai/flux/schnell",
        backend=SELF_HOSTED,
        arguments={},
        output_kind="image",
    )
    bad = CallPlan(
        tool="t",
        application="fal-ai/flux/dev",
        backend=SELF_HOSTED,
        arguments={},
        output_kind="image",
    )
    plan = Plan(calls=(ok, bad))
    with pytest.raises(FalTermsViolation, match="forbidden"):
        execute_plan(plan, dry_run=True, terms_context=_REFUSE_ALL)
    assert (
        len(execute_plan(Plan(calls=(ok,)), dry_run=True, terms_context=_REFUSE_ALL))
        == 1
    )
    assert len(execute_plan(plan, dry_run=True)) == 2  # no context: unchanged


def test_a_definite_prohibition_outranks_an_unknown():
    with pytest.raises(FalTermsViolation, match="commercial_use is forbidden"):
        check_terms("fal-ai/mmaudio-v2/text-to-audio", HOSTED, TermsContext())


def test_the_ledger_cannot_be_mutated_by_a_caller():
    with pytest.raises(TypeError):
        load_terms()[("x", "y")] = _row()


def test_tenancy_projection_counts_commercial_use():
    row = _row(commercial_use="forbidden")
    assert not third_party_tenancy_ok("m", "b", ledger=_ledger(row))


def _plan_calls():
    """One refusing-able call per plan_* function (minimal valid arguments)."""
    img = "https://x/y.png"
    aud = "https://x/y.mp3"
    return {
        "plan_generate_image": lambda **k: _plan.plan_generate_image("p", **k),
        "plan_edit_image": lambda **k: _plan.plan_edit_image(img, "p", **k),
        "plan_image_to_video": lambda **k: _plan.plan_image_to_video(img, "p", **k),
        "plan_text_to_video": lambda **k: _plan.plan_text_to_video("p", **k),
        "plan_animate_face": lambda **k: _plan.plan_animate_face(img, aud, **k),
        "plan_lipsync": lambda **k: _plan.plan_lipsync(img, aud, **k),
        "plan_text_to_speech": lambda **k: _plan.plan_text_to_speech("p", **k),
        "plan_generate_audio": lambda **k: _plan.plan_generate_audio("p", **k),
        "plan_generate_image_with_refs": lambda **k: (
            _plan.plan_generate_image_with_refs("p", [img], **k)
        ),
        "plan_composite_character_in_environment": lambda **k: (
            _plan.plan_composite_character_in_environment(img, img, **k)
        ),
        "plan_reference_to_video": lambda **k: _plan.plan_reference_to_video(
            "p", image_urls=[img], **k
        ),
        "plan_llm_complete": lambda **k: _plan.plan_llm_complete("p", **k),
    }


@pytest.mark.parametrize("name", sorted(_plan_calls()))
def test_each_plan_function_really_forwards_the_context(name, monkeypatch):
    """Not just that the parameter exists: a refusing ledger must stop the plan."""
    from falaw import terms

    monkeypatch.setattr(terms, "load_terms", lambda path=None: {})
    with pytest.raises(FalTermsViolation, match="no terms row"):
        _plan_calls()[name](terms_context=TermsContext())


# ── falaw#110: eager verbs, routed models, clearance, one licence vocabulary ──


def test_the_ambient_context_gates_every_eager_entry_point(monkeypatch):
    from falaw import call_fal, using_terms_context
    from falaw.cache import cached_call_fal

    sent = []
    monkeypatch.setattr(
        "falaw.backends.get_backend_executor",
        lambda backend: lambda app, args, **kw: sent.append(app) or {},
    )
    with using_terms_context(TermsContext()):
        with pytest.raises(FalTermsViolation, match="no terms row"):
            cached_call_fal("nobody/reviewed-this", {})
        with pytest.raises(FalTermsViolation, match="no terms row"):
            call_fal("nobody/reviewed-this", {})
        with pytest.raises(FalTermsViolation, match="no terms row"):
            falaw.generate_image("a fox", model_id="nobody/reviewed-this")
    assert sent == []  # refused before anything ran
    cached_call_fal("nobody/reviewed-this", {}, refresh=True)  # scope ended
    assert sent == ["nobody/reviewed-this"]


def test_a_router_is_judged_by_the_model_it_routes_to():
    ctx = TermsContext()
    ok = _row(model_id="vendor/small", backend="fal")
    ledger = _ledger(ok, _row(model_id="fal-ai/any-llm", backend="fal"))
    check_terms(
        "fal-ai/any-llm", "fal", ctx, ledger=ledger, arguments={"model": "vendor/small"}
    )
    with pytest.raises(FalTermsViolation, match="vendor/other"):
        check_terms(
            "fal-ai/any-llm",
            "fal",
            ctx,
            ledger=ledger,
            arguments={"model": "vendor/other"},
        )


def test_a_cleared_plan_proves_it_and_a_retargeted_one_does_not():
    import dataclasses

    ctx = TermsContext(third_party=True)
    call = falaw.plan.make_call_plan(
        tool="generate_image",
        application="fal-ai/flux/schnell",
        arguments={"prompt": "p"},
        output_kind="image",
        backend=SELF_HOSTED,
        consult_cache=False,
        terms_context=ctx,
    )
    from falaw.terms import is_cleared

    assert is_cleared(call, ctx)
    assert not is_cleared(call, TermsContext())
    assert not is_cleared(dataclasses.replace(call, backend="fal"), ctx)
    plain = _plan.plan_generate_image(
        "p", model_id="fal-ai/flux/schnell", consult_cache=False
    )
    assert not is_cleared(plain, ctx)
    assert falaw.plan_hash(falaw.Plan(calls=(call,))) == falaw.plan_hash(
        falaw.Plan(calls=(dataclasses.replace(call, metadata={}),))
    )  # descriptive only: never part of the identity


def test_a_missing_self_hosted_row_says_what_id_to_plan_under():
    with pytest.raises(FalTermsViolation, match="catalogue model id"):
        check_terms("custom-node-id", SELF_HOSTED, TermsContext(), ledger={})


def test_licences_share_one_spdx_vocabulary():
    from falaw.comfyui.licences import KNOWN_LICENCES
    from falaw.licences import is_valid_licence

    assert all(is_valid_licence(k) for k in KNOWN_LICENCES)
    assert all(is_valid_licence(r.license) for r in load_terms().values())
    assert is_valid_licence("MIT OR LicenseRef-x") and is_valid_licence("unknown")
    for bad in ("", "GPL", "MIT OR", "flux-license", "MIT Apache-2.0"):
        assert not is_valid_licence(bad)
    with pytest.raises(ValueError, match="LicenseRef"):
        _row(license="free text")


def test_the_ambient_context_refuses_cached_and_non_fal_executions(monkeypatch):
    from falaw import CallPlan, Plan, execute_plan, using_terms_context

    sent = []
    monkeypatch.setattr(
        "falaw.backends.get_backend_executor",
        lambda backend: lambda app, args, **kw: sent.append(app) or {},
    )
    call = CallPlan(
        tool="t",
        application="nobody/reviewed-this",
        backend="elsewhere",
        arguments={},
        output_kind="json",
    )
    plan = Plan(calls=(call,))
    from falaw.cache import cache_put

    cache_put("nobody/reviewed-this", {}, {"cached": True}, backend="elsewhere")
    with using_terms_context(TermsContext()):
        with pytest.raises(FalTermsViolation, match="no terms row"):
            execute_plan(plan, use_cache=False)
        with pytest.raises(FalTermsViolation, match="no terms row"):
            execute_plan(plan)
    assert sent == []


def test_planning_falls_back_to_the_ambient_context_and_stamps_it():
    from falaw import using_terms_context

    with using_terms_context(TermsContext()):
        with pytest.raises(FalTermsViolation):
            falaw.plan.make_call_plan(
                tool="t",
                application="nobody/reviewed-this",
                arguments={},
                output_kind="json",
            )
        ok = _plan.plan_generate_image(
            "p", model_id="fal-ai/flux/schnell", consult_cache=False
        )
    assert "terms_cleared" in ok.metadata


def test_a_scene_render_cache_hit_is_not_served_under_a_terms_context(monkeypatch):
    from falaw import using_terms_context
    from falaw.operations import render

    served = []
    monkeypatch.setattr(
        render, "cache_get", lambda *a, **k: served.append(a) or {"url": "cached"}
    )
    assert render.current_terms_context() is None
    with using_terms_context(TermsContext()):
        assert render.current_terms_context() is not None
        # the composite cache is skipped, so nothing unchecked can be served
        shot = falaw.Shot(id="s1", description="a fox")
        with pytest.raises(FalTermsViolation):
            render.render_shot(shot, quality="high")
    assert served == []


def test_a_clearance_goes_stale_when_its_ledger_row_is_edited():
    import dataclasses

    from falaw.terms import is_cleared, load_terms

    ctx = TermsContext(third_party=True)
    call = falaw.plan.make_call_plan(
        tool="generate_image",
        application="fal-ai/flux/schnell",
        arguments={"prompt": "p"},
        output_kind="image",
        backend=SELF_HOSTED,
        consult_cache=False,
        terms_context=ctx,
    )
    ledger = dict(load_terms())
    assert is_cleared(call, ctx, ledger=ledger)
    key = ("fal-ai/flux/schnell", SELF_HOSTED)
    ledger[key] = dataclasses.replace(ledger[key], third_party_tenancy="unknown")
    assert not is_cleared(call, ctx, ledger=ledger)


def test_one_routing_rule_serves_terms_and_the_llm_receipt():
    from falaw import routing, terms
    from falaw.operations import llm

    assert terms.ROUTERS is routing.ROUTERS
    assert llm._DEFAULT_LLM in routing.ROUTERS
    args = {"model": "anthropic/claude-sonnet-4.5"}
    assert terms.terms_subject(llm._DEFAULT_LLM, args) == routing.routed_model(
        llm._DEFAULT_LLM, args
    )


def test_the_row_digest_ignores_prose_and_follows_verdicts():
    import dataclasses

    from falaw.terms import get_terms, row_digest

    row = get_terms("fal-ai/flux/schnell", SELF_HOSTED)
    assert row_digest(dataclasses.replace(row, notes="reworded")) == row_digest(row)
    assert row_digest(dataclasses.replace(row, commercial_use="unknown")) != row_digest(
        row
    )
