"""ui.py — output formatting, interactive prompts, local resource listing."""

import shutil
import sys
from pathlib import Path

import questionary

from .core import (
    _packages_dir,
    _PROVIDER_TF,
    find_repo_root,
    latest_version,
)

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
    """Return all versioned molecules for a provider — authored (molecules/) + cached (eif_packages/)."""
    seen:   set  = set()
    result: list = []

    def _scan(mol_dir: Path) -> None:
        if not mol_dir.is_dir():
            return
        for mol in sorted(mol_dir.iterdir()):
            if not mol.is_dir() or mol.name in seen:
                continue
            ver = latest_version(mol)
            if ver:
                seen.add(mol.name)
                result.append({
                    "label":   f"{mol.name}  ({ver})",
                    "name":    mol.name,
                    "version": ver,
                    "source":  f"{provider}/{mol.name}",
                })

    _scan(repo_root / "molecules" / provider)
    _scan(_packages_dir(repo_root) / "molecules" / provider)
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
    from .commands import USAGE  # late import to avoid circular
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
