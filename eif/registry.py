"""registry.py — GitHub API + download helpers."""

import json
import urllib.request
from pathlib import Path

from .core import _is_semver, _semver_key


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
