"""diff.py — diff helpers + cmd_diff_*."""

import json
import re
import sys
import tempfile
from pathlib import Path

from .core import _is_semver, _semver_key, find_repo_root, latest_version
from .packages import _packages_dir, _check_outdated, _build_clients
from .registry import RegistryClient
from .ui import (
    _c, _em, _arr,
    _choose,
    _detect_providers,
    _list_atoms,
    _list_molecules,
    _resolve_matter_and_env,
)


def _parse_variables(tf_file: Path) -> dict[str, dict]:
    """Parse variable blocks from a Terraform .tf file.

    Returns {name: {"type": str, "has_default": bool}}.
    Uses brace-balanced scanning to handle nested types (e.g. object({...})).
    """
    if not tf_file.exists():
        return {}
    text = tf_file.read_text()
    result = {}
    for m in re.finditer(r'variable\s+"([^"]+)"\s*\{', text):
        name  = m.group(1)
        start = m.end()
        depth = 1
        i     = start
        while i < len(text) and depth > 0:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        body        = text[start : i - 1]
        has_default = bool(re.search(r"^\s*default\s*=", body, re.MULTILINE))
        type_match  = re.search(r"^\s*type\s*=\s*(.+)", body, re.MULTILINE)
        type_str    = type_match.group(1).strip() if type_match else "any"
        result[name] = {"type": type_str, "has_default": has_default}
    return result


def _parse_outputs(tf_file: Path) -> set[str]:
    """Return the set of output names defined in a Terraform .tf file."""
    if not tf_file.exists():
        return set()
    return {m.group(1) for m in re.finditer(r'output\s+"([^"]+)"', tf_file.read_text())}


def _diff_interface(old_path: Path, new_path: Path) -> list[dict]:
    """Compare variables.tf and outputs.tf between two versioned directories.

    Returns change records with keys: kind, name, breaking, and type extras.

    Kinds and breaking semantics:
      var_added         breaking if no default (new required var the matter must supply)
      var_removed       breaking (matter must stop passing it or TF errors)
      var_type_changed  breaking (potential incompatibility)
      var_became_req    breaking (default removed — matter must now explicitly set it)
      output_added      non-breaking
      output_removed    breaking (downstream consumers lose the value)
    """
    old_vars = _parse_variables(old_path / "variables.tf")
    new_vars = _parse_variables(new_path / "variables.tf")
    old_outs = _parse_outputs(old_path / "outputs.tf")
    new_outs = _parse_outputs(new_path / "outputs.tf")

    changes: list[dict] = []

    for name, info in new_vars.items():
        if name not in old_vars:
            changes.append({
                "kind":        "var_added",
                "name":        name,
                "type":        info["type"],
                "has_default": info["has_default"],
                "breaking":    not info["has_default"],
            })
        else:
            old = old_vars[name]
            if old["type"] != info["type"]:
                changes.append({
                    "kind":     "var_type_changed",
                    "name":     name,
                    "old_type": old["type"],
                    "new_type": info["type"],
                    "breaking": True,
                })
            if old["has_default"] and not info["has_default"]:
                changes.append({
                    "kind":     "var_became_req",
                    "name":     name,
                    "type":     info["type"],
                    "breaking": True,
                })

    for name in old_vars:
        if name not in new_vars:
            changes.append({"kind": "var_removed", "name": name, "breaking": True})

    for name in sorted(old_outs - new_outs):
        changes.append({"kind": "output_removed", "name": name, "breaking": True})

    for name in sorted(new_outs - old_outs):
        changes.append({"kind": "output_added", "name": name, "breaking": False})

    return changes


def _print_diff(changes: list[dict]) -> None:
    """Render a list of change records as colored diff rows."""
    from .ui import _diff_row
    for c in sorted(changes, key=lambda x: (x["kind"], x["name"])):
        name = c["name"]
        if c["kind"] == "var_added":
            req = "(required)" if not c["has_default"] else "(optional)"
            print(_diff_row("+", f"var  {name:<28} {c['type']:<22} {req}", "bg_green"))
        elif c["kind"] == "var_removed":
            print(_diff_row("-", f"var  {name}", "bg_red"))
        elif c["kind"] == "var_type_changed":
            print(_diff_row("~", f"var  {name:<28} {c['old_type']} → {c['new_type']}", "bg_yellow"))
        elif c["kind"] == "var_became_req":
            print(_diff_row("~", f"var  {name:<28} default removed — now required", "bg_yellow"))
        elif c["kind"] == "output_added":
            print(_diff_row("+", f"out  {name}", "bg_green"))
        elif c["kind"] == "output_removed":
            print(_diff_row("-", f"out  {name}", "bg_red"))


