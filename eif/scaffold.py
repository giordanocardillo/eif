"""scaffold.py — cmd_new_*, cmd_remove_*, _list_atoms, _list_molecules, _list_matters."""

import shutil
import sys
from pathlib import Path

from .core import (
    _atom_categories,
    _is_semver,
    _next_semver,
    find_repo_root,
    latest_version,
)
from .ui import (
    _c, _em, _arr,
    _ask, _choose, _confirm, _write,
    _detect_providers,
    _list_atoms,
    _list_molecules,
    _list_matters,
    _multiselect,
    _provider_tf_block,
)


def _confirm_remove(target: Path, repo_root: Path) -> None:
    """Print the target path and ask for confirmation before deleting."""
    rel = target.relative_to(repo_root)
    print(f"\n  {_c('remove', 'red', 'bold')}  {_c(str(rel), 'cyan')}\n")
    for f in sorted(target.rglob("*")):
        if f.is_file():
            print(f"    {_c('-', 'red')} {f.relative_to(repo_root)}")
    print()
    if not _confirm(f"delete {rel}?", default=False):
        sys.exit("aborted")
    shutil.rmtree(target)
    print(f"{_em('✅')}removed   {_arr()} {_c(str(rel), 'cyan')}")


def cmd_remove_atom(args: list[str]) -> None:
    repo_root = find_repo_root(Path.cwd())
    providers = _detect_providers(repo_root)

    provider = args[0] if len(args) > 0 else _choose("provider", providers)
    cats     = _atom_categories(provider, repo_root)
    category = args[1] if len(args) > 1 else _choose("category", cats)

    atom_dir = repo_root / "atoms" / provider / category
    atoms    = [d.name for d in sorted(atom_dir.iterdir()) if d.is_dir()] if atom_dir.is_dir() else []
    if not atoms:
        sys.exit(f"❌  ERROR: no atoms found in {atom_dir}")
    name = args[2] if len(args) > 2 else _choose("atom", atoms)

    target = atom_dir / name
    if not target.is_dir():
        sys.exit(f"❌  ERROR: {target} not found")
    _confirm_remove(target, repo_root)


def cmd_remove_molecule(args: list[str]) -> None:
    repo_root = find_repo_root(Path.cwd())
    providers = _detect_providers(repo_root)

    provider  = args[0] if len(args) > 0 else _choose("provider", providers)
    mol_dir   = repo_root / "molecules" / provider
    molecules = [d.name for d in sorted(mol_dir.iterdir()) if d.is_dir()] if mol_dir.is_dir() else []
    if not molecules:
        sys.exit(f"❌  ERROR: no molecules found for provider '{provider}'")
    name = args[1] if len(args) > 1 else _choose("molecule", molecules)

    target = mol_dir / name
    if not target.is_dir():
        sys.exit(f"❌  ERROR: {target} not found")
    _confirm_remove(target, repo_root)


def cmd_remove_matter(args: list[str]) -> None:
    repo_root = find_repo_root(Path.cwd())
    providers = _detect_providers(repo_root)

    provider = args[0] if len(args) > 0 else _choose("provider", providers)
    matters  = _list_matters(provider, repo_root)
    if not matters:
        sys.exit(f"❌  ERROR: no matters found for provider '{provider}'")
    name = args[1] if len(args) > 1 else _choose("matter", matters)

    target = repo_root / "matters" / name / provider
    if not target.is_dir():
        sys.exit(f"❌  ERROR: {target} not found")
    _confirm_remove(target, repo_root)
    # Remove the parent matter dir too if now empty
    parent = target.parent
    if parent.is_dir() and not any(parent.iterdir()):
        parent.rmdir()


def cmd_remove(args: list[str]) -> None:
    SUB = {
        "atom":      cmd_remove_atom,     "atoms":     cmd_remove_atom,
        "molecule":  cmd_remove_molecule, "molecules": cmd_remove_molecule,
        "matter":    cmd_remove_matter,   "matters":   cmd_remove_matter,
    }
    if not args or args[0] not in SUB:
        sys.exit(
            "Usage:\n"
            "  eif remove atom     [<provider> <category> <name>]\n"
            "  eif remove molecule [<provider> <name>]\n"
            "  eif remove matter   [<provider> <name>]"
        )
    SUB[args[0]](args[1:])


