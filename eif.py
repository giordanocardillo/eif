#!/usr/bin/env python3
"""
EIF — Elemental Infrastructure Framework
CLI renderer: environment composition + accounts.json → main.tf

Usage:
    eif <matter-dir> <env>

Example:
    uv run eif matter/three-tier-app dev
    uv run eif matter/three-tier-app prod
"""

import json
import os
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


def find_repo_root(start: Path) -> Path:
    """Walk up from start until we find accounts.json."""
    current = start
    while current != current.parent:
        if (current / "accounts.json").exists():
            return current
        current = current.parent
    sys.exit("[eif] ERROR: accounts.json not found in any parent directory")


def resolve_sources(molecules: list, repo_root: Path, output_dir: Path) -> None:
    """Rewrite each molecule's source to a path relative to the output directory."""
    for mol in molecules:
        mol_abs = (repo_root / mol["source"]).resolve()
        mol["source"] = os.path.relpath(mol_abs, output_dir)


def render(matter_dir: str, env: str) -> None:
    matter_path = Path(matter_dir).resolve()
    repo_root   = find_repo_root(matter_path)

    accounts_file    = repo_root / "accounts.json"
    composition_file = matter_path / f"{env}.json"
    template_file    = matter_path / "main.tf.j2"
    output_dir       = matter_path / ".rendered" / env
    output_file      = output_dir / "main.tf"

    for path, label in [
        (accounts_file,    "accounts.json"),
        (composition_file, f"{env}.json"),
        (template_file,    "main.tf.j2"),
    ]:
        if not path.exists():
            sys.exit(f"[eif] ERROR: {label} not found at {path}")

    with accounts_file.open() as fh:
        accounts = json.load(fh)

    with composition_file.open() as fh:
        composition = json.load(fh)

    account_key = composition.get("account")
    if account_key not in accounts:
        sys.exit(
            f"[eif] ERROR: account '{account_key}' not defined in accounts.json. "
            f"Available: {list(accounts.keys())}"
        )
    account_config = accounts[account_key]

    output_dir.mkdir(parents=True, exist_ok=True)
    resolve_sources(composition["molecules"], repo_root, output_dir)

    ctx = {**account_config, **composition, "environment": env}

    j2_env = Environment(
        loader=FileSystemLoader(str(matter_path)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = j2_env.get_template("main.tf.j2")
    rendered = template.render(**ctx)

    output_file.write_text(rendered)
    print(f"[eif] rendered  → {output_file}")
    print(f"[eif] deploy    → terraform -chdir={output_dir} init")
    print(f"[eif]             terraform -chdir={output_dir} apply")


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("Usage: eif <matter-dir> <env>")
    render(sys.argv[1], sys.argv[2])


if __name__ == "__main__":
    main()
