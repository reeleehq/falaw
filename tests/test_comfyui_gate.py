"""The ComfyUI deployment gate (falaw#94): manifest, licences, path screen, audit sink."""

from __future__ import annotations

import copy
import hashlib
import subprocess
from datetime import datetime, timezone

import pytest

from falaw.comfyui import (
    FileAuditSink,
    LicenceScreen,
    UnsafeGraphError,
    assert_safe_graph,
    check_graph_paths,
    check_manifest,
    git_commit_floor,
    nodes_digest,
    screen_licences,
    submit_graph,
)

SHA = "a" * 40
NODE = {"name": "n1", "repo": "https://example.com/n1", "commit": "b" * 40}


def _write(tmp_path, name, text):
    (tmp_path / name).write_text(text)
    return {"path": name, "sha256": hashlib.sha256(text.encode()).hexdigest()}


@pytest.fixture
def good(tmp_path):
    return {
        "comfyui": {"commit": SHA},
        "args": [
            "--listen",
            "127.0.0.1",
            "--port",
            "8188",
            "--disable-all-custom-nodes",
        ],
        "custom_nodes": [NODE],
        "network": {
            "public_ingress": False,
            "egress_allow": ["huggingface.co"],
            "metadata_blocked_by": _write(
                tmp_path, "netpol.yaml", "deny 169.254.169.254"
            ),
        },
        "proxy": {
            "config": _write(tmp_path, "proxy.conf", "auth all"),
            "facade_only_endpoints": ["/object_info", "/ws", "/queue", "/interrupt"],
            "client_endpoints": ["/prompt", "/history/{id}", "/view", "/upload/image"],
        },
        "mounts": [
            {"path": "/models", "mode": "ro", "source": "models-vol"},
            {"path": "/output", "mode": "rw", "source": "out-vol", "quota_gb": 20},
            {"path": "/temp", "mode": "rw", "source": "tmp-vol", "quota_gb": 5},
        ],
        "tenancy": "per_tenant",
        "licence_screen": {
            "checked_at": "2026-10-26T00:00:00",
            "nodes_digest": nodes_digest([("n1", "b" * 40)]),
            "agpl_packs": [],
            "undeterminable": [],
        },
    }


def _rescreen(m):
    """A stand-in for re-running the screen on the checkout: it agrees with m."""
    return lambda names: LicenceScreen(
        checked_at="now",
        nodes_digest=nodes_digest((n["name"], n["commit"]) for n in m["custom_nodes"]),
    )


def _check(m, tmp_path, **kw):
    kw.setdefault("commit_floor", lambda c: True)
    kw.setdefault("licence_screen", _rescreen(m))
    return check_manifest(m, base_dir=tmp_path, **kw)


def _items(problems):
    return {p.item for p in problems}


def test_a_good_manifest_passes(good, tmp_path):
    assert _check(good, tmp_path) == []


def test_every_checklist_row_has_a_way_to_fail(good, tmp_path):
    bad = copy.deepcopy(good)
    bad["comfyui"]["commit"] = "main"
    bad["args"] = ["--listen", "0.0.0.0", "--enable-manager", "--api-key", "x"]
    bad["network"] = {"public_ingress": True, "egress_allow": ["*"]}
    bad["proxy"] = {
        "config": "nope",
        "client_endpoints": ["/object_info", "/system_stats"],
    }
    bad["mounts"] = [{"path": "/models", "mode": "rw"}, {"path": "/home", "mode": "rw"}]
    bad["tenancy"] = None
    bad["licence_screen"] = {}
    assert _items(_check(bad, tmp_path)) >= {
        "1",
        "2",
        "3",
        "4",
        "6",
        "7",
        "8",
        "9",
        "L",
    }


def test_commit_floor_is_verified_not_trusted(good, tmp_path):
    assert "2" in _items(_check(good, tmp_path, commit_floor=lambda c: False))
    no_seam = check_manifest(good, base_dir=tmp_path)  # cannot verify -> a problem
    assert any("cannot verify" in str(p) for p in no_seam)
    assert any("self-asserted" in str(p) for p in no_seam)