def cmd_new_atom(args: list[str]) -> None:
    repo_root = find_repo_root(Path.cwd())
    cwd = repo_root

    name      = args[0] if len(args) > 0 else _ask("name")
    providers = _detect_providers(repo_root)
    if not providers:
        sys.exit("❌  ERROR: no providers found in providers/")

    if len(args) > 1:
        provider = args[1]
        if provider not in providers:
            sys.exit(f"❌  ERROR: unknown provider '{provider}'. Available: {providers}")
    else:
        provider = _choose("provider", providers)

    if len(args) > 2:
        cat = args[2]
    else:
        existing_cats = _atom_categories(provider, repo_root)
        categories    = existing_cats + (["other"] if existing_cats else ["compute", "networking", "storage", "security", "other"])
        cat = _choose("category", categories)
        if cat == "other":
            cat = _ask("category name")

    non_interactive = len(args) >= 3

    atom_dir = repo_root / "atoms" / provider / cat / name
    existing = latest_version(atom_dir)

    if existing:
        if _is_semver(existing):
            print(f"\n{_em('📦')}{_c(str(atom_dir.relative_to(cwd)), 'cyan')} — latest: {_c(existing, 'dim')}")
            bump    = _choose("bump type", ["patch", "minor", "major"])
            next_ver = _next_semver(existing, bump)
        else:
            next_ver = f"v{int(existing[1:]) + 1}"
        if non_interactive:
            print(f"{_em('📦')}{_c(str(atom_dir.relative_to(cwd)), 'cyan')} — latest: {_c(existing, 'dim')}, creating {_c(next_ver, 'bgreen')}")
        else:
            if not _confirm(f"create {next_ver}?"):
                sys.exit("aborted")
        new_ver = next_ver
    else:
        new_ver = "1.0.0"
        print(f"{_em('📦')}{_c(str(atom_dir.relative_to(cwd)), 'cyan')} — no existing versions, creating {_c(new_ver, 'bgreen')}")

    out = atom_dir / new_ver
    if out.exists():
        sys.exit(f"ERROR: {out.relative_to(cwd)} already exists")
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

    print(f"\n{_em('✅')}{_c('atom ready', 'bgreen', 'bold')} {_arr()} {_c(str(out.relative_to(cwd)), 'cyan')}")


def cmd_new_molecule(args: list[str]) -> None:
    repo_root = find_repo_root(Path.cwd())
    cwd = repo_root

    providers = _detect_providers(repo_root)
    if not providers:
        sys.exit("❌  ERROR: no providers found in providers/")

    if len(args) > 1:
        provider = args[1]
        if provider not in providers:
            sys.exit(f"❌  ERROR: unknown provider '{provider}'. Available: {providers}")
    else:
        provider = _choose("provider", providers)

    if not _list_atoms(provider, repo_root):
        sys.exit(f"❌  ERROR: no atoms found for {provider} — create atoms first with 'eif new atom'")

    name     = args[0] if len(args) > 0 else _ask("name")
    mol_dir  = repo_root / "molecules" / provider / name
    existing = latest_version(mol_dir)
    non_interactive = len(args) >= 3

    if existing:
        if _is_semver(existing):
            print(f"\n{_em('📦')}{_c(str(mol_dir.relative_to(cwd)), 'cyan')} — latest: {_c(existing, 'dim')}")
            bump     = _choose("bump type", ["patch", "minor", "major"])
            next_ver = _next_semver(existing, bump)
        else:
            next_ver = f"v{int(existing[1:]) + 1}"
        if non_interactive:
            print(f"{_em('📦')}{_c(str(mol_dir.relative_to(cwd)), 'cyan')} — latest: {_c(existing, 'dim')}, creating {_c(next_ver, 'bgreen')}")
        else:
            if not _confirm(f"create {next_ver}?"):
                sys.exit("aborted")
        new_ver = next_ver
    else:
        new_ver = "1.0.0"
        print(f"{_em('📦')}{_c(str(mol_dir.relative_to(cwd)), 'cyan')} — no existing versions, creating {_c(new_ver, 'bgreen')}")

    # Atom selection
    all_atoms = _list_atoms(provider, repo_root)
    selected_atoms: list[dict] = []
    if len(args) > 2:
        atom_map = {f"{a['category']}/{a['name']}": a for a in all_atoms}
        for key in (x.strip() for x in args[2].split(",") if x.strip()):
            if key not in atom_map:
                sys.exit(f"❌  ERROR: atom '{key}' not found. Available: {list(atom_map)}")
            selected_atoms.append(atom_map[key])
    else:
        print()
        selected_atoms = _multiselect("atoms to include", all_atoms)

    out = mol_dir / new_ver
    if out.exists():
        sys.exit(f"❌  ERROR: {out.relative_to(cwd)} already exists")
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
            f"#   source      = \"../../../../atoms/{provider}/<category>/<name>/1.0.0\"\n"
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

    print(f"\n{_em('✅')}{_c('molecule ready', 'bgreen', 'bold')} {_arr()} {_c(str(out.relative_to(cwd)), 'cyan')}")


