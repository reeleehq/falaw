"""Tests for falaw.plan — Plan/CallPlan primitives + execute()."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from falaw.plan import (
    CallPlan,
    Plan,
    execute,
    make_call_plan,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FALAW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))
    from falaw.events import clear_subscribers
    from falaw.journal import _default_journal

    _default_journal.cache_clear()
    clear_subscribers()
    yield
    clear_subscribers()
    _default_journal.cache_clear()


def _install_fake_fal(monkeypatch, *, response):
    def subscribe(application, *, arguments, with_logs, on_queue_update):
        return response

    fake = types.SimpleNamespace(
        InProgress=type("InProgress", (), {"__init__": lambda self, logs: None}),
        subscribe=subscribe,
    )
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    return fake


# --- CallPlan / Plan basics --------------------------------------------------


def test_callplan_billable_cost_normal():
    p = CallPlan(
        tool="generate_image",
        application="fal-ai/flux/dev",
        arguments={"prompt": "x"},
        output_kind="image",
        estimated_cost_usd=0.025,
        cache_status="miss",
    )
    assert p.billable_cost_usd == 0.025


def test_callplan_billable_cost_cache_hit_is_zero():
    p = CallPlan(
        tool="generate_image",
        application="fal-ai/flux/dev",
        arguments={"prompt": "x"},
        output_kind="image",
        estimated_cost_usd=0.025,
        cache_status="hit",
    )
    assert p.billable_cost_usd == 0.0


def test_callplan_billable_cost_unknown_estimate_is_zero():
    p = CallPlan(
        tool="generate_image",
        application="fal-ai/flux/dev",
        arguments={"prompt": "x"},
        output_kind="image",
        estimated_cost_usd=None,
        cache_status="miss",
    )
    assert p.billable_cost_usd == 0.0


def test_plan_total_cost_sums_billable():
    a = CallPlan(
        tool="x",
        application="m1",
        arguments={},
        output_kind="image",
        estimated_cost_usd=0.10,
        cache_status="miss",
    )
    b = CallPlan(
        tool="y",
        application="m2",
        arguments={},
        output_kind="video",
        estimated_cost_usd=0.50,
        cache_status="hit",
    )
    plan = Plan(calls=(a, b))
    # b is a hit → contributes 0; a is a miss → contributes 0.10
    assert plan.total_cost_usd == pytest.approx(0.10)
    assert plan.cache_hit_savings_usd == pytest.approx(0.50)


def test_plan_concatenation():
    p1 = CallPlan(tool="t1", application="m1", arguments={}, output_kind="image")
    p2 = CallPlan(tool="t2", application="m2", arguments={}, output_kind="video")
    a = Plan(calls=(p1,))
    b = Plan(calls=(p2,))
    combined = a + b
    assert combined.calls == (p1, p2)
    assert len(combined) == 2


def test_plan_indexing_and_iteration():
    p1 = CallPlan(tool="t1", application="m1", arguments={}, output_kind="image")
    p2 = CallPlan(tool="t2", application="m2", arguments={}, output_kind="video")
    plan = Plan(calls=(p1, p2))
    assert plan[0] is p1
    assert list(plan) == [p1, p2]


def test_plan_with_call_replaced():
    p1 = CallPlan(
        tool="t1",
        application="m1",
        arguments={},
        output_kind="image",
        estimated_cost_usd=0.10,
        cache_status="miss",
    )
    p2 = CallPlan(
        tool="t2",
        application="m2",
        arguments={},
        output_kind="image",
        estimated_cost_usd=0.20,
        cache_status="miss",
    )
    plan = Plan(calls=(p1,))
    new_plan = plan.with_call_replaced(0, p2)
    assert plan.calls == (p1,)  # original unchanged
    assert new_plan.calls == (p2,)


def test_plan_has_unknown_costs():
    a = CallPlan(
        tool="x",
        application="m1",
        arguments={},
        output_kind="image",
        estimated_cost_usd=0.10,
        cache_status="miss",
    )
    plan_known = Plan(calls=(a,))
    assert plan_known.has_unknown_costs is False

    b = CallPlan(
        tool="y",
        application="m2",
        arguments={},
        output_kind="video",
        estimated_cost_usd=None,
        cache_status="miss",
    )
    plan_unknown = Plan(calls=(a, b))
    assert plan_unknown.has_unknown_costs is True

    # Cache hits with unknown cost don't trigger has_unknown_costs:
    # they're a hit, the call won't bill, so the unknown estimate is moot.
    c = CallPlan(
        tool="z",
        application="m3",
        arguments={},
        output_kind="image",
        estimated_cost_usd=None,
        cache_status="hit",
    )
    plan_hit_only = Plan(calls=(a, c))
    assert plan_hit_only.has_unknown_costs is False


# --- make_call_plan with cache awareness -------------------------------------


def test_make_call_plan_no_cache_consult():
    p = make_call_plan(
        tool="generate_image",
        application="fal-ai/flux/dev",
        arguments={"prompt": "x"},
        output_kind="image",
        consult_cache=False,
    )
    assert p.cache_status == "unknown"


def test_make_call_plan_cache_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))
    p = make_call_plan(
        tool="generate_image",
        application="fal-ai/flux/dev",
        arguments={"prompt": "fresh request"},
        output_kind="image",
    )
    assert p.cache_status == "miss"


def test_make_call_plan_cache_hit(tmp_path, monkeypatch):
    """Pre-populate the cache, then planning should report 'hit'."""
    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))
    from falaw.cache import cache_put

    cache_put(
        "fal-ai/flux/dev",
        {"prompt": "hello"},
        {"images": [{"url": "http://x/cached.png"}]},
        note="fixture",
    )

    p = make_call_plan(
        tool="generate_image",
        application="fal-ai/flux/dev",
        arguments={"prompt": "hello"},
        output_kind="image",
    )
    assert p.cache_status == "hit"


# --- execute() ---------------------------------------------------------------


def test_execute_dry_run_yields_synthetic_artifacts():
    p1 = CallPlan(
        tool="generate_image",
        application="fal-ai/flux/dev",
        arguments={"prompt": "tiger"},
        output_kind="image",
        estimated_cost_usd=0.025,
        cache_status="miss",
    )
    p2 = CallPlan(
        tool="image_to_video",
        application="fal-ai/minimax/hailuo-02/pro/image-to-video",
        arguments={"image_url": "<from p1>"},
        output_kind="video",
        estimated_cost_usd=0.50,
        cache_status="miss",
    )
    plan = Plan(calls=(p1, p2))

    artifacts = execute(plan, dry_run=True)
    assert len(artifacts) == 2
    assert artifacts[0].kind == "image"
    assert artifacts[1].kind == "video"
    assert artifacts[0].url is None  # synthetic — no URL
    assert artifacts[0].bytes_size == 0
    assert artifacts[0].producer_call_id.startswith("dry-run:")


def test_execute_dry_run_is_deterministic():
    """Two dry-runs of the same Plan produce Artifacts with the same asset_ids.
    This lets tests assert on Artifact.id without time-coupling."""
    p1 = CallPlan(
        tool="generate_image",
        application="fal-ai/flux/dev",
        arguments={"prompt": "tiger"},
        output_kind="image",
    )
    plan = Plan(calls=(p1,))
    a1 = execute(plan, dry_run=True)[0]
    a2 = execute(plan, dry_run=True)[0]
    assert a1.asset_id == a2.asset_id


def test_execute_real_call_produces_artifact_with_url(monkeypatch):
    _install_fake_fal(
        monkeypatch,
        response={"images": [{"url": "http://x/img.png", "content_type": "image/png"}]},
    )

    p1 = CallPlan(
        tool="generate_image",
        application="fal-ai/flux/dev",
        arguments={"prompt": "x"},
        output_kind="image",
        estimated_cost_usd=0.025,
        cache_status="miss",
    )
    artifacts = execute(Plan(calls=(p1,)), use_cache=False)
    assert len(artifacts) == 1
    assert artifacts[0].url == "http://x/img.png"
    assert artifacts[0].kind == "image"
    assert artifacts[0].mime == "image/png"
    assert artifacts[0].cost_usd == 0.025


def test_execute_video_response_extracts_url_and_duration(monkeypatch):
    _install_fake_fal(
        monkeypatch,
        response={
            "video": {
                "url": "http://x/v.mp4",
                "duration": 8.0,
                "content_type": "video/mp4",
            }
        },
    )

    p = CallPlan(
        tool="image_to_video",
        application="fal-ai/hailuo",
        arguments={"image_url": "x"},
        output_kind="video",
        estimated_cost_usd=0.50,
        cache_status="miss",
    )
    artifacts = execute(Plan(calls=(p,)), use_cache=False)
    assert artifacts[0].url == "http://x/v.mp4"
    assert artifacts[0].duration_s == 8.0


def test_execute_uses_cache_by_default(monkeypatch, tmp_path):
    """With use_cache=True (default), a second execute over the same Plan
    doesn't re-fire the fal call."""
    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "cache"))

    call_count = [0]

    def subscribe(application, *, arguments, with_logs, on_queue_update):
        call_count[0] += 1
        return {"images": [{"url": "http://x/img.png", "content_type": "image/png"}]}

    fake = types.SimpleNamespace(InProgress=type("IP", (), {}), subscribe=subscribe)
    monkeypatch.setitem(sys.modules, "fal_client", fake)

    p = CallPlan(
        tool="generate_image",
        application="fal-ai/flux/dev",
        arguments={"prompt": "cache-me"},
        output_kind="image",
    )
    plan = Plan(calls=(p,))

    a1 = execute(plan)
    a2 = execute(plan)
    assert call_count[0] == 1, "second execute should hit the cache, not refire"
    assert a1[0].url == a2[0].url