def test_git_commit_floor_uses_ancestry(tmp_path):
    def git(*a):
        return subprocess.run(
            ["git", "-C", str(tmp_path), *a], check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q")
    git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "old",
    )
    old = git("rev-parse", "HEAD")
    git("tag", "v0.28.0")
    git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "new",
    )
    new = git("rev-parse", "HEAD")
    at_or_after = git_commit_floor(tmp_path)
    assert at_or_after(new) and at_or_after(old)  # the tag commit itself counts
    git("checkout", "-q", "-b", "side", "HEAD~2" if False else old + "~0")
    git(
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "side",
    )
    assert at_or_after(git("rev-parse", "HEAD"))
    assert not git_commit_floor(tmp_path, tag="v9.9.9")(
        new
    )  # missing tag: not verified


def test_evidence_must_match_its_digest(good, tmp_path):
    (tmp_path / "proxy.conf").write_text(
        "auth NONE"
    )  # edited after the manifest was written
    assert any("does not match its sha256" in str(p) for p in _check(good, tmp_path))
    assert any(
        "no base_dir" in str(p)
        for p in check_manifest(good, commit_floor=lambda c: True)
    )


def test_arguments_are_an_allowlist_not_a_secret_regex(good, tmp_path):
    good["args"] += ["--some-new-flag", "--tls-keyfile", "k"]
    msgs = [str(p) for p in _check(good, tmp_path)]
    assert any("--some-new-flag" in m and "allowlist" in m for m in msgs)
    good["args"] = [
        a for a in good["args"] if a not in ("--some-new-flag", "--tls-keyfile", "k")
    ]
    assert (
        _check(good, tmp_path, allowed_args={"--listen": (1, 1), "--port": (1, 1)})
        != []
    )  # allowlist is a seam
    good["args"].append("--enable-cors-header")
    assert any("--enable-cors-header" in str(p) for p in _check(good, tmp_path))


def test_whitelist_is_derived_from_custom_nodes_never_written_twice(good, tmp_path):
    good["args"] += ["--whitelist-custom-nodes", "n1"]
    assert _check(good, tmp_path) == []
    good["args"][-1] = "other"
    assert any("must equal custom_nodes" in str(p) for p in _check(good, tmp_path))


def test_listen_must_be_a_private_address(good, tmp_path):
    good["args"][1] = "8.8.8.8"
    assert "1" in _items(_check(good, tmp_path))
    good["args"][1] = "10.1.2.3"
    assert _check(good, tmp_path) == []


@pytest.mark.parametrize("host", ["*", "10.0.0.0/8", "1.2.3.4", "localhost", ""])
def test_egress_must_be_named_hosts(good, tmp_path, host):
    good["network"]["egress_allow"] = [host]
    assert "8" in _items(_check(good, tmp_path))


def test_object_info_is_facade_only_and_blocked_prefixes_apply_to_both_lists(
    good, tmp_path
):
    good["proxy"]["client_endpoints"].append("/object_info")
    good["proxy"]["facade_only_endpoints"].append("/userdata/x")
    msgs = [str(p) for p in _check(good, tmp_path)]
    assert any("facade only" in m for m in msgs) and any(
        "/userdata/x" in m for m in msgs
    )


def test_mounts_are_closed_and_output_has_a_quota(good, tmp_path):
    del good["mounts"][1]["quota_gb"]
    good["mounts"].append({"path": "/etc", "mode": "ro"})
    msgs = [str(p) for p in _check(good, tmp_path)]
    assert any("/output needs a quota_gb" in m for m in msgs) and any(
        "/etc" in m for m in msgs
    )


def test_shared_tenancy_needs_an_explicit_opt_in(good, tmp_path):
    good["tenancy"] = "shared"
    assert "9" in _items(_check(good, tmp_path))
    assert _check(good, tmp_path, allow_shared=True) == []


def test_licence_screen_must_match_the_current_nodes(good, tmp_path):
    good["custom_nodes"].append({**NODE, "name": "n2"})
    assert any("nodes_digest" in str(p) for p in _check(good, tmp_path))
    good["licence_screen"]["agpl_packs"] = ["n1"]
    assert any("AGPL" in str(p) for p in _check(good, tmp_path))


def test_agpl_third_party_worker_is_black_box_only(good, tmp_path):
    good["third_party_workers"] = [
        {"name": "w", "licence": "AGPL-3.0", "use": "forked"}
    ]
    assert "L" in _items(_check(good, tmp_path))


# --- licences ---------------------------------------------------------------


def _pack(root, name, text, filename="LICENSE"):
    d = root / name
    d.mkdir()
    if text is not None:
        (d / filename).write_text(text)


GPL3 = (
    "GNU GENERAL PUBLIC LICENSE\nVersion 3\n"
    + "\n".join(f"clause {i}" for i in range(200))  # section 13 is far from the title
    + "\n13. Use with the GNU Affero General Public License. ..."
)


