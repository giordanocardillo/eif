"""commands.py — cmd_add, cmd_list, cmd_version, cmd_cache_*, _usage, main dispatcher."""

import json
import shutil
import sys
from importlib.metadata import version as _pkg_version
from pathlib import Path

from .core import find_repo_root
from .packages import (
    _packages_dir,
    _require_registry,
    _matter_composition,
    _install_molecule,
    cmd_package,
)
from .render import cmd_render
from .diff import cmd_diff
from .deploy import cmd_plan, cmd_apply, cmd_scan, cmd_destroy, cmd_rollback
from .scaffold import cmd_new, cmd_remove
from .init import cmd_init, cmd_config, cmd_init_account
from .ui import (
    _IS_TTY,
    _c, _em, _arr,
    _confirm,
    _multiselect,
    _detect_providers,
    _list_atoms,
    _list_molecules,
    _resolve_matter_and_env,
)
from .registry import _remote_list_versions


def _pin_molecule_to_comp(comp_file: Path, comp: dict,
                          source: str, name: str, version: str) -> None:
    """Update or append a molecule entry in composition.json (mutates comp, writes file)."""
    existing = next((m for m in comp.get("molecules", []) if m["source"] == source), None)
    if existing:
        old_ver = existing["version"]
        if old_ver == version:
            print(f"  {_c(source, 'dim')} already at {_c(version, 'dim')} — skipped")
            return
        existing["version"] = version
        comp_file.write_text(json.dumps(comp, indent=2) + "\n")
        print(f"{_em('✅')}updated   {_c(source, 'cyan')} {_c(old_ver, 'yellow')} {_arr()} {_c(version, 'bgreen', 'bold')}")
    else:
        entry_name = name.replace("-", "_")
        comp.setdefault("molecules", []).append(
            {"name": entry_name, "source": source, "version": version}
        )
        comp_file.write_text(json.dumps(comp, indent=2) + "\n")
        print(f"{_em('✅')}pinned    {_c(source, 'cyan')}@{_c(version, 'bgreen', 'bold')} "
              f"{_c('→ composition.json', 'dim')}")


def cmd_add(args: list[str]) -> None:
    # eif add account — existing sub-command
    if args and args[0] == "account":
        return cmd_init_account(args[1:])

    # eif add [<provider>/<name>[@version]] — add molecule to current matter
    repo_root = find_repo_root(Path.cwd())
    registry  = _require_registry(repo_root)

    result = _matter_composition(repo_root)
    if result is None:
        sys.exit(
            "Usage:\n"
            "  eif add account                  Add an account entry to accounts.json\n"
            "  eif add [<pvd>/<name>[@ver]]     Add molecule to current matter\n"
            "  (run from inside a matter directory)"
        )

    comp_file, comp = result
    provider = comp_file.parent.name   # matters/<name>/<provider>/composition.json

    if args:
        # ── Non-interactive: eif add aws/db[@1.2.0] ──────────────────────────
        raw     = args[0]
        version = None
        if "@" in raw:
            raw, version = raw.split("@", 1)

        if "/" not in raw:
            sys.exit("❌  ERROR: source must be <provider>/<name>  e.g. aws/db")
        src_provider, name = raw.split("/", 1)
        source = f"{src_provider}/{name}"

        from .core import latest_version
        if not version:
            # Local-first: check authored then cached
            local_ver = (latest_version(repo_root / "molecules" / src_provider / name)
                         or latest_version(_packages_dir(repo_root) / "molecules" / src_provider / name))
            if local_ver:
                version = local_ver
            else:
                # Fall back to registry
                versions = _remote_list_versions(registry, f"molecules/{src_provider}/{name}")
                if not versions:
                    sys.exit(f"❌  ERROR: {source} not found locally or in registry")
                version = versions[-1]
                print(f"  {_c('fetching from registry', 'dim')} {_arr()} {_c(version, 'bgreen')}")
                _install_molecule(registry, src_provider, name, version, repo_root)
        else:
            # Specific version — ensure it's present locally, install if not
            cached = (_packages_dir(repo_root) / "molecules" / src_provider / name / version)
            local  = repo_root / "molecules" / src_provider / name / version
            if not local.is_dir() and not cached.is_dir():
                _install_molecule(registry, src_provider, name, version, repo_root)

        _pin_molecule_to_comp(comp_file, comp, source, name, version)

    else:
        # ── Interactive: pick from local + cached molecules ───────────────────
        all_mols = _list_molecules(provider, repo_root)
        if not all_mols:
            sys.exit(f"❌  ERROR: no molecules found for {provider} — "
                     f"run eif pkg i <provider>/<name> to fetch from registry first")
        print()
        selected = _multiselect("molecules to add", all_mols)
        print()
        for mol in selected:
            _pin_molecule_to_comp(comp_file, comp, mol["source"], mol["name"], mol["version"])


