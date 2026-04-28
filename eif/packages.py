"""packages.py — package store helpers + cmd_package_*."""

import json
import re
import sys
from pathlib import Path

from .core import _packages_dir, _semver_key, _is_semver, find_repo_root, load_registries, load_secure, latest_version
from .registry import RegistryClient, make_client
from .ui import _c, _em, _arr, _confirm, _choose, _resolve_matter_and_env


# ── Registry resolution ───────────────────────────────────────────────────────

def _build_clients(repo_root: Path) -> list[RegistryClient]:
    """Build registry clients merging eif.project.json with auth from eif.secure.json."""
    regs     = load_registries(repo_root)
    auth_map = load_secure(repo_root).get("registryAuth", {})
    return [make_client({**r, "auth": auth_map.get(r["name"], {})}) for r in regs]


def _require_clients(repo_root: Path) -> list[RegistryClient]:
    clients = _build_clients(repo_root)
    if not clients:
        sys.exit(
            "❌  ERROR: no registries configured\n"
            "    run: eif registry add <name> <url>"
        )
    return clients


def _find_client_for_molecule(
    clients: list[RegistryClient], provider: str, name: str, version: str | None = None
) -> tuple[RegistryClient, str] | None:
    """Return (client, resolved_version) for the first registry that has the molecule."""
    for client in clients:
        versions = client.list_versions(f"molecules/{provider}/{name}")
        if not versions:
            continue
        if version is None:
            return client, versions[-1]
        if version in versions:
            return client, version
    return None


# ── Package store helpers ─────────────────────────────────────────────────────

def _package_path(repo_root: Path, kind: str, provider: str, name: str, version: str) -> Path:
    """Return the local path for a package, regardless of whether it exists."""
    if kind == "molecule":
        return _packages_dir(repo_root) / "molecules" / provider / name / version
    return _packages_dir(repo_root) / "atoms" / provider / name / version


def _package_installed(repo_root: Path, kind: str, provider: str, name: str, version: str) -> bool:
    return _package_path(repo_root, kind, provider, name, version).is_dir()


def _collect_download_plan(
    client: RegistryClient, reg_rel_path: str, dest: Path
) -> list[tuple[str, Path]]:
    """Return list of (remote_path, local_dest_file) for all files under reg_rel_path."""
    items = client.list_dir(reg_rel_path)
    if not isinstance(items, list):
        sys.exit(f"❌  ERROR: could not fetch {reg_rel_path} from {client.name} ({client.url})")
    plan: list[tuple[str, Path]] = []
    for item in items:
        item_path = f"{reg_rel_path}/{item['name']}"
        if item["type"] == "file":
            plan.append((item_path, dest / item["name"]))
        elif item["type"] == "dir":
            plan.extend(_collect_download_plan(client, item_path, dest / item["name"]))
    return plan


def _run_download_plan(
    client: RegistryClient,
    plan: list[tuple[str, Path]],
    label: str,
    done_so_far: list[int],
    total: int,
    label_width: int = 0,
) -> None:
    """Execute a download plan, printing an apt-style progress bar."""
    bar_width = 24
    padded = label.ljust(label_width) if label_width else label
    for remote_path, local_dest in plan:
        local_dest.parent.mkdir(parents=True, exist_ok=True)
        content = client.fetch_file(remote_path)
        if content is not None:
            local_dest.write_text(content)
        done_so_far[0] += 1
        filled  = int(bar_width * done_so_far[0] / total)
        bar     = "█" * filled + "░" * (bar_width - filled)
        pct     = int(100 * done_so_far[0] / total)
        print(
            f"  {_c('↓', 'molecule')} {_c(padded, 'dim')}  "
            f"[{_c(bar, 'bgreen')}] {pct:3d}%  {done_so_far[0]}/{total} files\033[K",
            end="\r", flush=True,
        )


def _install_atom_deps(
    client: RegistryClient,
    mol_dest: Path,
    repo_root: Path,
    done_so_far: list[int],
    total: int,
    label: str,
    label_width: int = 0,
) -> None:
    """Scan molecule main.tf for atom source references and download them."""
    main_tf = mol_dest / "main.tf"
    if not main_tf.exists():
        return
    for m in re.finditer(r'source\s*=\s*"([^"]*atoms/[^"]+)"', main_tf.read_text()):
        rel    = m.group(1)
        atom_m = re.search(r'atoms/(.+)', rel)
        if not atom_m:
            continue
        atom_rel  = f"atoms/{atom_m.group(1).rstrip('/')}"
        parts     = atom_m.group(1).strip("/").split("/")
        if len(parts) < 4:
            continue
        atom_dest = _packages_dir(repo_root) / "atoms" / Path(*parts)
        if atom_dest.is_dir():
            continue
        local_atom = repo_root / "atoms" / Path(*parts)
        if local_atom.is_dir():
            continue
        atom_plan = _collect_download_plan(client, atom_rel, atom_dest)
        total    += len(atom_plan)
        _run_download_plan(client, atom_plan, label, done_so_far, total, label_width)


