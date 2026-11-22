"""Scene IR: the editable structure that survives all the way to the pixels.

Design thesis (from the Directa Labs one-pager): a film stays in *editable
structure* from idea to final cut. The creator authors a Scene as data.
A directorial note becomes a single IR edit. The renderer picks it up
and re-renders only what changed.

All entities are frozen dataclasses with content-derived ids so:

* equality and hashing are structural --- two beats with identical content
  share an id, and the cache can short-circuit re-rendering;
* edits create new entities (immutable); diffs against the previous
  version are obvious and surgical;
* serialization to JSON/YAML is mechanical (asdict).

The renderer (`falaw.operations.render`) consumes Scene; LLM tools
(`falaw.operations.llm`) produce or edit it.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Iterable, Mapping, Optional


def _slug(text: str, *, maxlen: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:maxlen] or "x"


def _content_hash(payload: Mapping[str, Any]) -> str:
    """Stable 12-char hash of the (json-serialised) payload.

    Used to assign deterministic ids derived from semantic content, so two
    structurally-identical entities collapse to the same id.
    """
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:12]


# --- core entities --------------------------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class Voice:
    """A character's voice spec.

    Three modes, choose any:
    * ``voice_id`` --- model-side voice id (e.g. ElevenLabs voice).
    * ``reference_audio_url`` --- a few seconds of audio to clone.
    * ``model_id`` --- override the default TTS model for this voice.

    Always provide ``name`` for stable, human-readable referencing.
    """

    name: str
    voice_id: str = ""
    reference_audio_url: str = ""
    model_id: str = ""
    style_notes: str = ""  # "warm, slightly raspy", etc.


@dataclass(frozen=True, slots=True, kw_only=True)
class Character:
    """A reusable character: stable face, stable voice, stable style."""

    name: str
    description: str = ""  # used to generate face if reference_image_url empty
    reference_image_url: str = ""  # the canonical face for lipsync
    voice: Optional[Voice] = None
    style_notes: str = ""  # "method-actor; reads thoughts before words"


@dataclass(frozen=True, slots=True, kw_only=True)
class Environment:
    """A reusable location/setting."""

    name: str
    description: str = ""
    reference_image_url: str = ""
    time_of_day: str = ""  # "dusk", "midnight", "golden hour"
    lighting: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class Shot:
    """A visual frame: framing + environment + characters in view.

    Beats anchor to a Shot via ``shot_id``. The Shot itself has its own
    rendered output (still or short clip used as the anchor for beat
    lipsync renders).
    """

    id: str
    description: str = ""
    framing: str = "medium"  # "wide" | "medium" | "close" | "ecu" | ...
    environment: str = ""  # Environment.name
    characters: tuple[str, ...] = ()  # Character names in shot
    camera: str = ""  # "static", "slow push-in", "handheld"
    notes: str = ""  # any other directorial intent


@dataclass(frozen=True, slots=True, kw_only=True)
class Beat:
    """The atomic unit of a scene: who, says what, with what intent.

    A Beat that has only ``action`` (no ``line``) is a non-verbal beat.
    """

    id: str
    speaker: str = ""  # Character.name; "" for non-verbal
    line: str = ""
    action: str = ""  # "she looks away"
    emotion: str = ""  # "cracking; tries to hide it"
    shot_id: str = ""  # which Shot this beat plays inside
    duration_s: Optional[float] = None  # None = infer from line
    notes: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class Scene:
    """The whole editable structure: cast, locations, shots, beats."""

    title: str
    style: str = ""  # "Wes Anderson symmetrical pastel"; overall look
    characters: tuple[Character, ...] = ()
    environments: tuple[Environment, ...] = ()
    shots: tuple[Shot, ...] = ()
    beats: tuple[Beat, ...] = ()
    notes: str = ""

    # --- lookup helpers ---

    def character(self, name: str) -> Character:
        """The character named ``name``; ``KeyError`` if there is none."""
        for c in self.characters:
            if c.name == name:
                return c
        raise KeyError(f"No character named {name!r} in scene {self.title!r}")

    def environment(self, name: str) -> Environment:
        """The environment named ``name``; ``KeyError`` if there is none."""
        for e in self.environments:
            if e.name == name:
                return e
        raise KeyError(f"No environment named {name!r} in scene {self.title!r}")

    def shot(self, shot_id: str) -> Shot:
        """The shot with id ``shot_id``; ``KeyError`` if there is none."""
        for s in self.shots:
            if s.id == shot_id:
                return s
        raise KeyError(f"No shot id {shot_id!r} in scene {self.title!r}")

    def beat(self, beat_id: str) -> Beat:
        """The beat with id ``beat_id``; ``KeyError`` if there is none."""
        for b in self.beats:
            if b.id == beat_id:
                return b
        raise KeyError(f"No beat id {beat_id!r} in scene {self.title!r}")

    # --- mutation: replace returns a new Scene ---

    def with_beat(self, beat: Beat) -> "Scene":
        """Return a new Scene with `beat` replacing any existing beat with the same id."""
        replaced = False
        new_beats: list[Beat] = []
        for b in self.beats:
            if b.id == beat.id:
                new_beats.append(beat)
                replaced = True
            else:
                new_beats.append(b)
        if not replaced:
            new_beats.append(beat)
        return replace(self, beats=tuple(new_beats))

    def with_character(self, character: Character) -> "Scene":
        """A copy of the scene with ``character`` added, or replacing the one of that name."""
        replaced = False
        new_chars: list[Character] = []
        for c in self.characters:
            if c.name == character.name:
                new_chars.append(character)
                replaced = True
            else:
                new_chars.append(c)
        if not replaced:
            new_chars.append(character)
        return replace(self, characters=tuple(new_chars))

    def with_environment(self, environment: Environment) -> "Scene":
        """A copy of the scene with ``environment`` added, or replacing the one of that name."""
        replaced = False
        new_envs: list[Environment] = []
        for e in self.environments:
            if e.name == environment.name:
                new_envs.append(environment)
                replaced = True
            else:
                new_envs.append(e)
        if not replaced:
            new_envs.append(environment)
        return replace(self, environments=tuple(new_envs))

    def with_shot(self, shot: Shot) -> "Scene":
        """A copy of the scene with ``shot`` added, or replacing the one with that id."""
        replaced = False
        new_shots: list[Shot] = []
        for s in self.shots:
            if s.id == shot.id:
                new_shots.append(shot)
                replaced = True
            else:
                new_shots.append(s)
        if not replaced:
            new_shots.append(shot)
        return replace(self, shots=tuple(new_shots))


# --- id generation --------------------------------------------------------


def beat_id(
    *, speaker: str, line: str, action: str = "", index: Optional[int] = None
) -> str:
    """Deterministic, human-readable-ish beat id.

    Pattern: ``{index?}-{speaker_slug}-{content_hash}``. Index makes
    chronological sort cheap; the hash makes the id stable when content
    is unchanged.
    """
    h = _content_hash({"speaker": speaker, "line": line, "action": action})
    parts = []
    if index is not None:
        parts.append(f"{index:03d}")
    parts.append(_slug(speaker or "narration", maxlen=20))
    parts.append(h)
    return "-".join(parts)


def shot_id(*, description: str, framing: str = "", index: Optional[int] = None) -> str:
    """A stable shot id derived from the description and framing (and ``index`` when given)."""
    h = _content_hash({"desc": description, "framing": framing})
    parts = []
    if index is not None:
        parts.append(f"{index:03d}")
    parts.append(_slug(framing or "shot", maxlen=10))
    parts.append(h)
    return "-".join(parts)


def beat_content_hash(beat: Beat, *, character: Optional[Character] = None) -> str:
    """Hash everything that affects how the beat *renders*.

    Includes the beat's content + the character's identity anchors
    (face image, voice spec). Style/emotion changes invalidate the
    cache; pure id renames do not.
    """
    payload: dict = {
        "speaker": beat.speaker,
        "line": beat.line,
        "action": beat.action,
        "emotion": beat.emotion,
        "duration": beat.duration_s,
    }
    if character is not None:
        payload["face"] = character.reference_image_url
        if character.voice:
            payload["voice"] = {
                "voice_id": character.voice.voice_id,
                "reference_audio_url": character.voice.reference_audio_url,
                "model_id": character.voice.model_id,
            }
    return _content_hash(payload)


def shot_content_hash(shot: Shot, *, environment: Optional[Environment] = None) -> str:
    """A content hash of everything that determines a shot's render."""
    payload: dict = {
        "desc": shot.description,
        "framing": shot.framing,
        "characters": list(shot.characters),
        "camera": shot.camera,
    }
    if environment is not None:
        payload["env"] = environment.reference_image_url
    return _content_hash(payload)


