"""registry.py — registry adapters: GitHub, GitLab, HTTP."""

import json
import os
import urllib.request
from pathlib import Path

SUPPORTED_TYPES = ("github", "gitlab", "http")


def _detect_type(url: str) -> str:
    if "github.com" in url:
        return "github"
    if "gitlab" in url:
        return "gitlab"
    return "http"


class RegistryClient:
    """Base registry adapter. Subclasses implement list_dir / fetch_file."""

    def __init__(self, entry: dict) -> None:
        self.name     = entry.get("name", "unnamed")
        self.url      = entry["url"].rstrip("/")
        self.priority = int(entry.get("priority", 0))
        self.type     = entry.get("type") or _detect_type(self.url)
        self._auth    = entry.get("auth", {})

    def list_versions(self, rel_path: str) -> list[str]:
        from .core import _is_semver, _semver_key
        data = self.list_dir(rel_path)
        if not isinstance(data, list):
            return []
        return sorted(
            [item["name"] for item in data if item.get("type") == "dir" and _is_semver(item["name"])],
            key=_semver_key,
        )

    def list_dir(self, rel_path: str) -> list[dict] | None:  # noqa: ARG002
        return None

    def fetch_file(self, rel_path: str) -> str | None:  # noqa: ARG002
        return None

    def _request_headers(self) -> dict:
        return {"User-Agent": "eif-cli"}

    def _get_json(self, url: str) -> list | dict | None:
        try:
            req = urllib.request.Request(url, headers=self._request_headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception:
            return None

    def _get_text(self, url: str) -> str | None:
        try:
            req = urllib.request.Request(url, headers=self._request_headers())
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read().decode()
        except Exception:
            return None

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r}, priority={self.priority})"


class GitHubClient(RegistryClient):
    """Registry backed by a GitHub repository.

    Auth (from eif.secure.json registryAuth): { token_env: "GITHUB_TOKEN" }
    """

    def __init__(self, entry: dict) -> None:
        super().__init__(entry)
        self._org_repo = self.url.removeprefix("https://github.com/").strip("/")

    def _request_headers(self) -> dict:
        h = {"User-Agent": "eif-cli", "Accept": "application/vnd.github.v3+json"}
        token_env = self._auth.get("token_env")
        if token_env:
            token = os.environ.get(token_env)
            if token:
                h["Authorization"] = f"Bearer {token}"
        return h

    def list_dir(self, rel_path: str) -> list[dict] | None:
        data = self._get_json(
            f"https://api.github.com/repos/{self._org_repo}/contents/{rel_path}"
        )
        if not isinstance(data, list):
            return None
        return [{"name": item["name"], "type": item["type"]} for item in data]

    def fetch_file(self, rel_path: str) -> str | None:
        return self._get_text(
            f"https://raw.githubusercontent.com/{self._org_repo}/main/{rel_path}"
        )


class GitLabClient(RegistryClient):
    """Registry backed by a GitLab repository (cloud or self-hosted).

    Auth (from eif.secure.json registryAuth): { token_env: "GITLAB_TOKEN" }
    """

    def __init__(self, entry: dict) -> None:
        super().__init__(entry)
        from urllib.parse import urlparse, quote
        parsed         = urlparse(self.url)
        self._base     = f"{parsed.scheme}://{parsed.netloc}"
        self._project  = parsed.path.strip("/")
        self._proj_enc = quote(self._project, safe="")

    def _request_headers(self) -> dict:
        h = {"User-Agent": "eif-cli"}
        token_env = self._auth.get("token_env")
        if token_env:
            token = os.environ.get(token_env)
            if token:
                h["PRIVATE-TOKEN"] = token
        return h

    def list_dir(self, rel_path: str) -> list[dict] | None:
        from urllib.parse import quote
        url  = (
            f"{self._base}/api/v4/projects/{self._proj_enc}/repository/tree"
            f"?path={quote(rel_path, safe='')}&ref=main&per_page=100"
        )
        data = self._get_json(url)
        if not isinstance(data, list):
            return None
        return [
            {"name": item["name"], "type": "dir" if item["type"] == "tree" else "file"}
            for item in data
        ]

    def fetch_file(self, rel_path: str) -> str | None:
        return self._get_text(f"{self._base}/{self._project}/-/raw/main/{rel_path}")


