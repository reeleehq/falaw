"""``falaw.testing`` — the fake asset transport falaw owns so consumers don't.

Every test here is a guard on a property that was *measured* downstream and
that a naive shared helper would quietly lose (thorwhalen/falaw#27):

* the fake must reach every entry point, including a consumer module that
  bound ``falaw.execute_plan`` at import time;
* it must reach a thread the installer never created;
* an explicit ``fetcher=`` must still win;
* ``file://`` must not be faked;
* and — the one that keeps biting — **refusing is not reporting**: falaw
  funnels a failed fetch through ``except Exception`` and *degrades* it to a
  URL-only artifact with a warning, so a guard that only raises leaves the
  suite green with the regression back in place. Both the fake and the network
  guard therefore *record*, and the recording is what is asserted.

Note the issue's claim that ``execute_isolated`` catches ``BaseException`` into
an outcome is **wrong** — ``_outcome_from_future`` re-raises a non-``Exception``
deliberately. The two tests at the bottom pin down what actually happens in
each case, so neither belief has to be taken on trust again.
"""

import sys
import threading
import types
import warnings

import pytest

from falaw import (
    CallPlan,
    Plan,
    content_ref_for_url,
    execute_plan,
    execute_plan_isolated,
    materialize_asset,
)
from falaw.content import _http_chunks, default_url_fetcher, using_url_fetcher
from falaw.testing import (
    FakeAssets,
    OutboundNetworkAttempt,
    blocked_outbound_network,
    is_network_url,
    serving_fake_assets,
    synthetic_asset_bytes,
)


# A consumer module that binds falaw's entry points *at import time* — the
# shape that makes patching ``falaw.execute_plan`` by name useless, and the
# reason the seam is the fallback fetcher rather than the public kwargs.
_bound_execute_plan = execute_plan
_bound_materialize_asset = materialize_asset


IMG = b"\x89PNG\r\n\x1a\n" + b"pixels"


class FakeFal:
    """A ``fal_client`` stub returning whatever URL the test names."""

    def __init__(self) -> None:
        self.behaviour: dict[str, dict] = {}

    def responds(self, application: str, response: dict) -> None:
        self.behaviour[application] = response

    def subscribe(
        self, application, *, arguments, with_logs=True, on_queue_update=None
    ):
        return self.behaviour.get(
            application, {"images": [{"url": f"http://cdn/{application}.png"}]}
        )


@pytest.fixture
def fal(monkeypatch) -> FakeFal:
    stub = FakeFal()
    monkeypatch.setitem(
        sys.modules,
        "fal_client",
        types.SimpleNamespace(
            InProgress=type("InProgress", (), {}), subscribe=stub.subscribe
        ),
    )
    return stub


def _image_plan(application: str = "m/img") -> Plan:
    return Plan(
        calls=(
            CallPlan(
                tool="generate_image",
                application=application,
                arguments={"prompt": application},
                output_kind="image",
            ),
        )
    )


# --- FakeAssets, on its own -------------------------------------------------


def test_an_unpinned_url_serves_deterministic_synthetic_bytes():
    """Two stub URLs must behave like two genuinely different renders."""
    assets = FakeAssets()
    a = b"".join(assets.chunks("http://cdn/one.png"))
    b = b"".join(assets.chunks("http://cdn/two.png"))
    assert a == synthetic_asset_bytes("http://cdn/one.png")
    assert a != b
    assert b"".join(assets.chunks("http://cdn/one.png")) == a, "not deterministic"


def test_serve_pins_bytes_so_two_urls_can_share_one_content_address(fake_assets):
    """The case content addressing exists for, expressed in one line of setup."""
    shared = fake_assets.serve("http://cdn/one.png", IMG)
    fake_assets.serve("http://cdn/two.png", shared)
    one = content_ref_for_url("http://cdn/one.png")
    two = content_ref_for_url("http://cdn/two.png")
    assert one.content_hash == two.content_hash
    assert one.bytes_size == len(IMG)


def test_fail_makes_a_url_404_the_way_an_expired_fal_asset_does(fake_assets):
    from falaw import FalAssetFetchError

    fake_assets.fail("http://cdn/gone.png")
    with pytest.raises(FalAssetFetchError):
        content_ref_for_url("http://cdn/gone.png")


