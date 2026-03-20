#!/usr/bin/env python3
"""
EIF — Elemental Infrastructure Framework
CLI renderer: Jinja2 template + composition.json → main.tf

Usage:
    python eif.py <matter-dir>

Example:
    python eif.py matter/three-tier-app
"""

import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


def render(matter_dir: str) -> None:
    matter_path = Path(matter_dir).resolve()

    composition_file = matter_path / "composition.json"
    template_file    = matter_path / "main.tf.j2"
    output_file      = matter_path / "main.tf"

    if not composition_file.exists():
        sys.exit(f"[eif] ERROR: composition.json not found in {matter_path}")
    if not template_file.exists():
        sys.exit(f"[eif] ERROR: main.tf.j2 not found in {matter_path}")

    with composition_file.open() as fh:
        composition = json.load(fh)

    env = Environment(
        loader=FileSystemLoader(str(matter_path)),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("main.tf.j2")
    rendered = template.render(**composition)

    output_file.write_text(rendered)
    print(f"[eif] rendered → {output_file}")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: eif <matter-dir>")
    render(sys.argv[1])


if __name__ == "__main__":
    main()