def test_execute_custom_artifact_converter(monkeypatch):
    """Custom converters let callers normalize unusual response shapes."""
    _install_fake_fal(monkeypatch, response={"weird_field": "http://x/special.bin"})

    def my_converter(raw, call):
        from lacing import Artifact
        from lacing.artifact import _now_rt
        from lacing.model import Provenance

        return Artifact(
            asset_id="0" * 64,
            kind=call.output_kind,
            path=None,
            url=raw.get("weird_field"),
            bytes_size=42,
            duration_s=None,
            mime=None,
            provenance=Provenance(
                was_generated_by="test",
                was_attributed_to="test",
                generated_at_time=_now_rt(),
            ),
            cost_usd=None,
            producer_call_id=None,
        )

    p = CallPlan(
        tool="weird_op",
        application="fal-ai/weird",
        arguments={},
        output_kind="binary",
    )
    artifacts = execute(
        Plan(calls=(p,)), use_cache=False, artifact_converter=my_converter
    )
    assert artifacts[0].url == "http://x/special.bin"
    assert artifacts[0].bytes_size == 42


def test_execute_empty_plan_returns_empty_list():
    assert execute(Plan(calls=()), dry_run=True) == []
    assert execute(Plan(calls=())) == []


# --- placeholder resolution -------------------------------------------------