def test_the_synthetic_prefix_is_per_suite():
    assets = FakeAssets(synthetic_prefix="nw-test-asset")
    assert b"".join(assets.chunks("http://x/a")).startswith(b"nw-test-asset::")


# --- the seam: one install, every entry point -------------------------------


def test_the_fake_covers_every_entry_point_that_reads_bytes(fal, fake_assets):
    """The hard-won detail: patch the fallback fetcher, not the public kwargs.

    ``execute_plan(asset_fetcher=…)`` / ``materialize_asset(fetcher=…)`` are the
    documented per-call seam, but a consumer reaches falaw through its *own*
    public API, which takes no transport argument. Worse, a consumer module that
    did ``from falaw import execute_plan`` at import time holds a binding that
    patching the name ``falaw.execute_plan`` never replaces — so the calls below
    go through the **import-time bindings** on purpose.

    Each entry point is given its **own** URL. Sharing one would let the
    ``url -> ContentRef`` hint index answer the second call without fetching,
    and the test would then pass while that entry point bypassed the fake
    entirely.
    """
    fal.responds("m/plan", {"images": [{"url": "http://cdn/from-plan.png"}]})
    fal.responds("m/iso", {"images": [{"url": "http://cdn/from-isolated.png"}]})

    (artifact,) = _bound_execute_plan(_image_plan("m/plan"))
    report = execute_plan_isolated(_image_plan("m/iso"))
    path = _bound_materialize_asset("http://cdn/materialized.png")
    ref = content_ref_for_url("http://cdn/direct.png")

    assert artifact.bytes_size == len(synthetic_asset_bytes("http://cdn/from-plan.png"))
    assert report.outcomes[0].artifact.bytes_size == len(
        synthetic_asset_bytes("http://cdn/from-isolated.png")
    )
    with open(path, "rb") as f:
        assert f.read() == synthetic_asset_bytes("http://cdn/materialized.png")
    assert ref.bytes_size > 0
    assert fake_assets.fetched == [
        "http://cdn/from-plan.png",
        "http://cdn/from-isolated.png",
        "http://cdn/materialized.png",
        "http://cdn/direct.png",
    ], "an entry point escaped the fake and would have hit the network"


def test_the_fake_reaches_a_thread_the_installer_did_not_create(fake_assets):
    """Why the override is a module global and not a ``ContextVar``.

    A downstream job runner executes falaw calls on its own worker pool, which
    does **not** inherit the installing thread's context. A per-context override
    would silently not apply there — a suite that believes it is hermetic,
    quietly on the network. Nothing here copies context, deliberately.
    """
    fake_assets.serve("http://cdn/threaded.png", IMG)
    seen: list = []

    def work():
        seen.append(content_ref_for_url("http://cdn/threaded.png"))

    thread = threading.Thread(target=work)
    thread.start()
    thread.join(timeout=10)

    assert seen and seen[0].bytes_size == len(IMG)
    assert fake_assets.fetched == ["http://cdn/threaded.png"]


def test_an_explicitly_passed_fetcher_still_wins(fake_assets):
    """``using_url_fetcher`` changes the *default*, never an explicit choice."""
    ref = content_ref_for_url("http://cdn/x.png", fetcher=lambda url: [b"explicit"])
    assert ref.bytes_size == len(b"explicit")
    assert fake_assets.fetched == [], "the fake served a call that chose a fetcher"


def test_using_url_fetcher_nests_and_restores(fake_assets):
    outer = default_url_fetcher()
    with using_url_fetcher(lambda url: [b"inner"]):
        assert default_url_fetcher() is not outer
    assert default_url_fetcher() is outer


def test_serving_fake_assets_works_without_pytest_fixtures():
    """The pytest-free core, for a script / notebook / other runner."""
    with serving_fake_assets() as assets:
        assets.serve("http://cdn/x.png", IMG)
        assert content_ref_for_url("http://cdn/x.png").bytes_size == len(IMG)
    assert default_url_fetcher() is not assets.chunks


# --- what must NOT be faked -------------------------------------------------


def test_file_urls_fall_through_to_the_real_fetcher(fake_assets, tmp_path):
    """``file://`` is a documented falaw input, not the network.

    Faking it would replace a real mp4 with synthetic bytes and break the
    ffmpeg that reads it.
    """
    real = tmp_path / "rendered.mp4"
    real.write_bytes(b"real local media")
    ref = content_ref_for_url(real.as_uri())
    assert ref.bytes_size == len(b"real local media")
    assert not is_network_url(real.as_uri())