def cmd_cache_clean(args: list[str]) -> None:  # noqa: ARG001
    repo_root   = find_repo_root(Path.cwd())
    cache_dir   = _packages_dir(repo_root)
    if not cache_dir.is_dir():
        print(f"{_c('cache already empty', 'dim')}")
        return

    # Tally size and file count
    files = list(cache_dir.rglob("*"))
    file_count = sum(1 for f in files if f.is_file())
    total_bytes = sum(f.stat().st_size for f in files if f.is_file())
    size_str = (
        f"{total_bytes / 1_048_576:.1f} MB" if total_bytes >= 1_048_576
        else f"{total_bytes / 1024:.1f} KB" if total_bytes >= 1024
        else f"{total_bytes} B"
    )

    print(f"\n  {_c('eif_packages/', 'cyan')}  {_c(f'{file_count} files · {size_str}', 'dim')}\n")
    if not _confirm("delete entire cache?", default=False):
        sys.exit("aborted")
    shutil.rmtree(cache_dir)
    print(f"{_em('✅')}cache cleared  {_c(f'({file_count} files removed)', 'dim')}")


def cmd_cache(args: list[str]) -> None:
    SUB = {"clean": cmd_cache_clean}
    if not args or args[0] not in SUB:
        sys.exit("Usage:\n  eif cache clean  Delete the eif_packages/ cache")
    SUB[args[0]](args[1:])


def cmd_version(_args: list[str]) -> None:
    print(f"eif {_pkg_version('eif')}")


def cmd_list(args: list[str]) -> None:
    _ALIAS = {"provider": "providers", "atom": "atoms", "molecule": "molecules", "matter": "matters"}
    SUBS = ("providers", "atoms", "molecules", "matters")
    repo_root = find_repo_root(Path.cwd())

    if args:
        args = [_ALIAS.get(args[0], args[0])] + args[1:]

    # bare `eif list` — print everything
    if not args or args[0] not in SUBS:
        b = lambda s: f"\033[1m{s}\033[0m"
        d = lambda s: f"\033[2m{s}\033[0m"
        print(b("PROVIDERS"))
        cmd_list(["providers"])
        print()
        print(b("ATOMS"))
        cmd_list(["atoms"])
        print()
        print(b("MOLECULES"))
        cmd_list(["molecules"])
        print()
        print(b("MATTERS"))
        cmd_list(["matters"])
        return

    sub       = args[0]
    provider_filter = args[1] if len(args) > 1 else None

    if sub == "providers":
        providers = _detect_providers(repo_root)
        if not providers:
            print(f"  {_c('no providers found', 'dim')}")
            return
        for p in providers:
            print(_c(p, "bcyan", "bold"))

    elif sub == "atoms":
        providers = [provider_filter] if provider_filter else _detect_providers(repo_root)
        for provider in providers:
            atoms = _list_atoms(provider, repo_root)
            if not atoms:
                continue
            print(_c(provider, "bcyan", "bold"))
            for a in atoms:
                label = f"{a['category']}/{a['name']}"
                print(f"  {_c(label, 'cyan'):<{30 + (9 if _IS_TTY else 0)}}  {_c(a['version'], 'dim')}")

    elif sub == "molecules":
        providers = [provider_filter] if provider_filter else _detect_providers(repo_root)
        for provider in providers:
            mols = _list_molecules(provider, repo_root)
            if not mols:
                continue
            print(_c(provider, "bcyan", "bold"))
            for m in mols:
                print(f"  {_c(m['name'], 'cyan'):<{40 + (9 if _IS_TTY else 0)}}  {_c(m['version'], 'dim')}")

    elif sub == "matters":
        matters_dir = repo_root / "matters"
        if not matters_dir.is_dir():
            print(f"  {_c('no matters found', 'dim')}")
            return
        for matter in sorted(matters_dir.iterdir()):
            if not matter.is_dir():
                continue
            providers = sorted(
                d.name for d in matter.iterdir()
                if d.is_dir() and (provider_filter is None or d.name == provider_filter)
            )
            if providers:
                print(f"{_c(matter.name, 'cyan'):<{40 + (9 if _IS_TTY else 0)}}  {_c(' '.join(providers), 'dim')}")