# --- serialization --------------------------------------------------------


def scene_to_dict(scene: Scene) -> dict:
    """The scene as a plain dict."""
    return asdict(scene)


def scene_from_dict(d: Mapping[str, Any]) -> Scene:
    """Inverse of asdict: reconstruct a Scene from a plain dict."""
    voice_of = lambda v: Voice(**v) if v else None  # noqa: E731
    chars = tuple(
        Character(
            name=c["name"],
            description=c.get("description", ""),
            reference_image_url=c.get("reference_image_url", ""),
            voice=voice_of(c.get("voice")),
            style_notes=c.get("style_notes", ""),
        )
        for c in d.get("characters", ())
    )
    envs = tuple(Environment(**e) for e in d.get("environments", ()))
    shots = tuple(
        Shot(
            id=s["id"],
            description=s.get("description", ""),
            framing=s.get("framing", "medium"),
            environment=s.get("environment", ""),
            characters=tuple(s.get("characters", ())),
            camera=s.get("camera", ""),
            notes=s.get("notes", ""),
        )
        for s in d.get("shots", ())
    )
    beats = tuple(Beat(**b) for b in d.get("beats", ()))
    return Scene(
        title=d["title"],
        style=d.get("style", ""),
        characters=chars,
        environments=envs,
        shots=shots,
        beats=beats,
        notes=d.get("notes", ""),
    )