def test_a_pinned_file_url_is_still_served_from_memory(fake_assets, tmp_path):
    """Explicit pinning overrides the pass-through, in both directions."""
    real = tmp_path / "rendered.mp4"
    real.write_bytes(b"on disk")
    fake_assets.serve(real.as_uri(), b"pinned instead")
    assert content_ref_for_url(real.as_uri()).bytes_size == len(b"pinned instead")


# --- refusing is not reporting ----------------------------------------------


def test_a_failed_fetch_leaves_the_run_green_but_the_fake_records_it(fal, fake_assets):
    """The measurement behind the whole issue, as an executable statement.

    falaw degrades rather than raises, so a test asserting "it blew up" would
    pass vacuously forever. What a test can rely on is the *record*.
    """
    fal.responds("m/img", {"images": [{"url": "http://cdn/expired.png"}]})
    fake_assets.fail("http://cdn/expired.png")

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        (artifact,) = execute_plan(_image_plan())

    assert artifact.bytes_size == 0 and artifact.url == "http://cdn/expired.png"
    assert any("URL-only artifact" in str(w.message) for w in caught)
    assert fake_assets.fetched == ["http://cdn/expired.png"], (
        "the fetch attempt must be recorded — the exception was swallowed by "
        "design, so the record is the only evidence a test can assert on"
    )


def test_an_ordinary_exception_refusal_is_absorbed_into_a_green_run(fal):
    """Why a guard that only raises is not a guard — measured, not assumed.

    ``_fetch_into_store`` turns any :class:`Exception` into a
    ``FalAssetFetchError``, which ``execute`` degrades to a URL-only artifact
    with a warning. So a refusal raised as an ordinary exception — nw's guard
    was a ``RuntimeError`` — leaves the run **complete and green** while the
    network access it refused is exactly the bug being hunted.
    """
    fal.responds("m/img", {"images": [{"url": "http://cdn/refused.png"}]})

    def refusing_fetcher(url, *, chunk_size=1 << 16):
        raise RuntimeError(f"refused {url}")
        yield b""  # pragma: no cover - generator marker

    with using_url_fetcher(refusing_fetcher), warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        report = execute_plan_isolated(_image_plan())

    assert report.is_complete, (
        "if this ever fails, falaw stopped degrading and a raising-only guard "
        "would finally be visible — revisit the recording requirement"
    )
    assert report.outcomes[0].artifact.bytes_size == 0  # degraded, silently


def test_a_baseexception_refusal_escapes_falaws_funnels(fal):
    """Which is why :class:`OutboundNetworkAttempt` derives from ``BaseException``.

    ``execute_isolated`` re-raises a non-``Exception`` deliberately: a run-level
    abort is not a call failure. The pairing matters — ``BaseException`` gets
    the refusal *out of falaw*, and the recording gets it past everything else.
    """
    fal.responds("m/img", {"images": [{"url": "http://cdn/blocked.png"}]})

    def refusing_fetcher(url, *, chunk_size=1 << 16):
        raise OutboundNetworkAttempt(url)
        yield b""  # pragma: no cover - generator marker

    with using_url_fetcher(refusing_fetcher):
        with pytest.raises(OutboundNetworkAttempt):
            execute_plan_isolated(_image_plan())


# --- the no-outbound-network backstop ---------------------------------------


def test_the_guard_refuses_and_records_a_dns_lookup():
    import socket

    with blocked_outbound_network() as attempts:
        with pytest.raises(OutboundNetworkAttempt):
            socket.getaddrinfo("example.invalid", 443)
    assert attempts == ["a DNS lookup for 'example.invalid'"]


def test_the_guard_records_even_when_the_refusal_is_swallowed():
    """A caller with a bare ``except BaseException`` must not be able to hide it.

    ``192.0.2.1`` is TEST-NET-1 (RFC 5737) and is guaranteed unroutable, so a
    broken guard cannot turn this into real traffic either.
    """
    import socket

    with blocked_outbound_network() as attempts:
        try:
            socket.socket().connect(("192.0.2.1", 443))
        except BaseException:  # noqa: BLE001 — exactly what falaw does
            pass
    assert attempts, "the swallowed refusal left no evidence"


