"""core.py — semver helpers, constants, find_repo_root, load_config, latest_version."""

import json
import re
import sys
from pathlib import Path

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
    """Walk up from start until we find accounts.json or eif.project.json."""
    current = start
    while current != current.parent:
        if (current / "accounts.json").exists() or (current / "eif.project.json").exists():
            return current
        current = current.parent
    sys.exit("❌  ERROR: no eif project found — run 'eif init' to scaffold a new project")


_DEFAULT_REGISTRY = "https://github.com/giordanocardillo/eif-library"


def load_config(repo_root: Path) -> dict:
    """Load eif.project.json, falling back to the default registry if not set."""
    defaults = {"registry": _DEFAULT_REGISTRY}
    cfg_file = repo_root / "eif.project.json"
    if cfg_file.exists():
        try:
            return {**defaults, **json.loads(cfg_file.read_text())}
        except json.JSONDecodeError as e:
            sys.exit(f"❌  ERROR: eif.project.json is invalid JSON — {e}")
    return defaults


def _packages_dir(repo_root: Path) -> Path:
    return repo_root / "eif_packages"


def latest_version(module_path: Path) -> str | None:
    """Return the highest semver directory inside module_path, or None."""
    if not module_path.is_dir():
        return None
    sv_dirs = [d.name for d in module_path.iterdir() if d.is_dir() and _is_semver(d.name)]
    if sv_dirs:
        return max(sv_dirs, key=_semver_key)
    return None
