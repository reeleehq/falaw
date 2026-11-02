"""Tests for the third cache mode — ``refresh=True``: skip the read, keep the write.

The defect these pin down (falaw#49, observed downstream as thorwhalen/reelee#384):
``use_cache`` was one flag doing two jobs, so a caller who reached for
``use_cache=False`` to mean *"ignore any cached answer"* also got *"and discard
the fresh one"*. That turns "re-verify this plan" into a guaranteed double
charge, because the next consumer re-bills the result the forced run already
paid for and threw away.

Every fal call here goes through a **counting** fake ``fal_client``, so the
assertions are on vendor-call counts — the unit the defect is measured in — not
on cache internals. Nothing reaches a paid API; the suite's autouse offline
fixtures (``tests/conftest.py``) cover the asset transport and the on-disk
stores.
"""

from __future__ import annotations

import sys
import types

import pytest

from falaw.plan import CallPlan, Plan, execute, execute_isolated

IMAGE_APPLICATION = "fal-ai/flux/dev"
VIDEO_APPLICATION = "fal-ai/hailuo/image-to-video"


def _install_counting_fal(monkeypatch) -> list[str]:
    """Install a fake ``fal_client`` that records one entry per vendor call.

    Returns the (live) list of applications called, in order. Its ``len`` is
    the spend: every entry is a call falaw would have been billed for.

    Every call mints a **fresh** URL, as fal does — that is the property the
    content-addressing tests turn on. The counter is per application, not
    global, so the n-th image is always ``i{n}.png`` however many video calls
    happen around it; a test that pins bytes to a URL needs to be able to name
    that URL without simulating the whole call sequence in its head.
    """
    called: list[str] = []
    minted: dict[str, int] = {}

    def subscribe(application, *, arguments, with_logs, on_queue_update):
        called.append(application)
        nth = minted[application] = minted.get(application, 0) + 1
        if "image-to-video" in application:
            return {
                "video": {
                    "url": f"https://fal.media/v{nth}.mp4",
                    "content_type": "video/mp4",
                }
            }
        return {
            "images": [
                {
                    "url": f"https://fal.media/i{nth}.png",
                    "content_type": "image/png",
                }
            ]
        }

    fake = types.SimpleNamespace(
        InProgress=type("InProgress", (), {"__init__": lambda self, logs: None}),
        subscribe=subscribe,
    )
    monkeypatch.setitem(sys.modules, "fal_client", fake)
    return called


def _image_plan(prompt: str = "a red panda") -> Plan:
    return Plan(
        calls=(
            CallPlan(
                tool="generate_image",
                application=IMAGE_APPLICATION,
                arguments={"prompt": prompt},
                output_kind="image",
                estimated_cost_usd=0.025,
            ),
        )
    )


def _chained_plan(prompt: str = "a red panda") -> Plan:
    """An image feeding an image-to-video — the shape with no caller workaround.

    Pre-dropping cache entries before an ordinary ``use_cache=True`` run is the
    workaround reelee considered and rejected: a chained call's *key* arguments
    hold ``"<from 0>"``, which cannot be resolved until call 0 has executed, so
    there is no key to drop ahead of time.
    """
    return Plan(
        calls=(
            CallPlan(
                tool="generate_image",
                application=IMAGE_APPLICATION,
                arguments={"prompt": prompt},
                output_kind="image",
                estimated_cost_usd=0.025,
            ),
            CallPlan(
                tool="image_to_video",
                application=VIDEO_APPLICATION,
                arguments={"image_url": "<from 0>"},
                output_kind="video",
                estimated_cost_usd=0.50,
            ),
        )
    )


# --- the regression: a forced re-run must not be a double spend --------------


def test_refresh_run_leaves_its_paid_result_in_the_cache(monkeypatch):
    """The reelee#384 sequence, in vendor calls: forced replay, then a consumer.

    Cold cache. The forced run re-executes (1 call) and **keeps** what it paid
    for, so the ordinary follow-up run — the ``run_stage`` in reelee's trace —
    is served from the cache and bills nothing. Total: 1.

    This is the assertion that fails if ``refresh=True`` is collapsed back into
    ``use_cache=False``: that mode never reaches ``cached_call_fal``, so it
    writes nothing, the follow-up re-bills, and the total is 2.
    """
    called = _install_counting_fal(monkeypatch)
    plan = _image_plan()

    execute(plan, use_cache=True, refresh=True)
    assert len(called) == 1, "the forced run itself executes exactly once"

    execute(plan)

    assert len(called) == 1, (
        "the forced run's paid result must be reusable — a follow-up run that "
        "re-bills means the re-run discarded what it bought (falaw#49)"
    )