def _install_molecule(
    client: RegistryClient, provider: str, name: str, version: str, repo_root: Path,
    label_width: int = 0,
) -> None:
    """Download a molecule and its atom dependencies to eif_packages/."""
    dest   = _package_path(repo_root, "molecule", provider, name, version)
    label  = f"{provider}/{name}@{version}"
    padded = label.ljust(label_width) if label_width else label
    if dest.is_dir():
        print(f"  {_c('✓', 'bgreen')} {_c(padded, 'cyan')}  already cached")
        return
    local = repo_root / "molecules" / provider / name / version
    if local.is_dir():
        print(f"  {_c('✓', 'bgreen')} {_c(padded, 'cyan')}  local")
        return

    reg_rel  = f"molecules/{provider}/{name}/{version}"
    mol_plan = _collect_download_plan(client, reg_rel, dest)

    total       = len(mol_plan)
    done_so_far = [0]

    print(f"  {_c('↓', 'molecule')} {_c(padded, 'dim')}  collecting...\033[K", end="\r", flush=True)
    _run_download_plan(client, mol_plan, label, done_so_far, total, label_width)
    _install_atom_deps(client, dest, repo_root, done_so_far, total, label, label_width)

    bar_width = 24
    bar = "█" * bar_width
    print(
        f"  {_c('✓', 'bgreen')} {_c(padded, 'cyan')}  "
        f"[{_c(bar, 'bgreen')}] 100%  {done_so_far[0]}/{done_so_far[0]} files"
    )


def _all_compositions(repo_root: Path) -> list[tuple[Path, dict]]:
    """Return all (path, composition) pairs found under matters/."""
    matters_dir = repo_root / "matters"
    if not matters_dir.is_dir():
        return []
    results = []
    for comp_file in sorted(matters_dir.rglob("composition.json")):
        try:
            comp = json.loads(comp_file.read_text())
            results.append((comp_file, comp))
        except json.JSONDecodeError:
            pass
    return results


def _check_outdated(molecules: list, clients: list[RegistryClient]) -> list[dict]:
    """Return list of {name, source, version, latest} for upgradeable molecules."""
    outdated = []
    for mol in molecules:
        source  = mol.get("source", "")
        version = mol.get("version", "")
        if not source or not version or "/" not in source:
            continue
        provider, name = source.split("/", 1)
        for client in clients:
            try:
                versions = client.list_versions(f"molecules/{provider}/{name}")
            except Exception:
                continue
            if not versions:
                continue
            latest = versions[-1]
            if _semver_key(latest) > _semver_key(version):
                outdated.append({
                    "name": mol["name"], "source": source,
                    "version": version, "latest": latest,
                })
            break  # found in this registry — stop searching
    return outdated


# ── Shared helper ─────────────────────────────────────────────────────────────

def _matter_composition(repo_root: Path) -> tuple[Path, dict] | None:
    """Return (comp_file, comp_dict) if cwd is inside a matter, else None."""
    cwd = Path.cwd()
    for candidate in (cwd / "composition.json", cwd.parent / "composition.json"):
        if candidate.exists():
            try:
                return candidate, json.loads(candidate.read_text())
            except json.JSONDecodeError:
                pass
    return None


# ── Commands (package) ────────────────────────────────────────────────────────

