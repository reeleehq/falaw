"""The one result type every gate check returns."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Problem:
    """One reason a deployment or a graph does not pass.

    ``item`` is the checklist row it belongs to (``"1"``..``"11"``, ``"L"``),
    so a failure points back at the requirement it breaks.
    """

    item: str
    message: str

    def __str__(self) -> str:
        return f"{self.item}: {self.message}"