def test_refresh_over_a_chained_plan_caches_every_call(monkeypatch):
    """The placeholder case: both entries survive, including the downstream one.

    Necessary but **not sufficient** — it cannot tell content-keying from
    URL-keying, because the second run's upstream is itself a cache hit and
    replays the same recorded URL, so a URL-keyed downstream would hit too.
    :func:`test_refresh_keys_the_downstream_call_on_content_not_url` and
    :func:`test_a_regenerated_upstream_still_hits_the_downstream_entry` are the
    two that discriminate.
    """
    called = _install_counting_fal(monkeypatch)
    plan = _chained_plan()

    execute(plan, use_cache=True, refresh=True)
    assert len(called) == 2, "two calls in the plan, two vendor calls"

    execute(plan)

    assert len(called) == 2, "both entries — image and video — must be reusable"


def _manifests_for(application: str) -> list[dict]:
    """Every cache manifest written for ``application``, read off disk.

    Read rather than reconstructed: recomputing the key here would use the same
    code path the test is trying to hold to account, so the assertion would
    agree with the bug.
    """
    import json
    import os

    from falaw.cache import _cache_dir

    found = []
    for root, _dirs, files in os.walk(_cache_dir()):
        for name in files:
            if name != "manifest.json":
                continue
            with open(os.path.join(root, name)) as f:
                manifest = json.load(f)
            if manifest.get("application") == application:
                found.append(manifest)
    return found


def test_refresh_keys_the_downstream_call_on_content_not_url(monkeypatch):
    """Under ``refresh``, the downstream entry is keyed on the upstream's hash.

    ``refresh`` leaves ``use_cache`` True, so ``_run_plan`` still resolves the
    *key* arguments with the strict ref. A mode that fell back to the wire
    arguments would key the video on a fal URL — minted fresh per upload — and
    the entry could never be reached again. Asserted on the manifest that was
    actually written, not on a recomputed key.
    """
    _install_counting_fal(monkeypatch)

    execute(_chained_plan(), use_cache=True, refresh=True)

    (video,) = _manifests_for(VIDEO_APPLICATION)
    keyed_on = video["arguments"]["image_url"]
    assert keyed_on.startswith("sha256:"), (
        f"the downstream entry is keyed on {keyed_on!r}; a fal URL there means "
        "refresh dropped back to the wire arguments and the entry is dead"
    )
    assert video["wire_arguments"]["image_url"].startswith("https://fal.media/"), (
        "the wire arguments must still carry the URL fal needs to fetch"
    )


def test_a_regenerated_upstream_still_hits_the_downstream_entry(
    monkeypatch, fake_assets
):
    """The behavioural half: a *new* upstream URL over identical bytes still hits.

    This is the sequence a URL-keyed downstream cannot survive, and the one the
    plain "run it twice" test cannot produce (there the upstream is a cache hit
    replaying its recorded URL, so the URL never changes):

    1. render the chain under ``refresh`` — upstream ``i1.png``, downstream
       keyed on the bytes behind it;
    2. re-render the **upstream alone** under ``refresh`` — fal mints
       ``i2.png``, a different URL over byte-identical content;
    3. run the whole chain at the default — the upstream now resolves to
       ``i2.png``.

    Keyed on content, step 3 costs nothing. Keyed on the URL, the downstream
    misses and re-bills the expensive call.
    """
    shared = fake_assets.serve("https://fal.media/i1.png", b"one upstream render")
    fake_assets.serve("https://fal.media/i2.png", shared)

    called = _install_counting_fal(monkeypatch)
    chained, upstream_only = _chained_plan(), _image_plan()

    execute(chained, use_cache=True, refresh=True)
    assert called == [IMAGE_APPLICATION, VIDEO_APPLICATION]

    execute(upstream_only, use_cache=True, refresh=True)
    assert len(called) == 3, "the upstream re-render is its own vendor call"

    execute(chained)

    assert len(called) == 3, (
        "a byte-identical upstream regeneration must leave the downstream "
        "entry reachable — an extra call here means it was keyed on the fal "
        "URL, which is minted fresh per upload"
    )


