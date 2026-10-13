"""Tests for ``CallPlan.key_extra`` — declared identity beyond wire args.

The field exists so a caller can say "a cached result minted without this
value must not be reused" (nw#27's Transform ``impl_version`` is the first
customer) — without renaming anything and, critically, without changing a
single existing key: empty means absent, everywhere.
"""

from __future__ import annotations

import sys
import threading
import types

import pytest

from falaw import CallPlan, Plan, call_plan_from_dict, call_plan_to_dict, plan_hash
from falaw.canonical import cache_key_payload, plan_identity_payload
from falaw import execute_plan_isolated


def _call(**overrides) -> CallPlan:
    base = dict(
        tool="generate_image",
        application="m/a",
        arguments={"prompt": "p"},
        output_kind="image",
        estimated_cost_usd=0.025,
    )
    base.update(overrides)
    return CallPlan(**base)


class TestKeyStability:
    def test_empty_key_extra_leaves_every_payload_byte_identical(self):
        """The omit-if-empty rule: no key ever issued changes."""
        assert (
            cache_key_payload("m/a", {"x": 1})
            == cache_key_payload("m/a", {"x": 1}, key_extra=None)
            == cache_key_payload("m/a", {"x": 1}, key_extra={})
            == {
                "app": "m/a",
                "args": {"x": 1},
            }
        )
        assert plan_identity_payload("m/a", {"x": 1}, tool="t") == {
            "app": "m/a",
            "args": {"x": 1},
            "tool": "t",
        }

    def test_plan_hash_unchanged_without_key_extra_and_changed_with(self):
        without = plan_hash(Plan(calls=(_call(),)))
        again = plan_hash(Plan(calls=(_call(),)))
        with_extra = plan_hash(Plan(calls=(_call(key_extra={"impl": "2"}),)))

        assert without == again
        assert with_extra != without

    def test_key_extra_round_trips_through_the_dict_form(self):
        call = _call(key_extra={"impl": "2"})

        rebuilt = call_plan_from_dict(call_plan_to_dict(call))

        assert rebuilt.key_extra == {"impl": "2"}
        # A dict written before the field existed still parses.
        legacy = call_plan_to_dict(_call())
        legacy.pop("key_extra")
        assert call_plan_from_dict(legacy).key_extra == {}


class _FakeFal:
    def __init__(self) -> None:
        self.calls: list = []
        self._lock = threading.Lock()

    def subscribe(
        self, application, *, arguments, with_logs=True, on_queue_update=None
    ):
        with self._lock:
            self.calls.append((application, dict(arguments)))
        return {"images": [{"url": f"http://x/{len(self.calls)}.png"}]}

    def module(self):
        return types.SimpleNamespace(
            InProgress=type("InProgress", (), {}), subscribe=self.subscribe
        )


@pytest.fixture
def fal(monkeypatch) -> _FakeFal:
    stub = _FakeFal()
    monkeypatch.setitem(sys.modules, "fal_client", stub.module())
    return stub


class TestCacheIsolation:
    def test_different_key_extra_never_shares_a_cache_entry(self, fal):
        """Same wire call, different declared identity: two vendor calls."""
        plain = Plan(calls=(_call(),))
        salted = Plan(calls=(_call(key_extra={"impl": "2"}),))

        execute_plan_isolated(plain)
        report = execute_plan_isolated(salted)

        assert len(fal.calls) == 2  # the salted call did NOT reuse the entry
        assert report.outcomes[0].cache_hit is False

    def test_same_key_extra_shares_its_own_entry(self, fal):
        salted = Plan(calls=(_call(key_extra={"impl": "2"}),))

        execute_plan_isolated(salted)
        report = execute_plan_isolated(salted)

        assert len(fal.calls) == 1
        assert report.outcomes[0].cache_hit is True
