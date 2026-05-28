#!/usr/bin/env python3
"""Build a Krita-importable Python plugin archive."""

from __future__ import annotations

import argparse
import os
import zipfile
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
PYKRITA_DIR = ROOT_DIR / "pykrita"
PLUGIN_NAME = "codex_krita"
PLUGIN_DIR = PYKRITA_DIR / PLUGIN_NAME
DESKTOP_FILE = PYKRITA_DIR / f"{PLUGIN_NAME}.desktop"
DEFAULT_OUTPUT = ROOT_DIR / "dist" / f"{PLUGIN_NAME}.zip"

EXCLUDED_DIRS = {"__pycache__"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def should_include(path: Path) -> bool:
    if any(part in EXCLUDED_DIRS for part in path.parts):
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    return path.is_file()


def iter_plugin_files() -> list[Path]:
    files = [path for path in PLUGIN_DIR.rglob("*") if should_include(path)]
    return sorted(files, key=lambda path: path.as_posix())


def iter_plugin_dirs() -> list[Path]:
    dirs = {PLUGIN_DIR}
    for path in iter_plugin_files():
        dirs.update(parent for parent in path.parents if parent != PYKRITA_DIR and PYKRITA_DIR in parent.parents)
    return sorted(dirs, key=lambda path: path.as_posix())


def validate_sources() -> None:
    if not DESKTOP_FILE.is_file():
        raise SystemExit(f"Missing Krita plugin desktop file: {DESKTOP_FILE}")
    if not (PLUGIN_DIR / "__init__.py").is_file():
        raise SystemExit(f"Missing plugin package: {PLUGIN_DIR}")


def build_archive(output_path: Path) -> None:
    validate_sources()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(DESKTOP_FILE, DESKTOP_FILE.name)
        for path in iter_plugin_dirs():
            archive.writestr(f"{path.relative_to(PYKRITA_DIR).as_posix()}/", "")
        for path in iter_plugin_files():
            archive.write(path, path.relative_to(PYKRITA_DIR).as_posix())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package Codex for Krita as a ZIP importable from Krita."
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Archive path to write. Defaults to {DEFAULT_OUTPUT.relative_to(ROOT_DIR)}.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = args.output
    if not output_path.is_absolute():
        output_path = ROOT_DIR / output_path

    build_archive(output_path)
    size = os.path.getsize(output_path)
    print(f"Built {output_path} ({size} bytes)")
    print("Import it in Krita with Tools > Scripts > Import Python Plugin from File.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