def test_screen_reads_the_license_files_and_fails_closed(tmp_path):
    _pack(
        tmp_path, "mit", "MIT License\n\nPermission is hereby granted, free of charge"
    )
    _pack(tmp_path, "gpl3", GPL3, "COPYING")  # names the AGPL in section 13: still GPL
    _pack(tmp_path, "agpl", "\n\n GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3")
    _pack(tmp_path, "spdx", "SPDX-License-Identifier: AGPL-3.0-or-later\nMIT License")
    _pack(tmp_path, "none", None)
    _pack(tmp_path, "garbage", "all rights reserved, ask me")
    _pack(tmp_path, ".git", None)
    screen = screen_licences(
        tmp_path,
        commit_of=lambda p: "c" * 40,
        clock=lambda: datetime(2026, 10, 26, tzinfo=timezone.utc),
    )
    assert screen.agpl_packs == ("agpl", "spdx")
    assert screen.undeterminable == ("garbage", "none")
    assert not screen.passed and len(screen.problems()) == 4
    assert screen.checked_at.startswith("2026-10-26")
    names = ["agpl", "garbage", "gpl3", "mit", "none", "spdx"]
    assert screen.nodes_digest == nodes_digest((n, "c" * 40) for n in names)


def test_screen_digest_is_order_independent_and_to_dict_is_manifest_shaped(tmp_path):
    _pack(tmp_path, "mit", "MIT License")
    screen = screen_licences(tmp_path, commit_of=lambda p: SHA)
    assert screen.passed
    assert set(screen.to_dict()) == {
        "checked_at",
        "nodes_digest",
        "agpl_packs",
        "undeterminable",
    }
    assert nodes_digest([("a", "1"), ("b", "2")]) == nodes_digest(
        [("b", "2"), ("a", "1")]
    )


# --- graph path screen ------------------------------------------------------

OBJECT_INFO = {
    "LoadImage": {"input": {"required": {"image": [["a.png", "sub/b.png"], {}]}}},
    "CheckpointLoader": {
        "input": {"required": {"ckpt_name": ["COMBO", {"options": ["m.safetensors"]}]}}
    },
    "CLIPTextEncode": {
        "input": {
            "required": {"text": ["STRING", {"multiline": True}], "clip": ["CLIP", {}]}
        }
    },
    "PathLoader": {"input": {"required": {"path": ["STRING", {}]}}},
    "StringConst": {"input": {"required": {"string": ["STRING", {"multiline": True}]}}},
    "SaveImage": {
        "input": {
            "required": {"images": ["IMAGE", {}], "filename_prefix": ["STRING", {}]}
        }
    },
}


def _g(class_type, **inputs):
    return {"1": {"class_type": class_type, "inputs": inputs}}


def test_a_clean_graph_passes_and_links_and_prose_are_not_screened():
    graph = {
        "1": {"class_type": "LoadImage", "inputs": {"image": "sub/b.png"}},
        "2": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": "wait.. C:\\ /imagine ../x", "clip": ["3", 0]},
        },
        "4": {
            "class_type": "SaveImage",
            "inputs": {"images": ["1", 0], "filename_prefix": "out/shot"},
        },
    }
    assert check_graph_paths(graph, OBJECT_INFO) == []
    assert_safe_graph(graph, OBJECT_INFO)


@pytest.mark.parametrize(
    "value",
    [
        "../../etc/passwd",
        "/etc/passwd",
        "a\\b.png",
        "C:\\x.png",
        "c:/x",
        "a\x00.png",
        "sub/../b.png",
    ],
)
def test_path_hazards_in_non_prose_strings_are_refused(value):
    problems = check_graph_paths(
        _g("SaveImage", images=["1", 0], filename_prefix=value), OBJECT_INFO
    )
    assert [p.item for p in problems] == ["5"]


def test_combo_values_must_be_declared_options_in_both_spellings():
    assert check_graph_paths(_g("LoadImage", image="c.png"), OBJECT_INFO)
    assert check_graph_paths(_g("CheckpointLoader", ckpt_name="x.ckpt"), OBJECT_INFO)
    assert (
        check_graph_paths(
            _g("CheckpointLoader", ckpt_name="m.safetensors"), OBJECT_INFO
        )
        == []
    )


def test_unknown_classes_and_undeclared_inputs_are_refused():
    assert check_graph_paths(_g("EvalNode", code="x"), OBJECT_INFO)
    assert any(
        "not declared" in str(p)
        for p in check_graph_paths(
            _g("LoadImage", image="a.png", extra="1"), OBJECT_INFO
        )
    )