def test_the_guard_leaves_loopback_and_unix_sockets_alone():
    import socket

    with blocked_outbound_network() as attempts:
        socket.getaddrinfo("localhost", 0)
        socket.getaddrinfo("127.0.0.1", 0)
    assert attempts == []


def test_the_guard_restores_the_socket_module():
    import socket

    real = socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex
    with blocked_outbound_network():
        pass
    assert (socket.getaddrinfo, socket.socket.connect, socket.socket.connect_ex) == real


def test_the_fixture_fails_the_test_at_teardown(pytester):
    """The reporting half, proved end-to-end: a *swallowed* attempt still fails.

    Run as a nested pytest session because a fixture that fails at teardown
    cannot be observed from inside the test it fails.
    """
    pytester.makeconftest(
        "from falaw.testing import (  # noqa: F401\n"
        "    isolated_falaw_cache,\n"
        "    no_outbound_network,\n"
        ")"
    )
    pytester.makepyfile(
        """
        import socket

        def test_swallows_an_outbound_attempt():
            try:
                socket.getaddrinfo("example.invalid", 443)
            except BaseException:
                pass
        """
    )
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*Outbound network access attempted*"])


def test_a_test_that_means_to_provoke_an_attempt_can_drain_the_record(
    no_outbound_network,
):
    """The documented escape hatch — and a live check that the fixture yields it."""
    import socket

    with pytest.raises(OutboundNetworkAttempt):
        socket.getaddrinfo("example.invalid", 443)
    assert no_outbound_network
    no_outbound_network.clear()


# --- the fixtures themselves ------------------------------------------------


def test_isolated_falaw_cache_points_falaw_at_the_tmp_dir(
    tmp_path, isolated_falaw_cache
):
    import os

    from falaw.cache import _cache_dir

    assert os.environ["FALAW_CACHE_DIR"].startswith(str(tmp_path))
    assert str(tmp_path) in _cache_dir()


def test_a_live_api_marked_test_gets_the_real_transport(fake_assets):
    """Sanity: the opt-out is by marker, and this test is not marked."""
    assert fake_assets is not None
    assert default_url_fetcher() is not _http_chunks


@pytest.mark.live_api
def test_live_api_tests_see_no_fake(fake_assets):
    # Never runs under `-m "not live_api"`; here so the opt-out is not a claim
    # made only in prose.
    assert fake_assets is None


def test_the_factory_produces_a_real_pytest_fixture(pytester):
    """A suite with its own live-marker names gets a working fixture, not a stub."""
    pytester.makeconftest(
        """
        from falaw.testing import isolated_falaw_cache, make_fake_assets_fixture

        fake_assets = make_fake_assets_fixture(
            live_markers=("live_api", "live_capture"),
            synthetic_prefix="downstream-test-asset",
        )
        """
    )
    pytester.makepyfile(
        """
        import pytest

        def test_the_fake_is_installed(fake_assets):
            from falaw import content_ref_for_url
            content_ref_for_url("http://cdn/x.png")
            assert fake_assets.fetched == ["http://cdn/x.png"]
            assert fake_assets.synthetic("http://cdn/x.png").startswith(
                b"downstream-test-asset::"
            )

        @pytest.mark.live_capture
        def test_the_extra_live_marker_opts_out(fake_assets):
            assert fake_assets is None
        """
    )
    result = pytester.runpytest_subprocess("-p", "no:cacheprovider")
    result.assert_outcomes(passed=2)


def test_testing_module_doctests_pass():
    import doctest

    import falaw.testing

    result = doctest.testmod(
        falaw.testing,
        optionflags=doctest.NORMALIZE_WHITESPACE | doctest.ELLIPSIS,
    )
    assert result.failed == 0


def test_the_live_gate_is_opt_in_not_key_presence(monkeypatch):
    """A developer shell with FAL_KEY exported must not be able to spend on a
    bare ``pytest`` — the gate arms only on an explicit FALAW_LIVE_API=1
    (fleet policy after a real near-spend; reelee#260's family)."""
    from tests.conftest import _live_api_skip_reason

    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.delenv("FALAW_LIVE_API", raising=False)
    assert _live_api_skip_reason() is not None  # key alone must not arm it

    monkeypatch.setenv("FALAW_LIVE_API", "1")
    assert _live_api_skip_reason() is None  # the explicit yes

    monkeypatch.setenv("CI", "true")
    assert _live_api_skip_reason() is not None  # CI always wins
