#!/usr/bin/env python3
"""Load every generated catalog with the installed Codex CLI, without API calls."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import sync_model_catalog as sync


def verify_catalog(cli: sync.BinaryInfo, path: Path, home: Path, timeout: float) -> int:
    expected = sync.validate_catalog(json.loads(path.read_text(encoding="utf-8")))
    configuration = "model_catalog_json=" + json.dumps(path.resolve().as_posix())
    completed = subprocess.run(
        sync.command_for_path(cli.path, "-c", configuration, "debug", "models"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "CODEX_HOME": str(home)},
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise sync.SyncError(f"{path}: {completed.stderr.strip()}")
    loaded = sync.validate_catalog(json.loads(completed.stdout))
    expected_models = {model["slug"]: model for model in expected["models"]}
    loaded_models = {model["slug"]: model for model in loaded["models"]}
    if set(loaded_models) != set(expected_models):
        raise sync.SyncError(f"{path}: CLI model IDs differ from the requested catalog")
    # Newer CLI releases omit legacy compatibility flags when serializing models.
    for slug, expected_model in expected_models.items():
        for field in (
            "display_name",
            "description",
            "context_window",
            "input_modalities",
            "default_reasoning_level",
            "supported_reasoning_levels",
        ):
            if loaded_models[slug].get(field) != expected_model.get(field):
                raise sync.SyncError(f"{path}: CLI changed {slug}.{field}")
    return len(expected_models)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli-codex", type=Path, help="explicit Codex executable or shim")
    parser.add_argument("--timeout", type=float, default=30.0)
    arguments = parser.parse_args()
    if arguments.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    try:
        cli = sync.discover_cli(arguments.cli_codex, arguments.timeout)
        if cli is None:
            raise sync.SyncError("no runnable Codex CLI was found")
        paths = [sync.PROJECT_DIR / "model_catalog.json", *sync.build_route_catalogs()]
        print(f"Codex CLI {cli.version}: verifying {len(paths)} catalogs", flush=True)
        # A fresh CODEX_HOME avoids reading credentials or changing user configuration.
        with tempfile.TemporaryDirectory(prefix="codex-catalog-verification-") as directory:
            for path in paths:
                model_count = verify_catalog(cli, path, Path(directory), arguments.timeout)
                print(
                    f"[ok] {path.relative_to(sync.PROJECT_DIR).as_posix()}: "
                    f"{model_count} models",
                    flush=True,
                )
        return 0
    except (sync.SyncError, OSError, ValueError, subprocess.SubprocessError) as exception:
        print(f"error: {exception}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