def _diff_component(label: str, path: str, component_dir: Path,
                       consumer_msg: str,
                       from_ver: str | None = None, to_ver: str | None = None) -> None:
    """Shared renderer for atom and molecule single-component diffs."""
    versions = sorted(
        [d.name for d in component_dir.iterdir() if d.is_dir() and _is_semver(d.name)],
        key=_semver_key,
    )

    if from_ver is not None or to_ver is not None:
        for v, flag in ((from_ver, "from"), (to_ver, "to")):
            if v and not (component_dir / v).is_dir():
                available = ", ".join(versions) or "none"
                sys.exit(f"❌  ERROR: version '{v}' not found — available: {available}")
        current, latest = from_ver, to_ver
    else:
        if len(versions) < 2:
            print(f"{_em('✅')}{_c('only one version exists — nothing to diff', 'green')}")
            return
        current, latest = versions[-2], versions[-1]
    changes         = _diff_interface(component_dir / current, component_dir / latest)
    is_breaking     = any(c["breaking"] for c in changes)
    status          = (f"{_em('💥')}{_c('BREAKING', 'bred', 'bold')}"
                       if is_breaking else _c("non-breaking", "bgreen"))
    ver_range       = f"{_c(current, 'yellow')} {_arr()} {_c(latest, 'bgreen', 'bold')}"

    print(f"\n{_em('👁️')} {_c(label + ' diff', 'bcyan', 'bold')}  {_arr()} {_c(path, 'cyan')}\n")
    print(f"  {_c(path, 'cyan', 'bold'):<30} {ver_range}  [{status}]\n")

    if not changes:
        print(f"  {_c('(no interface changes)', 'dim')}")
    else:
        _print_diff(changes)

    print()
    if is_breaking:
        print(f"{_em('💥')}{_c('BREAKING changes detected', 'bred', 'bold')}\n"
              f"   {consumer_msg}")
    else:
        print(f"{_em('✅')}{_c('no breaking changes', 'bgreen', 'bold')}")


def _diff_component_remote(label: str, path: str, remote_rel: str,
                              consumer_msg: str, client: RegistryClient,
                              from_ver: str | None, to_ver: str | None) -> None:
    """Preview a component that lives in a remote registry."""
    print(f"  {_c('fetching version list from registry...', 'dim')}", end="\r", flush=True)
    versions = client.list_versions(remote_rel)
    print(" " * 50, end="\r")

    if not versions:
        sys.exit(f"❌  ERROR: component '{path}' not found in registry {client.name} ({client.url})")

    if from_ver is not None or to_ver is not None:
        for v in (from_ver, to_ver):
            if v and v not in versions:
                sys.exit(f"❌  ERROR: version '{v}' not found — available: {', '.join(versions)}")
        current, latest = from_ver, to_ver
    else:
        if len(versions) < 2:
            print(f"{_em('✅')}{_c('only one version exists — nothing to diff', 'green')}")
            return
        current, latest = versions[-2], versions[-1]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for ver in (current, latest):
            ver_dir = tmp_path / ver
            ver_dir.mkdir()
            for tf_name in ("variables.tf", "outputs.tf"):
                content = client.fetch_file(f"{remote_rel}/{ver}/{tf_name}")
                if content:
                    (ver_dir / tf_name).write_text(content)

        changes     = _diff_interface(tmp_path / current, tmp_path / latest)
        is_breaking = any(c["breaking"] for c in changes)
        status      = (f"{_em('💥')}{_c('BREAKING', 'bred', 'bold')}"
                       if is_breaking else _c("non-breaking", "bgreen"))
        ver_range   = f"{_c(current, 'yellow')} {_arr()} {_c(latest, 'bgreen', 'bold')}"

        print(f"\n{_em('👁️')} {_c(label + ' diff', 'bcyan', 'bold')}  "
              f"{_arr()} {_c(path, 'cyan')}  {_c('[remote]', 'dim')}\n")
        print(f"  {_c(path, 'cyan', 'bold'):<30} {ver_range}  [{status}]\n")

        if not changes:
            print(f"  {_c('(no interface changes)', 'dim')}")
        else:
            _print_diff(changes)

        print()
        if is_breaking:
            print(f"{_em('💥')}{_c('BREAKING changes detected', 'bred', 'bold')}\n"
                  f"   {consumer_msg}")
        else:
            print(f"{_em('✅')}{_c('no breaking changes', 'bgreen', 'bold')}")


