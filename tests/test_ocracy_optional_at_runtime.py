"""falaw must import and resolve fal keys even where ``ocracy`` is not installed.

``ocracy`` is a declared dependency, but an editable checkout updated with ``git pull``
or a wheel installed with ``--no-deps`` can miss it. These tests run in a subprocess
with ``ocracy`` blocked at the import system and check that ``falaw._credentials``
falls back to its stdlib chain with the same behaviour, and says so with a warning.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap

_BLOCK = textwrap.dedent(
    """
    import sys, warnings
    warnings.simplefilter("always")

    class _Block:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] == "ocracy":
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)
            return None

    sys.meta_path.insert(0, _Block())
    """
)


def _run(body: str, tmp_path) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("FAL_KEY", "FAL_API_KEY")}
    return subprocess.run(
        [sys.executable, "-c", _BLOCK + textwrap.dedent(body)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(tmp_path),
        timeout=120,
    )


def test_falaw_key_chain_works_without_ocracy(tmp_path):
    proc = _run(
        """
        import os
        import pytest
        import falaw
        from falaw import current_fal_key, using_fal_credentials
        from falaw import _credentials
        from falaw.pricing import _resolve_api_key

        assert _credentials.SHARED_KIT is False
        assert "ocracy" not in sys.modules
        assert current_fal_key() is None
        with using_fal_credentials(None):
            assert current_fal_key() is None
        with using_fal_credentials("outer"):
            with using_fal_credentials("inner"):
                assert current_fal_key() == "inner"
                assert _resolve_api_key(None) == "inner"
            assert current_fal_key() == "outer"
            assert _resolve_api_key("explicit") == "explicit"
        assert current_fal_key() is None
        os.environ["FAL_API_KEY"] = "server-key"
        assert _resolve_api_key(None) == "server-key"
        del os.environ["FAL_API_KEY"]
        with pytest.raises(RuntimeError, match="FAL_KEY"):
            _resolve_api_key(None)
        print("OK")
        """,
        tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip().endswith("OK")
    assert "ocracy" in proc.stderr and "RuntimeWarning" in proc.stderr
