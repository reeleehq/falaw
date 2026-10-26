"""Task-level verbs: stable, agent-friendly entry points.

Each submodule registers its functions via the `register_tool` decorator,
so importing this package populates the ToolRegistry as a side effect.
"""

from .audio import generate_audio, text_to_speech, voice_clone  # noqa: F401
from .avatar import animate_face, lipsync, talking_avatar_from_text  # noqa: F401
from .images import (  # noqa: F401
    composite_character_in_environment,
    edit_image,
    generate_image,
    generate_image_with_refs,
    remove_background,
    upscale_image,
)
from .llm import (  # noqa: F401
    apply_note_to_beat,
    apply_note_to_scene,
    LlmReceipt,
    llm_complete,
    llm_complete_with_receipt,
    parse_screenplay,
)
from .preproduction import (  # noqa: F401
    cast_character,
    cast_voice,
    establish_environment,
    storyboard_shot,
)
from .render import (  # noqa: F401
    iter_render_scene,
    render_beat,
    render_scene,
    render_shot,
)
from .video import image_to_video, text_to_video  # noqa: F401

# Plan/Execute siblings: pure-data planning for the ops nw needs first.
from ._plan import (  # noqa: F401
    plan_animate_face,
    plan_composite_character_in_environment,
    plan_edit_image,
    plan_generate_image,
    plan_generate_image_with_refs,
    plan_image_to_video,
    plan_reference_to_video,
    plan_text_to_video,
    plan_lipsync,
    plan_llm_complete,
    plan_generate_audio,
    plan_text_to_speech,
)
