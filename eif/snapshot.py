"""snapshot.py — snapshot helpers."""

import datetime
import json
import shutil
import subprocess
import sys
from pathlib import Path

from .ui import _c, _em, _pfx, _arr


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