def cmd_new_matter(args: list[str]) -> None:
    repo_root = find_repo_root(Path.cwd())
    cwd = repo_root

    name      = args[0] if len(args) > 0 else _ask("name")
    providers = _detect_providers(repo_root)
    if not providers:
        sys.exit("❌  ERROR: no providers found in providers/")

    if len(args) > 1:
        provider = args[1]
        if provider not in providers:
            sys.exit(f"❌  ERROR: unknown provider '{provider}'. Available: {providers}")
    else:
        provider = _choose("provider", providers)

    out = repo_root / "matters" / name / provider
    if out.exists():
        sys.exit(f"❌  ERROR: {out.relative_to(cwd)} already exists")

    # Molecule selection — local authored + cached packages only
    # Use `eif package install` first to fetch packages from the registry
    all_mols = _list_molecules(provider, repo_root)

    selected_mols: list[dict] = []
    if len(args) > 2:
        mol_map = {m["name"]: m for m in all_mols}
        for mol_name in (x.strip() for x in args[2].split(",") if x.strip()):
            if mol_name not in mol_map:
                sys.exit(f"❌  ERROR: molecule '{mol_name}' not found. Available: {list(mol_map)}")
            selected_mols.append(mol_map[mol_name])
    elif all_mols:
        print()
        selected_mols = _multiselect("molecules to include", all_mols)
    else:
        print(f"  {_c(f'no molecules found for {provider} — run eif package install first', 'dim')}")

    out.mkdir(parents=True)
    print()

    # Build molecule list for composition (all already local/cached)
    mol_entries = []
    for mol in selected_mols:
        mol_entries.append({"name": mol["name"], "source": f"{provider}/{mol['name']}", "version": mol["version"]})

    # composition.json
    import json
    composition = {
        "matter": name,
        "molecules": mol_entries,
    }
    (out / "composition.json").write_text(json.dumps(composition, indent=2) + "\n")
    print(f"{_em('✨')}created   {_arr()} {_c(str((out / 'composition.json').relative_to(cwd)), 'cyan')}")

    _write(out / "dev.example.json",  json.dumps({"account": "dev"},  indent=2) + "\n", cwd)
    _write(out / "prod.example.json", json.dumps({"account": "prod"}, indent=2) + "\n", cwd)

    # main.tf.j2 — one module block per selected molecule
    # provider block is prepended automatically by the renderer — no need to include it here
    template = "# ── Molecules ─────────────────────────────────────────────────────────────────\n\n"
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
    _write(out / "main.tf.j2", template, cwd)

    render_path = out.relative_to(cwd)
    dev_example = str((out / "dev.example.json").relative_to(cwd))
    dev_json    = str((out / "dev.json").relative_to(cwd))
    main_j2     = str((out / "main.tf.j2").relative_to(cwd))
    print(f"\n{_em('✅')}{_c('matter ready', 'bgreen', 'bold')} {_arr()} {_c(str(render_path), 'cyan')}")
    print(f"\n{_c('next steps:', 'bold')}")
    print(f"  1. {_c(f'cp {dev_example} {dev_json}', 'dim')}")
    print(f"  2. wire variables in {_c(main_j2, 'cyan')}")
    print(f"  3. {_c(f'uv run eif apply {render_path} dev', 'bcyan')}")


def cmd_new(args: list[str]) -> None:
    SUB = {
        "atom":      cmd_new_atom,      "atoms":     cmd_new_atom,
        "molecule":  cmd_new_molecule,  "molecules": cmd_new_molecule,
        "matter":    cmd_new_matter,    "matters":   cmd_new_matter,
    }
    if not args or args[0] not in SUB:
        sys.exit(
            "Usage:\n"
            "  eif new atom     [<name> [<provider> [<category>]]]\n"
            "  eif new molecule [<name> [<provider> [<category/atom>,...]]]\n"
            "  eif new matter   [<name> [<provider> [<molecule>,...  ]]]"
        )
    SUB[args[0]](args[1:])
