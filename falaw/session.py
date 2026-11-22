"""Session: optional stateful controller over a sequence of falaw operations.

Plain function calls work without a session. Sessions exist to make multi-step
flows ergonomic --- a working directory, a result history, and a journal
binding that future-you (or another agent) can read.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

from .journal import Journal, _default_journal
from .results import Result


@dataclass
class Session:
    """A working session for a sequence of falaw operations.

    >>> import tempfile
    >>> s = Session(output_dir=tempfile.mkdtemp())
    >>> s.history
    []
    """

    output_dir: str = field(default_factory=os.getcwd)
    journal: Journal = field(default_factory=_default_journal)
    history: list[Result] = field(default_factory=list)

    def __post_init__(self):
        os.makedirs(self.output_dir, exist_ok=True)

    def record(self, result: Result) -> Result:
        """Append ``result`` to the history and return it."""
        self.history.append(result)
        return result

    def latest(self, *, kind: Optional[str] = None) -> Optional[Result]:
        """The most recent result (of the given asset ``kind``, if given), or ``None``."""
        for r in reversed(self.history):
            if kind is None or any(a.kind == kind for a in r.assets):
                return r
        return None