def test_placeholder_resolution_in_execute(monkeypatch):
    """`<from N>` in a CallPlan's arguments resolves to artifacts[N].url at execute time."""
    captured: list[dict] = []

    def subscribe(application, *, arguments, with_logs, on_queue_update):
        captured.append({"app": application, "args": dict(arguments)})
        if "image_to_video" in application or "hailuo" in application:
            return {
                "video": {
                    "url": "http://x/v.mp4",
                    "duration": 8.0,
                    "content_type": "video/mp4",
                }
            }
        return {"images": [{"url": "http://x/img.png", "content_type": "image/png"}]}

    fake = types.SimpleNamespace(InProgress=type("IP", (), {}), subscribe=subscribe)
    monkeypatch.setitem(sys.modules, "fal_client", fake)

    p1 = CallPlan(
        tool="generate_image",
        application="fal-ai/flux/dev",
        arguments={"prompt": "x"},
        output_kind="image",
    )
    p2 = CallPlan(
        tool="image_to_video",
        application="fal-ai/minimax/hailuo-02/pro/image-to-video",
        arguments={"image_url": "<from 0>", "prompt": "spin"},
        output_kind="video",
    )
    plan = Plan(calls=(p1, p2))
    artifacts = execute(plan, use_cache=False)
    assert len(captured) == 2
    # Second call should have received the URL from the first artifact, not the literal placeholder.
    assert captured[1]["args"]["image_url"] == artifacts[0].url
    assert captured[1]["args"]["prompt"] == "spin"


def test_placeholder_bad_index_raises(monkeypatch):
    p1 = CallPlan(
        tool="generate_image",
        application="fal-ai/flux/dev",
        arguments={"prompt": "x"},
        output_kind="image",
    )
    p2 = CallPlan(
        tool="t",
        application="m",
        arguments={"image_url": "<from 5>"},  # only 1 artifact will exist
        output_kind="video",
    )
    fake = types.SimpleNamespace(
        InProgress=type("IP", (), {}),
        subscribe=lambda app, **k: {"images": [{"url": "http://x/i.png"}]},
    )
    monkeypatch.setitem(sys.modules, "fal_client", fake)

    with pytest.raises(ValueError, match="references artifact index 5"):
        execute(Plan(calls=(p1, p2)), use_cache=False)


def test_placeholder_in_nested_dict(monkeypatch):
    """Placeholder rewriting recurses into nested dicts too."""
    captured: list[dict] = []

    def subscribe(application, *, arguments, with_logs, on_queue_update):
        captured.append(dict(arguments))
        return {"images": [{"url": "http://x/y.png"}]}

    fake = types.SimpleNamespace(InProgress=type("IP", (), {}), subscribe=subscribe)
    monkeypatch.setitem(sys.modules, "fal_client", fake)

    p1 = CallPlan(tool="t1", application="m1", arguments={}, output_kind="image")
    p2 = CallPlan(
        tool="t2",
        application="m2",
        arguments={"options": {"reference_image": "<from 0>"}},
        output_kind="image",
    )
    artifacts = execute(Plan(calls=(p1, p2)), use_cache=False)
    assert captured[1]["options"]["reference_image"] == artifacts[0].url