def test_free_text_exemption_is_by_declared_type_and_overridable():
    graph = _g("SaveImage", images=["9", 0], filename_prefix="/x")
    pair = {("SaveImage", "filename_prefix")}
    assert check_graph_paths(graph, OBJECT_INFO, free_text=pair) == []
    # a non-multiline STRING is never exempt just because of its name
    assert check_graph_paths(_g("PathLoader", path="/etc/passwd"), OBJECT_INFO)
    with pytest.raises(UnsafeGraphError) as e:
        assert_safe_graph(graph, OBJECT_INFO)
    assert e.value.problems


# --- audit sink -------------------------------------------------------------


class _ListSink:
    def __init__(self, events):
        self.events, self.records = events, []

    def write(self, record):
        self.events.append("audit")
        self.records.append(record)


def test_the_record_is_in_the_sink_before_the_request_is_sent():
    events = []
    sink = _ListSink(events)
    graph = _g("LoadImage", image="a.png")

    def send(g):
        events.append("send")
        return "prompt-id"

    out = submit_graph(
        graph, send=send, sink=sink, object_info=OBJECT_INFO, context={"tenant": "t1"}
    )
    assert out == "prompt-id" and events == ["audit", "send"]
    rec = sink.records[0]
    assert (
        rec["graph"] == graph
        and rec["context"] == {"tenant": "t1"}
        and rec["rejected"] == []
    )
    assert len(rec["graph_sha256"]) == 64


def test_a_failing_sink_stops_the_request():
    class Broken:
        def write(self, record):
            raise OSError("disk full")

    sent = []
    with pytest.raises(OSError):
        submit_graph(
            _g("LoadImage", image="a.png"),
            send=sent.append,
            sink=Broken(),
            object_info=OBJECT_INFO,
        )
    assert sent == []


def test_an_unsafe_graph_is_audited_then_refused():
    events = []
    sink = _ListSink(events)
    sent = []
    with pytest.raises(UnsafeGraphError):
        submit_graph(
            _g("LoadImage", image="../../x"),
            send=sent.append,
            sink=sink,
            object_info=OBJECT_INFO,
        )
    assert sent == [] and sink.records[0]["rejected"]


def test_file_sink_appends_durable_json_lines(tmp_path):
    import json

    sink = FileAuditSink(tmp_path / "audit")
    submit_graph(
        _g("LoadImage", image="a.png"),
        send=lambda g: None,
        sink=sink,
        object_info=OBJECT_INFO,
    )
    submit_graph(
        _g("LoadImage", image="sub/b.png"),
        send=lambda g: None,
        sink=sink,
        object_info=OBJECT_INFO,
    )
    lines = sink.path.read_text().splitlines()
    assert [json.loads(x)["graph"]["1"]["inputs"]["image"] for x in lines] == [
        "a.png",
        "sub/b.png",
    ]


# --- review findings (hostile shapes) -------------------------------------------


def test_a_prose_node_wired_into_a_path_is_screened():
    graph = {
        "1": {"class_type": "StringConst", "inputs": {"string": "/etc/passwd"}},
        "2": {"class_type": "PathLoader", "inputs": {"path": ["1", 0]}},
    }
    problems = check_graph_paths(graph, OBJECT_INFO)
    assert any("node 1" in str(p) for p in problems)


def test_a_link_shaped_literal_is_not_a_wire_unless_it_names_a_node():
    assert check_graph_paths(_g("LoadImage", image=["/etc/passwd", 0]), OBJECT_INFO)
    assert check_graph_paths(_g("PathLoader", path=["/etc/passwd", 0]), OBJECT_INFO)


def test_hazards_hide_in_whitespace_nested_values_and_keys():
    assert check_graph_paths(_g("PathLoader", path="  /etc/passwd"), OBJECT_INFO)
    assert check_graph_paths(_g("PathLoader", path=["ok", {"/etc/x": 1}]), OBJECT_INFO)


@pytest.mark.parametrize(
    "graph",
    [
        [],
        {"1": 5},
        {"1": {"class_type": ["x"], "inputs": []}},
        {"1": {"class_type": "LoadImage", "inputs": ["a"]}},
    ],
)
def test_malformed_graphs_are_problems_not_exceptions(graph):
    assert check_graph_paths(graph, OBJECT_INFO)


