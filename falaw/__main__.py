"""CLI entry: ``python -m falaw <command>``.

Commands:
  refresh-llms          Conditional GET of llms.txt and llms-full.txt.
  refresh-full          Re-crawl per-page docs (gated on llms-full staleness).
  refresh-llm-rates     Diff llm_rates.json against its two live sources.
                         Pass --write to persist a proposed table + diff
                         (never overwrites the committed table).
  state                 Print the saved refresh state (etags, last fetch).
  regen-skill           Regenerate the Claude SKILL.md from the registry.
  export-schema [DIR]   Write the JSON contract the TypeScript twin (ts/)
                         is generated from (default DIR: schema).
"""

from __future__ import annotations

import json
import sys

from .bridges.skill import write_skill_files
from .llm_rates_refresh import refresh_llm_rates
from .refresh import refresh_full_docs, refresh_llms, refresh_state


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    """Run the ``falaw`` command line; return the process exit code."""
    argv = argv if argv is not None else sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, *rest = argv
    if cmd == "refresh-llms":
        _print_json(refresh_llms())
        return 0
    if cmd == "refresh-full":
        force = "--force" in rest
        _print_json(refresh_full_docs(force=force))
        return 0
    if cmd == "refresh-llm-rates":
        write = "--write" in rest
        _print_json(refresh_llm_rates(write=write))
        return 0
    if cmd == "state":
        _print_json(refresh_state())
        return 0
    if cmd == "regen-skill":
        import os

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for d in (
            os.path.join(repo_root, "falaw", "data", "skills", "falaw"),
            os.path.join(repo_root, ".claude", "skills", "falaw"),
        ):
            print("wrote", write_skill_files(d))
        return 0
    if cmd == "export-schema":
        from .schema_export import export_schema

        for path in export_schema(rest[0] if rest else None):
            print(path)
        return 0
    print(f"Unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
