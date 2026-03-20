#!/usr/bin/env python3
"""
EIF — Elemental Infrastructure Framework
CLI renderer, upgrade tool, scaffolding, and deployment lifecycle.

Commands:
    eif render   [<provider> <matter> <env>]  Render composition + env → .rendered/<env>/main.tf
    eif upgrade  [<provider> <matter> <env>]  Bump all molecule sources to their latest version
    eif plan     [<provider> <matter> <env>]  Render and run terraform plan
    eif apply    [<provider> <matter> <env>]  Render, run terraform apply, snapshot on success
    eif destroy  [<provider> <matter> <env>]  Run terraform destroy on the rendered output
    eif rollback [<provider> <matter> <env>]  Restore a previous snapshot and re-apply
    eif init backend [<provider> <matter> <env>]  Bootstrap remote state bucket
    eif add account                               Add an account entry to accounts.json
    eif new atom     [<name> [<provider> [<category>]]]
    eif new molecule [<name> [<provider> [<category/atom>,...  ]]]
    eif new matter   [<name> [<provider> [<molecule>,...       ]]]

Install as a shell command:
    uv tool install --editable .

Examples:
    eif render                                       # fully interactive
    eif render   aws three-tier-app dev              # fully non-interactive
    eif upgrade  aws three-tier-app dev
    eif plan     aws three-tier-app dev
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
from pathlib import Path

import questionary
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


# ── Core helpers ──────────────────────────────────────────────────────────────

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

def _ask(label: str, default: str | None = None) -> str:
    """Free-text prompt; exits on empty with no default."""
    val = questionary.text(label, default=default or "").ask()
    if val is None:
        sys.exit("[eif] aborted")
    val = val.strip()
    if not val:
        sys.exit(f"[eif] ERROR: {label} is required")
    return val


def _choose(label: str, options: list[str]) -> str:
    """Arrow-key single-select."""
    val = questionary.select(label, choices=options).ask()
    if val is None:
        sys.exit("[eif] aborted")
    return val


def _confirm(label: str, default: bool = False) -> bool:
    val = questionary.confirm(label, default=default).ask()
    if val is None:
        sys.exit("[eif] aborted")
    return val


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
    """Space-bar checkbox multi-select; at least one item required."""
    by_label = {item["label"]: item for item in items}
    while True:
        chosen = questionary.checkbox(label, choices=list(by_label)).ask()
        if chosen is None:
            sys.exit("[eif] aborted")
        if chosen:
            return [by_label[c] for c in chosen]
        print("[eif] select at least one item")


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
        sys.exit("[eif] ERROR: no providers found in providers/")
    provider = _choose("provider", providers)

    matters = _list_matters(provider, repo_root)
    if not matters:
        sys.exit(f"[eif] ERROR: no matters found for provider '{provider}'")
    matter_name = _choose("matter", matters)

    matter_path = repo_root / "matters" / matter_name / provider
    envs = _list_envs(matter_path)
    if not envs:
        sys.exit(f"[eif] ERROR: no environment files found in {matter_path.relative_to(repo_root)}")
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
    print(f"[eif] created   {path.relative_to(cwd)}")


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
    print(f"[eif] rendered  → {output_file}")

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
    print(f"[eif] snapshot  → .history/{env}/{ts}/main.tf")

    # Remote snapshot — if backend configured
    backend = account_config.get("backend")
    if backend:
        provider       = account_config["provider"]
        remote_prefix  = f"eif/{matter_name}/{env}/history/{ts}"
        try:
            _upload_snapshot(provider, backend, account_config, remote_prefix, local_dir)
            print(f"[eif] uploaded  → remote:{remote_prefix}/")
        except Exception as exc:
            print(f"[eif] WARNING: remote snapshot upload failed — {exc}")

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
        sys.exit(f"[eif] ERROR: snapshot main.tf not found at {src}")
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, output_dir / "main.tf")
    print(f"[eif] restored  → {output_dir}/main.tf  (snapshot {snapshot['timestamp']})")


# ── Terraform runner ───────────────────────────────────────────────────────────

def _tf(cmd: list[str], output_dir: Path) -> int:
    """Run a terraform subcommand in output_dir, streaming output."""
    full_cmd = ["terraform", f"-chdir={output_dir}"] + cmd
    print(f"[eif] running   {' '.join(full_cmd)}")
    return subprocess.run(full_cmd).returncode


# ── Commands (render / upgrade) ───────────────────────────────────────────────

def cmd_render(args: list[str]) -> None:
    matter_path, env = _resolve_matter_and_env(args)
    output_dir, _, _, _, _ = _do_render(matter_path, env)
    print(f"[eif] deploy    → terraform -chdir={output_dir} init")
    print(f"[eif]             terraform -chdir={output_dir} apply")


def cmd_upgrade(args: list[str]) -> None:
    matter_path, env = _resolve_matter_and_env(args)
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


# ── Commands (plan / apply / destroy / rollback) ───────────────────────────────

def cmd_plan(args: list[str]) -> None:
    matter_path, env = _resolve_matter_and_env(args)
    output_dir, _, _, _, _ = _do_render(matter_path, env)
    rc = _tf(["init", "-input=false"], output_dir)
    if rc != 0:
        sys.exit(rc)
    sys.exit(_tf(["plan", "-input=false"], output_dir))


def cmd_apply(args: list[str]) -> None:
    matter_path, env = _resolve_matter_and_env(args)
    output_dir, account_config, _, _, _ = _do_render(matter_path, env)
    matter_name = matter_path.parent.name

    rc = _tf(["init", "-input=false"], output_dir)
    if rc != 0:
        sys.exit(rc)

    rc = _tf(["apply", "-input=false"], output_dir)
    if rc != 0:
        sys.exit(rc)

    _take_snapshot(output_dir, matter_path, matter_name, env, account_config)


def cmd_destroy(args: list[str]) -> None:
    matter_path, env = _resolve_matter_and_env(args)
    output_dir = matter_path / ".rendered" / env
    if not (output_dir / "main.tf").exists():
        sys.exit(
            f"[eif] ERROR: no rendered config at {output_dir} — run 'eif render' first"
        )
    sys.exit(_tf(["destroy", "-input=false"], output_dir))


def cmd_rollback(args: list[str]) -> None:
    matter_path, env = _resolve_matter_and_env(args)
    output_dir = matter_path / ".rendered" / env

    snapshots = _list_snapshots(matter_path, env)
    if not snapshots:
        sys.exit(
            f"[eif] ERROR: no snapshots found in .history/{env}/\n"
            "       Run 'eif apply' at least once to create a snapshot."
        )

    choices   = [s["timestamp"] for s in snapshots]
    chosen_ts = _choose("snapshot to restore", choices)
    snapshot  = next(s for s in snapshots if s["timestamp"] == chosen_ts)

    _restore_snapshot(snapshot, output_dir)

    if not _confirm("run terraform apply with restored config?", default=True):
        print("[eif] restored main.tf — run 'terraform apply' manually when ready")
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
            "[eif] ERROR: no 'backend' key in accounts.json for this account.\n"
            "       Add a 'backend' object — see accounts.example.json."
        )

    provider = account_config["provider"]
    print(f"[eif] bootstrapping {provider} remote backend...")

    if provider == "aws":
        _init_backend_aws(backend, account_config)
    elif provider == "azure":
        _init_backend_azure(backend, account_config)
    elif provider == "gcp":
        _init_backend_gcp(backend, account_config)
    else:
        sys.exit(f"[eif] ERROR: no backend bootstrap support for provider '{provider}'")

    print("[eif] backend ready — run 'eif apply' to deploy")


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

    print(f"[eif] S3 bucket '{bucket}' created with versioning enabled")

    if dynamo:
        subprocess.run([
            "aws", "dynamodb", "create-table",
            "--table-name", dynamo,
            "--attribute-definitions", "AttributeName=LockID,AttributeType=S",
            "--key-schema", "AttributeName=LockID,KeyType=HASH",
            "--billing-mode", "PAY_PER_REQUEST",
            "--region", region,
        ], check=True)
        print(f"[eif] DynamoDB table '{dynamo}' created for state locking")


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
    print(f"[eif] Azure storage '{storage}' / container '{container}' ready")


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
    print(f"[eif] GCS bucket 'gs://{bucket}' created with versioning enabled")


def cmd_init_account(args: list[str]) -> None:  # noqa: ARG001
    repo_root     = find_repo_root(Path.cwd())
    accounts_file = repo_root / "accounts.json"

    with accounts_file.open() as fh:
        accounts = json.load(fh)

    providers = _detect_providers(repo_root)
    provider  = _choose("provider", providers)
    env_name  = _ask("account key (e.g. dev, prod, azure-dev)")

    if env_name in accounts:
        sys.exit(f"[eif] ERROR: account '{env_name}' already exists in accounts.json")

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
    print(f"[eif] added     accounts.json → '{env_name}'")

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
        sys.exit("[eif] ERROR: no providers found in providers/")

    if len(args) > 1:
        provider = args[1]
        if provider not in providers:
            sys.exit(f"[eif] ERROR: unknown provider '{provider}'. Available: {providers}")
    else:
        provider = _choose("provider", providers)

    if len(args) > 2:
        cat = args[2]
    else:
        categories = ATOM_CATEGORIES + ["other"]
        cat = _choose("category", categories)
        if cat == "other":
            cat = _ask("category name")

    non_interactive = len(args) >= 3

    atom_dir = repo_root / "atoms" / provider / cat / name
    existing = latest_version(atom_dir)

    if existing:
        next_ver = f"v{int(existing[1:]) + 1}"
        if non_interactive:
            print(f"[eif] {atom_dir.relative_to(cwd)} — latest: {existing}, creating {next_ver}")
        else:
            print(f"\n[eif] {atom_dir.relative_to(cwd)} — latest: {existing}")
            if not _confirm(f"create {next_ver}?"):
                sys.exit("[eif] aborted")
        new_ver = next_ver
    else:
        print(f"[eif] {atom_dir.relative_to(cwd)} — no existing versions, creating v1")
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


def cmd_new_molecule(args: list[str]) -> None:
    repo_root = find_repo_root(Path.cwd())
    cwd = Path.cwd()

    name      = args[0] if len(args) > 0 else _ask("name")
    providers = _detect_providers(repo_root)
    if not providers:
        sys.exit("[eif] ERROR: no providers found in providers/")

    if len(args) > 1:
        provider = args[1]
        if provider not in providers:
            sys.exit(f"[eif] ERROR: unknown provider '{provider}'. Available: {providers}")
    else:
        provider = _choose("provider", providers)

    mol_dir  = repo_root / "molecules" / provider / name
    existing = latest_version(mol_dir)
    non_interactive = len(args) >= 3

    if existing:
        next_ver = f"v{int(existing[1:]) + 1}"
        if non_interactive:
            print(f"[eif] {mol_dir.relative_to(cwd)} — latest: {existing}, creating {next_ver}")
        else:
            print(f"\n[eif] {mol_dir.relative_to(cwd)} — latest: {existing}")
            if not _confirm(f"create {next_ver}?"):
                sys.exit("[eif] aborted")
        new_ver = next_ver
    else:
        print(f"[eif] {mol_dir.relative_to(cwd)} — no existing versions, creating v1")
        new_ver = "v1"

    # Atom selection
    all_atoms = _list_atoms(provider, repo_root)
    selected_atoms: list[dict] = []
    if len(args) > 2:
        atom_map = {f"{a['category']}/{a['name']}": a for a in all_atoms}
        for key in (x.strip() for x in args[2].split(",") if x.strip()):
            if key not in atom_map:
                sys.exit(f"[eif] ERROR: atom '{key}' not found. Available: {list(atom_map)}")
            selected_atoms.append(atom_map[key])
    elif all_atoms:
        print()
        selected_atoms = _multiselect("atoms to include", all_atoms)
    else:
        print(f"[eif] no atoms found for {provider} — scaffolding empty molecule")

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


def cmd_new_matter(args: list[str]) -> None:
    repo_root = find_repo_root(Path.cwd())
    cwd = Path.cwd()

    name      = args[0] if len(args) > 0 else _ask("name")
    providers = _detect_providers(repo_root)
    if not providers:
        sys.exit("[eif] ERROR: no providers found in providers/")

    if len(args) > 1:
        provider = args[1]
        if provider not in providers:
            sys.exit(f"[eif] ERROR: unknown provider '{provider}'. Available: {providers}")
    else:
        provider = _choose("provider", providers)

    out = repo_root / "matters" / name / provider
    if out.exists():
        sys.exit(f"[eif] ERROR: {out.relative_to(cwd)} already exists")

    # Molecule selection
    all_mols = _list_molecules(provider, repo_root)
    selected_mols: list[dict] = []
    if len(args) > 2:
        mol_map = {m["name"]: m for m in all_mols}
        for mol_name in (x.strip() for x in args[2].split(",") if x.strip()):
            if mol_name not in mol_map:
                sys.exit(f"[eif] ERROR: molecule '{mol_name}' not found. Available: {list(mol_map)}")
            selected_mols.append(mol_map[mol_name])
    elif all_mols:
        print()
        selected_mols = _multiselect("molecules to include", all_mols)
    else:
        print(f"[eif] no molecules found for {provider} — scaffolding empty matter")

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
    print(f"[eif]   3. uv run eif apply {render_path} dev")


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


# ── Entry point ───────────────────────────────────────────────────────────────

USAGE = (
    "Usage:\n"
    "  eif render   [<provider> <matter> <env>]\n"
    "  eif upgrade  [<provider> <matter> <env>]\n"
    "  eif plan     [<provider> <matter> <env>]\n"
    "  eif apply    [<provider> <matter> <env>]\n"
    "  eif destroy  [<provider> <matter> <env>]\n"
    "  eif rollback [<provider> <matter> <env>]\n"
    "  eif init backend [<provider> <matter> <env>]\n"
    "  eif add account\n"
    "  eif new atom     [<name> [<provider> [<category>]]]\n"
    "  eif new molecule [<name> [<provider> [<category/atom>,...]]]\n"
    "  eif new matter   [<name> [<provider> [<molecule>,...  ]]]\n"
    "  (all positional args optional — missing ones are prompted interactively)"
)

def main() -> None:
    args = sys.argv[1:]
    if not args:
        sys.exit(USAGE)

    cmd = args[0]
    CMDS = {
        "render":   cmd_render,
        "upgrade":  cmd_upgrade,
        "plan":     cmd_plan,
        "apply":    cmd_apply,
        "destroy":  cmd_destroy,
        "rollback": cmd_rollback,
        "new":      cmd_new,
        "add":      cmd_add,
        "init":     cmd_init,
    }

    if cmd not in CMDS:
        sys.exit(USAGE)

    CMDS[cmd](args[1:])


if __name__ == "__main__":
    main()
