#!/usr/bin/env python3
"""
EIF — Elemental Infrastructure Framework
CLI renderer, upgrade tool, and scaffolding.

Commands:
    eif render      <matter-dir> <env>   Render composition + env → .rendered/<env>/main.tf
    eif upgrade     <matter-dir> <env>   Bump all molecule sources to their latest version
    eif new atom    [name]               Scaffold a new atom (interactive)
    eif new molecule [name]              Scaffold a new molecule (interactive)
    eif new matter  [name]               Scaffold a new matter (interactive)

Examples:
    uv run eif render      matters/three-tier-app/aws dev
    uv run eif render      matters/three-tier-app/aws prod
    uv run eif upgrade     matters/three-tier-app/aws dev
    uv run eif new atom
    uv run eif new molecule my-service
    uv run eif new matter   my-app
"""

import json
import os
import re
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


# ── Constants ─────────────────────────────────────────────────────────────────

ATOM_CATEGORIES = ["compute", "networking", "storage", "security"]

_PROVIDER_TF: dict[str, str] = {
    "aws": (
        "terraform {\n"
        "  required_providers {\n"
        "    aws = {\n"
        '      source  = "hashicorp/aws"\n'
        '      version = ">= 5.0"\n'
        "    }\n"
        "  }\n"
        '  required_version = ">= 1.5"\n'
        "}\n"
    ),
    "azure": (
        "terraform {\n"
        "  required_providers {\n"
        "    azurerm = {\n"
        '      source  = "hashicorp/azurerm"\n'
        '      version = ">= 3.0"\n'
        "    }\n"
        "  }\n"
        '  required_version = ">= 1.5"\n'
        "}\n"
    ),
    "gcp": (
        "terraform {\n"
        "  required_providers {\n"
        "    google = {\n"
        '      source  = "hashicorp/google"\n'
        '      version = ">= 5.0"\n'
        "    }\n"
        "  }\n"
        '  required_version = ">= 1.5"\n'
        "}\n"
    ),
}


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


# ── Interactive helpers ────────────────────────────────────────────────────────