def cmd_package_install(args: list[str]) -> None:
    repo_root = find_repo_root(Path.cwd())
    clients   = _require_clients(repo_root)

    if args:
        raw     = args[0]
        version = None
        if "@" in raw:
            raw, version = raw.split("@", 1)

        if "/" not in raw:
            sys.exit("❌  ERROR: source must be <provider>/<name>  e.g. aws/db")
        provider, name = raw.split("/", 1)
        source = f"{provider}/{name}"

        result = _find_client_for_molecule(clients, provider, name, version)
        if result is None:
            regs = ", ".join(c.name for c in clients)
            sys.exit(f"❌  ERROR: {source}{('@' + version) if version else ''} not found in [{regs}]")
        client, version = result
        print(f"  {_c(client.name, 'dim')} {_arr()} {_c(version, 'bgreen')}")

        _install_molecule(client, provider, name, version, repo_root)

        result2 = _matter_composition(repo_root)
        if result2 is None:
            print(f"{_c('  tip: run inside a matter directory to pin to composition.json', 'dim')}")
            return

        comp_file, comp = result2
        existing = next((m for m in comp.get("molecules", []) if m["source"] == source), None)
        if existing:
            old_ver = existing["version"]
            existing["version"] = version
            comp_file.write_text(json.dumps(comp, indent=2) + "\n")
            print(f"{_em('✅')}updated   {_c(source, 'cyan')} {_c(old_ver, 'yellow')} {_arr()} {_c(version, 'bgreen', 'bold')}")
        else:
            mol_name = name.replace("-", "_")
            comp.setdefault("molecules", []).append({"name": mol_name, "source": source, "version": version})
            comp_file.write_text(json.dumps(comp, indent=2) + "\n")
            print(f"{_em('✅')}pinned    {_c(source, 'cyan')}@{_c(version, 'bgreen', 'bold')} {_c('→ composition.json', 'dim')}")
        return

    # ── No args: install all pinned packages ──────────────────────────────────
    compositions = _all_compositions(repo_root)
    if not compositions:
        print(f"{_c('no composition.json files found', 'dim')}")
        return

    reg_names = ", ".join(c.name for c in clients)
    print(f"{_em('📦')}installing packages {_arr()} {_c(reg_names, 'dim')}\n")

    seen: set = set()
    all_mols: list = []
    mols_to_install = []
    for _, comp in compositions:
        for mol in comp.get("molecules", []):
            source  = mol.get("source", "")
            version = mol.get("version", "")
            if not source or not version or "/" not in source:
                continue
            all_mols.append(mol)
            key = (source, version)
            if key in seen:
                continue
            seen.add(key)
            provider, name = source.split("/", 1)
            mols_to_install.append((provider, name, version))

    lw = max((len(f"{p}/{n}@{v}") for p, n, v in mols_to_install), default=0)
    for provider, name, version in mols_to_install:
        result = _find_client_for_molecule(clients, provider, name, version)
        if result is None:
            regs = ", ".join(c.name for c in clients)
            print(f"  {_c('✗', 'bred')} {_c(f'{provider}/{name}@{version}', 'cyan')}  not found in [{regs}]")
            continue
        client, _ = result
        _install_molecule(client, provider, name, version, repo_root, lw)

    print(f"\n{_em('✅')}{_c('done', 'bgreen', 'bold')}")

    outdated = _check_outdated(all_mols, clients)
    if outdated:
        print(f"\n  {_c(f'{len(outdated)} package(s) have updates available', 'yellow')} "
              f"{_arr()} run {_c('eif package update', 'bcyan')} to upgrade")


def cmd_package_remove(args: list[str]) -> None:
    repo_root = find_repo_root(Path.cwd())
    matter_path, _ = _resolve_matter_and_env([])
    comp_file = matter_path / "composition.json"
    if not comp_file.exists():
        sys.exit(f"❌  ERROR: composition.json not found at {comp_file}")

    if not args:
        sys.exit("Usage: eif package remove <provider>/<name>")
    source = args[0]

    comp = json.loads(comp_file.read_text())
    before = len(comp["molecules"])
    comp["molecules"] = [m for m in comp["molecules"] if m.get("source") != source]
    if len(comp["molecules"]) == before:
        sys.exit(f"❌  ERROR: {source} not found in composition.json")
    comp_file.write_text(json.dumps(comp, indent=2) + "\n")
    print(f"{_em('✅')}removed   {_c(source, 'cyan')} from composition.json")
    print(f"  {_c('note: eif_packages/ cache not deleted (may be shared)', 'dim')}")


def cmd_package_update(args: list[str]) -> None:
    from .diff import _diff_component_remote

    safe_mode = "--safe" in args
    args      = [a for a in args if a != "--safe"]

    repo_root = find_repo_root(Path.cwd())
    clients   = _require_clients(repo_root)

    matter_path, _ = _resolve_matter_and_env([])
    comp_file = matter_path / "composition.json"
    if not comp_file.exists():
        sys.exit(f"❌  ERROR: composition.json not found at {comp_file}")

    comp    = json.loads(comp_file.read_text())
    changed = False

    target_source = args[0] if args else None

    if safe_mode:
        print(f"{_em('🔒')}{_c('safe mode', 'byellow', 'bold')} — skipping major-version bumps\n")

    for mol in comp["molecules"]:
        source  = mol.get("source", "")
        version = mol.get("version", "")
        if not source or not version or "/" not in source:
            continue
        if target_source and source != target_source:
            continue

        provider, name = source.split("/", 1)

        # Find registry that has this molecule and get latest version
        result = None
        for client in clients:
            try:
                versions = client.list_versions(f"molecules/{provider}/{name}")
            except Exception:
                continue
            if versions:
                result = (client, versions[-1])
                break

        if result is None:
            print(f"  {_c('skip', 'dim')} {_c(source, 'dim')} — not found in any registry")
            continue

        client, latest = result

        if _semver_key(latest) <= _semver_key(version):
            print(f"  {_em('✅')}{_c(source, 'green')}@{_c(version, 'dim')}  up-to-date")
            continue

        if safe_mode and _semver_key(latest)[0] > _semver_key(version)[0]:
            print(
                f"  {_em('⏭️')} {_c('skip (major bump)', 'byellow')}  "
                f"{_c(source, 'dim')}  {_c(version, 'dim')} {_arr()} {_c(latest, 'dim')}"
            )
            continue

        _diff_component_remote(
            "molecule", source,
            f"molecules/{provider}/{name}",
            "update composition.json when safe",
            client, version, latest,
        )

        if not _confirm(f"update {source} {_c(version, 'yellow')} → {_c(latest, 'bgreen')}?", default=True):
            continue

        mol["version"] = latest
        _install_molecule(client, provider, name, latest, repo_root)
        changed = True

    if changed:
        comp_file.write_text(json.dumps(comp, indent=2) + "\n")
        print(f"\n{_em('💾')}wrote     {_arr()} {_c(str(comp_file), 'cyan')}")
    else:
        print(f"\n{_em('✅')}{_c('nothing to update', 'green')}")


