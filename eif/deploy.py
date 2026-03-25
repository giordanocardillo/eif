"""deploy.py — _tf, _scan, cmd_plan, cmd_apply, cmd_scan, cmd_destroy, cmd_rollback."""

import shutil
import subprocess
import sys
from pathlib import Path

from .ui import _c, _em, _arr, _confirm, _choose, _resolve_matter_and_env
from .render import _do_render
from .snapshot import _take_snapshot, _list_snapshots, _restore_snapshot


def _tf(cmd: list[str], output_dir: Path) -> int:
    """Run a terraform subcommand in output_dir, streaming output."""
    full_cmd = ["terraform", f"-chdir={output_dir}"] + cmd
    print(f"{_em('⚙️')} {_c(' '.join(full_cmd), 'dim')}")
    return subprocess.run(full_cmd).returncode


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
