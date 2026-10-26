"""The ComfyUI licence screen reads SPDX tags against the shared vocabulary (falaw#115)."""

from falaw.comfyui.licences import screen_licences


def _screen(tmp_path, text):
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "LICENSE").write_text(text)
    return screen_licences(tmp_path, commit_of=lambda p: "abc123")


def test_a_valid_spdx_tag_makes_a_licence_determinable(tmp_path):
    assert _screen(tmp_path, "SPDX-License-Identifier: BSD-3-Clause\n").passed


def test_a_tag_outside_the_vocabulary_is_undeterminable(tmp_path):
    screen = _screen(tmp_path, "SPDX-License-Identifier: Totally-Made-Up-1.0\n")
    assert screen.undeterminable == ("pack",)


def test_an_invalid_tag_outweighs_a_matching_title(tmp_path):
    text = "MIT License\n\nSPDX-License-Identifier: Totally-Made-Up-1.0\n"
    assert _screen(tmp_path, text).undeterminable == ("pack",)


def test_an_agpl_tag_is_still_restricted(tmp_path):
    assert _screen(tmp_path, "SPDX-License-Identifier: AGPL-3.0-only\n").agpl_packs == (
        "pack",
    )


def test_a_licenseref_tag_is_not_a_determinable_licence(tmp_path):
    screen = _screen(tmp_path, "SPDX-License-Identifier: LicenseRef-Proprietary-NC\n")
    assert screen.undeterminable == ("pack",)


def test_a_tag_in_a_comment_and_a_with_exception_are_read(tmp_path):
    assert _screen(
        tmp_path, "/* SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception */\n"
    ).passed


def test_a_tag_overrides_a_title_that_matched_before(tmp_path):
    assert _screen(
        tmp_path, "MIT License\nSPDX-License-Identifier: LicenseRef-Proprietary\n"
    ).undeterminable == ("pack",)


def test_tag_ids_are_case_insensitive(tmp_path):
    assert _screen(tmp_path, "SPDX-License-Identifier: mit\n").passed


def test_a_decorated_agpl_tag_past_the_title_is_still_restricted(tmp_path):
    text = "MIT License\n" + "\n".join(f"line {i}" for i in range(20))
    text += "\n * SPDX-License-Identifier: AGPL-3.0-only *\n"
    assert _screen(tmp_path, text).agpl_packs == ("pack",)