def cmd_package_list(args: list[str]) -> None:  # noqa: ARG001
    from .ui import _IS_TTY
    repo_root = find_repo_root(Path.cwd())
    pdir      = _packages_dir(repo_root)

    if not pdir.is_dir():
        print(f"  {_c('no packages installed — run: eif package install', 'dim')}")
        return

    for kind in ("molecules", "atoms"):
        kind_dir = pdir / kind
        if not kind_dir.is_dir():
            continue
        print(_c(kind, "bcyan", "bold"))
        for provider_dir in sorted(kind_dir.iterdir()):
            if not provider_dir.is_dir():
                continue
            for name_dir in sorted(provider_dir.iterdir()):
                if not name_dir.is_dir():
                    continue
                for ver_dir in sorted(name_dir.iterdir(), key=lambda d: _semver_key(d.name) if _is_semver(d.name) else (0,0,0), reverse=True):
                    if ver_dir.is_dir() and _is_semver(ver_dir.name):
                        label = f"{provider_dir.name}/{name_dir.name}"
                        print(f"  {_c(label, 'cyan'):<{30 + (9 if _IS_TTY else 0)}}  {_c(ver_dir.name, 'dim')}")


def cmd_package_outdated(args: list[str]) -> None:  # noqa: ARG001
    from .ui import _IS_TTY
    repo_root = find_repo_root(Path.cwd())
    clients   = _require_clients(repo_root)

    compositions = _all_compositions(repo_root)
    if not compositions:
        print(f"{_c('no composition.json files found', 'dim')}")
        return

    any_outdated = False
    for comp_file, comp in compositions:
        outdated = _check_outdated(comp.get("molecules", []), clients)
        if not outdated:
            continue
        any_outdated = True
        matter_label = str(comp_file.parent.parent.parent.name) + "/" + comp_file.parent.name
        print(f"\n{_c(matter_label, 'bcyan', 'bold')}")
        for o in outdated:
            print(
                f"  {_c(o['source'], 'cyan'):<{30 + (9 if _IS_TTY else 0)}}  "
                f"{_c(o['version'], 'yellow')} {_arr()} {_c(o['latest'], 'bgreen')}"
            )

    if not any_outdated:
        print(f"{_em('✅')}{_c('all packages up-to-date', 'bgreen', 'bold')}")
    else:
        print(f"\n{_c('run: eif package update', 'dim')}")


def cmd_package(args: list[str]) -> None:
    SUBS = {
        "install":  cmd_package_install,  "i":  cmd_package_install,
        "remove":   cmd_package_remove,   "rm": cmd_package_remove,
        "update":   cmd_package_update,   "up": cmd_package_update,
        "list":     cmd_package_list,     "ls": cmd_package_list,
        "outdated": cmd_package_outdated, "od": cmd_package_outdated,
    }
    if not args or args[0] not in SUBS:
        sys.exit(
            "Usage:\n"
            "\n"
            "  eif package install                         Install all pinned packages\n"
            "  eif package install <provider>/<name>[@ver] Download package (+ pin if inside a matter)\n"
            "  eif package remove <provider>/<name>        Remove package from matter\n"
            "  eif package update [<provider>/<name>]      Update to latest (interactive diff + confirm)\n"
            "  eif package update --safe                    Skip major-version bumps\n"
            "  eif package list                             Show installed packages\n"
            "  eif package outdated                         Show available updates across all matters"
        )
    SUBS[args[0]](args[1:])