def _prompt(label: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default else ""
    try:
        val = input(f"  {label}{suffix}: ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit("[eif] aborted")
    return val if val else (default or "")


def _require(label: str, default: str | None = None) -> str:
    """Like _prompt but exits if the result is empty."""
    val = _prompt(label, default)
    if not val:
        sys.exit(f"[eif] ERROR: {label} is required")
    return val


def _choose(label: str, options: list[str]) -> str:
    """Present a numbered menu and return the chosen option."""
    print(f"  {label}:")
    for i, opt in enumerate(options, 1):
        print(f"    {i}) {opt}")
    while True:
        raw = _prompt("choice")
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1]
        if raw in options:
            return raw
        print(f"  [!] enter a number 1–{len(options)} or the name directly")


def _confirm(label: str, default: bool = False) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    val = _prompt(f"{label} {hint}").lower()
    if not val:
        return default
    return val in ("y", "yes")


def _detect_providers(repo_root: Path) -> list[str]:
    providers_dir = repo_root / "providers"
    if not providers_dir.is_dir():
        return []
    return sorted(d.name for d in providers_dir.iterdir() if d.is_dir())


def _list_atoms(provider: str, repo_root: Path) -> list[dict]:
    """Return all versioned atoms for a provider as a list of dicts."""
    atoms_dir = repo_root / "atoms" / provider
    if not atoms_dir.is_dir():
        return []
    result = []
    for cat in sorted(atoms_dir.iterdir()):
        if not cat.is_dir():
            continue
        for atom in sorted(cat.iterdir()):
            if not atom.is_dir():
                continue
            ver = latest_version(atom)
            if ver:
                result.append({
                    "label":    f"{cat.name}/{atom.name}  ({ver})",
                    "name":     atom.name,
                    "category": cat.name,
                    "version":  ver,
                    "rel_path": f"../../../../atoms/{provider}/{cat.name}/{atom.name}/{ver}",
                })
    return result


def _list_molecules(provider: str, repo_root: Path) -> list[dict]:
    """Return all versioned molecules for a provider as a list of dicts."""
    mol_dir = repo_root / "molecules" / provider
    if not mol_dir.is_dir():
        return []
    result = []
    for mol in sorted(mol_dir.iterdir()):
        if not mol.is_dir():
            continue
        ver = latest_version(mol)
        if ver:
            result.append({
                "label":   f"{mol.name}  ({ver})",
                "name":    mol.name,
                "version": ver,
                "source":  f"molecules/{provider}/{mol.name}/{ver}",
            })
    return result


def _multiselect(label: str, items: list[dict]) -> list[dict]:
    """Present a numbered list and return the user-selected subset (at least one)."""
    print(f"  {label}:")
    for i, item in enumerate(items, 1):
        print(f"    {i}) {item['label']}")
    while True:
        raw = _prompt("select (comma-separated, e.g. 1,3)")
        try:
            parts = [x.strip() for x in raw.split(",") if x.strip()]
            indices = [int(p) - 1 for p in parts]
            if parts and all(0 <= idx < len(items) for idx in indices):
                return [items[idx] for idx in indices]
        except ValueError:
            pass
        print(f"  [!] enter comma-separated numbers from 1 to {len(items)}")


def _provider_tf_block(provider: str) -> str:
    if provider in _PROVIDER_TF:
        return _PROVIDER_TF[provider]
    return (
        "terraform {\n"
        "  required_providers {\n"
        f"    # TODO: configure {provider} provider\n"
        "  }\n"
        '  required_version = ">= 1.5"\n'
        "}\n"
    )


def _write(path: Path, content: str, cwd: Path) -> None:
    path.write_text(content)
    print(f"[eif] created   {path.relative_to(cwd)}")


# ── Commands (render / upgrade) ───────────────────────────────────────────────

def render_provider_block(account_config: dict, repo_root: Path) -> str:
    """Render providers/<cloud>/provider.tf.j2 with the account config."""
    provider = account_config.get("provider")
    if not provider:
        sys.exit("[eif] ERROR: account entry is missing a 'provider' field")
    provider_template = repo_root / "providers" / provider / "provider.tf.j2"
    if not provider_template.exists():
        sys.exit(f"[eif] ERROR: no provider template found at {provider_template}")
    j2_env = Environment(
        loader=FileSystemLoader(str(provider_template.parent)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    return j2_env.get_template("provider.tf.j2").render(**account_config)


def cmd_render(matter_dir: str, env: str) -> None:
    matter_path = Path(matter_dir).resolve()
    account_config, composition, env_config, repo_root, _ = load_inputs(matter_path, env)

    output_dir  = matter_path / ".rendered" / env
    output_file = output_dir / "main.tf"
    output_dir.mkdir(parents=True, exist_ok=True)

    src = resolve_sources(composition["molecules"], repo_root, output_dir)
    provider_block = render_provider_block(account_config, repo_root)

    # Flat env vars (minus "account") + auto-injected environment + src lookup
    env_vars = {k: v for k, v in env_config.items() if k != "account"}
    ctx = {
        **account_config,
        **env_vars,
        "environment": env,
        "account": env_config["account"],
        "molecules": composition["molecules"],
        "src": src,
        "provider_block": provider_block,
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

    if upgraded:
        clean = {**composition, "molecules": [
            {"name": m["name"], "source": m["source"]} for m in composition["molecules"]
        ]}
        composition_file.write_text(json.dumps(clean, indent=2) + "\n")
        print(f"[eif] wrote     → {composition_file}")
    else:
        print("[eif] nothing to upgrade")


# ── Commands (new) ────────────────────────────────────────────────────────────

def cmd_new_atom(name_arg: str | None) -> None:
    repo_root = find_repo_root(Path.cwd())
    cwd = Path.cwd()
    print("[eif] New atom\n")

    name = name_arg or _require("name")

    providers = _detect_providers(repo_root)
    if not providers:
        sys.exit("[eif] ERROR: no providers found in providers/")
    provider = _choose("provider", providers)

    categories = ATOM_CATEGORIES + ["other"]
    cat = _choose("category", categories)
    if cat == "other":
        cat = _require("category name")

    atom_dir = repo_root / "atoms" / provider / cat / name
    existing = latest_version(atom_dir)

    if existing:
        next_ver = f"v{int(existing[1:]) + 1}"
        print(f"\n[eif] {atom_dir.relative_to(cwd)} — latest: {existing}")
        if not _confirm(f"create {next_ver}?"):
            sys.exit("[eif] aborted")
        new_ver = next_ver
    else:
        print(f"\n[eif] {atom_dir.relative_to(cwd)} — no existing versions, creating v1")
        new_ver = "v1"

    out = atom_dir / new_ver
    if out.exists():
        sys.exit(f"[eif] ERROR: {out.relative_to(cwd)} already exists")
    out.mkdir(parents=True)

    tf = _provider_tf_block(provider)

    _write(out / "main.tf", (
        f"{tf}\n"
        f"# TODO: implement {name} atom\n"
        f"# resource \"{provider}_{name}\" \"this\" {{\n"
        "#   ...\n"
        "# }\n"
    ), cwd)

    _write(out / "variables.tf", (
        'variable "environment" {\n'
        '  description = "Deployment environment (e.g. dev, test, prod)."\n'
        '  type        = string\n'
        "}\n\n"
        "# TODO: add variables\n"
    ), cwd)

    _write(out / "outputs.tf", (
        "# TODO: add outputs\n"
        "# output \"id\" {\n"
        "#   description = \"...\"\n"
        f"#   value       = {provider}_{name}.this.id\n"
        "# }\n"
    ), cwd)

    print(f"\n[eif] atom ready → {out.relative_to(cwd)}")


def cmd_new_molecule(name_arg: str | None) -> None:
    repo_root = find_repo_root(Path.cwd())
    cwd = Path.cwd()
    print("[eif] New molecule\n")

    name = name_arg or _require("name")

    providers = _detect_providers(repo_root)
    if not providers:
        sys.exit("[eif] ERROR: no providers found in providers/")
    provider = _choose("provider", providers)

    mol_dir = repo_root / "molecules" / provider / name
    existing = latest_version(mol_dir)

    if existing:
        next_ver = f"v{int(existing[1:]) + 1}"
        print(f"\n[eif] {mol_dir.relative_to(cwd)} — latest: {existing}")
        if not _confirm(f"create {next_ver}?"):
            sys.exit("[eif] aborted")
        new_ver = next_ver
    else:
        print(f"\n[eif] {mol_dir.relative_to(cwd)} — no existing versions, creating v1")
        new_ver = "v1"

    # Atom selection
    atoms = _list_atoms(provider, repo_root)
    selected_atoms: list[dict] = []
    if atoms:
        print()
        selected_atoms = _multiselect("atoms to include", atoms)
    else:
        print(f"\n[eif] no atoms found for {provider} — scaffolding empty molecule")

    out = mol_dir / new_ver
    if out.exists():
        sys.exit(f"[eif] ERROR: {out.relative_to(cwd)} already exists")
    out.mkdir(parents=True)
    print()

    tf = _provider_tf_block(provider)

    # main.tf — one module block per selected atom
    main_tf = f"{tf}\n"
    if selected_atoms:
        for atom in selected_atoms:
            bar = "─" * max(1, 60 - len(atom["category"]) - len(atom["name"]))
            main_tf += (
                f"# ── Atom: {atom['category']}/{atom['name']} {bar}\n"
                f"module \"{atom['name']}\" {{\n"
                f"  source = \"{atom['rel_path']}\"\n\n"
                f"  environment = var.environment\n"
                f"  # TODO: add variables\n"
                f"}}\n\n"
            )
    else:
        main_tf += (
            f"# TODO: add module blocks referencing atoms/{provider}/...\n"
            "# module \"example\" {\n"
            f"#   source      = \"../../../../atoms/{provider}/<category>/<name>/v1\"\n"
            "#   environment = var.environment\n"
            "# }\n"
        )
    _write(out / "main.tf", main_tf, cwd)

    _write(out / "variables.tf", (
        'variable "environment" {\n'
        '  description = "Deployment environment (e.g. dev, test, prod)."\n'
        '  type        = string\n'
        "}\n\n"
        "# TODO: add variables\n"
    ), cwd)

    # outputs.tf — one commented stub per selected atom
    if selected_atoms:
        outputs_tf = "# TODO: expose atom outputs\n"
        for atom in selected_atoms:
            outputs_tf += (
                f"# output \"{atom['name']}_id\" {{\n"
                f"#   description = \"...\"\n"
                f"#   value       = module.{atom['name']}.id\n"
                f"# }}\n"
            )
        _write(out / "outputs.tf", outputs_tf, cwd)
    else:
        _write(out / "outputs.tf", (
            "# TODO: expose atom outputs\n"
            "# output \"example_id\" {\n"
            "#   description = \"...\"\n"
            "#   value       = module.example.id\n"
            "# }\n"
        ), cwd)

    print(f"\n[eif] molecule ready → {out.relative_to(cwd)}")


def cmd_new_matter(name_arg: str | None) -> None:
    repo_root = find_repo_root(Path.cwd())
    cwd = Path.cwd()
    print("[eif] New matter\n")

    name = name_arg or _require("name")

    providers = _detect_providers(repo_root)
    if not providers:
        sys.exit("[eif] ERROR: no providers found in providers/")
    provider = _choose("provider", providers)

    out = repo_root / "matters" / name / provider
    if out.exists():
        sys.exit(f"[eif] ERROR: {out.relative_to(cwd)} already exists")

    # Molecule selection
    molecules = _list_molecules(provider, repo_root)
    selected_mols: list[dict] = []
    if molecules:
        print()
        selected_mols = _multiselect("molecules to include", molecules)
    else:
        print(f"\n[eif] no molecules found for {provider} — scaffolding empty matter")

    out.mkdir(parents=True)
    print()

    # composition.json
    composition = {
        "matter": name,
        "molecules": [{"name": m["name"], "source": m["source"]} for m in selected_mols],
    }
    (out / "composition.json").write_text(json.dumps(composition, indent=2) + "\n")
    print(f"[eif] created   {(out / 'composition.json').relative_to(cwd)}")

    _write(out / "dev.example.json",  json.dumps({"account": "dev"},  indent=2) + "\n", cwd)
    _write(out / "prod.example.json", json.dumps({"account": "prod"}, indent=2) + "\n", cwd)

    # main.tf.j2 — one module block per selected molecule
    template = "{{ provider_block }}\n"
    template += "# ── Molecules ─────────────────────────────────────────────────────────────────\n\n"
    if selected_mols:
        for mol in selected_mols:
            template += (
                f"module \"{mol['name']}\" {{\n"
                f"  source = \"{{{{ src['{mol['name']}'] }}}}\"\n\n"
                f"  environment = \"{{{{ environment }}}}\"\n"
                f"  # TODO: add variables\n"
                f"}}\n\n"
            )
    else:
        template += (
            "# TODO: add module blocks\n"
            "# module \"example\" {\n"
            "#   source      = \"{{ src['example'] }}\"\n"
            "#   environment = \"{{ environment }}\"\n"
            "# }\n\n"
        )
    template += (
        "# ── Outputs ───────────────────────────────────────────────────────────────────\n"
        "{% for mol in molecules %}\n"
        "output \"{{ mol.name | replace('-', '_') }}_outputs\" {\n"
        "  description = \"Outputs from the {{ mol.name }} molecule.\"\n"
        "  value       = module.{{ mol.name }}\n"
        "}\n"
        "{% endfor %}\n"
    )
    _write(out / "main.tf.j2", template, cwd)

    render_path = out.relative_to(cwd)
    print(f"\n[eif] matter ready → {render_path}")
    print(f"[eif] next steps:")
    print(f"[eif]   1. cp {(out / 'dev.example.json').relative_to(cwd)} {(out / 'dev.json').relative_to(cwd)}")
    print(f"[eif]   2. wire variables in {(out / 'main.tf.j2').relative_to(cwd)}")
    print(f"[eif]   3. uv run eif render {render_path} dev")


def cmd_new(args: list[str]) -> None:
    SUB = {
        "atom":     cmd_new_atom,
        "molecule": cmd_new_molecule,
        "matter":   cmd_new_matter,
    }
    if not args or args[0] not in SUB:
        sys.exit(
            "Usage:\n"
            "  eif new atom     [name]\n"
            "  eif new molecule [name]\n"
            "  eif new matter   [name]"
        )
    name_arg = args[1] if len(args) > 1 else None
    SUB[args[0]](name_arg)


# ── Entry point ───────────────────────────────────────────────────────────────

USAGE = (
    "Usage:\n"
    "  eif render      <matter-dir> <env>\n"
    "  eif upgrade     <matter-dir> <env>\n"
    "  eif new atom    [name]\n"
    "  eif new molecule [name]\n"
    "  eif new matter  [name]"
)

def main() -> None:
    args = sys.argv[1:]
    if not args:
        sys.exit(USAGE)

    cmd = args[0]

    if cmd == "new":
        cmd_new(args[1:])
    elif cmd == "render" and len(args) == 3:
        cmd_render(args[1], args[2])
    elif cmd == "upgrade" and len(args) == 3:
        cmd_upgrade(args[1], args[2])
    else:
        sys.exit(USAGE)


if __name__ == "__main__":
    main()
