"""Tests for falaw#23 — when falaw may trust the ``url -> content hash`` index.

The index is only sound for URLs that cannot re-point at different bytes. The
defect was that ``materialize_asset`` is public and reached with arbitrary
caller-supplied URLs, so a mutable one kept resolving to the old hash — a
changed input producing an unchanged content address, silently, with the stale
hash flowing into ``Artifact.asset_id`` and every downstream cache key.

What these pin, in order of how much they would cost to get wrong:

* a **changed** mutable URL yields new bytes and a new address;
* an **unknown** answer (no validators, or a transport that cannot revalidate)
  makes falaw re-fetch — never trust;
* an **unreachable** origin falls back to stored bytes rather than failing,
  which is falaw#14's guarantee and does not conflict: staleness is only a lie
  when the truth was available and falaw did not look;
* a **fal** URL still costs nothing, which is what keeps a 200-shot re-run free.
"""

from __future__ import annotations

import os
import warnings

import pytest

from falaw import materialize_asset
from falaw.content import (
    IMMUTABLE_URL_HOSTS,
    ContentRef,
    Validators,
    content_ref_for_url,
    is_immutable_url,
    remembered_ref,
)


IMG_A = b"\x89PNG-pretend-image-A" * 4
IMG_B = b"\x89PNG-pretend-image-B" * 8


# --- which URLs may be trusted ----------------------------------------------


@pytest.mark.parametrize(
    "url,immutable",
    [
        ("https://fal.media/files/x.png", True),
        ("https://v3b.fal.media/files/x.png", True),
        ("https://v3.fal.media/files/x.png", True),
        ("https://fal.run/x", True),
        ("https://example.com/reference.png", False),
        ("http://cdn/clip.mp4", False),
        ("file:///tmp/render.mp4", False),
        ("", False),
        # A host merely *containing* a trusted name is not that host.
        ("https://fal.media.attacker.example/x.png", False),
        ("https://notfal.media/x.png", False),
    ],
)
def test_is_immutable_url(url, immutable):
    assert is_immutable_url(url) is immutable


def test_a_deployment_can_declare_its_own_immutable_host(fake_assets, monkeypatch):
    """Open-closed: an immutable-by-construction CDN should not pay per asset."""
    url = "https://cdn.example.com/sha256-abc.png"
    fake_assets.serve(url, IMG_A)
    materialize_asset(url)
    fake_assets.fetched.clear()

    fake_assets.revalidated.clear()
    # Before declaring it: a mutable host, so falaw asks (cheaply).
    materialize_asset(url)
    assert fake_assets.revalidated == [url], "a mutable host must be revalidated"

    fake_assets.revalidated.clear()
    monkeypatch.setattr(
        "falaw.content.IMMUTABLE_URL_HOSTS", IMMUTABLE_URL_HOSTS | {"cdn.example.com"}
    )
    materialize_asset(url)

    # After declaring it: no request of any kind. Asserting only `fetched == []`
    # would pass without the declaration ever being read, since revalidation
    # transfers no body either.
    assert fake_assets.fetched == []
    assert fake_assets.revalidated == [], "a declared host must not be asked at all"


def test_a_declared_immutable_host_covers_its_subdomains(fake_assets, monkeypatch):
    """The SKILL.md recipe is `IMMUTABLE_URL_HOSTS.add(host)`; edge nodes count."""
    url = "https://edge1.cdn.example.com/sha256-abc.png"
    fake_assets.serve(url, IMG_A)
    monkeypatch.setattr(
        "falaw.content.IMMUTABLE_URL_HOSTS", IMMUTABLE_URL_HOSTS | {"cdn.example.com"}
    )
    materialize_asset(url)
    fake_assets.fetched.clear()
    fake_assets.revalidated.clear()

    materialize_asset(url)

    assert fake_assets.fetched == [] and fake_assets.revalidated == []


# --- the defect itself ------------------------------------------------------


