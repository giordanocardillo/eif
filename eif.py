#!/usr/bin/env python3
"""
EIF — Elemental Infrastructure Framework
CLI renderer and upgrade tool.

Commands:
    eif render  <matter-dir> <env>    Render composition + env → .rendered/<env>/main.tf
    eif upgrade <matter-dir> <env>    Bump all molecule sources to their latest version

Examples:
    uv run eif render  matter/three-tier-app dev
    uv run eif render  matter/three-tier-app prod
    uv run eif upgrade matter/three-tier-app dev
"""

import json
import os
import re
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_repo_root(start: Path) -> Path:
    """Walk up from start until we find accounts.json."""
    current = start
    while current != current.parent:
        if (current / "accounts.json").exists():
            return current
        current = current.parent
    sys.exit("[eif] ERROR: accounts.json not found in any parent directory")


def latest_version(module_path: Path) -> str | None:
    """Return the highest vN directory name inside module_path, or None."""
    if not module_path.is_dir():
        return None
    versions = [
        d.name for d in module_path.iterdir()
        if d.is_dir() and re.fullmatch(r"v\d+", d.name)
    ]
    if not versions:
        return None
    return max(versions, key=lambda v: int(v[1:]))


def resolve_sources(molecules: list, repo_root: Path, output_dir: Path) -> dict:
    """Return {mol_name: relative_path} for each molecule."""
    return {
        mol["name"]: os.path.relpath((repo_root / mol["source"]).resolve(), output_dir)
        for mol in molecules
    }


def load_inputs(matter_path: Path, env: str) -> tuple:
    repo_root = find_repo_root(matter_path)

    accounts_file    = repo_root / "accounts.json"
    composition_file = matter_path / "composition.json"
    env_file         = matter_path / f"{env}.json"
    template_file    = matter_path / "main.tf.j2"

    for path, label in [
        (accounts_file,    "accounts.json"),
        (composition_file, "composition.json"),
        (env_file,         f"{env}.json"),
        (template_file,    "main.tf.j2"),
    ]:
        if not path.exists():
            sys.exit(f"[eif] ERROR: {label} not found at {path}")

    with accounts_file.open() as fh:
        accounts = json.load(fh)
    with composition_file.open() as fh:
        composition = json.load(fh)
    with env_file.open() as fh:
        env_config = json.load(fh)

    account_key = env_config.get("account")
    if account_key not in accounts:
        sys.exit(
            f"[eif] ERROR: account '{account_key}' not defined in accounts.json. "
            f"Available: {list(accounts.keys())}"
        )

    return accounts[account_key], composition, env_config, repo_root, composition_file


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_render(matter_dir: str, env: str) -> None:
    matter_path = Path(matter_dir).resolve()
    account_config, composition, env_config, repo_root, _ = load_inputs(matter_path, env)

    output_dir  = matter_path / ".rendered" / env
    output_file = output_dir / "main.tf"
    output_dir.mkdir(parents=True, exist_ok=True)

    src = resolve_sources(composition["molecules"], repo_root, output_dir)

    # Flat env vars (minus "account") + auto-injected environment + src lookup
    env_vars = {k: v for k, v in env_config.items() if k != "account"}
    ctx = {
        **account_config,
        **env_vars,
        "environment": env,
        "account": env_config["account"],
        "molecules": composition["molecules"],
        "src": src,
    }

    j2_env = Environment(
        loader=FileSystemLoader(str(matter_path)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    rendered = j2_env.get_template("main.tf.j2").render(**ctx)

    header = (
        "# ============================================================================\n"
        "# EIF — Elemental Infrastructure Framework\n"
        f"# Matter      : {composition['matter']}\n"
        f"# Environment : {env}\n"
        f"# Account     : {env_config['account']}\n"
        "# DO NOT EDIT — rendered by eif. Edit the .j2 template and composition files.\n"
        "# ============================================================================\n"
        "\n"
    )
    output_file.write_text(header + rendered)

    print(f"[eif] rendered  → {output_file}")
    print(f"[eif] deploy    → terraform -chdir={output_dir} init")
    print(f"[eif]             terraform -chdir={output_dir} apply")


def cmd_upgrade(matter_dir: str, env: str) -> None:
    matter_path = Path(matter_dir).resolve()
    _, composition, _, repo_root, composition_file = load_inputs(matter_path, env)

    upgraded = []
    for mol in composition["molecules"]:
        source = mol["source"]
        parts  = source.rsplit("/", 1)

        if len(parts) != 2 or not re.fullmatch(r"v\d+", parts[1]):
            print(f"[eif] skip      {source!r} — no version suffix")
            continue

        base    = repo_root / parts[0]
        current = parts[1]
        latest  = latest_version(base)

        if latest is None:
            print(f"[eif] skip      {source!r} — no versioned directories found")
            continue

        if latest == current:
            print(f"[eif] up-to-date {source!r}")
        else:
            mol["source"] = f"{parts[0]}/{latest}"
            upgraded.append((source, mol["source"]))
            print(f"[eif] upgraded  {source!r} → {mol['source']!r}")

    # Write back only the composition file (env files are unaffected by upgrades)
    if upgraded:
        clean = {**composition, "molecules": [
            {"name": m["name"], "source": m["source"]} for m in composition["molecules"]
        ]}
        composition_file.write_text(json.dumps(clean, indent=2) + "\n")
        print(f"[eif] wrote     → {composition_file}")
    else:
        print("[eif] nothing to upgrade")


# ── Entry point ───────────────────────────────────────────────────────────────

COMMANDS = {"render": cmd_render, "upgrade": cmd_upgrade}

def main() -> None:
    if len(sys.argv) != 4 or sys.argv[1] not in COMMANDS:
        sys.exit(
            "Usage:\n"
            "  eif render  <matter-dir> <env>\n"
            "  eif upgrade <matter-dir> <env>"
        )
    COMMANDS[sys.argv[1]](sys.argv[2], sys.argv[3])


if __name__ == "__main__":
    main()