def _usage() -> str:
    b  = lambda s: f"\033[1m{s}\033[0m"       # bold
    d  = lambda s: f"\033[2m{s}\033[0m"       # dim
    c  = lambda s: f"\033[96m{s}\033[0m"      # cyan
    g  = lambda s: f"\033[92m{s}\033[0m"      # green
    y  = lambda s: f"\033[93m{s}\033[0m"      # yellow
    p  = lambda s: f"\033[35m{s}\033[0m"      # purple (packages)
    T  = lambda s: f"\033[38;2;74;240;196m{s}\033[0m"   # teal  #4af0c4
    B  = lambda s: f"\033[38;2;58;143;255m{s}\033[0m"   # blue  #3a8fff
    O  = lambda s: f"\033[38;2;240;136;74m{s}\033[0m"   # orange #f0884a

    def row(cmd, args, desc):
        return f"  {g(b('eif'))} {b(cmd):<28} {c(args):<42} {d(desc)}"

    def sub(cmd, sub_, args, desc):
        return f"  {g(b('eif'))} {b(cmd)} {y(b(sub_)):<24} {c(args):<38} {d(desc)}"

    def psub(sub_, args, desc):
        return f"  {g(b('eif'))} {p(b('package'))} {p(sub_):<18} {c(args):<34} {d(desc)}"

    lines = [
        f"  {T('E')}{b('LEMENTAL')}",
        f"  {B('I')}{b('NFRASTRUCTURE')}",
        f"  {O('F')}{b('RAMEWORK')}",
        "",
        b("  PROJECT"),
        row("init",    "[<folder>]",                    "scaffold new project (providers, accounts, .gitignore)"),
        row("config",  "backend [<pvd> <matter> <env>]","bootstrap remote state bucket"),
        row("add",     "account",                       "add an account entry to accounts.json"),
        row("add",     "[<pvd>/<name>[@ver]]",           "add molecule to current matter (interactive if no args)"),
        row("list",    "[providers|atoms|molecules|matters] [<pvd>]", "list local components (all if no subcommand)"),
        row("version", "",                              "print eif version"),
        "",
        b("  AUTHORING"),
        sub("new",    "atom",     "[<name> [<pvd> [<category>]]]",       "scaffold a new atom"),
        sub("new",    "molecule", "[<name> [<pvd> [<atoms>]]]",           "scaffold a new molecule"),
        sub("new",    "matter",   "[<name> [<pvd> [<molecules>]]]",       "scaffold a new matter"),
        sub("remove", "atom",     "[<pvd> <category> <name>]",            "delete a local atom"),
        sub("remove", "molecule", "[<pvd> <name>]",                       "delete a local molecule"),
        sub("remove", "matter",   "[<pvd> <name>]",                       "delete a local matter"),
        "",
        b("  PACKAGES  ") + d("(remote molecules + bundled atoms from registry)"),

        psub("install",  "",                            "install all pinned packages"),
        psub("install",  "<pvd>/<name>[@<ver>]",        "download package (+ pin if inside matter)"),
        psub("remove",   "<pvd>/<name>",                "unpin molecule from matter"),
        psub("update",   "[<pvd>/<name>] [--safe]",     "update to latest, show diff, confirm"),
        psub("outdated", "",                            "show available updates across all matters"),
        psub("list",     "",                            "show installed packages"),
        row("cache",  "clean",                          "delete eif_packages/ cache"),
        "",
        b("  DEPLOYMENT"),
        row("render",   "[<pvd> <matter> <env>]",       "render composition → .rendered/<env>/main.tf"),
        row("diff",     "atom|molecule [<pvd> <name> [<from> <to>]]", "diff interface, flag breaking changes"),
        row("diff",     "matter [<pvd> <matter> <env>]","diff all packages against registry"),
        row("plan",     "[<pvd> <matter> <env>] [--scan]", "render + terraform plan"),
        row("apply",    "[<pvd> <matter> <env>] [--scan]", "render + terraform apply + snapshot"),
        row("destroy",  "[<pvd> <matter> <env>]",       "terraform destroy"),
        row("rollback", "[<pvd> <matter> <env>]",       "restore previous snapshot and re-apply"),
        row("scan",     "[<pvd> <matter> <env>]",       "trivy vulnerability scan"),
        "",
        d("  All positional args are optional — missing ones are prompted interactively."),
        d("  --safe  skips breaking major-version bumps during package update."),
        d("  --scan  auto-runs trivy; without it, plan/apply prompt if trivy is installed."),
    ]
    return "\n".join(lines)


USAGE = _usage()


def main() -> None:
    args = sys.argv[1:]
    if not args:
        sys.exit(USAGE)

    cmd = args[0]
    CMDS = {
        "version":   cmd_version,
        "list":      cmd_list,
        "render":    cmd_render,
        "diff":      cmd_diff,
        "scan":      cmd_scan,
        "plan":      cmd_plan,
        "apply":     cmd_apply,
        "destroy":   cmd_destroy,
        "rollback":  cmd_rollback,
        "new":       cmd_new,
        "remove":    cmd_remove,
        "add":       cmd_add,
        "init":      cmd_init,
        "config":    cmd_config,
        "package":  cmd_package,
        "packages": cmd_package,
        "pkg":      cmd_package,
        "cache":     cmd_cache,
        "help":      lambda _: sys.exit(USAGE),
    }

    if cmd not in CMDS:
        sys.exit(USAGE)

    CMDS[cmd](args[1:])