def test_a_malformed_graph_is_still_audited():
    sink = _ListSink([])
    with pytest.raises(UnsafeGraphError):
        submit_graph(
            {"1": {"class_type": "LoadImage", "inputs": {"image": {1, 2}}}},
            send=print,
            sink=sink,
            object_info=OBJECT_INFO,
        )
    assert sink.records[0]["rejected"] and "graph_repr" in sink.records[0]


def test_send_receives_the_frozen_copy_that_was_screened_and_audited():
    sink = _ListSink([])
    graph = _g("LoadImage", image="a.png")

    def send(g):
        graph["1"]["inputs"]["image"] = "/etc/passwd"  # caller mutates its own object
        return g

    sent = submit_graph(graph, send=send, sink=sink, object_info=OBJECT_INFO)
    assert (
        sent["1"]["inputs"]["image"]
        == "a.png"
        == sink.records[0]["graph"]["1"]["inputs"]["image"]
    )


@pytest.mark.parametrize(
    "args, item",
    [
        (
            ["--listen", "--port", "8188", "--disable-all-custom-nodes"],
            "7",
        ),  # bare --listen = all interfaces
        (
            ["--disable-all-custom-nodes", "hf_TOKEN"],
            "7",
        ),  # value after a flag taking none
        (["--cpu", "sk-SECRET", "--disable-all-custom-nodes"], "7"),
        (["--listen=0.0.0.0", "--disable-all-custom-nodes"], "7"),
        (["--port", "1", "--port", "2", "--disable-all-custom-nodes"], "7"),
        (["stray", "--disable-all-custom-nodes"], "7"),
    ],
)
def test_argument_shapes_that_leak_or_widen(good, tmp_path, args, item):
    good["args"] = args
    assert item in _items(_check(good, tmp_path))


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/internal/logs",
        "/api/system_stats",
        "//internal",
        "/INTERNAL/",
        "/userdata*",
        "/",
        "/api/object_info",
    ],
)
def test_endpoint_aliases_and_wildcards_are_refused(good, tmp_path, endpoint):
    good["proxy"]["client_endpoints"].append(endpoint)
    assert "3" in _items(_check(good, tmp_path))


@pytest.mark.parametrize(
    "manifest",
    [
        [],
        "x",
        {
            "comfyui": "x",
            "mounts": ["x"],
            "third_party_workers": [3],
            "args": "abc",
            "custom_nodes": 5,
            "network": [],
        },
    ],
)
def test_wrong_typed_manifests_are_problems_not_exceptions(manifest, tmp_path):
    assert check_manifest(manifest, base_dir=tmp_path)


def test_evidence_cannot_escape_base_dir(good, tmp_path):
    outside = tmp_path.parent / "outside.conf"
    outside.write_text("x")
    good["proxy"]["config"] = {
        "path": "../outside.conf",
        "sha256": hashlib.sha256(b"x").hexdigest(),
    }
    assert any("outside base_dir" in str(p) for p in _check(good, tmp_path))


def test_internal_egress_names_mounts_and_workers(good, tmp_path):
    good["network"]["egress_allow"] = ["metadata.google.internal"]
    good["mounts"][1]["quota_gb"] = True
    good["mounts"][0]["source"] = "/"
    good["mounts"].append("/:/host")
    good["third_party_workers"] = [
        {"name": "w", "licence": "GNU Affero GPL v3", "use": "forked"}
    ]
    msgs = " | ".join(str(p) for p in _check(good, tmp_path))
    assert "internal name" in msgs and "/output needs a quota_gb" in msgs
    assert "source must name" in msgs and "AGPL-family worker" in msgs


def test_screen_judges_each_licence_file_separately(tmp_path):
    d = tmp_path / "both"
    d.mkdir()
    (d / "COPYING").write_text(GPL3)
    (d / "LICENSE").write_text("GNU AFFERO GENERAL PUBLIC LICENSE\nVersion 3")
    late = tmp_path / "late"
    late.mkdir()
    (late / "LICENSE").write_text(
        "\n".join(["x"] * 3) + "\n   GNU AFFERO GENERAL PUBLIC LICENSE\n"
    )
    sspl = tmp_path / "sspl"
    sspl.mkdir()
    (sspl / "LICENSE").write_text(
        "Server Side Public License\nVersion 1\nGNU General Public License"
    )
    nc = tmp_path / "nc"
    nc.mkdir()
    (nc / "LICENSE").write_text(
        "\n".join(["Non-commercial use only"] * 20)
        + "\nPermission is hereby granted, free of charge"
    )
    (tmp_path / "single.py").write_text("print()")
    screen = screen_licences(tmp_path, commit_of=lambda p: SHA)
    assert set(screen.agpl_packs) == {"both", "late", "sspl"}
    assert set(screen.undeterminable) == {"nc", "single.py"}