def test_a_changed_mutable_url_produces_a_new_content_hash(fake_assets):
    """The issue's reproduction. Used to return the old hash with no network."""
    url = "https://example.com/reference.png"
    fake_assets.serve(url, IMG_A)
    before = content_ref_for_url(url)

    fake_assets.serve(url, IMG_B)
    after = content_ref_for_url(url)

    assert after.content_hash != before.content_hash
    assert after.bytes_size == len(IMG_B)


def test_an_unchanged_mutable_url_is_confirmed_without_transferring_the_body(
    fake_assets,
):
    url = "https://example.com/reference.png"
    fake_assets.serve(url, IMG_A)
    first = content_ref_for_url(url)
    fake_assets.fetched.clear()

    fake_assets.revalidated.clear()
    again = content_ref_for_url(url)

    assert again == first
    assert fake_assets.fetched == [], "no body may cross the wire"
    # ... but falaw *did* ask. Without this the assertion above is equally
    # satisfied by the un-fixed code, which trusted the index and asked nothing.
    assert fake_assets.revalidated == [url]


def test_validators_are_recorded_on_the_very_first_read(fake_assets):
    """Otherwise nothing can ever be revalidated and every read re-downloads.

    The plain ``UrlFetcher`` seam yields bytes, not a response, so a first fetch
    routed only through it can never learn an ETag.
    """
    from falaw.content import _remembered_record

    url = "https://example.com/reference.png"
    fake_assets.serve(url, IMG_A)
    content_ref_for_url(url)

    record = _remembered_record(url)
    assert record is not None
    assert record.validators, "no validators recorded on first read"


# --- what falaw does when it cannot check -----------------------------------


def test_a_transport_that_cannot_revalidate_forces_a_refetch(fake_assets):
    """An unverifiable hint is not evidence. Re-fetch, never trust."""
    url = "https://example.com/reference.png"
    calls = []

    def bytes_only_fetcher(u):
        """A plain UrlFetcher: no ``conditional_fetch`` capability."""
        calls.append(u)
        yield IMG_A if len(calls) == 1 else IMG_B

    first = content_ref_for_url(url, fetcher=bytes_only_fetcher)
    second = content_ref_for_url(url, fetcher=bytes_only_fetcher)

    assert len(calls) == 2, "a hint it cannot verify must not be trusted"
    assert second.content_hash != first.content_hash


def test_an_index_record_written_before_validators_existed_is_refetched(fake_assets):
    """Old records read back with empty validators, which already means re-fetch.

    Deliberately no migration: the pre-falaw#23 record degrades into the correct
    behaviour rather than into a special case.
    """
    import json

    from falaw.content import _url_index_path

    url = "https://example.com/reference.png"
    fake_assets.serve(url, IMG_A)
    ref = content_ref_for_url(url)

    # Rewrite the index entry in the old shape — no etag, no last_modified.
    with open(_url_index_path(url), "w") as f:
        json.dump(
            {
                "url": url,
                "content_hash": ref.content_hash,
                "bytes_size": ref.bytes_size,
            },
            f,
        )
    assert remembered_ref(url) == ContentRef(ref.content_hash, ref.bytes_size)
    fake_assets.serve(url, IMG_B)
    fake_assets.fetched.clear()

    again = content_ref_for_url(url)

    assert fake_assets.fetched == [url]
    assert again.content_hash != ref.content_hash


def test_an_unreachable_origin_falls_back_to_the_stored_bytes(fake_assets):
    """falaw#14's guarantee survives falaw#23, and the two do not conflict."""
    url = "https://example.com/reference.png"
    fake_assets.serve(url, IMG_A)
    first = content_ref_for_url(url)

    fake_assets.fail(url)

    with pytest.warns(
        UserWarning, match="is gone from its origin|could not be re-read"
    ):
        again = content_ref_for_url(url)

    assert again == first


def test_an_unreachable_origin_with_no_stored_bytes_still_raises(fake_assets):
    """The fallback is for bytes falaw *has*, not a way to swallow failures."""
    from falaw.errors import FalAssetFetchError

    url = "https://example.com/missing.png"
    fake_assets.fail(url)

    with pytest.raises(FalAssetFetchError):
        content_ref_for_url(url)


