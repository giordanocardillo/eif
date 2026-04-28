"""init.py — cmd_init_*, cmd_config_*, _init_backend_*, cmd_init_account."""

import json
import subprocess
import sys
from pathlib import Path

import questionary

from .core import find_repo_root
from .render import load_inputs
from .ui import _c, _em, _arr, _ask, _choose, _confirm, _detect_providers, _resolve_matter_and_env

# ── Init-time provider templates (full provider.tf.j2 + backend.tf.j2 content) ──

_PROVIDER_TF: dict[str, str] = {
    "aws": """\
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
  required_version = ">= 1.5"
{% if backend_block %}
{{ backend_block }}
{% endif %}
}

provider "aws" {
  region = "{{ aws_region }}"
{% if assume_role_arn is defined %}
  assume_role {
    role_arn = "{{ assume_role_arn }}"
  }
{% elif profile is defined %}
  profile = "{{ profile }}"
{% endif %}
}
""",
    "azure": """\
terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 3.0"
    }
  }
  required_version = ">= 1.5"
{% if backend_block %}
{{ backend_block }}
{% endif %}
}

provider "azurerm" {
  subscription_id = "{{ subscription_id }}"
  tenant_id       = "{{ tenant_id }}"
{% if client_id is defined %}
  client_id       = "{{ client_id }}"
  client_secret   = "{{ client_secret }}"
{% endif %}
  features {}
}
""",
    "gcp": """\
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
  required_version = ">= 1.5"
{% if backend_block %}
{{ backend_block }}
{% endif %}
}

provider "google" {
  project = "{{ project }}"
  region  = "{{ region }}"
{% if credentials_file is defined %}
  credentials = file("{{ credentials_file }}")
{% endif %}
}
""",
}

_PROVIDER_BACKEND: dict[str, str] = {
    "aws": """\
  backend "s3" {
    bucket  = "{{ backend.bucket }}"
    key     = "{{ backend_key }}"
    region  = "{{ backend.region }}"
    encrypt = true
{% if 'dynamodb_table' in backend %}
    dynamodb_table = "{{ backend.dynamodb_table }}"
{% endif %}
  }
""",
    "azure": """\
  backend "azurerm" {
    resource_group_name  = "{{ backend.resource_group_name }}"
    storage_account_name = "{{ backend.storage_account_name }}"
    container_name       = "{{ backend.container_name }}"
    key                  = "{{ backend_key }}"
  }
""",
    "gcp": """\
  backend "gcs" {
    bucket = "{{ backend.bucket }}"
    prefix = "{{ backend_prefix }}"
  }
""",
}

_ACCOUNTS_ENTRY: dict[str, dict] = {
    "aws": {
        "dev": {
            "provider": "aws",
            "aws_region": "us-east-1",
            "profile": "YOUR_AWS_CLI_PROFILE",
        },
    },
    "azure": {
        "azure-dev": {
            "provider": "azure",
            "subscription_id": "YOUR_SUBSCRIPTION_ID",
            "tenant_id": "YOUR_TENANT_ID",
            "client_id": "YOUR_CLIENT_ID",
            "client_secret": "YOUR_CLIENT_SECRET",
        },
    },
    "gcp": {
        "gcp-dev": {
            "provider": "gcp",
            "project": "YOUR_PROJECT_ID",
            "region": "us-central1",
            "credentials_file": "/path/to/service-account.json",
        },
    },
}

_GITIGNORE_CONTENT = """\
# eif
accounts.json
eif.secure.json
eif_packages/
.rendered/
.history/
"""


# ── Backend bootstrap ──────────────────────────────────────────────────────────

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


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_config_backend(args: list[str]) -> None:
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


def cmd_init_project(args: list[str]) -> None:
    if args and not args[0].startswith("-"):
        target = Path(args[0]).resolve()
        target.mkdir(parents=True, exist_ok=True)
        cwd = target
    else:
        cwd = Path.cwd()

    # Detect if already inside an eif project
    probe = cwd
    while probe != probe.parent:
        if (probe / "accounts.json").exists() or (probe / "eif.project.json").exists():
            sys.exit(f"❌  ERROR: already inside an eif project at {probe}")
        probe = probe.parent

    print(f"\n{_em('◈')} {_c('eif init', 'bgreen', 'bold')} — scaffold a new project\n")

    # Provider selection (none pre-selected)
    while True:
        selected = questionary.checkbox("cloud providers to include", choices=["aws", "azure", "gcp"]).ask()
        if selected is None:
            sys.exit("aborted")
        if selected:
            break
        print("  ⚠️  select at least one provider")

    # providers/ — write tf.j2 files for each selected provider
    for prov in selected:
        pdir = cwd / "providers" / prov
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "provider.tf.j2").write_text(_PROVIDER_TF[prov])
        (pdir / "backend.tf.j2").write_text(_PROVIDER_BACKEND[prov])
        print(f"{_em('✨')}created   {_arr()} {_c(f'providers/{prov}/', 'cyan')}")

    # accounts.json — merge entries for selected providers
    accounts: dict = {}
    for prov in selected:
        accounts.update(_ACCOUNTS_ENTRY[prov])
    accounts_file = cwd / "accounts.json"
    accounts_file.write_text(json.dumps(accounts, indent=2) + "\n")
    print(f"{_em('✨')}created   {_arr()} {_c('accounts.json', 'cyan')}  {_c('← fill in your credentials', 'dim')}")

    # eif.project.json
    project_file = cwd / "eif.project.json"
    _OFFICIAL_REGISTRY = "https://github.com/giordanocardillo/eif-library"
    add_official = _confirm(f"add official registry ({_OFFICIAL_REGISTRY})?", default=True)
    registries = []
    if add_official:
        registries.append({"name": "official", "type": "github", "url": _OFFICIAL_REGISTRY, "priority": 0})
    project_data = {"name": cwd.name, "registries": registries}
    project_file.write_text(json.dumps(project_data, indent=2) + "\n")
    print(f"{_em('✨')}created   {_arr()} {_c('eif.project.json', 'cyan')}")

    # .gitignore
    gi = cwd / ".gitignore"
    if gi.exists():
        existing = gi.read_text()
        if "eif_packages" not in existing:
            gi.write_text(existing.rstrip() + "\n" + _GITIGNORE_CONTENT)
            print(f"{_em('✨')}updated   {_arr()} {_c('.gitignore', 'cyan')}")
    else:
        gi.write_text(_GITIGNORE_CONTENT)
        print(f"{_em('✨')}created   {_arr()} {_c('.gitignore', 'cyan')}")

    # matters/
    (cwd / "matters").mkdir(exist_ok=True)
    print(f"{_em('✨')}created   {_arr()} {_c('matters/', 'cyan')}")

    print(f"\n{_em('✅')} {_c('project ready', 'bgreen', 'bold')}\n")
    print(f"  {_c('next steps:', 'dim')}")
    print(f"  {_c('1.', 'dim')} edit {_c('accounts.json', 'cyan')} with your cloud credentials")
    print(f"  {_c('2.', 'dim')} run  {_c('eif package install <pvd>/<name>', 'bgreen')} to fetch packages")
    print(f"  {_c('3.', 'dim')} run  {_c('eif new matter', 'bgreen')} to scaffold your first matter\n")


def cmd_config(args: list[str]) -> None:
    SUB = {"backend": cmd_config_backend}
    if not args or args[0] not in SUB:
        sys.exit("Usage:\n  eif config backend [<provider> <matter> <env>]  Bootstrap remote state bucket")
    SUB[args[0]](args[1:])


def cmd_init(args: list[str]) -> None:
    cmd_init_project(args)
