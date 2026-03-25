"""render.py — render helpers + cmd_render + resolve_sources + load_inputs."""

import json
import os
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .core import find_repo_root, load_config, latest_version, _packages_dir
from .packages import _check_outdated
from .ui import _c, _em, _pfx, _arr, _resolve_matter_and_env


def resolve_sources(molecules: list, repo_root: Path, output_dir: Path) -> dict:
    """Return {mol_name: relative_tf_path} for each molecule.

    Resolution order:
      1. eif_packages/molecules/<provider>/<name>/<version>/
      2. local molecules/<provider>/<name>/  (latest local version, for authoring)
      3. fail with install message
    """
    result = {}
    for mol in molecules:
        source  = mol["source"]   # "aws/db"
        version = mol["version"]  # "1.2.0"
        provider, name = source.split("/", 1)

        # 1. package store
        package_path = repo_root / "eif_packages" / "molecules" / provider / name / version
        if package_path.is_dir():
            result[mol["name"]] = os.path.relpath(package_path.resolve(), output_dir)
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
            f"    run: eif package install"
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
    # Strip any {{ provider_block }} the template may have included manually,
    # then prepend the provider block automatically so templates don't need it.
    rendered_clean = rendered.replace(provider_block, "").lstrip("\n")
    output_file.write_text(header + provider_block + "\n" + rendered_clean)
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
                print(f"  {_c('run: eif package update', 'dim')}")
        except Exception:
            pass  # no network — skip silently

    return output_dir, account_config, composition, env_config, repo_root


def cmd_render(args: list[str]) -> None:
    matter_path, env = _resolve_matter_and_env(args)
    output_dir, _, _, _, _ = _do_render(matter_path, env)
    print(f"{_pfx()} {_em('💡')}deploy    {_arr()} {_c(f'terraform -chdir={output_dir} init', 'dim')}")
    print(f"{_pfx()}             {_c(f'terraform -chdir={output_dir} apply', 'dim')}")