# --- file:// is mutable too -------------------------------------------------


def test_a_locally_rendered_file_that_is_rewritten_gets_a_new_hash(tmp_path):
    """Re-rendering a clip to the same path is the textbook mutable URL."""
    render = tmp_path / "render.mp4"
    render.write_bytes(IMG_A)
    url = render.as_uri()

    before = content_ref_for_url(url)
    render.write_bytes(IMG_B)
    after = content_ref_for_url(url)

    assert after.content_hash != before.content_hash
    assert after.bytes_size == len(IMG_B)


def test_an_untouched_local_file_is_not_re_read(tmp_path, monkeypatch):
    """`(mtime, size)` is what a filesystem answers without reading the file.

    Proven by making a body read *fail*: if the second call still succeeds, no
    bytes were read. Asserting the two ``ContentRef``\\ s are equal would not
    show this — an unchanged file hashes the same whether or not falaw re-read
    every byte of it, so that assertion passes with the optimisation removed.
    """
    render = tmp_path / "render.mp4"
    render.write_bytes(IMG_A)
    url = render.as_uri()

    first = content_ref_for_url(url)

    def refuse(*a, **kw):
        raise AssertionError("re-read the file body despite unchanged mtime/size")

    monkeypatch.setattr("falaw.content._http_chunks", refuse)
    # `simplefilter("error")` is load-bearing: without it the stored-bytes
    # fallback catches the refusal, warns, and returns the right answer — so the
    # assertion below would pass with the revalidation removed entirely.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        again = content_ref_for_url(url)

    assert again == first


def test_a_local_file_records_its_mtime_and_size_as_validators(tmp_path):
    """Without these there is nothing to compare, and every read re-hashes."""
    from falaw.content import _remembered_record

    render = tmp_path / "render.mp4"
    render.write_bytes(IMG_A)
    url = render.as_uri()

    content_ref_for_url(url)

    record = _remembered_record(url)
    assert record is not None
    assert record.validators.etag.startswith("file:")
    assert str(len(IMG_A)) in record.validators.etag


# --- the explicit override --------------------------------------------------


def test_assume_immutable_true_restores_unconditional_trust(fake_assets):
    url = "https://example.com/reference.png"
    fake_assets.serve(url, IMG_A)
    first = content_ref_for_url(url)

    fake_assets.serve(url, IMG_B)
    fake_assets.fetched.clear()
    fake_assets.revalidated.clear()
    again = content_ref_for_url(url, assume_immutable=True)

    assert again == first
    assert fake_assets.fetched == []
    assert fake_assets.revalidated == [], "assume_immutable must skip the check"


def test_assume_immutable_false_forces_revalidation_even_for_fal(fake_assets):
    url = "https://v3b.fal.media/files/x.png"
    fake_assets.serve(url, IMG_A)
    content_ref_for_url(url)

    fake_assets.serve(url, IMG_B)
    again = content_ref_for_url(url, assume_immutable=False)

    assert again.bytes_size == len(IMG_B)


# --- the fake's own capability ----------------------------------------------


def test_fake_assets_answers_a_revalidation(fake_assets):
    """falaw owns the fake, so downstream suites get the cheap path too."""
    url = "https://example.com/x.png"
    fake_assets.serve(url, IMG_A)
    etag = fake_assets.etag_for(url)

    unchanged = fake_assets.conditional_fetch(url, Validators(etag=etag))
    assert unchanged.not_modified is True
    assert fake_assets.fetched == [], "a 304 transfers no body"

    fake_assets.serve(url, IMG_B)
    changed = fake_assets.conditional_fetch(url, Validators(etag=etag))
    assert changed.not_modified is False
    assert b"".join(changed.chunks) == IMG_B