def test_refresh_skips_the_read_so_a_warm_cache_still_re_executes(monkeypatch):
    """The other half of the mode: it is a *re-run*, not a no-op on a warm cache."""
    called = _install_counting_fal(monkeypatch)
    plan = _image_plan()

    execute(plan)
    assert len(called) == 1

    execute(plan)
    assert len(called) == 1, "the default mode reads the cache"

    execute(plan, use_cache=True, refresh=True)
    assert len(called) == 2, "refresh must ignore the warm entry and re-execute"


# --- the existing mode keeps its meaning ------------------------------------


def test_use_cache_false_still_writes_nothing(monkeypatch):
    """``use_cache=False`` is unchanged: it touches the cache at neither end.

    Silently redefining it would be worse than the gap this issue closes —
    "do not touch the cache at all" is a legitimate thing to ask for, and it is
    the only mode that provides it.
    """
    called = _install_counting_fal(monkeypatch)
    plan = _image_plan()

    execute(plan, use_cache=False)
    assert len(called) == 1

    execute(plan)

    assert len(called) == 2, (
        "use_cache=False must keep writing nothing — a follow-up run re-bills"
    )


def test_use_cache_false_still_ignores_a_warm_cache(monkeypatch):
    """And it still skips the read, so it remains a genuine re-run."""
    called = _install_counting_fal(monkeypatch)
    plan = _image_plan()

    execute(plan)
    assert len(called) == 1

    execute(plan, use_cache=False)
    assert len(called) == 2


def test_default_mode_reads_and_writes(monkeypatch):
    """The default is unmoved: first run bills, second run does not."""
    called = _install_counting_fal(monkeypatch)
    plan = _image_plan()

    execute(plan)
    execute(plan)

    assert len(called) == 1


# --- the fourth corner has no meaning ----------------------------------------


def test_refresh_with_use_cache_off_raises(monkeypatch):
    """``use_cache=False, refresh=True`` is contradictory, so it is refused.

    There is no key to write under when the cache is off, and picking one of
    the two intents silently would hand the caller a spend policy they did not
    ask for.
    """
    called = _install_counting_fal(monkeypatch)

    with pytest.raises(ValueError, match="refresh=True requires use_cache=True"):
        execute(_image_plan(), use_cache=False, refresh=True)

    assert called == [], "the refusal must happen before anything is billed"


def test_refresh_with_use_cache_off_raises_from_execute_isolated(monkeypatch):
    """The isolated executor refuses it too — this is a run-level configuration
    error, not a per-call failure to be reported as an outcome."""
    _install_counting_fal(monkeypatch)

    with pytest.raises(ValueError, match="refresh=True requires use_cache=True"):
        execute_isolated(_image_plan(), use_cache=False, refresh=True)


# --- the seam is available on both executors ---------------------------------


def test_execute_isolated_honours_refresh(monkeypatch):
    """``execute_plan_isolated`` gets the same three modes as ``execute_plan``."""
    called = _install_counting_fal(monkeypatch)
    plan = _image_plan()

    report = execute_isolated(plan, use_cache=True, refresh=True)
    assert report.is_complete
    assert len(called) == 1

    execute(plan)
    assert len(called) == 1, "the isolated executor writes what it paid for too"


def test_refresh_is_keyword_only():
    """A positional third argument must not silently land on ``refresh``."""
    with pytest.raises(TypeError):
        execute(_image_plan(), None, False, True, True)  # type: ignore[misc]


# --- uncached(plan): the quote for a cache-skipping run (falaw#139) ---------


def _quoted(status: str, cost):
    return CallPlan(
        tool="generate_image",
        application=IMAGE_APPLICATION,
        arguments={"prompt": status},
        output_kind="image",
        estimated_cost_usd=cost,
        cache_status=status,
    )


def test_uncached_bills_every_call_a_predicted_hit_included():
    from falaw import uncached_plan

    plan = Plan(
        calls=(_quoted("hit", 0.03), _quoted("miss", 0.05), _quoted("unknown", 0.07))
    )
    assert plan.total_cost_usd == pytest.approx(0.12)
    billed = uncached_plan(plan)
    assert [c.cache_status for c in billed.calls] == ["miss"] * 3
    assert billed.total_cost_usd == pytest.approx(0.15)
    assert billed.cache_hit_savings_usd == 0.0


def test_uncached_makes_an_unpriced_hit_unknown_not_free():
    from falaw import uncached_plan

    plan = Plan(calls=(_quoted("hit", None),))
    assert plan.has_unknown_costs is False  # a hit bills nothing
    assert uncached_plan(plan).has_unknown_costs is True


