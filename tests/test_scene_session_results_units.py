"""Lookup/replace helpers on Scene, scene persistence, Session history, and Asset downloads (no network)."""

import warnings

import pytest

from falaw import results as R
from falaw.results import Asset, Result
from falaw.scene import (
    Character,
    Environment,
    Scene,
    load_scene,
    make_beat,
    make_shot,
    save_scene,
    scene_from_dict,
    scene_to_dict,
    shot_content_hash,
)
from falaw.session import Session


def _scene():
    return Scene(
        title="T",
        characters=(Character(name="Sarah"),),
        environments=(Environment(name="Kitchen"),),
        shots=(make_shot("wide of kitchen", framing="wide", index=1),),
        beats=(make_beat("Sarah", "Hi", index=1),),
    )


# --- Scene lookups and replacements ----------------------------------------


def test_lookups_find_and_raise_keyerror_naming_the_scene():
    s = _scene()
    assert s.character("Sarah").name == "Sarah"
    assert s.environment("Kitchen").name == "Kitchen"
    assert s.shot(s.shots[0].id) is s.shots[0]
    assert s.beat(s.beats[0].id) is s.beats[0]
    for call, what in [
        (lambda: s.character("X"), "character"),
        (lambda: s.environment("X"), "environment"),
        (lambda: s.shot("X"), "shot"),
        (lambda: s.beat("X"), "beat"),
    ]:
        with pytest.raises(KeyError, match=f"No {what}.*'T'"):
            call()


def test_with_helpers_add_or_replace_without_mutating():
    s = _scene()
    s2 = s.with_character(Character(name="Sarah", description="new")).with_character(
        Character(name="Bob")
    )
    assert [c.name for c in s2.characters] == ["Sarah", "Bob"]
    assert s2.character("Sarah").description == "new"
    assert s.character("Sarah").description == ""

    s3 = s.with_environment(Environment(name="Kitchen", lighting="dim")).with_environment(
        Environment(name="Roof")
    )
    assert [e.name for e in s3.environments] == ["Kitchen", "Roof"]
    assert s3.environment("Kitchen").lighting == "dim"

    shot = make_shot("wide of kitchen", framing="wide", index=1, notes="n")
    s4 = s.with_shot(shot).with_shot(make_shot("other", index=2))
    assert len(s4.shots) == 2 and s4.shots[0].notes == "n"

    beat = make_beat("Sarah", "Hi", index=1, emotion="sad")
    s5 = s.with_beat(beat).with_beat(make_beat("Bob", "Yo", index=2))
    assert len(s5.beats) == 2 and s5.beats[0].emotion == "sad"


def test_make_helpers_ids_are_stable_and_content_sensitive():
    assert make_shot("a", index=1).id == make_shot("a", index=1).id
    assert make_shot("a").id != make_shot("b").id
    assert make_beat("S", "x").id != make_beat("S", "y").id
    sh = make_shot("a", characters=["S"])
    assert sh.characters == ("S",)


def test_shot_content_hash_depends_on_environment_reference():
    sh = make_shot("a")
    base = shot_content_hash(sh)
    env1 = Environment(name="E", reference_image_url="u1")
    env2 = Environment(name="E", reference_image_url="u2")
    assert shot_content_hash(sh, environment=env1) != shot_content_hash(sh, environment=env2)
    assert base != shot_content_hash(sh, environment=env1)


def test_scene_round_trips_through_dict_and_file(tmp_path):
    s = _scene()
    assert scene_from_dict(scene_to_dict(s)) == s
    path = save_scene(s, str(tmp_path / "sub" / "scene.json"))
    assert load_scene(path) == s


# --- Session ---------------------------------------------------------------


def test_session_records_and_finds_latest_by_kind(tmp_path):
    s = Session(output_dir=str(tmp_path / "out"))
    assert (tmp_path / "out").is_dir() and s.latest() is None
    img = Result(assets=[Asset(url="u", kind="image")])
    vid = Result(assets=[Asset(url="v", kind="video")])
    assert s.record(img) is img
    s.record(vid)
    assert s.latest() is vid
    assert s.latest(kind="image") is img
    assert s.latest(kind="audio") is None


# --- Asset.download / Result ------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
SVG = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"


@pytest.fixture
def fetch(monkeypatch):
    box = {"data": PNG}
    monkeypatch.setattr(R, "_fetch", lambda url: box["data"])
    return box


def test_download_to_matching_suffix_writes_bytes(tmp_path, fetch):
    to = str(tmp_path / "d" / "a.png")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert Asset(url="u", kind="image").download(to=to) == to
    assert open(to, "rb").read() == PNG


def test_download_warns_on_suffix_mismatch_and_can_fix_it(tmp_path, fetch):
    fetch["data"] = SVG
    a = Asset(url="u", kind="image")
    with pytest.warns(UserWarning, match="content is '.svg'"):
        a.download(to=str(tmp_path / "x.png"))
    fixed = a.download(to=str(tmp_path / "y.png"), fix_suffix=True)
    assert fixed.endswith("y.svg")


def test_download_without_target_names_by_sniffed_extension(tmp_path, fetch, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = Asset(url="u", kind="image").download()
    assert path.endswith(".png") and "falaw_asset_" in path


@pytest.mark.parametrize(
    "kind, ctype, ext",
    [("video", "", ".mp4"), ("audio", "", ".mp3"), ("other", "", ".bin"), ("image", "image/png", ".png")],
)
def test_infer_extension(kind, ctype, ext):
    assert Asset(url="u", kind=kind, content_type=ctype)._infer_extension() == ext


def test_download_all_names_files_after_application(tmp_path, fetch):
    r = Result(
        assets=[Asset(url="a", kind="image"), Asset(url="b", kind="image")],
        application="fal-ai/flux/dev",
    )
    paths = r.download_all(to_dir=str(tmp_path / "o"))
    assert [__import__("os").path.basename(p) for p in paths] == ["fal-ai_flux_dev_0.png", "fal-ai_flux_dev_1.png"]
    assert Result().first is None


def test_sniff_extension_variants():
    assert R.sniff_extension(b"\xff\xd8\xff....") == ".jpg"
    assert R.sniff_extension(b"GIF89a") == ".gif"
    assert R.sniff_extension(b"RIFF....WEBPVP8 ") == ".webp"
    assert R.sniff_extension(b"  \n<?xml version='1.0'?><svg/>") == ".svg"
    assert R.sniff_extension(b"plain text") == ""