def test_a_failed_conditional_fetch_is_recorded_as_a_fetch(fake_assets):
    """falaw degrades a failed fetch to a warning, so the fake must record it."""
    import urllib.error

    url = "https://example.com/gone.png"
    fake_assets.fail(url)

    with pytest.raises(urllib.error.HTTPError):
        fake_assets.conditional_fetch(url, Validators(etag='"whatever"'))

    assert fake_assets.fetched == [url]


def test_materialize_asset_returns_the_local_copy_when_the_origin_dies(fake_assets):
    """Circle 1 as a fallback: tried the origin, it is gone, the file is here."""
    url = "https://example.com/reference.png"
    fake_assets.serve(url, IMG_A)
    first = materialize_asset(url)
    fake_assets.fail(url)

    with pytest.warns(
        UserWarning, match="is gone from its origin|could not be re-read"
    ):
        again = materialize_asset(url)

    assert again == first
    assert os.path.exists(again)


# --- the real HTTP conditional request --------------------------------------
#
# Everything above reaches revalidation through `FakeAssets` or the `file://`
# branch. That left the actual `ETag` / `If-None-Match` / `304` code — the
# mechanism this issue is about — with **zero** executed lines, which a
# coverage run of the first cut confirmed. These drive it against a real HTTP
# origin on loopback (which the no-outbound-network guard permits, since it
# only refuses non-loopback).


class _ETagServer:
    """A minimal ETag-aware origin, served from memory on loopback."""

    def __init__(self, body: bytes):
        import http.server
        import threading

        self.body = body
        self.requests: list[dict] = []
        self.last_modified = "Wed, 21 Oct 2015 07:28:00 GMT"
        origin = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):  # keep pytest output clean
                pass

            def do_GET(self):
                origin.requests.append(
                    {
                        "If-None-Match": self.headers.get("If-None-Match"),
                        "If-Modified-Since": self.headers.get("If-Modified-Since"),
                    }
                )
                etag = origin.etag()
                if self.headers.get("If-None-Match") == etag:
                    self.send_response(304)
                    self.send_header("ETag", etag)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("ETag", etag)
                self.send_header("Last-Modified", origin.last_modified)
                self.send_header("Content-Length", str(len(origin.body)))
                self.end_headers()
                self.wfile.write(origin.body)

        self._server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def etag(self) -> str:
        import hashlib

        return f'"{hashlib.sha256(self.body).hexdigest()[:16]}"'

    @property
    def url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}/asset.png"

    def close(self):
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture()
def etag_origin():
    server = _ETagServer(IMG_A)
    try:
        yield server
    finally:
        server.close()


def test_a_real_conditional_get_replays_the_etag_and_takes_the_304(etag_origin):
    from falaw.content import _http_chunks as real

    """The mechanism itself: first read records an ETag, second read gets a 304."""
    first = content_ref_for_url(etag_origin.url, fetcher=real)
    assert etag_origin.requests[0]["If-None-Match"] is None, "nothing to replay yet"

    again = content_ref_for_url(etag_origin.url, fetcher=real)

    assert again == first
    assert len(etag_origin.requests) == 2
    assert etag_origin.requests[1]["If-None-Match"] == etag_origin.etag()


def test_a_real_origin_serving_new_bytes_yields_a_new_content_hash(etag_origin):
    from falaw.content import _http_chunks as real

    first = content_ref_for_url(etag_origin.url, fetcher=real)

    etag_origin.body = IMG_B  # the ETag moves with it
    after = content_ref_for_url(etag_origin.url, fetcher=real)

    assert after.content_hash != first.content_hash
    assert after.bytes_size == len(IMG_B)


def test_the_recorded_validators_come_from_the_response_headers(etag_origin):
    from falaw.content import _http_chunks as real
    from falaw.content import _remembered_record

    content_ref_for_url(etag_origin.url, fetcher=real)

    record = _remembered_record(etag_origin.url)
    assert record.validators.etag == etag_origin.etag()
    assert record.validators.last_modified == etag_origin.last_modified


