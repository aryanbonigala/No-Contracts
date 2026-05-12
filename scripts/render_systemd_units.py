#!/usr/bin/env python3
"""Render systemd unit templates with concrete paths (no install, no secrets printed)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PLACEHOLDERS = ("__USER__", "__WORKING_DIRECTORY__", "__ENVIRONMENT_FILE__", "__PYTHON_PATH__")


def _render_text(text: str, mapping: dict[str, str]) -> tuple[str, list[str]]:
    warnings: list[str] = []
    out = text
    for placeholder, val in mapping.items():
        out = out.replace(placeholder, val)
    for ph in PLACEHOLDERS:
        if ph in out:
            warnings.append(f"unreplaced_placeholder:{ph}")
    return out, warnings


def main() -> None:
    p = argparse.ArgumentParser(description="Render deploy/digitalocean systemd templates into build/systemd/")
    p.add_argument("--template-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--user", required=True, dest="user")
    p.add_argument("--working-directory", required=True, dest="working_directory")
    p.add_argument("--environment-file", required=True, dest="environment_file")
    p.add_argument("--python-path", required=True, dest="python_path")
    args = p.parse_args()

    warnings: list[str] = []
    files_rendered: list[str] = []

    mapping = {
        "__USER__": args.user,
        "__WORKING_DIRECTORY__": args.working_directory,
        "__ENVIRONMENT_FILE__": args.environment_file,
        "__PYTHON_PATH__": args.python_path,
    }

    # Safety: refuse obvious secret material in values (lightweight guardrail)
    joined = "\n".join(mapping.values()).lower()
    if "password=" in joined or "-----begin" in joined:
        payload = {
            "success": False,
            "template_dir": str(args.template_dir),
            "output_dir": str(args.output_dir),
            "files_rendered": [],
            "warnings": ["refused: possible secret in substitution values"],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        raise SystemExit(1)

    if not args.template_dir.is_dir():
        payload = {
            "success": False,
            "template_dir": str(args.template_dir),
            "output_dir": str(args.output_dir),
            "files_rendered": [],
            "warnings": [f"template_dir_not_found:{args.template_dir}"],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        raise SystemExit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    for pattern in ("*.service", "*.timer"):
        for path in sorted(args.template_dir.glob(pattern)):
            raw = path.read_text(encoding="utf-8")
            rendered, w = _render_text(raw, mapping)
            warnings.extend(w)
            out_path = args.output_dir / path.name
            out_path.write_text(rendered, encoding="utf-8")
            files_rendered.append(path.name)

    payload = {
        "success": True,
        "template_dir": str(args.template_dir.resolve()),
        "output_dir": str(args.output_dir.resolve()),
        "files_rendered": sorted(files_rendered),
        "warnings": warnings,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except BrokenPipeError:
        try:
            sys.stdout.close()
        except Exception:
            pass
        raise SystemExit(0)