def _resolve_provider(args: list[str], offset: int = 0) -> tuple[str, Path]:
    """Return (provider, repo_root) from args[offset] or interactive prompt."""
    repo_root = find_repo_root(Path.cwd())
    providers = _detect_providers(repo_root)
    if not providers:
        sys.exit("❌  ERROR: no providers found in providers/")
    if len(args) > offset:
        provider = args[offset]
        if provider not in providers:
            sys.exit(f"❌  ERROR: unknown provider '{provider}'. Available: {providers}")
    else:
        provider = _choose("provider", providers)
    return provider, repo_root


def _parse_versions(args: list[str], name_idx: int) -> tuple[str | None, str | None]:
    """Return (from_ver, to_ver) if provided at args[name_idx+1:name_idx+3], else (None, None).

    Accepts semver only (MAJOR.MINOR.PATCH).
    """
    v_args = args[name_idx + 1:]
    if not v_args:
        return None, None
    if len(v_args) == 1:
        sys.exit("❌  ERROR: provide both versions or neither  e.g. 1.0.0 2.0.0")
    from_ver, to_ver = v_args[0], v_args[1]
    for v in (from_ver, to_ver):
        if not _is_semver(v):
            sys.exit(
                f"❌  ERROR: '{v}' is not a valid version — "
                "expected MAJOR.MINOR.PATCH  e.g. 1.0.0, 2.0.0"
            )
    if _semver_key(from_ver) >= _semver_key(to_ver):
        sys.exit(f"❌  ERROR: from-version must be older than to-version  (got {from_ver} → {to_ver})")
    return from_ver, to_ver


def _get_clients(repo_root: Path) -> list[RegistryClient]:
    return _build_clients(repo_root)


def cmd_diff_atom(args: list[str]) -> None:
    provider, repo_root = _resolve_provider(args)

    if len(args) >= 2:
        raw = args[1]
        if "/" not in raw:
            sys.exit("❌  ERROR: atom must be <category>/<name>  e.g. storage/rds")
        category, name = raw.split("/", 1)
        from_ver, to_ver = _parse_versions(args, 1)
    else:
        atoms = _list_atoms(provider, repo_root)
        if not atoms:
            sys.exit(f"❌  ERROR: no atoms found for provider '{provider}'")
        chosen   = _choose("atom", [a["label"] for a in atoms])
        atom     = next(a for a in atoms if a["label"] == chosen)
        category, name = atom["category"], atom["name"]
        from_ver, to_ver = None, None

    atom_dir = repo_root / "atoms" / provider / category / name
    if not atom_dir.is_dir():
        clients = _get_clients(repo_root)
        rel     = f"atoms/{provider}/{category}/{name}"
        for client in clients:
            if client.list_versions(rel):
                _diff_component_remote(
                    "atom", f"{provider}/{category}/{name}", rel,
                    "molecules that use this atom may need to be updated",
                    client, from_ver, to_ver,
                )
                return
        sys.exit(f"❌  ERROR: atom not found locally or in any registry")

    _diff_component("atom", f"{provider}/{category}/{name}", atom_dir,
                       "molecules that use this atom may need to be updated",
                       from_ver, to_ver)


def cmd_diff_molecule(args: list[str]) -> None:
    provider, repo_root = _resolve_provider(args)

    if len(args) >= 2:
        name = args[1]
        from_ver, to_ver = _parse_versions(args, 1)
    else:
        mols = _list_molecules(provider, repo_root)
        if not mols:
            sys.exit(f"❌  ERROR: no molecules found for provider '{provider}'")
        chosen = _choose("molecule", [m["label"] for m in mols])
        name   = next(m["name"] for m in mols if m["label"] == chosen)
        from_ver, to_ver = None, None

    mol_dir = repo_root / "molecules" / provider / name
    if not mol_dir.is_dir():
        clients = _get_clients(repo_root)
        rel     = f"molecules/{provider}/{name}"
        for client in clients:
            if client.list_versions(rel):
                _diff_component_remote(
                    "molecule", f"{provider}/{name}", rel,
                    "matters that use this molecule may need to be updated",
                    client, from_ver, to_ver,
                )
                return
        sys.exit(f"❌  ERROR: molecule not found locally or in any registry")

    _diff_component("molecule", f"{provider}/{name}", mol_dir,
                       "matters that use this molecule may need to be updated",
                       from_ver, to_ver)