def test_an_origin_offering_no_validators_is_re_fetched_not_trusted():
    from falaw.content import _http_chunks as real

    """No ETag, no Last-Modified — falaw has no way to check, so it re-reads."""
    import http.server
    import threading

    state = {"body": IMG_A, "gets": 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            state["gets"] += 1
            self.send_response(200)
            self.send_header("Content-Length", str(len(state["body"])))
            self.end_headers()
            self.wfile.write(state["body"])

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        host, port = server.server_address
        url = f"http://{host}:{port}/x.png"
        first = content_ref_for_url(url, fetcher=real)
        state["body"] = IMG_B
        second = content_ref_for_url(url, fetcher=real)
    finally:
        server.shutdown()
        server.server_close()

    assert state["gets"] == 2, "an unverifiable hint must not be trusted"
    assert second.content_hash != first.content_hash


def test_a_transient_failure_does_not_make_stale_bytes_look_current(fake_assets):
    """The fallback is for *gone*, not for *unreachable*.

    A timeout / 500 / 429 says the origin could not be reached, which is a
    different claim from the asset being gone. Serving stored bytes for one
    reports a superseded hash as current — on that call and every later one.
    """
    from falaw.errors import FalAssetFetchError

    url = "https://example.com/reference.png"
    fake_assets.serve(url, IMG_A)
    content_ref_for_url(url)

    def flaky(u, validators, **kw):
        raise TimeoutError("upstream timed out")

    fake_assets.conditional_fetch = flaky

    with pytest.raises(FalAssetFetchError):
        content_ref_for_url(url)


def test_a_store_failure_does_not_make_stale_bytes_look_current(
    fake_assets, monkeypatch
):
    """The origin was reachable and the new bytes were in hand.

    An earlier cut had the store write inside the fallback's `try`, so a full
    disk — the exact condition `falaw.prune` exists for — discarded bytes
    already fetched and returned the *previous* content hash for them.
    """
    from falaw.errors import FalAssetFetchError

    url = "https://example.com/reference.png"
    fake_assets.serve(url, IMG_A)
    first = content_ref_for_url(url)

    fake_assets.serve(url, IMG_B)
    monkeypatch.setattr(
        "falaw.content._store_chunks",
        lambda *a, **k: (_ for _ in ()).throw(
            FalAssetFetchError("no space left on device", url=url)
        ),
    )

    with pytest.raises(FalAssetFetchError):
        content_ref_for_url(url)
    assert remembered_ref(url) == first, "the index must not record a failed write"


def test_not_modified_is_refused_when_falaw_holds_no_bytes(fake_assets):
    """A transport is not obliged to be correct.

    Reachable for real: `prune_content` deletes blobs and deliberately never
    prunes `url_index`, so "record exists, blob does not" is a routine state.
    """
    from falaw.content import ConditionalOutcome
    from falaw.errors import FalAssetFetchError

    url = "https://example.com/reference.png"

    def liar(u, validators, **kw):
        return ConditionalOutcome(not_modified=True)

    fake_assets.conditional_fetch = liar

    with pytest.raises(FalAssetFetchError, match="holds no bytes"):
        content_ref_for_url(url)


def test_a_bogus_capability_is_ignored_rather_than_believed(fake_assets):
    """A MagicMock auto-creates `conditional_fetch`, and every Mock is truthy."""
    from unittest.mock import MagicMock

    url = "https://example.com/reference.png"
    fake_assets.serve(url, IMG_A)
    fetcher = MagicMock(side_effect=lambda u: iter([IMG_A]))

    ref = content_ref_for_url(url, fetcher=fetcher)

    from lacing import hash_bytes

    assert ref.content_hash == hash_bytes(IMG_A), "fell through to a plain fetch"


def test_a_capability_with_the_wrong_signature_is_ignored(fake_assets):
    """An unrelated `conditional_fetch` must not become a stale-serve."""
    from lacing import hash_bytes

    class Transport:
        def conditional_fetch(self, request):  # a different protocol entirely
            raise AssertionError("should never be called successfully")

        def chunks(self, url):
            yield IMG_B

    ref = content_ref_for_url("https://example.com/x.png", fetcher=Transport().chunks)

    assert ref.content_hash == hash_bytes(IMG_B)


def test_a_partial_wrapped_fetcher_keeps_its_capability(fake_assets):
    """`partial(assets.chunks, chunk_size=...)` hides both the attr and __self__."""
    import functools

    url = "https://example.com/reference.png"
    fake_assets.serve(url, IMG_A)
    fetcher = functools.partial(fake_assets.chunks, chunk_size=4096)

    content_ref_for_url(url, fetcher=fetcher)
    fake_assets.fetched.clear()
    fake_assets.revalidated.clear()
    content_ref_for_url(url, fetcher=fetcher)

    assert fake_assets.revalidated == [url], "capability lost through partial"
    assert fake_assets.fetched == []


def test_read_does_not_swallow_a_base_exception(fake_assets):
    """`falaw.testing`'s network guard derives from BaseException on purpose.

    `_read` is a funnel, and the module's design note says a guard that only
    raises is invisible if a funnel converts it. Pinned here because a mutation
    widening this catch to `BaseException` otherwise leaves the suite green.
    """
    from falaw.testing import OutboundNetworkAttempt

    url = "https://example.com/reference.png"

    def guarded(u, validators, **kw):
        raise OutboundNetworkAttempt("refused")

    fake_assets.conditional_fetch = guarded

    with pytest.raises(OutboundNetworkAttempt):
        content_ref_for_url(url)


def test_a_hostname_with_a_character_no_dns_name_has_is_not_a_subdomain():
    """The label-wise check is not enough on its own.

    A netloc can be free of parser-disagreement characters and still carry a
    host that is not a DNS name. `ev!l.fal.media` ends with `.fal.media`, so
    suffix matching *and* label matching both accept it; only the charset rule
    refuses. The safe direction is to revalidate.
    """
    assert is_immutable_url("https://ev!l.fal.media/x.png") is False
    assert is_immutable_url("https://ev_l.fal.media/x.png") is False
    # ... while an ordinary subdomain is still trusted.
    assert is_immutable_url("https://v3b.fal.media/x.png") is True


def test_a_local_file_touched_without_changing_size_is_re_read(tmp_path):
    """Size alone is not a validator.

    `cp -p` / `git checkout` / `rsync -t` all restore a file with its original
    length. Without mtime and ctime in the validator, falaw would report the
    superseded bytes' hash for the new ones.
    """
    import os as _os
    import time as _time

    render = tmp_path / "render.mp4"
    render.write_bytes(IMG_A)
    url = render.as_uri()
    before = content_ref_for_url(url)

    same_length = bytes(b ^ 0xFF for b in IMG_A)
    assert len(same_length) == len(IMG_A)
    _time.sleep(0.01)
    render.write_bytes(same_length)
    _os.utime(render, ns=(0, 0))  # forge the mtime, as a restore would

    after = content_ref_for_url(url)

    assert after.content_hash != before.content_hash, (
        "same length + forged mtime read as unchanged"
    )


def test_a_degradation_goes_to_the_sink_rather_than_the_warning_stream(fake_assets):
    """`execute_plan(concurrency=N)` collects degradations; this is one.

    The more severe the degradation, the worse it is for it to be the one that
    escapes collection — and serving a possibly-superseded hash as current is
    more severe than the URL-only artifact that *was* already collected.
    """
    from falaw.degrade import deferred_degrade_warnings

    url = "https://example.com/reference.png"
    fake_assets.serve(url, IMG_A)
    content_ref_for_url(url)
    fake_assets.fail(url)

    with warnings.catch_warnings(record=True) as escaped:
        warnings.simplefilter("always")
        with deferred_degrade_warnings() as sink:
            content_ref_for_url(url)

    assert len(sink) == 1 and "is gone from its origin" in sink[0]
    assert escaped == [], "the degradation escaped the sink"
