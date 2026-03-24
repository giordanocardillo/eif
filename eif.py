#!/usr/bin/env python3
"""
EIF — Elemental Infrastructure Framework
CLI renderer, scaffolding, and deployment lifecycle.

Commands:
    eif render   [<provider> <matter> <env>]  Render composition + env → .rendered/<env>/main.tf
    eif preview  [<provider> <matter> <env>]  Diff molecule interface changes, flag breaking changes
    eif plan     [<provider> <matter> <env>]  Render and run terraform plan           [--scan]
    eif apply    [<provider> <matter> <env>]  Render, run terraform apply, snapshot   [--scan]
    eif destroy  [<provider> <matter> <env>]  Run terraform destroy on the rendered output
    eif rollback [<provider> <matter> <env>]  Restore a previous snapshot and re-apply
    eif init backend [<provider> <matter> <env>]  Bootstrap remote state bucket
    eif add account                               Add an account entry to accounts.json
    eif new atom     [<name> [<provider> [<category>]]]
    eif new molecule [<name> [<provider> [<category/atom>,...  ]]]
    eif new matter   [<name> [<provider> [<molecule>,...       ]]]
    eif particle init|install|add|remove|update|list|outdated

Install as a shell command:
    uv tool install --editable .

Examples:
    eif render                                       # fully interactive
    eif preview  aws three-tier-app dev              # check upgrade safety before updating
    eif render   aws three-tier-app dev              # fully non-interactive
    eif particle update
    eif plan     aws three-tier-app dev
    eif plan     aws three-tier-app dev --scan       # auto-scan with trivy if installed
    eif apply    aws three-tier-app dev
    eif destroy  aws three-tier-app dev
    eif rollback aws three-tier-app dev
    eif init backend aws three-tier-app dev
    eif add account
    eif new atom
    eif new atom     my-resource aws networking
    eif new molecule my-service  aws storage/s3,networking/cloudfront
    eif new matter   my-app      aws single-page-application,db
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from importlib.metadata import version as _pkg_version
from pathlib import Path

import questionary
from jinja2 import Environment, FileSystemLoader, StrictUndefined


# ── Output formatting ──────────────────────────────────────────────────────────

_IS_TTY: bool = sys.stdout.isatty()

_ANSI: dict[str, str] = {
    "bold":    "\033[1m",
    "dim":     "\033[2m",
    "red":     "\033[31m",
    "green":   "\033[32m",
    "yellow":  "\033[33m",
    "cyan":    "\033[36m",
    "bred":    "\033[91m",
    "bgreen":  "\033[92m",
    "byellow": "\033[93m",
    "bcyan":   "\033[96m",
    # background colors for diff rows
    "bg_red":    "\033[41m",
    "bg_green":  "\033[42m",
    "bg_yellow": "\033[43m",
    "white":     "\033[97m",
    "black":     "\033[30m",
}


def _c(text: str, *styles: str) -> str:
    """Wrap text in ANSI styles when stdout is a TTY; pass through otherwise."""
    if not _IS_TTY or not styles:
        return text
    codes = "".join(_ANSI.get(s, "") for s in styles)
    return f"{codes}{text}\033[0m"


def _pfx(kind: str = "dim") -> str:  # noqa: ARG001
    """Intentionally empty — prefix removed in favour of emoji anchors."""
    return ""


def _arr() -> str:
    return _c("→", "dim")


def _em(emoji: str) -> str:
    """Return emoji + space when TTY, empty string otherwise."""
    return f"{emoji} " if _IS_TTY else ""


def _diff_row(sym: str, text: str, bg: str) -> str:
    """Return a full-width background-colored diff row.

    When stdout is a TTY the row background fills the terminal width (git-style).
    When piped, returns plain text with just the sym prefix.
    """
    if not _IS_TTY:
        return f"{sym} {text}"
    width  = shutil.get_terminal_size((80, 24)).columns
    line   = f"{sym} {text}"
    padded = line + " " * max(0, width - len(line))
    fg     = "white" if bg in ("bg_red", "bg_green") else "black"
    return _c(padded, bg, fg, "bold")


# ── Semver helpers ─────────────────────────────────────────────────────────────

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _is_semver(name: str) -> bool:
    return bool(_SEMVER_RE.match(name))


def _semver_key(v: str) -> tuple[int, int, int]:
    m = _SEMVER_RE.match(v)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else (0, 0, 0)


def _next_semver(current: str, bump: str) -> str:
    """Return the next semver given a bump type: major, minor, or patch."""
    ma, mi, pa = _semver_key(current)
    if bump == "major":
        return f"{ma + 1}.0.0"
    if bump == "minor":
        return f"{ma}.{mi + 1}.0"
    return f"{ma}.{mi}.{pa + 1}"



# ── Constants ─────────────────────────────────────────────────────────────────

def _atom_categories(provider: str, repo_root: Path) -> list[str]:
    """Return sorted atom category names that already exist for the provider."""
    cat_dir = repo_root / "atoms" / provider
    if not cat_dir.is_dir():
        return []
    return sorted(d.name for d in cat_dir.iterdir() if d.is_dir())

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


# ── Core helpers ──────────────────────────────────────────────────────────────

def find_repo_root(start: Path) -> Path:
    """Walk up from start until we find accounts.json."""
    current = start
    while current != current.parent:
        if (current / "accounts.json").exists():
            return current
        current = current.parent
    sys.exit("❌  ERROR: accounts.json not found in any parent directory")


def load_config(repo_root: Path) -> dict:
    """Load eif.particles.json from repo_root, defaulting to local registry."""
    cfg_file = repo_root / "eif.particles.json"
    if cfg_file.exists():
        try:
            return json.loads(cfg_file.read_text())
        except json.JSONDecodeError as e:
            sys.exit(f"❌  ERROR: eif.particles.json is invalid JSON — {e}")
    return {"registry": "local"}


def latest_version(module_path: Path) -> str | None:
    """Return the highest semver directory inside module_path, or None."""
    if not module_path.is_dir():
        return None
    sv_dirs = [d.name for d in module_path.iterdir() if d.is_dir() and _is_semver(d.name)]
    if sv_dirs:
        return max(sv_dirs, key=_semver_key)
    return None


# ── Remote registry (GitHub) ───────────────────────────────────────────────────

def _github_org_repo(github_url: str) -> str:
    return github_url.rstrip("/").removeprefix("https://github.com/")


def _gh_api(url: str) -> list | dict | None:
    """GET a GitHub API URL; returns parsed JSON or None on error."""
    try:
        req = urllib.request.Request(
            url, headers={"Accept": "application/vnd.github.v3+json", "User-Agent": "eif-cli"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _remote_list_versions(registry: str, rel_path: str) -> list[str]:
    """Return sorted semver version directories at rel_path in the remote registry."""
    org_repo = _github_org_repo(registry)
    data     = _gh_api(f"https://api.github.com/repos/{org_repo}/contents/{rel_path}")
    if not isinstance(data, list):
        return []
    return sorted(
        [item["name"] for item in data if item["type"] == "dir" and _is_semver(item["name"])],
        key=_semver_key,
    )


def _remote_fetch_tf(registry: str, rel_path: str) -> str | None:
    """Fetch raw file content from the remote registry (main branch)."""
    org_repo = _github_org_repo(registry)
    raw_url  = f"https://raw.githubusercontent.com/{org_repo}/main/{rel_path}"
    try:
        req = urllib.request.Request(raw_url, headers={"User-Agent": "eif-cli"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode()
    except Exception:
        return None


def _remote_list_atoms(registry: str, provider: str) -> list[dict]:
    org_repo = _github_org_repo(registry)
    cats     = _gh_api(f"https://api.github.com/repos/{org_repo}/contents/atoms/{provider}")
    if not isinstance(cats, list):
        return []
    result = []
    for cat_item in sorted(cats, key=lambda x: x["name"]):
        if cat_item["type"] != "dir":
            continue
        cat      = cat_item["name"]
        atom_lst = _gh_api(f"https://api.github.com/repos/{org_repo}/contents/atoms/{provider}/{cat}")
        if not isinstance(atom_lst, list):
            continue
        for atom_item in sorted(atom_lst, key=lambda x: x["name"]):
            if atom_item["type"] != "dir":
                continue
            atom_name = atom_item["name"]
            vers      = _remote_list_versions(registry, f"atoms/{provider}/{cat}/{atom_name}")
            if vers:
                ver = vers[-1]
                result.append({
                    "label":    f"{cat}/{atom_name}  ({ver}) [remote]",
                    "name":     atom_name,
                    "category": cat,
                    "version":  ver,
                    "remote":   True,
                    "registry": registry,
                    "rel_path": f"atoms/{provider}/{cat}/{atom_name}/{ver}",
                })
    return result


def _remote_list_molecules(registry: str, provider: str) -> list[dict]:
    org_repo  = _github_org_repo(registry)
    mol_items = _gh_api(f"https://api.github.com/repos/{org_repo}/contents/molecules/{provider}")
    if not isinstance(mol_items, list):
        return []
    result = []
    for item in sorted(mol_items, key=lambda x: x["name"]):
        if item["type"] != "dir":
            continue
        mol_name = item["name"]
        vers     = _remote_list_versions(registry, f"molecules/{provider}/{mol_name}")
        if vers:
            ver = vers[-1]
            result.append({
                "label":    f"{mol_name}  ({ver}) [remote]",
                "name":     mol_name,
                "version":  ver,
                "remote":   True,
                "registry": registry,
                "source":   f"molecules/{provider}/{mol_name}/{ver}",
            })
    return result


# ── Particle store helpers ─────────────────────────────────────────────────────

def _particles_dir(repo_root: Path) -> Path:
    return repo_root / "eif_particles"


def _particle_path(repo_root: Path, kind: str, provider: str, name: str, version: str) -> Path:
    """Return the local path for a particle, regardless of whether it exists."""
    if kind == "molecule":
        return _particles_dir(repo_root) / "molecules" / provider / name / version
    return _particles_dir(repo_root) / "atoms" / provider / name / version


def _particle_installed(repo_root: Path, kind: str, provider: str, name: str, version: str) -> bool:
    return _particle_path(repo_root, kind, provider, name, version).is_dir()


def _particle_download_dir(registry: str, reg_rel_path: str, dest: Path) -> None:
    """Recursively download all files at reg_rel_path in the registry to dest."""
    items = _gh_api(f"https://api.github.com/repos/{_github_org_repo(registry)}/contents/{reg_rel_path}")
    if not isinstance(items, list):
        sys.exit(f"❌  ERROR: could not fetch {reg_rel_path} from {registry}")
    dest.mkdir(parents=True, exist_ok=True)
    for item in items:
        if item["type"] == "file":
            content = _remote_fetch_tf(registry, item["path"])
            if content is not None:
                (dest / item["name"]).write_text(content)
        elif item["type"] == "dir":
            _particle_download_dir(registry, item["path"], dest / item["name"])


def _install_atom_deps(registry: str, mol_dest: Path, repo_root: Path) -> None:
    """Scan molecule main.tf for atom source references and download them."""
    main_tf = mol_dest / "main.tf"
    if not main_tf.exists():
        return
    for m in re.finditer(r'source\s*=\s*"([^"]*atoms/[^"]+)"', main_tf.read_text()):
        rel = m.group(1)
        atom_m = re.search(r'atoms/(.+)', rel)
        if not atom_m:
            continue
        atom_rel = f"atoms/{atom_m.group(1).rstrip('/')}"
        parts    = atom_m.group(1).strip("/").split("/")
        if len(parts) < 4:
            continue
        # parts: [provider, category, name, version] or [provider, name, version]
        atom_dest = _particles_dir(repo_root) / "atoms" / Path(*parts)
        if atom_dest.is_dir():
            continue
        label = f"atom:{'/'.join(parts[:-1])}@{parts[-1]}"
        print(f"  {_em('↓')} {_c(label, 'dim')}  downloading...", end="\r", flush=True)
        _particle_download_dir(registry, atom_rel, atom_dest)
        print(f"  {_c('✓', 'bgreen')} {_c(label, 'cyan')}  installed          ")


def _install_molecule(registry: str, provider: str, name: str, version: str, repo_root: Path) -> None:
    """Download a molecule and its atom dependencies to eif_particles/."""
    dest = _particle_path(repo_root, "molecule", provider, name, version)
    if dest.is_dir():
        print(f"  {_c('✓', 'bgreen')} {_c(f'{provider}/{name}@{version}', 'cyan')}  already cached")
        return
    reg_rel = f"molecules/{provider}/{name}/{version}"
    print(f"  {_em('↓')} {_c(f'{provider}/{name}@{version}', 'dim')}  downloading...", end="\r", flush=True)
    _particle_download_dir(registry, reg_rel, dest)
    print(f"  {_c('✓', 'bgreen')} {_c(f'{provider}/{name}@{version}', 'cyan')}  installed          ")
    _install_atom_deps(registry, dest, repo_root)


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


def _check_outdated(molecules: list, registry: str) -> list[dict]:
    """Return list of {name, source, version, latest} for upgradeable molecules."""
    if registry == "local":
        return []
    outdated = []
    for mol in molecules:
        source  = mol.get("source", "")
        version = mol.get("version", "")
        if not source or not version or "/" not in source:
            continue
        provider, name = source.split("/", 1)
        try:
            versions = _remote_list_versions(registry, f"molecules/{provider}/{name}")
        except Exception:
            continue
        if not versions:
            continue
        latest = versions[-1]
        if _semver_key(latest) > _semver_key(version):
            outdated.append({"name": mol["name"], "source": source, "version": version, "latest": latest})
    return outdated


def resolve_sources(molecules: list, repo_root: Path, output_dir: Path) -> dict:
    """Return {mol_name: relative_tf_path} for each molecule.

    Resolution order:
      1. eif_particles/molecules/<provider>/<name>/<version>/
      2. local molecules/<provider>/<name>/  (latest local version, for authoring)
      3. fail with install message
    """
    result = {}
    for mol in molecules:
        source  = mol["source"]   # "aws/db"
        version = mol["version"]  # "1.2.0"
        provider, name = source.split("/", 1)

        # 1. particle store
        particle_path = repo_root / "eif_particles" / "molecules" / provider / name / version
        if particle_path.is_dir():
            result[mol["name"]] = os.path.relpath(particle_path.resolve(), output_dir)
            continue

        # 2. local authoring directory
        local_path = repo_root / "molecules" / provider / name
        if local_path.is_dir():
            ver = latest_version(local_path)
            if ver:
                result[mol["name"]] = os.path.relpath((local_path / ver).resolve(), output_dir)
                continue

        # 3. not found
        sys.exit(
            f"❌  ERROR: {source}@{version} not installed\n"
            f"    run: eif particle install"
        )
    return result


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
            sys.exit(f"❌  ERROR: {label} not found at {path}")

    with accounts_file.open() as fh:
        accounts = json.load(fh)
    with composition_file.open() as fh:
        composition = json.load(fh)
    with env_file.open() as fh:
        env_config = json.load(fh)

    account_key = env_config.get("account")
    if account_key not in accounts:
        sys.exit(
            f"❌  ERROR: account '{account_key}' not defined in accounts.json. "
            f"Available: {list(accounts.keys())}"
        )

    return accounts[account_key], composition, env_config, repo_root, composition_file


# ── Interactive helpers ────────────────────────────────────────────────────────

def _ask(label: str, default: str | None = None) -> str:
    """Free-text prompt; exits on empty with no default."""
    val = questionary.text(label, default=default or "").ask()
    if val is None:
        sys.exit("aborted")
    val = val.strip()
    if not val:
        sys.exit(f"❌  ERROR: {label} is required")
    return val


def _choose(label: str, options: list[str]) -> str:
    """Arrow-key single-select."""
    val = questionary.select(label, choices=options).ask()
    if val is None:
        sys.exit("aborted")
    return val


def _confirm(label: str, default: bool = False) -> bool:
    val = questionary.confirm(label, default=default).ask()
    if val is None:
        sys.exit("aborted")
    return val


def _detect_providers(repo_root: Path) -> list[str]:
    providers_dir = repo_root / "providers"
    if not providers_dir.is_dir():
        return []
    return sorted(d.name for d in providers_dir.iterdir() if d.is_dir())


def _list_atoms(provider: str, repo_root: Path) -> list[dict]:
    """Return all versioned atoms for a provider as a list of dicts (local only)."""
    atoms_dir = repo_root / "atoms" / provider
    result    = []
    if atoms_dir.is_dir():
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
    """Return all versioned molecules for a provider as a list of dicts (local only)."""
    mol_dir = repo_root / "molecules" / provider
    result  = []
    if mol_dir.is_dir():
        for mol in sorted(mol_dir.iterdir()):
            if not mol.is_dir():
                continue
            ver = latest_version(mol)
            if ver:
                result.append({
                    "label":   f"{mol.name}  ({ver})",
                    "name":    mol.name,
                    "version": ver,
                    "source":  f"{provider}/{mol.name}",
                })
    return result


def _multiselect(label: str, items: list[dict]) -> list[dict]:
    """Space-bar checkbox multi-select; at least one item required."""
    by_label = {item["label"]: item for item in items}
    while True:
        chosen = questionary.checkbox(label, choices=list(by_label)).ask()
        if chosen is None:
            sys.exit("aborted")
        if chosen:
            return [by_label[c] for c in chosen]
        print("  ⚠️  select at least one item")


def _list_matters(provider: str, repo_root: Path) -> list[str]:
    matters_dir = repo_root / "matters"
    if not matters_dir.is_dir():
        return []
    return sorted(
        d.name for d in matters_dir.iterdir()
        if d.is_dir() and (d / provider).is_dir()
    )


def _list_envs(matter_path: Path) -> list[str]:
    return sorted(
        f.stem for f in matter_path.glob("*.json")
        if not f.name.endswith(".example.json") and f.name != "composition.json"
    )


def _resolve_matter_and_env(args: list[str]) -> tuple[Path, str]:
    """Return (matter_path, env) from [provider, matter, env] args or interactive prompts."""
    repo_root = find_repo_root(Path.cwd())

    if len(args) == 3:
        provider, matter_name, env = args
        return repo_root / "matters" / matter_name / provider, env

    if len(args) != 0:
        sys.exit(USAGE)

    # Interactive
    providers = _detect_providers(repo_root)
    if not providers:
        sys.exit("❌  ERROR: no providers found in providers/")
    provider = _choose("provider", providers)

    matters = _list_matters(provider, repo_root)
    if not matters:
        sys.exit(f"❌  ERROR: no matters found for provider '{provider}'")
    matter_name = _choose("matter", matters)

    matter_path = repo_root / "matters" / matter_name / provider
    envs = _list_envs(matter_path)
    if not envs:
        sys.exit(f"❌  ERROR: no environment files found in {matter_path.relative_to(repo_root)}")
    env = _choose("environment", envs)

    return matter_path, env


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
    print(f"{_pfx()} {_em('✨')}created   {_arr()} {_c(str(path.relative_to(cwd)), 'cyan')}")


# ── Render helpers ─────────────────────────────────────────────────────────────

def render_backend_block(account_config: dict, matter_name: str, env: str, repo_root: Path) -> str:
    """Render providers/<cloud>/backend.tf.j2 if a backend is configured, else ''."""
    backend = account_config.get("backend")
    if not backend:
        return ""
    provider = account_config["provider"]
    backend_template = repo_root / "providers" / provider / "backend.tf.j2"
    if not backend_template.exists():
        return ""
    j2_env = Environment(
        loader=FileSystemLoader(str(backend_template.parent)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    ctx = {
        **account_config,
        "backend_key":    f"eif/{matter_name}/{env}/terraform.tfstate",
        "backend_prefix": f"eif/{matter_name}/{env}",
    }
    return j2_env.get_template("backend.tf.j2").render(**ctx)


def render_provider_block(account_config: dict, repo_root: Path, backend_block: str = "") -> str:
    """Render providers/<cloud>/provider.tf.j2 with the account config."""
    provider = account_config.get("provider")
    if not provider:
        sys.exit("❌  ERROR: account entry is missing a 'provider' field")
    provider_template = repo_root / "providers" / provider / "provider.tf.j2"
    if not provider_template.exists():
        sys.exit(f"❌  ERROR: no provider template found at {provider_template}")
    j2_env = Environment(
        loader=FileSystemLoader(str(provider_template.parent)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    ctx = {**account_config, "backend_block": backend_block}
    return j2_env.get_template("provider.tf.j2").render(**ctx)


def _do_render(matter_path: Path, env: str) -> tuple[Path, dict, dict, dict, Path]:
    """
    Render main.tf into .rendered/<env>/main.tf.
    Returns (output_dir, account_config, composition, env_config, repo_root).
    """
    account_config, composition, env_config, repo_root, _ = load_inputs(matter_path, env)

    matter_name = matter_path.parent.name
    output_dir  = matter_path / ".rendered" / env
    output_file = output_dir / "main.tf"
    output_dir.mkdir(parents=True, exist_ok=True)

    src           = resolve_sources(composition["molecules"], repo_root, output_dir)
    backend_block = render_backend_block(account_config, matter_name, env, repo_root)
    provider_block = render_provider_block(account_config, repo_root, backend_block)

    env_vars = {k: v for k, v in env_config.items() if k != "account"}
    ctx = {
        **account_config,
        **env_vars,
        "environment":    env,
        "account":        env_config["account"],
        "molecules":      composition["molecules"],
        "src":            src,
        "provider_block": provider_block,
        "backend_block":  backend_block,
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
    print(f"{_pfx()} {_em('🔧')}rendered  {_arr()} {_c(str(output_file), 'cyan')}")

    outputs_tf = "".join(
        f'output "{mol["name"].replace("-", "_")}_outputs" {{\n'
        f'  description = "Outputs from the {mol["name"]} molecule."\n'
        f'  value       = module.{mol["name"]}\n'
        f'}}\n'
        for mol in composition["molecules"]
    )
    (output_dir / "outputs.tf").write_text(outputs_tf)
    print(f"{_pfx()} {_em('🔧')}rendered  {_arr()} {_c(str(output_dir / 'outputs.tf'), 'cyan')}")

    # Outdated check (non-blocking, silently skip on network error)
    config   = load_config(repo_root)
    registry = config.get("registry", "local")
    if registry != "local":
        try:
            outdated = _check_outdated(composition["molecules"], registry)
            if outdated:
                print()
                for o in outdated:
                    print(
                        f"  {_c('⚠', 'byellow')}  {_c(o['source'], 'cyan')}  "
                        f"{_c(o['version'], 'yellow')} {_arr()} {_c(o['latest'], 'bgreen')} available"
                    )
                print(f"  {_c('run: eif particle update', 'dim')}")
        except Exception:
            pass  # no network — skip silently

    return output_dir, account_config, composition, env_config, repo_root


# ── Snapshot helpers ───────────────────────────────────────────────────────────

def _snapshot_timestamp() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _local_history_dir(matter_path: Path, env: str) -> Path:
    return matter_path / ".history" / env


def _take_snapshot(output_dir: Path, matter_path: Path, matter_name: str,
                   env: str, account_config: dict) -> str:
    """
    Save a snapshot of .rendered/<env>/main.tf locally and (if backend configured) remotely.
    Returns the timestamp string.
    """
    ts      = _snapshot_timestamp()
    main_tf = output_dir / "main.tf"

    # Local snapshot — always
    local_dir = _local_history_dir(matter_path, env) / ts
    local_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(main_tf, local_dir / "main.tf")
    meta = {"timestamp": ts, "matter": matter_name, "env": env}
    (local_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n")
    print(f"{_pfx()} {_em('📸')}snapshot  {_arr()} {_c(f'.history/{env}/{ts}/main.tf', 'cyan')}")

    # Remote snapshot — if backend configured
    backend = account_config.get("backend")
    if backend:
        provider       = account_config["provider"]
        remote_prefix  = f"eif/{matter_name}/{env}/history/{ts}"
        try:
            _upload_snapshot(provider, backend, account_config, remote_prefix, local_dir)
            print(f"{_pfx()} {_em('☁️')} uploaded  {_arr()} {_c(f'remote:{remote_prefix}/', 'cyan')}")
        except Exception as exc:
            print(f"{_pfx()} {_em('⚠️')} {_c('WARNING:', 'byellow', 'bold')} remote snapshot upload failed {_arr()} {exc}")

    return ts


def _upload_snapshot(provider: str, backend: dict, account_config: dict,
                     remote_prefix: str, local_dir: Path) -> None:
    if provider == "aws":
        bucket = backend["bucket"]
        region = backend.get("region", account_config.get("aws_region", "us-east-1"))
        for fname in ("main.tf", "meta.json"):
            subprocess.run([
                "aws", "s3", "cp",
                str(local_dir / fname),
                f"s3://{bucket}/{remote_prefix}/{fname}",
                "--region", region,
            ], check=True, capture_output=True)
    elif provider == "azure":
        for fname in ("main.tf", "meta.json"):
            subprocess.run([
                "az", "storage", "blob", "upload",
                "--account-name", backend["storage_account_name"],
                "--container-name", backend["container_name"],
                "--name", f"{remote_prefix}/{fname}",
                "--file", str(local_dir / fname),
                "--overwrite",
            ], check=True, capture_output=True)
    elif provider == "gcp":
        bucket = backend["bucket"]
        for fname in ("main.tf", "meta.json"):
            subprocess.run([
                "gsutil", "cp",
                str(local_dir / fname),
                f"gs://{bucket}/{remote_prefix}/{fname}",
            ], check=True, capture_output=True)


def _list_snapshots(matter_path: Path, env: str) -> list[dict]:
    """List local snapshots sorted newest-first."""
    hist = _local_history_dir(matter_path, env)
    if not hist.is_dir():
        return []
    snapshots = []
    for ts_dir in sorted(hist.iterdir(), reverse=True):
        if not ts_dir.is_dir():
            continue
        meta_file = ts_dir / "meta.json"
        if not meta_file.exists():
            continue
        with meta_file.open() as fh:
            meta = json.load(fh)
        meta["_local_dir"] = str(ts_dir)
        snapshots.append(meta)
    return snapshots


def _restore_snapshot(snapshot: dict, output_dir: Path) -> None:
    src = Path(snapshot["_local_dir"]) / "main.tf"
    if not src.exists():
        sys.exit(f"❌  ERROR: snapshot main.tf not found at {src}")
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, output_dir / "main.tf")
    ts = snapshot["timestamp"]
    print(f"{_em('⏪')}{_c('restored', 'bcyan')}  {_arr()} {_c(f'{output_dir}/main.tf', 'cyan')}  {_c(f'(snapshot {ts})', 'dim')}")


# ── Terraform runner ───────────────────────────────────────────────────────────

def _tf(cmd: list[str], output_dir: Path) -> int:
    """Run a terraform subcommand in output_dir, streaming output."""
    full_cmd = ["terraform", f"-chdir={output_dir}"] + cmd
    print(f"{_em('⚙️')} {_c(' '.join(full_cmd), 'dim')}")
    return subprocess.run(full_cmd).returncode


# ── Commands (render) ─────────────────────────────────────────────────────────

def cmd_render(args: list[str]) -> None:
    matter_path, env = _resolve_matter_and_env(args)
    output_dir, _, _, _, _ = _do_render(matter_path, env)
    print(f"{_pfx()} {_em('💡')}deploy    {_arr()} {_c(f'terraform -chdir={output_dir} init', 'dim')}")
    print(f"{_pfx()}             {_c(f'terraform -chdir={output_dir} apply', 'dim')}")


# ── Preview helpers ────────────────────────────────────────────────────────────

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


# ── Commands (preview) ─────────────────────────────────────────────────────────

def _print_diff(changes: list[dict]) -> None:
    """Render a list of change records as colored diff rows."""
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


def _preview_component(label: str, path: str, component_dir: Path,
                       consumer_msg: str,
                       from_ver: str | None = None, to_ver: str | None = None) -> None:
    """Shared renderer for atom and molecule single-component previews."""
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

    print(f"\n{_em('👁️')} {_c(label + ' preview', 'bcyan', 'bold')}  {_arr()} {_c(path, 'cyan')}\n")
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


def _preview_component_remote(label: str, path: str, remote_rel: str,
                              consumer_msg: str, registry: str,
                              from_ver: str | None, to_ver: str | None) -> None:
    """Preview a component that lives in the remote registry."""
    print(f"  {_c('fetching version list from registry...', 'dim')}", end="\r", flush=True)
    versions = _remote_list_versions(registry, remote_rel)
    print(" " * 50, end="\r")  # clear the line

    if not versions:
        sys.exit(f"❌  ERROR: component '{path}' not found locally or in registry {registry}")

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
                content = _remote_fetch_tf(registry, f"{remote_rel}/{ver}/{tf_name}")
                if content:
                    (ver_dir / tf_name).write_text(content)

        changes     = _diff_interface(tmp_path / current, tmp_path / latest)
        is_breaking = any(c["breaking"] for c in changes)
        status      = (f"{_em('💥')}{_c('BREAKING', 'bred', 'bold')}"
                       if is_breaking else _c("non-breaking", "bgreen"))
        ver_range   = f"{_c(current, 'yellow')} {_arr()} {_c(latest, 'bgreen', 'bold')}"

        print(f"\n{_em('👁️')} {_c(label + ' preview', 'bcyan', 'bold')}  "
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


def cmd_preview_atom(args: list[str]) -> None:
    provider, repo_root = _resolve_provider(args)
    config   = load_config(repo_root)
    registry = config.get("registry", "local")

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
        if registry == "local":
            sys.exit(f"❌  ERROR: atom not found at {atom_dir}")
        _preview_component_remote(
            "atom", f"{provider}/{category}/{name}",
            f"atoms/{provider}/{category}/{name}",
            "molecules that use this atom may need to be updated",
            registry, from_ver, to_ver,
        )
        return

    _preview_component("atom", f"{provider}/{category}/{name}", atom_dir,
                       "molecules that use this atom may need to be updated",
                       from_ver, to_ver)


def cmd_preview_molecule(args: list[str]) -> None:
    provider, repo_root = _resolve_provider(args)
    config   = load_config(repo_root)
    registry = config.get("registry", "local")

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
        if registry == "local":
            sys.exit(f"❌  ERROR: molecule not found at {mol_dir}")
        _preview_component_remote(
            "molecule", f"{provider}/{name}",
            f"molecules/{provider}/{name}",
            "matters that use this molecule may need to be updated",
            registry, from_ver, to_ver,
        )
        return

    _preview_component("molecule", f"{provider}/{name}", mol_dir,
                       "matters that use this molecule may need to be updated",
                       from_ver, to_ver)


def cmd_preview_matter(args: list[str]) -> None:
    matter_path, env = _resolve_matter_and_env(args)
    _, composition, _, repo_root, _ = load_inputs(matter_path, env)

    provider    = matter_path.name
    matter_name = matter_path.parent.name

    print(f"\n{_em('👁️')} {_c('matter preview', 'bcyan', 'bold')}  "
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
        base   = repo_root / "molecules" / provider_mol / mol_name
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
        changes         = _diff_interface(base / current, base / latest)
        is_breaking     = any(c["breaking"] for c in changes)
        if is_breaking:
            overall_breaking = True

        status    = (f"{_em('💥')}{_c('BREAKING', 'bred', 'bold')}"
                     if is_breaking else _c("non-breaking", "bgreen"))
        ver_range = f"{_c(current, 'yellow')} {_arr()} {_c(latest, 'bgreen', 'bold')}"
        print(f"  {_c(mol['name'], 'cyan', 'bold'):<30} {ver_range}  [{status}]")

        if not changes:
            print(f"    {_c('(no interface changes)', 'dim')}\n")
            continue

        _print_diff(changes)
        print()

    print()
    if not any_upgradeable:
        print(f"{_em('✅')}{_c('all molecules up-to-date — nothing to preview', 'green')}")
    elif overall_breaking:
        print(f"{_em('💥')}{_c('BREAKING changes detected', 'bred', 'bold')}\n"
              f"   update the matter template and env vars before running "
              f"{_c('eif particle update', 'bcyan')}")
    else:
        print(f"{_em('✅')}{_c('no breaking changes', 'bgreen', 'bold')} "
              f"{_arr()} safe to run {_c('eif particle update', 'bcyan')}")


def cmd_preview(args: list[str]) -> None:
    SUBS = {"atom": cmd_preview_atom, "molecule": cmd_preview_molecule, "matter": cmd_preview_matter}

    if args and args[0] in SUBS:
        return SUBS[args[0]](args[1:])

    if args:
        # positional args with no matching subcommand → assume matter shorthand
        return cmd_preview_matter(args)

    # fully interactive — ask what level to preview
    sub = _choose("preview", ["atom", "molecule", "matter"])
    SUBS[sub]([])


# ── Vulnerability scanner ──────────────────────────────────────────────────────

def _scan(output_dir: Path, *, auto: bool = False) -> None:
    """Run trivy config scan on the rendered output directory.

    - If trivy is not on PATH: skip silently.
    - If auto=True (--scan flag): scan without prompting.
    - Otherwise: ask interactively whether to scan.
    Blocks on CRITICAL or HIGH findings.
    """
    if not shutil.which("trivy"):
        return

    if not auto and not _confirm(f"{_em('🔍')}run trivy scan?", default=False):
        return

    print(f"{_em('🔍')}scanning  {_arr()} trivy config {_c(str(output_dir), 'cyan')}")
    rc = subprocess.run([
        "trivy", "config",
        "--severity", "CRITICAL,HIGH",
        "--exit-code", "1",
        str(output_dir),
    ]).returncode

    if rc != 0:
        sys.exit(
            "❌  ERROR: scan found CRITICAL or HIGH vulnerabilities — fix before deploying\n"
            "    run 'eif scan' for the full report"
        )
    print(f"{_em('✅')}scan      {_arr()} {_c('passed', 'bgreen', 'bold')}")


# ── Commands (plan / apply / destroy / rollback) ───────────────────────────────

def cmd_plan(args: list[str]) -> None:
    auto_scan = "--scan" in args
    args      = [a for a in args if a != "--scan"]
    matter_path, env = _resolve_matter_and_env(args)
    output_dir, _, _, _, _ = _do_render(matter_path, env)
    _scan(output_dir, auto=auto_scan)
    rc = _tf(["init", "-input=false"], output_dir)
    if rc != 0:
        sys.exit(rc)
    sys.exit(_tf(["plan", "-input=false"], output_dir))


def cmd_apply(args: list[str]) -> None:
    auto_scan = "--scan" in args
    args      = [a for a in args if a != "--scan"]
    matter_path, env = _resolve_matter_and_env(args)
    output_dir, account_config, _, _, _ = _do_render(matter_path, env)
    matter_name = matter_path.parent.name

    _scan(output_dir, auto=auto_scan)

    rc = _tf(["init", "-input=false"], output_dir)
    if rc != 0:
        sys.exit(rc)

    rc = _tf(["apply", "-input=false"], output_dir)
    if rc != 0:
        sys.exit(rc)

    _take_snapshot(output_dir, matter_path, matter_name, env, account_config)


def cmd_scan(args: list[str]) -> None:
    matter_path, env = _resolve_matter_and_env(args)
    output_dir = matter_path / ".rendered" / env
    if not output_dir.is_dir():
        sys.exit(
            f"❌  ERROR: no rendered output at {output_dir} — run 'eif render' first"
        )
    if not shutil.which("trivy"):
        sys.exit(
            "❌  ERROR: trivy not found\n"
            "           install from https://aquasecurity.github.io/trivy"
        )
    print(f"{_em('🔍')}scanning  {_arr()} trivy config {_c(str(output_dir), 'cyan')}")
    subprocess.run([
        "trivy", "config",
        "--severity", "CRITICAL,HIGH,MEDIUM,LOW",
        str(output_dir),
    ])


def cmd_destroy(args: list[str]) -> None:
    matter_path, env = _resolve_matter_and_env(args)
    output_dir = matter_path / ".rendered" / env
    if not (output_dir / "main.tf").exists():
        sys.exit(
            f"❌  ERROR: no rendered config at {output_dir} — run 'eif render' first"
        )
    sys.exit(_tf(["destroy", "-input=false"], output_dir))


def cmd_rollback(args: list[str]) -> None:
    matter_path, env = _resolve_matter_and_env(args)
    output_dir = matter_path / ".rendered" / env

    snapshots = _list_snapshots(matter_path, env)
    if not snapshots:
        sys.exit(
            f"❌  ERROR: no snapshots found in .history/{env}/\n"
            "    Run 'eif apply' at least once to create a snapshot."
        )

    choices   = [s["timestamp"] for s in snapshots]
    chosen_ts = _choose("snapshot to restore", choices)
    snapshot  = next(s for s in snapshots if s["timestamp"] == chosen_ts)

    _restore_snapshot(snapshot, output_dir)

    if not _confirm("run terraform apply with restored config?", default=True):
        print(f"{_em('⏪')}{_c('restored main.tf', 'cyan')} — run {_c('terraform apply', 'dim')} manually when ready")
        return

    rc = _tf(["init", "-input=false"], output_dir)
    if rc != 0:
        sys.exit(rc)
    sys.exit(_tf(["apply", "-input=false"], output_dir))


# ── Commands (init) ────────────────────────────────────────────────────────────

def cmd_init_backend(args: list[str]) -> None:
    matter_path, env = _resolve_matter_and_env(args)
    account_config, _, _, _, _ = load_inputs(matter_path, env)

    backend = account_config.get("backend")
    if not backend:
        sys.exit(
            "❌  ERROR: no 'backend' key in accounts.json for this account.\n"
            "    Add a 'backend' object — see accounts.example.json."
        )

    provider = account_config["provider"]
    print(f"{_em('📦')}bootstrapping {_c(provider, 'cyan')} remote backend...")

    if provider == "aws":
        _init_backend_aws(backend, account_config)
    elif provider == "azure":
        _init_backend_azure(backend, account_config)
    elif provider == "gcp":
        _init_backend_gcp(backend, account_config)
    else:
        sys.exit(f"❌  ERROR: no backend bootstrap support for provider '{provider}'")

    print(f"{_em('✅')}{_c('backend ready', 'bgreen')} — run {_c('eif apply', 'bcyan')} to deploy")


def _init_backend_aws(backend: dict, account_config: dict) -> None:
    bucket = backend["bucket"]
    region = backend.get("region", account_config.get("aws_region", "us-east-1"))
    dynamo = backend.get("dynamodb_table")

    create_args = ["aws", "s3api", "create-bucket", "--bucket", bucket, "--region", region]
    if region != "us-east-1":
        create_args += ["--create-bucket-configuration", f"LocationConstraint={region}"]
    subprocess.run(create_args, check=True)

    subprocess.run([
        "aws", "s3api", "put-bucket-versioning",
        "--bucket", bucket,
        "--versioning-configuration", "Status=Enabled",
    ], check=True)

    subprocess.run([
        "aws", "s3api", "put-public-access-block",
        "--bucket", bucket,
        "--public-access-block-configuration",
        "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true",
    ], check=True)

    print(f"{_em('✅')}S3 bucket {_c(repr(bucket), 'cyan')} created with versioning enabled")

    if dynamo:
        subprocess.run([
            "aws", "dynamodb", "create-table",
            "--table-name", dynamo,
            "--attribute-definitions", "AttributeName=LockID,AttributeType=S",
            "--key-schema", "AttributeName=LockID,KeyType=HASH",
            "--billing-mode", "PAY_PER_REQUEST",
            "--region", region,
        ], check=True)
        print(f"{_em('✅')}DynamoDB table {_c(repr(dynamo), 'cyan')} created for state locking")


def _init_backend_azure(backend: dict, account_config: dict) -> None:
    rg        = backend["resource_group_name"]
    storage   = backend["storage_account_name"]
    container = backend["container_name"]
    location  = backend.get("location", "eastus")

    subprocess.run(["az", "group", "create", "--name", rg, "--location", location], check=True)
    subprocess.run([
        "az", "storage", "account", "create",
        "--name", storage, "--resource-group", rg,
        "--sku", "Standard_LRS", "--kind", "StorageV2",
    ], check=True)
    subprocess.run([
        "az", "storage", "container", "create",
        "--name", container, "--account-name", storage,
    ], check=True)
    subprocess.run([
        "az", "storage", "account", "blob-service-properties", "update",
        "--account-name", storage, "--resource-group", rg,
        "--enable-versioning", "true",
    ], check=True)
    print(f"{_em('✅')}Azure storage {_c(repr(storage), 'cyan')} / container {_c(repr(container), 'cyan')} ready")


def _init_backend_gcp(backend: dict, account_config: dict) -> None:
    bucket  = backend["bucket"]
    project = account_config.get("project")
    region  = account_config.get("region", "us-central1")

    mb_args = ["gsutil", "mb"]
    if project:
        mb_args += ["-p", project]
    mb_args += ["-l", region, f"gs://{bucket}"]
    subprocess.run(mb_args, check=True)

    subprocess.run(["gsutil", "versioning", "set", "on", f"gs://{bucket}"], check=True)
    gcs_url = f"gs://{bucket}"
    print(f"{_em('✅')}GCS bucket {_c(repr(gcs_url), 'cyan')} created with versioning enabled")


def cmd_init_account(args: list[str]) -> None:  # noqa: ARG001
    repo_root     = find_repo_root(Path.cwd())
    accounts_file = repo_root / "accounts.json"

    with accounts_file.open() as fh:
        accounts = json.load(fh)

    providers = _detect_providers(repo_root)
    provider  = _choose("provider", providers)
    env_name  = _ask("account key (e.g. dev, prod, azure-dev)")

    if env_name in accounts:
        sys.exit(f"❌  ERROR: account '{env_name}' already exists in accounts.json")

    entry: dict = {"provider": provider}

    if provider == "aws":
        entry["aws_region"] = _ask("aws_region", "us-east-1")
        auth = _choose("auth method", ["profile", "assume_role"])
        if auth == "profile":
            entry["profile"] = _ask("profile name")
        else:
            entry["assume_role_arn"] = _ask("assume_role_arn")
    elif provider == "azure":
        entry["subscription_id"] = _ask("subscription_id")
        entry["tenant_id"]       = _ask("tenant_id")
        if _confirm("use service principal?"):
            entry["client_id"]     = _ask("client_id")
            entry["client_secret"] = _ask("client_secret")
    elif provider == "gcp":
        entry["project"] = _ask("project")
        entry["region"]  = _ask("region", "us-central1")
        if _confirm("use credentials file?"):
            entry["credentials_file"] = _ask("credentials_file path")

    if _confirm("configure remote backend?"):
        backend: dict = {}
        if provider == "aws":
            backend["bucket"]         = _ask("S3 bucket name")
            backend["region"]         = entry.get("aws_region", "us-east-1")
            backend["dynamodb_table"] = _ask("DynamoDB table name (for locking)")
        elif provider == "azure":
            backend["resource_group_name"]  = _ask("resource_group_name")
            backend["storage_account_name"] = _ask("storage_account_name")
            backend["container_name"]       = _ask("container_name")
            backend["location"]             = _ask("location", "eastus")
        elif provider == "gcp":
            backend["bucket"] = _ask("GCS bucket name")
        if backend:
            entry["backend"] = backend

    accounts[env_name] = entry
    with accounts_file.open("w") as fh:
        json.dump(accounts, fh, indent=2)
        fh.write("\n")
    print(f"{_em('✅')}added     accounts.json {_arr()} {_c(repr(env_name), 'cyan')}")

    if entry.get("backend") and _confirm("bootstrap backend now?"):
        if provider == "aws":
            _init_backend_aws(entry["backend"], entry)
        elif provider == "azure":
            _init_backend_azure(entry["backend"], entry)
        elif provider == "gcp":
            _init_backend_gcp(entry["backend"], entry)


def cmd_init(args: list[str]) -> None:
    SUB = {"backend": cmd_init_backend}
    if not args or args[0] not in SUB:
        sys.exit(
            "Usage:\n"
            "  eif init backend [<provider> <matter> <env>]  Bootstrap remote state bucket"
        )
    SUB[args[0]](args[1:])


def cmd_add(args: list[str]) -> None:
    SUB = {"account": cmd_init_account}
    if not args or args[0] not in SUB:
        sys.exit("Usage:\n  eif add account  Add an account entry to accounts.json")
    SUB[args[0]](args[1:])


# ── Commands (new) ────────────────────────────────────────────────────────────

def cmd_new_atom(args: list[str]) -> None:
    repo_root = find_repo_root(Path.cwd())
    cwd = Path.cwd()

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
    cwd = Path.cwd()

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
    elif all_atoms:
        print()
        selected_atoms = _multiselect("atoms to include", all_atoms)
    else:
        print(f"  {_c(f'no atoms found for {provider} — scaffolding empty molecule', 'dim')}")

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
    cwd = Path.cwd()

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

    # Molecule selection — prefer registry if configured
    config    = load_config(repo_root)
    registry  = config.get("registry", "local")
    all_mols  = _list_molecules(provider, repo_root)  # local first

    if not all_mols and registry != "local":
        print(f"  {_c('querying registry...', 'dim')}", end="\r", flush=True)
        all_mols = _remote_list_molecules(registry, provider)
        print(" " * 40, end="\r")

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
        print(f"  {_c(f'no molecules found for {provider} — scaffolding empty matter', 'dim')}")

    out.mkdir(parents=True)
    print()

    # Install remote particles and build molecule list for composition
    mol_entries = []
    for mol in selected_mols:
        if mol.get("remote") and registry != "local":
            version = mol["version"]
            _install_molecule(registry, provider, mol["name"], version, repo_root)
        else:
            # local molecule — get its latest version
            local_path = repo_root / "molecules" / provider / mol["name"]
            version = latest_version(local_path) or "1.0.0"
        mol_entries.append({"name": mol["name"], "source": f"{provider}/{mol['name']}", "version": version})

    # composition.json
    composition = {
        "matter": name,
        "molecules": mol_entries,
    }
    (out / "composition.json").write_text(json.dumps(composition, indent=2) + "\n")
    print(f"{_em('✨')}created   {_arr()} {_c(str((out / 'composition.json').relative_to(cwd)), 'cyan')}")

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
        "atom":     cmd_new_atom,
        "molecule": cmd_new_molecule,
        "matter":   cmd_new_matter,
    }
    if not args or args[0] not in SUB:
        sys.exit(
            "Usage:\n"
            "  eif new atom     [<name> [<provider> [<category>]]]\n"
            "  eif new molecule [<name> [<provider> [<category/atom>,...]]]\n"
            "  eif new matter   [<name> [<provider> [<molecule>,...  ]]]"
        )
    SUB[args[0]](args[1:])




# ── Commands (particle) ────────────────────────────────────────────────────────

def _require_registry(repo_root: Path) -> str:
    config   = load_config(repo_root)
    registry = config.get("registry", "local")
    if registry == "local":
        sys.exit(
            "❌  ERROR: no remote registry configured\n"
            "    create eif.particles.json with:\n"
            '    {"registry": "https://github.com/giordanocardillo/eif-library"}'
        )
    return registry


def cmd_particle_install(args: list[str]) -> None:  # noqa: ARG001
    repo_root = find_repo_root(Path.cwd())
    registry  = _require_registry(repo_root)

    compositions = _all_compositions(repo_root)
    if not compositions:
        print(f"{_c('no composition.json files found', 'dim')}")
        return

    print(f"{_em('📦')}installing particles {_arr()} {_c(registry, 'dim')}\n")

    seen = set()
    for _, comp in compositions:
        for mol in comp.get("molecules", []):
            source  = mol.get("source", "")
            version = mol.get("version", "")
            if not source or not version or "/" not in source:
                continue
            key = (source, version)
            if key in seen:
                continue
            seen.add(key)
            provider, name = source.split("/", 1)
            _install_molecule(registry, provider, name, version, repo_root)

    print(f"\n{_em('✅')}{_c('done', 'bgreen', 'bold')}")


def cmd_particle_add(args: list[str]) -> None:
    """Add a molecule to the current matter's composition.json and install it.

    Usage: eif particle add <provider>/<name> <version>
    """
    repo_root   = find_repo_root(Path.cwd())
    registry    = _require_registry(repo_root)
    matter_path, env = _resolve_matter_and_env([])

    if len(args) >= 2:
        source, version = args[0], args[1]
    elif len(args) == 1:
        source  = args[0]
        if "/" not in source:
            sys.exit("❌  ERROR: source must be <provider>/<name>  e.g. aws/db")
        provider, name = source.split("/", 1)
        versions = _remote_list_versions(registry, f"molecules/{provider}/{name}")
        if not versions:
            sys.exit(f"❌  ERROR: no versions found for {source} in registry")
        version = versions[-1]
        print(f"  {_c('latest', 'dim')} {_arr()} {_c(version, 'bgreen')}")
    else:
        sys.exit("Usage: eif particle add <provider>/<name> [<version>]")

    if "/" not in source:
        sys.exit("❌  ERROR: source must be <provider>/<name>  e.g. aws/db")
    provider, name = source.split("/", 1)

    # Install
    _install_molecule(registry, provider, name, version, repo_root)

    # Update composition.json
    comp_file = matter_path / "composition.json"
    if not comp_file.exists():
        sys.exit(f"❌  ERROR: composition.json not found at {comp_file}")
    comp = json.loads(comp_file.read_text())

    # Check if already present
    existing = next((m for m in comp["molecules"] if m["source"] == source), None)
    if existing:
        old_ver = existing["version"]
        existing["version"] = version
        comp_file.write_text(json.dumps(comp, indent=2) + "\n")
        print(f"{_em('✅')}updated   {_c(source, 'cyan')} {_c(old_ver, 'yellow')} {_arr()} {_c(version, 'bgreen', 'bold')}")
    else:
        mol_name = name.replace("-", "_")
        comp["molecules"].append({"name": mol_name, "source": source, "version": version})
        comp_file.write_text(json.dumps(comp, indent=2) + "\n")
        print(f"{_em('✅')}added     {_c(source, 'cyan')}@{_c(version, 'bgreen', 'bold')}")


def cmd_particle_remove(args: list[str]) -> None:
    repo_root = find_repo_root(Path.cwd())
    matter_path, _ = _resolve_matter_and_env([])
    comp_file = matter_path / "composition.json"
    if not comp_file.exists():
        sys.exit(f"❌  ERROR: composition.json not found at {comp_file}")

    if not args:
        sys.exit("Usage: eif particle remove <provider>/<name>")
    source = args[0]

    comp = json.loads(comp_file.read_text())
    before = len(comp["molecules"])
    comp["molecules"] = [m for m in comp["molecules"] if m.get("source") != source]
    if len(comp["molecules"]) == before:
        sys.exit(f"❌  ERROR: {source} not found in composition.json")
    comp_file.write_text(json.dumps(comp, indent=2) + "\n")
    print(f"{_em('✅')}removed   {_c(source, 'cyan')} from composition.json")
    print(f"  {_c('note: eif_particles/ cache not deleted (may be shared)', 'dim')}")


def cmd_particle_update(args: list[str]) -> None:
    safe_mode = "--safe" in args
    args      = [a for a in args if a != "--safe"]

    repo_root = find_repo_root(Path.cwd())
    registry  = _require_registry(repo_root)

    # Resolve which matter to update
    matter_path, _ = _resolve_matter_and_env([])
    comp_file = matter_path / "composition.json"
    if not comp_file.exists():
        sys.exit(f"❌  ERROR: composition.json not found at {comp_file}")

    comp    = json.loads(comp_file.read_text())
    changed = False

    # Filter to specific source if provided
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
        try:
            versions = _remote_list_versions(registry, f"molecules/{provider}/{name}")
        except Exception:
            print(f"  {_c('skip', 'dim')} {_c(source, 'dim')} — registry unavailable")
            continue

        if not versions:
            continue
        latest = versions[-1]

        if _semver_key(latest) <= _semver_key(version):
            print(f"  {_em('✅')}{_c(source, 'green')}@{_c(version, 'dim')}  up-to-date")
            continue

        if safe_mode and _semver_key(latest)[0] > _semver_key(version)[0]:
            print(
                f"  {_em('⏭️')} {_c('skip (major bump)', 'byellow')}  "
                f"{_c(source, 'dim')}  {_c(version, 'dim')} {_arr()} {_c(latest, 'dim')}"
            )
            continue

        # Show diff
        _preview_component_remote(
            "molecule", source,
            f"molecules/{provider}/{name}",
            "update composition.json when safe",
            registry, version, latest,
        )

        if not _confirm(f"update {source} {_c(version, 'yellow')} → {_c(latest, 'bgreen')}?", default=True):
            continue

        mol["version"] = latest
        _install_molecule(registry, provider, name, latest, repo_root)
        changed = True

    if changed:
        comp_file.write_text(json.dumps(comp, indent=2) + "\n")
        print(f"\n{_em('💾')}wrote     {_arr()} {_c(str(comp_file), 'cyan')}")
    else:
        print(f"\n{_em('✅')}{_c('nothing to update', 'green')}")


def cmd_particle_list(args: list[str]) -> None:  # noqa: ARG001
    repo_root = find_repo_root(Path.cwd())
    pdir      = _particles_dir(repo_root)

    if not pdir.is_dir():
        print(f"  {_c('no particles installed — run: eif particle install', 'dim')}")
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


def cmd_particle_outdated(args: list[str]) -> None:  # noqa: ARG001
    repo_root = find_repo_root(Path.cwd())
    registry  = _require_registry(repo_root)

    compositions = _all_compositions(repo_root)
    if not compositions:
        print(f"{_c('no composition.json files found', 'dim')}")
        return

    any_outdated = False
    for comp_file, comp in compositions:
        outdated = _check_outdated(comp.get("molecules", []), registry)
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
        print(f"{_em('✅')}{_c('all particles up-to-date', 'bgreen', 'bold')}")
    else:
        print(f"\n{_c('run: eif particle update', 'dim')}")


def cmd_particle_init(args: list[str]) -> None:  # noqa: ARG001
    repo_root = find_repo_root(Path.cwd())
    cfg_file  = repo_root / "eif.particles.json"
    if cfg_file.exists():
        print(f"{_em('ℹ️')} {_c('eif.particles.json already exists', 'dim')}")
        print(cfg_file.read_text())
        return
    registry = _ask("registry URL (or 'local')", "https://github.com/giordanocardillo/eif-library")
    config   = {"registry": registry}
    cfg_file.write_text(json.dumps(config, indent=2) + "\n")
    print(f"{_em('✅')}created   {_arr()} {_c(str(cfg_file), 'cyan')}")


def cmd_particle(args: list[str]) -> None:
    SUBS = {
        "install":  cmd_particle_install,
        "add":      cmd_particle_add,
        "remove":   cmd_particle_remove,
        "update":   cmd_particle_update,
        "list":     cmd_particle_list,
        "outdated": cmd_particle_outdated,
        "init":     cmd_particle_init,
    }
    if not args or args[0] not in SUBS:
        sys.exit(
            "Usage:\n"
            "  eif particle init                          Init eif.particles.json\n"
            "  eif particle install                       Install all particles from composition files\n"
            "  eif particle add <provider>/<name> [<ver>] Add molecule to matter + install\n"
            "  eif particle remove <provider>/<name>     Remove molecule from matter\n"
            "  eif particle update [<provider>/<name>]   Update to latest (interactive diff + confirm)\n"
            "  eif particle update --safe                 Skip major-version bumps\n"
            "  eif particle list                          Show installed particles\n"
            "  eif particle outdated                      Show available updates across all matters"
        )
    SUBS[args[0]](args[1:])


# ── Entry point ───────────────────────────────────────────────────────────────

def cmd_version(_args: list[str]) -> None:
    print(f"eif {_pkg_version('eif')}")


# ── Commands (list) ────────────────────────────────────────────────────────────

def cmd_list(args: list[str]) -> None:
    SUBS = ("providers", "atoms", "molecules", "matters")
    if not args or args[0] not in SUBS:
        sys.exit("Usage:\n  eif list providers|atoms|molecules|matters  [<provider>]")

    repo_root = find_repo_root(Path.cwd())
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


USAGE = (
    "Usage:\n"
    "  eif version\n"
    "  eif list providers|atoms|molecules|matters  [<provider>]\n"
    "  eif render   [<provider> <matter> <env>]\n"
    "  eif preview atom     [<provider> <category/name> [<from> <to>]]\n"
    "  eif preview molecule [<provider> <name>         [<from> <to>]]\n"
    "  eif preview matter   [<provider> <matter> <env>]\n"
    "  eif scan     [<provider> <matter> <env>]\n"
    "  eif plan     [<provider> <matter> <env>]  [--scan]\n"
    "  eif apply    [<provider> <matter> <env>]  [--scan]\n"
    "  eif destroy  [<provider> <matter> <env>]\n"
    "  eif rollback [<provider> <matter> <env>]\n"
    "  eif init backend [<provider> <matter> <env>]\n"
    "  eif add account\n"
    "  eif new atom     [<name> [<provider> [<category>]]]\n"
    "  eif new molecule [<name> [<provider> [<category/atom>,...]]]\n"
    "  eif new matter   [<name> [<provider> [<molecule>,...  ]]]\n"
    "  eif particle init\n"
    "  eif particle install\n"
    "  eif particle add <provider>/<name> [<version>]\n"
    "  eif particle remove <provider>/<name>\n"
    "  eif particle update [<provider>/<name>]  [--safe]\n"
    "  eif particle list\n"
    "  eif particle outdated\n"
    "  (all positional args optional — missing ones are prompted interactively)\n"
    "  (--safe  skips breaking major-version bumps during eif particle update)\n"
    "  (--scan  auto-runs trivy if installed; without it, plan/apply prompt interactively)\n"
    "  (eif preview shows interface diffs and flags breaking changes before update)\n"
    "  (eif particle init  creates eif.particles.json with registry config)"
)

def main() -> None:
    args = sys.argv[1:]
    if not args:
        sys.exit(USAGE)

    cmd = args[0]
    CMDS = {
        "version":  cmd_version,
        "list":     cmd_list,
        "render":   cmd_render,
        "preview":  cmd_preview,
        "scan":     cmd_scan,
        "plan":     cmd_plan,
        "apply":    cmd_apply,
        "destroy":  cmd_destroy,
        "rollback": cmd_rollback,
        "new":      cmd_new,
        "add":      cmd_add,
        "init":     cmd_init,
        "particle": cmd_particle,
    }

    if cmd not in CMDS:
        sys.exit(USAGE)

    CMDS[cmd](args[1:])


if __name__ == "__main__":
    main()
