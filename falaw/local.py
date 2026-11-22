"""Local utilities: ffmpeg + PIL glue for stitching fal outputs.

The fal calls produce URLs. This module materializes them into local
files and assembles them into watchable scenes (concat, transitions,
thumbnails, etc.). Anything that's cheap to do locally lives here so
the cloud calls stay focused on generation.

`ffmpeg` is the one external dependency. The functions raise a clear
error if it's missing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Iterable, Optional

from .cache import materialize_asset


def _require(binary: str) -> str:
    path = shutil.which(binary)
    if path is None:
        raise RuntimeError(
            f"falaw.local: required binary {binary!r} not found on PATH. "
            f"On macOS: `brew install {binary}`."
        )
    return path


def _run(cmd: list[str], *, capture: bool = False) -> str:
    proc = subprocess.run(
        cmd,
        check=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc.stdout if capture else ""


def concatenate_clips(
    clip_urls: Iterable[str],
    *,
    output_path: str,
    transition_s: float = 0.0,
    audio: bool = True,
) -> str:
    """Materialize each clip and concatenate into one mp4.

    Args:
        clip_urls: ordered iterable of fal-served clip URLs (or local paths).
        output_path: where to write the concatenated mp4.
        transition_s: crossfade duration in seconds (0 = hard cut).
        audio: whether to include audio in the output.

    Returns:
        The output path.
    """
    ffmpeg = _require("ffmpeg")
    locals_ = [_to_local(u) for u in clip_urls]
    if not locals_:
        raise ValueError("concatenate_clips: empty clip list")

    if transition_s <= 0:
        # Hard-cut concat using the demuxer.
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False
        ) as listfile:
            for p in locals_:
                listfile.write(f"file '{os.path.abspath(p)}'\n")
            listpath = listfile.name
        try:
            os.makedirs(
                os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True
            )
            cmd = [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                listpath,
                "-c",
                "copy",
                output_path,
            ]
            if not audio:
                cmd[-1:-1] = ["-an"]
            _run(cmd)
        finally:
            os.unlink(listpath)
        return output_path

    # Crossfade variant: build an xfade filtergraph chain.
    n = len(locals_)
    inputs: list[str] = []
    for p in locals_:
        inputs += ["-i", p]
    durations = [_probe_duration(p) for p in locals_]
    filter_lines: list[str] = []
    last = "[0:v]"
    offset = 0.0
    for i in range(1, n):
        offset += durations[i - 1] - transition_s
        out = f"[v{i}]"
        filter_lines.append(
            f"{last}[{i}:v]xfade=transition=fade:duration={transition_s}:"
            f"offset={offset:.3f}{out}"
        )
        last = out
    afilter = ""
    if audio:
        a_last = "[0:a]"
        a_offset = 0.0
        for i in range(1, n):
            a_offset += durations[i - 1] - transition_s
            a_out = f"[a{i}]"
            filter_lines.append(f"{a_last}[{i}:a]acrossfade=d={transition_s}{a_out}")
            a_last = a_out
        afilter = f";{a_last}"
    filtergraph = ";".join(filter_lines)
    cmd = [
        ffmpeg,
        "-y",
        *inputs,
        "-filter_complex",
        filtergraph,
        "-map",
        last,
    ]
    if audio:
        cmd += ["-map", a_last]
    cmd += [output_path]
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    _run(cmd)
    return output_path


def extract_thumbnail(
    clip_url: str,
    *,
    output_path: str,
    at_seconds: float = 1.0,
) -> str:
    """Save a single frame from a clip as a PNG."""
    ffmpeg = _require("ffmpeg")
    src = _to_local(clip_url)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    _run(
        [
            ffmpeg,
            "-y",
            "-ss",
            f"{at_seconds:.3f}",
            "-i",
            src,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            output_path,
        ]
    )
    return output_path


def overlay_audio(
    video_url: str,
    audio_url: str,
    *,
    output_path: str,
    replace_audio: bool = True,
) -> str:
    """Mix an audio track onto a video clip.

    With ``replace_audio=True`` (default) the original audio is dropped.
    """
    ffmpeg = _require("ffmpeg")
    v = _to_local(video_url)
    a = _to_local(audio_url)
    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    cmd = [ffmpeg, "-y", "-i", v, "-i", a]
    if replace_audio:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    else:
        cmd += [
            "-filter_complex",
            "[0:a][1:a]amix=inputs=2:duration=longest",
        ]
    cmd += ["-c:v", "copy", "-shortest", output_path]
    _run(cmd)
    return output_path


def _probe_duration(path: str) -> float:
    """Return the duration of a media file in seconds, via ffprobe."""
    ffprobe = _require("ffprobe")
    out = _run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nokey=1:noprint_wrappers=1",
            path,
        ],
        capture=True,
    )
    return float(out.strip())


def _to_local(url_or_path: str) -> str:
    if os.path.exists(url_or_path):
        return url_or_path
    if "://" in url_or_path:
        return materialize_asset(url_or_path)
    raise FileNotFoundError(f"Not a URL or local path: {url_or_path!r}")


def has_ffmpeg() -> bool:
    """Whether both ``ffmpeg`` and ``ffprobe`` are on ``PATH``."""
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