def test_uncached_changes_nothing_but_cache_status_and_leaves_the_plan_alone(
    tmp_path,
):
    """Every other field survives, on the wire and in identity.

    Built with every optional :class:`CallPlan` field off its default, so a
    rewrite that dropped or reset one (a fresh ``CallPlan(...)`` instead of
    ``replace``) shows up in the serialized dict.
    """
    from falaw import (
        CostBasis,
        plan_from_dict,
        plan_hash,
        plan_to_dict,
        uncached_plan,
    )
    from falaw.upload import localize_paths

    source = tmp_path / "ref.png"
    source.write_bytes(b"reference")
    arguments, local_files = localize_paths({"prompt": "p", "image": source})
    call = CallPlan(
        tool="generate_image",
        application=IMAGE_APPLICATION,
        backend="other-backend",
        arguments=arguments,
        output_kind="image",
        estimated_cost_usd=0.03,
        cache_status="hit",
        expected_duration_s=(1.0, 2.0),
        expected_wall_time_s=(3.0, 4.0),
        metadata={"shot_id": "s1"},
        key_extra={"impl_version": "2"},
        local_files=local_files,
        cost_basis=CostBasis(
            pricer="model_catalogue",
            priced=IMAGE_APPLICATION,
            quantities={"images": 1},
            table="t.json",
            table_version="v1",
        ),
    )
    plan = Plan(calls=(call,))
    billed = uncached_plan(plan)

    assert plan.calls[0].cache_status == "hit"  # the input is not mutated
    assert billed.calls[0].cache_status == "miss"

    def without_status(d):
        return {**d, "calls": [{**c, "cache_status": None} for c in d["calls"]]}

    assert without_status(plan_to_dict(billed)) == without_status(plan_to_dict(plan))
    assert plan_from_dict(plan_to_dict(billed)) == billed
    assert plan_hash(billed) == plan_hash(plan)  # same work, different quote


# --- priced_as_run: the quote for a run, from execute's own keywords --------


def _total_billed(artifacts) -> float:
    return sum(a.cost_usd for a in artifacts)


def test_priced_as_run_quotes_what_each_cache_mode_bills(monkeypatch):
    """The quote and the run agree, mode by mode, over a predicted hit.

    The cache is warmed for one call, so the planner predicts a hit there and a
    miss for the other. The default run reads the cache and bills only the
    miss; ``refresh=True`` and ``use_cache=False`` skip the read and bill both.
    Quoting ``refresh=True`` from ``use_cache`` alone would price it as the
    default run, the under-quote ``priced_as_run`` exists to prevent.
    """
    from falaw import make_call_plan, priced_as_run, uncached_plan

    called = _install_counting_fal(monkeypatch)
    execute(_image_plan("warm"))
    assert len(called) == 1

    def planned(prompt, cost):
        return make_call_plan(
            tool="generate_image",
            application=IMAGE_APPLICATION,
            arguments={"prompt": prompt},
            output_kind="image",
            estimated_cost_usd=cost,
        )

    plan = Plan(calls=(planned("warm", 0.025), planned("cold", 0.04)))
    assert [c.cache_status for c in plan.calls] == ["hit", "miss"]
    assert priced_as_run(plan) is plan
    assert plan.total_cost_usd == pytest.approx(0.04)

    # Order matters: the default run writes "cold", which the later runs skip
    # reading anyway.
    assert _total_billed(execute(plan)) == pytest.approx(plan.total_cost_usd)

    refreshed = priced_as_run(plan, use_cache=True, refresh=True)
    assert refreshed.total_cost_usd == pytest.approx(0.065)
    assert _total_billed(execute(plan, refresh=True)) == pytest.approx(
        refreshed.total_cost_usd
    )

    bypassed = priced_as_run(plan, use_cache=False)
    assert bypassed.total_cost_usd == uncached_plan(plan).total_cost_usd
    assert _total_billed(execute(plan, use_cache=False)) == pytest.approx(
        bypassed.total_cost_usd
    )


def test_priced_as_run_refuses_the_fourth_corner_like_execute():
    from falaw import priced_as_run

    with pytest.raises(ValueError, match="refresh=True requires use_cache=True"):
        priced_as_run(_image_plan(), use_cache=False, refresh=True)


def test_priced_as_run_cache_keywords_are_keyword_only():
    from falaw import priced_as_run

    with pytest.raises(TypeError):
        priced_as_run(_image_plan(), False)  # type: ignore[misc]