def save_scene(scene: Scene, path: str) -> str:
    """Write the scene to ``path`` as JSON and return the path."""
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(scene_to_dict(scene), f, indent=2, default=str)
    return path


def load_scene(path: str) -> Scene:
    """Read a scene from the JSON file at ``path``."""
    with open(path) as f:
        return scene_from_dict(json.load(f))


# --- convenience constructors --------------------------------------------


def make_beat(
    speaker: str,
    line: str = "",
    *,
    action: str = "",
    emotion: str = "",
    shot_id: str = "",
    index: Optional[int] = None,
    notes: str = "",
    duration_s: Optional[float] = None,
) -> Beat:
    """Build a :class:`Beat` for ``speaker`` saying ``line``."""
    return Beat(
        id=beat_id(speaker=speaker, line=line, action=action, index=index),
        speaker=speaker,
        line=line,
        action=action,
        emotion=emotion,
        shot_id=shot_id,
        duration_s=duration_s,
        notes=notes,
    )


def make_shot(
    description: str,
    *,
    framing: str = "medium",
    environment: str = "",
    characters: Iterable[str] = (),
    camera: str = "",
    notes: str = "",
    index: Optional[int] = None,
) -> Shot:
    """Build a :class:`Shot` from a description and framing."""
    return Shot(
        id=shot_id(description=description, framing=framing, index=index),
        description=description,
        framing=framing,
        environment=environment,
        characters=tuple(characters),
        camera=camera,
        notes=notes,
    )
