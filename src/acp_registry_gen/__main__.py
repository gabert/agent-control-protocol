"""CLI: draft a registry from SQL DDL, an OpenAPI spec, or an MCP tool list.

Usage (from the repo checkout)::

    python -m acp_registry_gen sql     schema.sql        --domain payments -o draft.registry.yaml
    python -m acp_registry_gen openapi api.yaml          --domain ledger
    python -m acp_registry_gen mcp     tools.json        --domain crm

The output is a DRAFT: every guessed kind/attribute carries a TODO(review)
marker. The draft is schema-validated before it is written; a validation
failure is a generator bug and exits non-zero.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

from acp_registry_gen.emit import emit_yaml, validate_registry_yaml
from acp_registry_gen.importers import draft_from_mcp_tools, draft_from_openapi
from acp_registry_gen.model import DraftRegistry
from acp_registry_gen.sql import draft_from_sql


def _load_structured(path: Path) -> Any:
    # YAML is a JSON superset, so one loader covers .json/.yaml/.yml inputs.
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _build(source: str, path: Path, domain: str) -> DraftRegistry:
    if source == "sql":
        return draft_from_sql(path.read_text(encoding="utf-8"), domain=domain)
    if source == "openapi":
        return draft_from_openapi(_load_structured(path), domain=domain)
    return draft_from_mcp_tools(_load_structured(path), domain=domain)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="acp_registry_gen",
        description="Draft an ACP registry (authoring format, docs/06) from existing artefacts.",
    )
    parser.add_argument("source", choices=("sql", "openapi", "mcp"), help="input artefact type")
    parser.add_argument("input", type=Path, help="DDL file, OpenAPI spec, or MCP tool list")
    parser.add_argument("--domain", default=None, help="registry domain (default: input file stem)")
    parser.add_argument("-o", "--out", type=Path, default=None, help="output file (default: stdout)")
    args = parser.parse_args(argv)

    domain = args.domain or args.input.stem
    draft = _build(args.source, args.input, domain)
    if not draft.entities:
        print(f"error: no entities/actions found in {args.input}", file=sys.stderr)
        return 1

    text = emit_yaml(draft)
    problems = validate_registry_yaml(text)
    if problems:  # a generator bug — never ship an invalid draft
        for p in problems:
            print(f"error: generated draft fails registry.schema.json: {p}", file=sys.stderr)
        return 1

    if args.out is None:
        sys.stdout.write(text)
    else:
        args.out.write_text(text, encoding="utf-8", newline="\n")
        entities = len(draft.entities)
        actions = sum(len(e.actions) for e in draft.entities)
        print(
            f"wrote {args.out} ({entities} entities, {actions} drafted actions) — "
            f"review every TODO(review) before use",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