def test_a_pack_that_is_not_a_git_checkout_is_undeterminable(tmp_path):
    _pack(tmp_path, "mit", "MIT License")
    screen = screen_licences(tmp_path)  # real git_head: tmp_path/mit is no repo
    assert screen.undeterminable == ("mit",)


# --- second review ----------------------------------------------------------------


def _wired(prompt, consumer_class, consumer_input, consumer_spec):
    info = {
        **OBJECT_INFO,
        consumer_class: {"input": {"required": {consumer_input: consumer_spec}}},
    }
    graph = {
        "1": {"class_type": "StringConst", "inputs": {"string": prompt}},
        "2": {"class_type": consumer_class, "inputs": {consumer_input: ["1", 0]}},
    }
    return check_graph_paths(graph, info)


def test_a_prompt_wired_into_conditioning_stays_prose():
    prompt = r"portrait of \(cyberpunk\) /imagine blurry"
    assert _wired(prompt, "KSampler", "positive", ["CONDITIONING", {}]) == []


def test_a_string_wired_into_a_path_input_is_screened_even_in_two_hops():
    assert _wired("/etc/passwd", "Loader", "path", ["STRING", {}])
    graph = {
        "1": {"class_type": "StringConst", "inputs": {"string": "/etc/passwd"}},
        "2": {"class_type": "Concat", "inputs": {"a": ["1", 0]}},
        "3": {"class_type": "PathLoader", "inputs": {"path": ["2", 0]}},
    }
    info = {
        **OBJECT_INFO,
        "Concat": {"input": {"required": {"a": ["STRING", {"multiline": True}]}}},
    }
    assert any("node 1" in str(p) for p in check_graph_paths(graph, info))


@pytest.mark.parametrize(
    "endpoint",
    [
        "/v2/userdata",
        "/api/v2/userdata",
        "/./internal",
        "/view/../internal",
        "/%69nternal",
    ],
)
def test_endpoint_traversal_and_v2_userdata_are_refused(good, tmp_path, endpoint):
    good["proxy"]["client_endpoints"].append(endpoint)
    assert "3" in _items(_check(good, tmp_path))


@pytest.mark.parametrize("source", ["/.", "/..", "/etc", "/proc/self", "../x", ""])
def test_mount_sources_cannot_reach_the_host(good, tmp_path, source):
    good["mounts"][0]["source"] = source
    assert "6" in _items(_check(good, tmp_path))


@pytest.mark.parametrize(
    "flag", ["--output-directory", "--temp-directory", "--input-directory"]
)
def test_directory_flags_only_name_the_quota_mounts(good, tmp_path, flag):
    good["args"] += [flag, "/proc/self"]
    assert "6" in _items(_check(good, tmp_path))


@pytest.mark.parametrize(
    "object_info", [None, [], {"LoadImage": {"input": {"required": []}}}]
)
def test_a_screen_that_cannot_run_refuses_and_is_audited(object_info):
    sink = _ListSink([])
    with pytest.raises(UnsafeGraphError):
        submit_graph(
            _g("LoadImage", image="a.png"),
            send=print,
            sink=sink,
            object_info=object_info,
            context=object(),
        )
    assert len(sink.records) == 1 and sink.records[0]["rejected"]


def test_the_rescreen_catches_a_self_asserted_clean_manifest(good, tmp_path):
    bad = lambda names: LicenceScreen(
        checked_at="now", nodes_digest="x", agpl_packs=("n1",)
    )
    msgs = " | ".join(str(p) for p in _check(good, tmp_path, licence_screen=bad))
    assert "AGPL-family" in msgs and "does not match custom_nodes" in msgs


def test_screen_only_the_declared_packs_and_catch_agplv3_spelling(tmp_path):
    _pack(tmp_path, "mine", "MIT License\n\nthis pack is AGPLv3 in spirit")
    _pack(tmp_path, "other", None)
    (tmp_path / "websocket_image_save.py").write_text("x")
    screen = screen_licences(tmp_path, only={"mine"}, commit_of=lambda p: SHA)
    assert screen.agpl_packs == ("mine",) and screen.undeterminable == ()
    assert screen.nodes_digest == nodes_digest([("mine", SHA)])
