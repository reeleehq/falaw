"""Which model a router call really goes to (falaw#115).

``fal-ai/any-llm`` is one catalogue record that routes many upstream models.
The routed model is who serves, prices and licenses the call, so both the rate
table (:mod:`falaw.llm_rates`) and the terms ledger (:mod:`falaw.terms`) judge
it, not the router. This module is the one place that knows which applications
route and by which argument.

>>> routed_model("fal-ai/any-llm", {"model": "anthropic/claude-sonnet-4.5"})
'anthropic/claude-sonnet-4.5'
>>> routed_model("fal-ai/flux/dev", {"model": "ignored"})
'fal-ai/flux/dev'
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping, Optional

ANY_LLM = "fal-ai/any-llm"
"""The application that routes an LLM call to one of many upstream models."""

ROUTERS = MappingProxyType({ANY_LLM: "model", f"{ANY_LLM}/vision": "model"})
"""Applications that route to another model, mapped to the argument naming it."""


def routed_model(application: str, arguments: Optional[Mapping] = None) -> str:
    """The model that serves the call: the one a router's argument names, else
    *application* itself."""
    arg = ROUTERS.get(application)
    routed = (arguments or {}).get(arg) if arg else None
    return routed if isinstance(routed, str) and routed else application


__all__ = ["ANY_LLM", "ROUTERS", "routed_model"]
