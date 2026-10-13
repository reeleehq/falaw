"""Tests for the Scene IR."""

from __future__ import annotations

import json

import pytest

from falaw.scene import (
    Beat,
    Character,
    Environment,
    Scene,
    Shot,
    Voice,
    beat_content_hash,
    beat_id,
    load_scene,
    make_beat,
    make_shot,
    save_scene,
    scene_from_dict,
    scene_to_dict,
    shot_id,
)


def test_beat_id_deterministic_on_content():
    a = beat_id(speaker="Sarah", line="It's fine.", index=3)
    b = beat_id(speaker="Sarah", line="It's fine.", index=3)
    assert a == b
    # Different content -> different hash component
    c = beat_id(speaker="Sarah", line="It's NOT fine.", index=3)
    assert a != c


def test_shot_id_deterministic():
    a = shot_id(description="wide of diner", framing="wide", index=0)
    b = shot_id(description="wide of diner", framing="wide", index=0)
    assert a == b


def test_make_beat_helper():
    b = make_beat("John", "Hi.", action="he waves", emotion="warm", index=0)
    assert b.speaker == "John"
    assert b.line == "Hi."
    assert b.id.startswith("000-john-")


def test_scene_with_beat_replaces_in_place():
    scene = Scene(
        title="t", beats=(make_beat("A", "x", index=0), make_beat("B", "y", index=1))
    )
    target = scene.beats[0]
    edited = Beat(
        id=target.id,
        speaker=target.speaker,
        line="EDITED",
        action=target.action,
        emotion=target.emotion,
    )
    new = scene.with_beat(edited)
    assert new is not scene
    assert new.beats[0].line == "EDITED"
    assert new.beats[1].line == "y"


def test_scene_with_beat_appends_when_id_unknown():
    scene = Scene(title="t", beats=())
    new_beat = make_beat("A", "x", index=0)
    new = scene.with_beat(new_beat)
    assert len(new.beats) == 1


def test_scene_with_character_replaces():
    s = Scene(title="t", characters=(Character(name="A"), Character(name="B")))
    s2 = s.with_character(Character(name="A", description="updated"))
    assert s2.character("A").description == "updated"
    assert len(s2.characters) == 2


def test_scene_lookup_helpers_raise_keyerror():
    s = Scene(title="t")
    with pytest.raises(KeyError):
        s.character("nope")
    with pytest.raises(KeyError):
        s.environment("nope")
    with pytest.raises(KeyError):
        s.shot("nope")
    with pytest.raises(KeyError):
        s.beat("nope")


def test_beat_content_hash_changes_with_content():
    b1 = make_beat("A", "Hello", emotion="calm", index=0)
    b2 = make_beat("A", "Hello", emotion="frantic", index=0)
    char = Character(name="A", reference_image_url="http://x/face.png")
    h1 = beat_content_hash(b1, character=char)
    h2 = beat_content_hash(b2, character=char)
    assert h1 != h2


def test_beat_content_hash_changes_with_face_swap():
    b = make_beat("A", "Hello", index=0)
    c1 = Character(name="A", reference_image_url="http://x/face1.png")
    c2 = Character(name="A", reference_image_url="http://x/face2.png")
    assert beat_content_hash(b, character=c1) != beat_content_hash(b, character=c2)


def test_scene_roundtrip_via_dict():
    voice = Voice(name="Sarah", reference_audio_url="http://x/sarah.wav")
    scene = Scene(
        title="Diner Encounter",
        style="Wes-Anderson pastel",
        characters=(
            Character(
                name="Sarah",
                description="mid-30s",
                reference_image_url="http://x/s.png",
                voice=voice,
            ),
            Character(name="Tom"),
        ),
        environments=(
            Environment(name="diner", description="1950s", time_of_day="midnight"),
        ),
        shots=(
            make_shot(
                "two-shot at the booth",
                framing="medium",
                environment="diner",
                characters=("Sarah", "Tom"),
                index=0,
            ),
        ),
        beats=(
            make_beat(
                "Sarah", "Why are you here?", shot_id="x", emotion="wary", index=0
            ),
            make_beat("Tom", "I came to apologize.", index=1),
        ),
    )
    d = scene_to_dict(scene)
    blob = json.dumps(d)  # must serialize cleanly
    restored = scene_from_dict(json.loads(blob))
    assert restored.title == "Diner Encounter"
    assert restored.character("Sarah").voice.reference_audio_url == "http://x/sarah.wav"
    assert restored.environment("diner").time_of_day == "midnight"
    assert restored.beats[0].emotion == "wary"


def test_save_load_scene_roundtrip(tmp_path):
    scene = Scene(title="t", characters=(Character(name="A"),))
    p = tmp_path / "scene.json"
    save_scene(scene, str(p))
    restored = load_scene(str(p))
    assert restored.title == "t"
    assert restored.character("A").name == "A"