def cmd_diff_matter(args: list[str]) -> None:
    matter_path, env = _resolve_matter_and_env(args)
    repo_root       = find_repo_root(matter_path)
    comp_file       = matter_path / "composition.json"
    if not comp_file.exists():
        sys.exit(f"❌  ERROR: composition.json not found at {comp_file}")
    composition = json.loads(comp_file.read_text())

    provider    = matter_path.name
    matter_name = matter_path.parent.name

    print(f"\n{_em('👁️')} {_c('matter diff', 'bcyan', 'bold')}  "
          f"{_arr()} {_c(f'{provider}/{matter_name}/{env}', 'cyan')}\n")

    any_upgradeable  = False
    overall_breaking = False

    for mol in composition["molecules"]:
        source  = mol.get("source", "")
        current = mol.get("version", "")
        if not source or not current or not _is_semver(current):
            print(f"  {_c(mol['name'], 'dim'):<30} {_c('(unversioned, skipping)', 'dim')}")
            continue

        if "/" not in source:
            print(f"  {_c(mol['name'], 'dim'):<30} {_c('(invalid source, skipping)', 'dim')}")
            continue

        provider_mol, mol_name = source.split("/", 1)

        # Determine if this is a cached package or a locally authored molecule
        package_base = _packages_dir(repo_root) / "molecules" / provider_mol / mol_name
        local_base    = repo_root / "molecules" / provider_mol / mol_name
        is_package   = package_base.is_dir()
        base          = package_base if is_package else local_base

        if is_package:
            # For packages: query registry for latest version
            try:
                clients = _get_clients(repo_root)
                latest  = None
                for _c2 in clients:
                    versions = _c2.list_versions(f"molecules/{provider_mol}/{mol_name}")
                    if versions:
                        latest = versions[-1]
                        break
            except Exception:
                latest = None
        else:
            latest = latest_version(base)

        if latest is None:
            print(f"  {_c(mol['name'], 'dim'):<30} {current}  "
                  f"{_c('(no versioned directories found)', 'dim')}")
            continue

        if latest == current:
            print(f"  {_c(mol['name'], 'cyan'):<30} {_c(current, 'dim')}  "
                  f"{_em('✅')}{_c('up-to-date', 'green')}")
            continue

        any_upgradeable = True
        status_label    = f"{_em('💥')}{_c('BREAKING', 'bred', 'bold')}"
        ver_range       = f"{_c(current, 'yellow')} {_arr()} {_c(latest, 'bgreen', 'bold')}"

        if is_package:
            # Registry package: version diff only — no local interface diff available
            print(f"  {_c(mol['name'], 'cyan', 'bold'):<30} {ver_range}  "
                  f"[{_c('package update available', 'bgreen')}]")
            print(f"    {_c('run eif package update to fetch latest', 'dim')}\n")
        else:
            changes     = _diff_interface(base / current, base / latest)
            is_breaking = any(c["breaking"] for c in changes)
            if is_breaking:
                overall_breaking = True
            status = (status_label if is_breaking else _c("non-breaking", "bgreen"))
            print(f"  {_c(mol['name'], 'cyan', 'bold'):<30} {ver_range}  [{status}]")
            if not changes:
                print(f"    {_c('(no interface changes)', 'dim')}\n")
                continue
            _print_diff(changes)
            print()

    print()
    if not any_upgradeable:
        print(f"{_em('✅')}{_c('all components up-to-date — nothing to diff', 'green')}")
    elif overall_breaking:
        print(f"{_em('💥')}{_c('BREAKING changes detected', 'bred', 'bold')}\n"
              f"   update the matter template and env vars before running "
              f"{_c('eif package update', 'bcyan')}")
    else:
        print(f"{_em('✅')}{_c('no breaking changes', 'bgreen', 'bold')} "
              f"{_arr()} safe to run {_c('eif package update', 'bcyan')}")


def cmd_diff(args: list[str]) -> None:
    SUBS = {"atom": cmd_diff_atom, "atoms": cmd_diff_atom, "molecule": cmd_diff_molecule, "molecules": cmd_diff_molecule, "matter": cmd_diff_matter, "matters": cmd_diff_matter}

    if args and args[0] in SUBS:
        return SUBS[args[0]](args[1:])

    if args:
        # positional args with no matching subcommand → assume matter shorthand
        return cmd_diff_matter(args)

    # fully interactive — ask what level to diff
    sub = _choose("diff", ["atom", "molecule", "matter"])
    SUBS[sub]([])