class HttpClient(RegistryClient):
    """Generic HTTP registry following the EIF HTTP protocol.

    Auth types (from eif.secure.json registryAuth):
      bearer:       { type: bearer,       token_env: "..." }
      basic:        { type: basic,         username_env: "...", password_env: "..." }
      oauth_client: { type: oauth_client, client_id_env: "...", client_secret_env: "...", token_url: "..." }

    Directory listing: GET <url>/<path>/  → JSON [{name, type: dir|file}, ...]
    File fetch:        GET <url>/<path>   → raw file content
    """

    def __init__(self, entry: dict) -> None:
        super().__init__(entry)
        self._oauth_token: str | None = None

    def _request_headers(self) -> dict:
        h    = {"User-Agent": "eif-cli"}
        auth = self._auth
        t    = auth.get("type")

        if t == "bearer":
            token_env = auth.get("token_env")
            if token_env:
                token = os.environ.get(token_env)
                if token:
                    h["Authorization"] = f"Bearer {token}"

        elif t == "basic":
            import base64
            user = os.environ.get(auth.get("username_env", ""), "")
            pwd  = os.environ.get(auth.get("password_env", ""), "")
            if user or pwd:
                encoded = base64.b64encode(f"{user}:{pwd}".encode()).decode()
                h["Authorization"] = f"Basic {encoded}"

        elif t == "oauth_client":
            token = self._get_oauth_token()
            if token:
                h["Authorization"] = f"Bearer {token}"

        return h

    def _get_oauth_token(self) -> str | None:
        if self._oauth_token:
            return self._oauth_token
        import urllib.parse
        auth          = self._auth
        client_id     = os.environ.get(auth.get("client_id_env", ""), "")
        client_secret = os.environ.get(auth.get("client_secret_env", ""), "")
        token_url     = auth.get("token_url", "")
        if not (client_id and client_secret and token_url):
            return None
        try:
            data = urllib.parse.urlencode({
                "grant_type":    "client_credentials",
                "client_id":     client_id,
                "client_secret": client_secret,
            }).encode()
            req = urllib.request.Request(
                token_url, data=data, method="POST",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                self._oauth_token = json.loads(resp.read()).get("access_token")
                return self._oauth_token
        except Exception:
            return None

    def list_dir(self, rel_path: str) -> list[dict] | None:
        data = self._get_json(f"{self.url}/{rel_path.rstrip('/')}/")
        if not isinstance(data, list):
            return None
        return data

    def fetch_file(self, rel_path: str) -> str | None:
        return self._get_text(f"{self.url}/{rel_path}")


def make_client(entry: dict) -> RegistryClient:
    """Return the appropriate RegistryClient for the given registry entry.

    entry may include an 'auth' key already merged from eif.secure.json.
    """
    t = entry.get("type") or _detect_type(entry.get("url", ""))
    if t == "github":
        return GitHubClient(entry)
    if t == "gitlab":
        return GitLabClient(entry)
    return HttpClient(entry)


# ── Convenience helpers for listing remote components ─────────────────────────

def list_remote_atoms(client: RegistryClient, provider: str) -> list[dict]:
    cats = client.list_dir(f"atoms/{provider}")
    if not isinstance(cats, list):
        return []
    result = []
    for cat_item in sorted(cats, key=lambda x: x["name"]):
        if cat_item["type"] != "dir":
            continue
        cat      = cat_item["name"]
        atom_lst = client.list_dir(f"atoms/{provider}/{cat}")
        if not isinstance(atom_lst, list):
            continue
        for atom_item in sorted(atom_lst, key=lambda x: x["name"]):
            if atom_item["type"] != "dir":
                continue
            atom_name = atom_item["name"]
            vers      = client.list_versions(f"atoms/{provider}/{cat}/{atom_name}")
            if vers:
                result.append({
                    "label":    f"{cat}/{atom_name}  ({vers[-1]}) [remote:{client.name}]",
                    "name":     atom_name,
                    "category": cat,
                    "version":  vers[-1],
                    "remote":   True,
                    "client":   client,
                    "rel_path": f"atoms/{provider}/{cat}/{atom_name}/{vers[-1]}",
                })
    return result


def list_remote_molecules(client: RegistryClient, provider: str) -> list[dict]:
    mol_items = client.list_dir(f"molecules/{provider}")
    if not isinstance(mol_items, list):
        return []
    result = []
    for item in sorted(mol_items, key=lambda x: x["name"]):
        if item["type"] != "dir":
            continue
        mol_name = item["name"]
        vers     = client.list_versions(f"molecules/{provider}/{mol_name}")
        if vers:
            result.append({
                "label":   f"{mol_name}  ({vers[-1]}) [remote:{client.name}]",
                "name":    mol_name,
                "version": vers[-1],
                "remote":  True,
                "client":  client,
                "source":  f"molecules/{provider}/{mol_name}/{vers[-1]}",
            })
    return result
