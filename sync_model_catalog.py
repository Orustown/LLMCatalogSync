#!/usr/bin/env python3
"""Synchronize Codex model catalogs from local and upstream sources."""

from __future__ import annotations

import argparse
import copy
import dataclasses
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any, Iterable
import urllib.error
import urllib.request


PROJECT_DIR = Path(__file__).resolve().parent
GITHUB_RAW_ROOT = "https://raw.githubusercontent.com/openai/codex"
MODELS_PATH = "codex-rs/models-manager/models.json"
PRICING_METADATA_PATH = PROJECT_DIR / "pricing_metadata.json"
THIRD_PARTY_DIR = PROJECT_DIR / "third_party"
ROUTES_DIR = THIRD_PARTY_DIR / "routes"
SOURCE_NAMES = (
    "cli-bundled",
    "cli-github-tag",
    "app-bundled",
    "app-github-tag",
    "github-main",
)
THIRD_PARTY_PRESETS = {
    "claude": THIRD_PARTY_DIR / "claude.json",
    "grok": THIRD_PARTY_DIR / "grok.json",
    "gemini": THIRD_PARTY_DIR / "gemini.json",
    "muse": THIRD_PARTY_DIR / "muse.json",
    "qwen": THIRD_PARTY_DIR / "qwen.json",
    "hunyuan": THIRD_PARTY_DIR / "hunyuan.json",
    "deepseek": THIRD_PARTY_DIR / "deepseek.json",
    "glm": THIRD_PARTY_DIR / "glm.json",
    "kimi": THIRD_PARTY_DIR / "kimi.json",
    "minimax": THIRD_PARTY_DIR / "minimax.json",
    "mimo": THIRD_PARTY_DIR / "mimo.json",
}
CODEX_SUPPORTED_INPUT_MODALITIES = frozenset({"text", "image", "audio"})
ROUTE_MANIFESTS = {
    name: ROUTES_DIR / name / "route.json"
    for name in ("cc-switch", "litellm", "openrouter")
}
ARCHIVE_SOURCE_INFO = {
    "cli-bundled": ("cli", "bundled"),
    "cli-github-tag": ("cli", "github-tag"),
    "app-bundled": ("app", "bundled"),
    "app-github-tag": ("app", "github-tag"),
}
VERSION_RE = re.compile(
    r"\b(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?)\b"
)


class SyncError(RuntimeError):
    """An expected synchronization error with a user-facing message."""


@dataclasses.dataclass(frozen=True)
class BinaryInfo:
    path: Path
    label: str
    version: str


@dataclasses.dataclass
class SourceResult:
    name: str
    status: str
    origin: str
    version: str | None = None
    catalog: dict[str, Any] | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok" and self.catalog is not None


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Download Codex model catalogs, keep versioned archives, and merge "
            "project-owned model overrides into model_catalog.json."
        )
    )
    parser.add_argument(
        "--base",
        choices=("auto", *SOURCE_NAMES),
        default="auto",
        help=(
            "source promoted to model_catalog.json (default: auto, preferring "
            "the Codex App bundled catalog, then the PATH CLI bundled catalog)"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_DIR / "model_catalog.json",
        help="generated catalog path",
    )
    parser.add_argument(
        "--overrides",
        type=Path,
        default=PROJECT_DIR / "model_overrides.json",
        help="model additions and patches applied by slug",
    )
    parser.add_argument(
        "--preset",
        action="append",
        choices=(*THIRD_PARTY_PRESETS, "all"),
        default=[],
        help=(
            "merge a maintained third-party catalog; repeat for multiple providers "
            "or use 'all'"
        ),
    )
    parser.add_argument(
        "--archive-dir",
        "--sources-dir",
        dest="archive_dir",
        type=Path,
        default=PROJECT_DIR / "catalogs",
        help=(
            "versioned catalog archive directory (default: ./catalogs; "
            "--sources-dir is a deprecated alias)"
        ),
    )
    parser.add_argument(
        "--cli-codex",
        type=Path,
        help="explicit Codex CLI executable or shim",
    )
    parser.add_argument(
        "--app-codex",
        type=Path,
        help="explicit Codex App bundled executable",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=45.0,
        help="timeout in seconds for each command or download (default: 45)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="skip GitHub sources and use local bundled catalogs only",
    )
    parser.add_argument(
        "--no-overrides",
        action="store_true",
        help="skip model_overrides.json (selected third-party presets still apply)",
    )
    parser.add_argument(
        "--no-pricing-enrichment",
        action="store_true",
        help=(
            "skip rewriting model descriptions with provider, context, pricing, "
            "and modality metadata from pricing_metadata.json"
        ),
    )
    parser.add_argument(
        "--no-routes",
        action="store_true",
        help="skip generated third_party/routes model catalogs",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write files; fail if model_catalog.json is not current",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="fail when any available source errors instead of using partial results",
    )
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero")
    return args


def command_for_path(path: Path, *args: str) -> list[str]:
    suffix = path.suffix.lower()
    if os.name == "nt" and suffix in {".cmd", ".bat"}:
        command_shell = os.environ.get("COMSPEC", "cmd.exe")
        return [command_shell, "/d", "/c", str(path), *args]
    if os.name == "nt" and suffix == ".ps1":
        powershell = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
        if not powershell:
            raise SyncError(f"PowerShell is required to run {path}")
        return [powershell, "-NoProfile", "-File", str(path), *args]
    return [str(path), *args]


def run_binary(path: Path, args: Iterable[str], timeout: float) -> str:
    command = command_for_path(path, *args)
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="strict",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise SyncError(f"could not run {path}: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        if len(detail) > 500:
            detail = detail[:500] + "..."
        raise SyncError(
            f"{path.name} exited with code {completed.returncode}"
            + (f": {detail}" if detail else "")
        )
    return completed.stdout


def extract_version(text: str) -> str:
    match = VERSION_RE.search(text)
    if not match:
        raise SyncError(f"could not parse a semantic version from {text.strip()!r}")
    return match.group(1)


def inspect_binary(path: Path, label: str, timeout: float) -> BinaryInfo:
    if not path.exists():
        raise SyncError(f"{label} does not exist: {path}")
    version = extract_version(run_binary(path, ("--version",), timeout))
    return BinaryInfo(path=path.resolve(), label=label, version=version)


def discover_cli(explicit: Path | None, timeout: float) -> BinaryInfo | None:
    if explicit is not None:
        return inspect_binary(explicit.expanduser(), "PATH CLI", timeout)

    # On Windows, codex.exe can be an inaccessible Microsoft Store app alias.
    # Prefer package-manager shims and keep trying when a candidate cannot run.
    names = ("codex.cmd", "codex.bat", "codex.ps1", "codex.exe", "codex")
    failures: list[str] = []
    for name in names:
        resolved = shutil.which(name)
        if resolved:
            try:
                return inspect_binary(Path(resolved), "PATH CLI", timeout)
            except SyncError as exc:
                failures.append(str(exc))
    if failures:
        print(
            "warning: no runnable PATH Codex CLI was found: " + "; ".join(failures),
            file=sys.stderr,
        )
    return None


def discover_app_binary(explicit: Path | None, timeout: float) -> BinaryInfo | None:
    if explicit is not None:
        return inspect_binary(explicit.expanduser(), "Codex App CLI", timeout)

    candidates: list[Path] = []
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            app_bin = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
            if app_bin.is_dir():
                candidates.extend(app_bin.rglob("codex.exe"))
    elif sys.platform == "darwin":
        candidates.extend(
            path
            for path in (
                Path("/Applications/Codex.app/Contents/Resources/codex"),
                Path("/Applications/Codex.app/Contents/MacOS/codex"),
                Path.home()
                / "Applications"
                / "Codex.app"
                / "Contents"
                / "Resources"
                / "codex",
            )
            if path.is_file()
        )

    if not candidates:
        return None
    newest = max(candidates, key=lambda path: path.stat().st_mtime_ns)
    return inspect_binary(newest, "Codex App CLI", timeout)


def validate_catalog(value: Any, *, allow_empty: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SyncError("catalog root must be a JSON object")
    models = value.get("models")
    if not isinstance(models, list):
        raise SyncError("catalog must contain a 'models' array")
    if not models and not allow_empty:
        raise SyncError("catalog 'models' array is empty")

    seen: set[str] = set()
    for index, model in enumerate(models):
        if not isinstance(model, dict):
            raise SyncError(f"models[{index}] must be a JSON object")
        slug = model.get("slug")
        if not isinstance(slug, str) or not slug.strip():
            raise SyncError(f"models[{index}].slug must be a non-empty string")
        display_name = model.get("display_name")
        if display_name is not None and (
            not isinstance(display_name, str) or not display_name.strip()
        ):
            raise SyncError(f"models[{index}].display_name must be a non-empty string")

        reasoning_levels = model.get("supported_reasoning_levels")
        if reasoning_levels is not None:
            if not isinstance(reasoning_levels, list) or not reasoning_levels:
                raise SyncError(
                    f"models[{index}].supported_reasoning_levels must be a non-empty array"
                )
            efforts: list[str] = []
            for level_index, level in enumerate(reasoning_levels):
                if not isinstance(level, dict):
                    raise SyncError(
                        f"models[{index}].supported_reasoning_levels[{level_index}] "
                        "must be a JSON object"
                    )
                effort = level.get("effort")
                if not isinstance(effort, str) or not effort.strip():
                    raise SyncError(
                        f"models[{index}].supported_reasoning_levels[{level_index}] "
                        "effort must be a non-empty string"
                    )
                if effort in efforts:
                    raise SyncError(
                        f"models[{index}] has duplicate reasoning effort: {effort}"
                    )
                efforts.append(effort)
            default_reasoning_level = model.get("default_reasoning_level")
            if default_reasoning_level is not None and (
                not isinstance(default_reasoning_level, str)
                or default_reasoning_level not in efforts
            ):
                raise SyncError(
                    f"models[{index}].default_reasoning_level must be one of "
                    "supported reasoning efforts"
                )

        for boolean_field in (
            "supported_in_api",
            "supports_reasoning_summaries",
            "supports_parallel_tool_calls",
            "supports_image_detail_original",
            "supports_search_tool",
            "use_responses_lite",
        ):
            if boolean_field in model and not isinstance(model[boolean_field], bool):
                raise SyncError(f"models[{index}].{boolean_field} must be a boolean")

        for context_field in ("context_window", "max_context_window"):
            context_value = model.get(context_field)
            if context_value is not None and (
                not isinstance(context_value, int)
                or isinstance(context_value, bool)
                or context_value <= 0
            ):
                raise SyncError(
                    f"models[{index}].{context_field} must be a positive integer"
                )
        context_window = model.get("context_window")
        max_context_window = model.get("max_context_window")
        if (
            isinstance(context_window, int)
            and not isinstance(context_window, bool)
            and isinstance(max_context_window, int)
            and not isinstance(max_context_window, bool)
            and context_window > max_context_window
        ):
            raise SyncError(
                f"models[{index}].context_window cannot exceed max_context_window"
            )

        input_modalities = model.get("input_modalities")
        if input_modalities is not None and (
            not isinstance(input_modalities, list)
            or not input_modalities
            or any(
                not isinstance(modality, str) or not modality.strip()
                for modality in input_modalities
            )
        ):
            raise SyncError(
                f"models[{index}].input_modalities must be a non-empty string array"
            )

        priority = model.get("priority")
        if priority is not None and (
            not isinstance(priority, int)
            or isinstance(priority, bool)
            or priority < 0
        ):
            raise SyncError(f"models[{index}].priority must be a non-negative integer")
        if slug in seen:
            raise SyncError(f"duplicate model slug: {slug}")
        seen.add(slug)
    return value


def parse_catalog_bytes(payload: bytes, origin: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"invalid JSON from {origin}: {exc}") from exc
    return validate_catalog(value)


def catalog_from_binary(binary: BinaryInfo, timeout: float) -> dict[str, Any]:
    stdout = run_binary(binary.path, ("debug", "models", "--bundled"), timeout)
    return parse_catalog_bytes(stdout.encode("utf-8"), binary.label)


def download_catalog(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "codex-model-catalog-sync/1",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SyncError(f"download failed for {url}: {exc}") from exc
    return parse_catalog_bytes(payload, url)


def collect_sources(
    cli: BinaryInfo | None,
    app: BinaryInfo | None,
    *,
    timeout: float,
    offline: bool,
) -> dict[str, SourceResult]:
    results: dict[str, SourceResult] = {}

    def bundled(name: str, binary: BinaryInfo | None) -> None:
        if binary is None:
            results[name] = SourceResult(name, "skipped", "local binary not found")
            return
        try:
            catalog = catalog_from_binary(binary, timeout)
            results[name] = SourceResult(
                name,
                "ok",
                f"{binary.label}: codex debug models --bundled",
                version=binary.version,
                catalog=catalog,
            )
        except SyncError as exc:
            results[name] = SourceResult(
                name,
                "error",
                f"{binary.label}: codex debug models --bundled",
                version=binary.version,
                error=str(exc),
            )

    def github_tag(name: str, binary: BinaryInfo | None) -> None:
        if binary is None:
            results[name] = SourceResult(name, "skipped", "local binary not found")
            return
        url = f"{GITHUB_RAW_ROOT}/rust-v{binary.version}/{MODELS_PATH}"
        if offline:
            results[name] = SourceResult(
                name, "skipped", url, version=binary.version, error="offline mode"
            )
            return
        try:
            catalog = download_catalog(url, timeout)
            results[name] = SourceResult(
                name, "ok", url, version=binary.version, catalog=catalog
            )
        except SyncError as exc:
            results[name] = SourceResult(
                name,
                "error",
                url,
                version=binary.version,
                error=str(exc),
            )

    bundled("cli-bundled", cli)
    github_tag("cli-github-tag", cli)
    bundled("app-bundled", app)
    github_tag("app-github-tag", app)

    main_url = f"{GITHUB_RAW_ROOT}/main/{MODELS_PATH}"
    if offline:
        results["github-main"] = SourceResult(
            "github-main", "skipped", main_url, error="offline mode"
        )
    else:
        try:
            catalog = download_catalog(main_url, timeout)
            results["github-main"] = SourceResult(
                "github-main", "ok", main_url, catalog=catalog
            )
        except SyncError as exc:
            results["github-main"] = SourceResult(
                "github-main", "error", main_url, error=str(exc)
            )
    return results


def choose_base(requested: str, results: dict[str, SourceResult]) -> SourceResult:
    if requested != "auto":
        result = results[requested]
        if not result.ok:
            detail = result.error or result.origin
            raise SyncError(f"selected base source {requested!r} is unavailable: {detail}")
        return result

    for name in (
        "app-bundled",
        "cli-bundled",
        "app-github-tag",
        "cli-github-tag",
        "github-main",
    ):
        if results[name].ok:
            return results[name]
    raise SyncError("no model catalog source succeeded")


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_overrides(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"models": [], "remove_models": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"could not read overrides from {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SyncError("override root must be a JSON object")
    unknown = set(value) - {"metadata", "models", "remove_models"}
    if unknown:
        raise SyncError(f"unknown override keys: {', '.join(sorted(unknown))}")

    metadata = value.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise SyncError("override 'metadata' must be a JSON object")
        for key in ("provider", "verified_on", "upstream_api", "codex_transport"):
            if not isinstance(metadata.get(key), str) or not metadata[key].strip():
                raise SyncError(f"override metadata.{key} must be a non-empty string")
        try:
            dt.date.fromisoformat(metadata["verified_on"])
        except ValueError as exc:
            raise SyncError("override metadata.verified_on must use YYYY-MM-DD") from exc
        sources = metadata.get("sources")
        if not isinstance(sources, list) or not sources or any(
            not isinstance(url, str) or not url.startswith("https://")
            for url in sources
        ):
            raise SyncError(
                "override metadata.sources must be a non-empty array of HTTPS URLs"
            )

    models = value.get("models", [])
    validate_catalog({"models": models}, allow_empty=True)
    removals = value.get("remove_models", [])
    if not isinstance(removals, list) or any(
        not isinstance(slug, str) or not slug for slug in removals
    ):
        raise SyncError("override 'remove_models' must be an array of model slugs")
    if len(removals) != len(set(removals)):
        raise SyncError("override 'remove_models' contains duplicate slugs")
    return {"models": models, "remove_models": removals}


def selected_preset_names(requested: Iterable[str]) -> list[str]:
    requested_set = set(requested)
    if "all" in requested_set:
        return list(THIRD_PARTY_PRESETS)
    return [name for name in THIRD_PARTY_PRESETS if name in requested_set]


def load_route_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"could not read route manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SyncError(f"route manifest root must be a JSON object: {path}")
    if value.get("schema_version") != 1:
        raise SyncError(f"unsupported route manifest schema in {path}")
    if value.get("classification") != "third-party":
        raise SyncError(f"route manifest classification must be 'third-party': {path}")

    for key in ("route", "verified_on", "wire_api", "base_url"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise SyncError(f"route manifest {key} must be a non-empty string: {path}")
    try:
        dt.date.fromisoformat(value["verified_on"])
    except ValueError as exc:
        raise SyncError(f"route verified_on must use YYYY-MM-DD: {path}") from exc

    sources = value.get("sources")
    if not isinstance(sources, list) or not sources or any(
        not isinstance(url, str) or not url.startswith("https://") for url in sources
    ):
        raise SyncError(f"route sources must be non-empty HTTPS URLs: {path}")

    providers = value.get("providers")
    if not isinstance(providers, dict) or not providers:
        raise SyncError(f"route providers must be a non-empty JSON object: {path}")
    for provider, config in providers.items():
        if provider not in THIRD_PARTY_PRESETS or not isinstance(config, dict):
            raise SyncError(f"unsupported route provider {provider!r}: {path}")
        for key in ("official_catalog", "output", "transport"):
            if not isinstance(config.get(key), str) or not config[key].strip():
                raise SyncError(
                    f"route provider {provider}.{key} must be a non-empty string: {path}"
                )
        mappings = config.get("model_mappings")
        if not isinstance(mappings, dict) or not mappings or any(
            not isinstance(source, str)
            or not source
            or not isinstance(target, str)
            or not target
            for source, target in mappings.items()
        ):
            raise SyncError(
                f"route provider {provider}.model_mappings must map model slugs: {path}"
            )
        if len(set(mappings.values())) != len(mappings):
            raise SyncError(f"duplicate route model slug for {provider}: {path}")
        patches = config.get("model_patches", {})
        if not isinstance(patches, dict) or any(
            source not in mappings or not isinstance(patch, dict)
            for source, patch in patches.items()
        ):
            raise SyncError(
                f"route provider {provider}.model_patches must match source slugs: {path}"
            )
        suffix = config.get("display_suffix", "")
        if not isinstance(suffix, str):
            raise SyncError(
                f"route provider {provider}.display_suffix must be a string: {path}"
            )
    return value


def build_route_catalogs(
    manifests: dict[str, Path] | None = None,
) -> dict[Path, dict[str, Any]]:
    manifests = ROUTE_MANIFESTS if manifests is None else manifests
    outputs: dict[Path, dict[str, Any]] = {}
    routes_root = ROUTES_DIR.resolve()
    third_party_root = THIRD_PARTY_DIR.resolve()

    for expected_route, manifest_path in manifests.items():
        manifest = load_route_manifest(manifest_path)
        if manifest["route"] != expected_route:
            raise SyncError(
                f"route manifest name mismatch: expected {expected_route!r}, "
                f"got {manifest['route']!r}"
            )

        for provider, config in manifest["providers"].items():
            official_path = (manifest_path.parent / config["official_catalog"]).resolve()
            if not official_path.is_relative_to(third_party_root):
                raise SyncError(f"official catalog escapes third_party: {official_path}")
            expected_official = THIRD_PARTY_PRESETS[provider].resolve()
            if official_path != expected_official:
                raise SyncError(
                    f"route {expected_route}.{provider} must use {expected_official}"
                )

            try:
                official_document = json.loads(
                    official_path.read_text(encoding="utf-8-sig")
                )
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise SyncError(
                    f"could not read official vendor catalog {official_path}: {exc}"
                ) from exc
            metadata = official_document.get("metadata", {})
            expected_classification = "third-party" if provider == "muse" else "official"
            if (
                not isinstance(metadata, dict)
                or metadata.get("classification") != expected_classification
                or metadata.get("catalog_kind") != "vendor-baseline"
                or (
                    provider == "muse"
                    and metadata.get("model_id_scope") != "route-specific"
                )
            ):
                raise SyncError(
                    f"vendor baseline metadata is missing from {official_path}"
                )

            official = load_overrides(official_path)
            by_slug = {model["slug"]: model for model in official["models"]}
            models: list[dict[str, Any]] = []
            suffix = config.get("display_suffix", "")
            patches = config.get("model_patches", {})
            for source_slug, route_slug in config["model_mappings"].items():
                if source_slug not in by_slug:
                    raise SyncError(
                        f"route {expected_route}.{provider} references unknown model "
                        f"{source_slug!r}"
                    )
                model = copy.deepcopy(by_slug[source_slug])
                model["slug"] = route_slug
                if suffix:
                    model["display_name"] = f"{model['display_name']} {suffix}"
                if source_slug in patches:
                    model = deep_merge(model, patches[source_slug])
                models.append(model)

            catalog, _ = normalize_catalog_compatibility(
                validate_catalog({"models": models})
            )
            catalog, _ = enrich_catalog_descriptions(catalog)
            output_path = (manifest_path.parent / config["output"]).resolve()
            if not output_path.is_relative_to(routes_root):
                raise SyncError(f"route catalog output escapes routes directory: {output_path}")
            if output_path in outputs:
                raise SyncError(f"duplicate route catalog output: {output_path}")
            outputs[output_path] = catalog
    return outputs


def combine_overrides(documents: Iterable[dict[str, Any]]) -> dict[str, Any]:
    combined: dict[str, Any] = {"models": [], "remove_models": []}
    positions: dict[str, int] = {}
    removed: set[str] = set()

    for document in documents:
        for patch in document["models"]:
            slug = patch["slug"]
            if slug in positions:
                index = positions[slug]
                combined["models"][index] = deep_merge(
                    combined["models"][index], patch
                )
            else:
                positions[slug] = len(combined["models"])
                combined["models"].append(copy.deepcopy(patch))

        for slug in document["remove_models"]:
            if slug not in removed:
                combined["remove_models"].append(slug)
                removed.add(slug)

    validate_catalog({"models": combined["models"]}, allow_empty=True)
    return combined


def merge_overrides(
    catalog: dict[str, Any], overrides: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    merged = copy.deepcopy(catalog)
    models: list[dict[str, Any]] = merged["models"]
    positions = {model["slug"]: index for index, model in enumerate(models)}
    changes: dict[str, list[str]] = {"added": [], "updated": [], "removed": []}

    for patch in overrides["models"]:
        slug = patch["slug"]
        if slug in positions:
            index = positions[slug]
            updated = deep_merge(models[index], patch)
            if updated != models[index]:
                models[index] = updated
                changes["updated"].append(slug)
        else:
            positions[slug] = len(models)
            models.append(copy.deepcopy(patch))
            changes["added"].append(slug)

    removals = set(overrides["remove_models"])
    if removals:
        changes["removed"] = [model["slug"] for model in models if model["slug"] in removals]
        merged["models"] = [model for model in models if model["slug"] not in removals]

    validate_catalog(merged)
    return merged, changes


def normalize_catalog_compatibility(
    catalog: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Fill fields required by older Codex CLI releases.

    Codex App / newer upstream catalogs may omit
    ``supports_reasoning_summaries`` and ``supports_parallel_tool_calls``.
    Codex CLI 0.144.x still requires both fields when loading
    ``model_catalog_json``, so generated catalogs must keep them present for
    every model.
    """
    normalized = copy.deepcopy(catalog)
    fixed_slugs: list[str] = []
    for model in normalized["models"]:
        model_was_fixed = False
        input_modalities = model.get("input_modalities")
        if isinstance(input_modalities, list):
            supported_modalities = [
                modality
                for modality in input_modalities
                if modality in CODEX_SUPPORTED_INPUT_MODALITIES
            ]
            if supported_modalities != input_modalities:
                model["input_modalities"] = supported_modalities or ["text"]
                model_was_fixed = True
        if "supports_reasoning_summaries" not in model:
            # CLI OpenAI models use true; third-party presets set this
            # explicitly. Missing values almost always come from App/upstream
            # OpenAI catalogs.
            model["supports_reasoning_summaries"] = True
            model_was_fixed = True
        if "supports_parallel_tool_calls" not in model:
            # Catalogs without this field predate the CLI parser's required
            # field. All current Codex and maintained vendor entries support
            # parallel calls, so true is the compatibility-safe default.
            model["supports_parallel_tool_calls"] = True
            model_was_fixed = True
        if model_was_fixed:
            fixed_slugs.append(str(model["slug"]))
    validate_catalog(normalized)
    return normalized, fixed_slugs


def load_pricing_metadata(path: Path | None = None) -> dict[str, Any]:
    metadata_path = PRICING_METADATA_PATH if path is None else path
    if not metadata_path.exists():
        raise SyncError(f"pricing metadata is missing: {metadata_path}")
    try:
        value = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"could not read pricing metadata from {metadata_path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SyncError("pricing metadata root must be a JSON object")
    if value.get("schema_version") != 1:
        raise SyncError(f"unsupported pricing metadata schema in {metadata_path}")
    try:
        dt.date.fromisoformat(str(value.get("verified_on", "")))
    except ValueError as exc:
        raise SyncError("pricing metadata verified_on must use YYYY-MM-DD") from exc

    sources = value.get("sources")
    if not isinstance(sources, dict) or not sources:
        raise SyncError("pricing metadata sources must be a non-empty JSON object")
    for source_name, source_info in sources.items():
        if not isinstance(source_info, dict):
            raise SyncError(f"pricing source {source_name!r} must be a JSON object")
        for key in ("label", "url", "reliability"):
            if not isinstance(source_info.get(key), str) or not source_info[key].strip():
                raise SyncError(
                    f"pricing source {source_name}.{key} must be a non-empty string"
                )
        if not source_info["url"].startswith("https://"):
            raise SyncError(f"pricing source {source_name}.url must be an HTTPS URL")

    aliases = value.get("aliases", {})
    if not isinstance(aliases, dict) or any(
        not isinstance(source, str)
        or not source
        or not isinstance(target, str)
        or not target
        for source, target in aliases.items()
    ):
        raise SyncError("pricing metadata aliases must map slug strings to slug strings")

    models = value.get("models")
    if not isinstance(models, dict) or not models:
        raise SyncError("pricing metadata models must be a non-empty JSON object")
    for slug, entry in models.items():
        if not isinstance(slug, str) or not slug:
            raise SyncError("pricing model keys must be non-empty strings")
        if not isinstance(entry, dict):
            raise SyncError(f"pricing entry for {slug!r} must be a JSON object")
        provider = entry.get("provider")
        if not isinstance(provider, str) or not provider.strip():
            raise SyncError(f"pricing entry {slug}.provider must be a non-empty string")
        for price_key in ("input_per_m", "output_per_m"):
            price_value = entry.get(price_key)
            if not isinstance(price_value, (int, float)) or isinstance(price_value, bool):
                raise SyncError(f"pricing entry {slug}.{price_key} must be a number")
            if float(price_value) < 0:
                raise SyncError(f"pricing entry {slug}.{price_key} must be non-negative")
        source_name = entry.get("source")
        if not isinstance(source_name, str) or source_name not in sources:
            raise SyncError(
                f"pricing entry {slug}.source must reference a known sources key"
            )
        source_url = entry.get("source_url")
        if source_url is not None and (
            not isinstance(source_url, str) or not source_url.startswith("https://")
        ):
            raise SyncError(f"pricing entry {slug}.source_url must be an HTTPS URL")
        if (
            source_url is not None
            and sources[source_name]["reliability"] == "official"
            and "openrouter.ai" in source_url
        ):
            raise SyncError(
                f"pricing entry {slug}.source_url cannot cite OpenRouter "
                "when source reliability is official"
            )
        notes = entry.get("notes")
        if notes is not None and (not isinstance(notes, str) or not notes.strip()):
            raise SyncError(f"pricing entry {slug}.notes must be a non-empty string")
    return value


def resolve_pricing_entry(
    slug: str, pricing_metadata: dict[str, Any]
) -> dict[str, Any] | None:
    models = pricing_metadata["models"]
    if slug in models:
        return models[slug]
    aliases = pricing_metadata.get("aliases", {})
    aliased = aliases.get(slug)
    if isinstance(aliased, str) and aliased in models:
        return models[aliased]
    return None


def format_context_window(token_count: int) -> str:
    if token_count >= 1_000_000:
        millions = token_count / 1_000_000
        # Vendor "1M context" windows are often 2^20 (1,048,576). Prefer the
        # whole-million label when the value is within 5% of an integer million.
        nearest_million = round(millions)
        if nearest_million >= 1 and abs(millions - nearest_million) <= 0.05:
            return f"{int(nearest_million)}M context"
        text = f"{millions:.2f}".rstrip("0").rstrip(".")
        return f"{text}M context"
    if token_count >= 1_000:
        thousands = token_count / 1_000
        # Prefer whole-thousand labels for picker density (e.g. 262144 -> 262K).
        nearest_thousand = round(thousands)
        if nearest_thousand >= 1:
            return f"{int(nearest_thousand)}K context"
        return f"{token_count} context"
    return f"{token_count} context"


def format_price_per_million(amount: float) -> str:
    if abs(amount - round(amount)) < 1e-9:
        return f"${int(round(amount))}/M"
    text = f"{amount:.3f}".rstrip("0").rstrip(".")
    return f"${text}/M"


def format_modality_label(input_modalities: Any) -> str | None:
    if not isinstance(input_modalities, list) or not input_modalities:
        return None
    normalized = {
        item.strip().lower()
        for item in input_modalities
        if isinstance(item, str) and item.strip()
    }
    if "image" in normalized:
        return "Vision"
    if "text" in normalized:
        return "Text"
    if normalized:
        return "/".join(sorted(item.title() for item in normalized))
    return None


def build_picker_description_parts(
    model: dict[str, Any], pricing_entry: dict[str, Any]
) -> list[str]:
    """Return description columns used by the Codex model picker.

    Columns:
    1. provider
    2. context window
    3. input price
    4. output price
    5. modality (Vision / Text)
    """
    parts: list[str] = []
    parts.append(str(pricing_entry["provider"]).strip())

    context_window = model.get("context_window")
    if isinstance(context_window, int) and not isinstance(context_window, bool):
        parts.append(format_context_window(context_window))
    else:
        parts.append("")

    parts.append(f"{format_price_per_million(float(pricing_entry['input_per_m']))} input")
    parts.append(
        f"{format_price_per_million(float(pricing_entry['output_per_m']))} output"
    )

    modality = format_modality_label(model.get("input_modalities"))
    parts.append(modality or "")
    return parts


def measure_picker_column_widths(rows: list[list[str]]) -> list[int]:
    if not rows:
        return []
    column_count = max(len(row) for row in rows)
    widths = [0] * column_count
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))
    return widths


def format_aligned_picker_description(
    parts: list[str], column_widths: list[int]
) -> str:
    """Join padded columns so monospaced TUI rows form vertical columns."""
    if not parts:
        return ""
    if not column_widths:
        return " · ".join(part for part in parts if part)

    padded_parts: list[str] = []
    last_index = len(parts) - 1
    for index, part in enumerate(parts):
        width = column_widths[index] if index < len(column_widths) else len(part)
        # Keep trailing spaces only between columns; last column can stay tight.
        if index == last_index:
            padded_parts.append(part)
        else:
            padded_parts.append(part.ljust(width))
    return " · ".join(padded_parts)


def build_picker_description(
    model: dict[str, Any],
    pricing_entry: dict[str, Any],
    column_widths: list[int] | None = None,
) -> str:
    parts = build_picker_description_parts(model, pricing_entry)
    if column_widths is None:
        return " · ".join(part for part in parts if part)
    return format_aligned_picker_description(parts, column_widths)


def enrich_catalog_descriptions(
    catalog: dict[str, Any],
    pricing_metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    metadata = (
        load_pricing_metadata() if pricing_metadata is None else pricing_metadata
    )
    enriched = copy.deepcopy(catalog)
    changes: dict[str, list[str]] = {"updated": [], "skipped": []}

    # Two-pass formatting keeps provider / context / price columns aligned in
    # monospaced Codex /model pickers even when vendor names and prices differ.
    priced_rows: list[tuple[dict[str, Any], list[str]]] = []
    for model in enriched["models"]:
        slug = model["slug"]
        pricing_entry = resolve_pricing_entry(slug, metadata)
        if pricing_entry is None:
            changes["skipped"].append(slug)
            continue
        parts = build_picker_description_parts(model, pricing_entry)
        priced_rows.append((model, parts))

    column_widths = measure_picker_column_widths([parts for _, parts in priced_rows])
    for model, parts in priced_rows:
        description = format_aligned_picker_description(parts, column_widths)
        if model.get("description") != description:
            model["description"] = description
            changes["updated"].append(model["slug"])
    validate_catalog(enriched)
    return enriched, changes


def serialized_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def catalog_digest(catalog: dict[str, Any]) -> str:
    canonical = json.dumps(
        catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def write_if_changed(path: Path, payload: bytes) -> bool:
    try:
        if path.is_file() and path.read_bytes() == payload:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, path)
        return True
    except OSError as exc:
        raise SyncError(f"could not write {path}: {exc}") from exc


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def version_sort_key(version: str) -> tuple[Any, ...]:
    """Return a SemVer-compatible key; stable releases sort after prereleases."""
    without_build = version.split("+", 1)[0]
    release, separator, prerelease = without_build.partition("-")
    try:
        release_key = tuple(int(part) for part in release.split("."))
    except ValueError as exc:
        raise SyncError(f"invalid semantic version: {version}") from exc
    if not separator:
        return (*release_key, 1, ())

    prerelease_key: list[tuple[int, int | str]] = []
    for identifier in prerelease.split("."):
        if identifier.isdigit():
            prerelease_key.append((0, int(identifier)))
        else:
            prerelease_key.append((1, identifier))
    return (*release_key, 0, tuple(prerelease_key))


def sort_archive_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_source = sorted(records, key=lambda record: str(record["source"]))
    return sorted(
        by_source,
        key=lambda record: version_sort_key(str(record["version"])),
        reverse=True,
    )


def load_archive_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": 1,
            "classification": "official",
            "catalog_kind": "openai-source-archive",
            "archives": {"app": [], "cli": [], "upstream": []},
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SyncError(f"could not read archive index {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise SyncError(f"unsupported archive index schema in {path}")
    if value.get("classification") not in (None, "official"):
        raise SyncError(f"invalid archive classification in {path}")
    if value.get("catalog_kind") not in (None, "openai-source-archive"):
        raise SyncError(f"invalid archive kind in {path}")
    archives = value.get("archives")
    if not isinstance(archives, dict) or any(
        not isinstance(archives.get(category), list)
        for category in ("app", "cli", "upstream")
    ):
        raise SyncError(f"invalid archive lists in {path}")
    return value


def archive_record_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record["source"]),
        str(record.get("version", "")),
        str(record["sha256"]),
    )


def archive_catalog(
    archive_dir: Path, result: SourceResult, archived_at: str
) -> tuple[str, dict[str, Any]]:
    assert result.ok and result.catalog is not None
    digest = catalog_digest(result.catalog)
    payload = serialized_json(result.catalog)

    if result.name in ARCHIVE_SOURCE_INFO:
        category, kind = ARCHIVE_SOURCE_INFO[result.name]
        assert result.version is not None
        relative = Path(category) / result.version / f"{kind}.json"
    else:
        category = "upstream"
        relative = Path("upstream") / "main" / f"{digest[:12]}.json"

    target = archive_dir / relative
    if target.is_file() and target.read_bytes() != payload:
        if result.name in ARCHIVE_SOURCE_INFO:
            relative = relative.with_name(f"{relative.stem}-{digest[:12]}.json")
        else:
            relative = relative.with_name(f"{digest}.json")
        target = archive_dir / relative
        if target.is_file() and target.read_bytes() != payload:
            raise SyncError(f"archive hash collision at {target}")
    write_if_changed(target, payload)

    record: dict[str, Any] = {
        "source": result.name,
        "file": relative.as_posix(),
        "models": len(result.catalog["models"]),
        "sha256": digest,
        "archived_at": archived_at,
        "origin": result.origin,
    }
    if result.version:
        record["version"] = result.version
    return category, record


def merge_archive_records(
    existing: list[dict[str, Any]], incoming: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    combined = {archive_record_key(record): copy.deepcopy(record) for record in existing}
    for record in incoming:
        key = archive_record_key(record)
        previous = combined.get(key)
        if previous and previous.get("archived_at"):
            record = copy.deepcopy(record)
            record["archived_at"] = previous["archived_at"]
        combined[key] = record
    return list(combined.values())


def render_archive_index(index: dict[str, Any]) -> str:
    lines = [
        "# Codex model catalog 版本归档",
        "",
        "> 此文件由 `sync_model_catalog.py` 自动生成，请勿手工编辑。",
        "> 归档 JSON 是来自 OpenAI Codex CLI、App 或 `openai/codex` 的官方原始快照；归档版本不代表当前默认推荐模型。",
        "",
        "[返回项目 README](../README.md)",
        "",
        "## 当前基线",
        "",
    ]
    selected = index["selected_base"]
    version = selected.get("version", "rolling")
    lines.extend(
        [
            "| 来源 | 版本 | 模型数 | SHA-256 | 归档 |",
            "| --- | --- | ---: | --- | --- |",
            (
                f"| `{selected['source']}` | `{version}` | {selected['models']} | "
                f"`{selected['sha256'][:12]}` | [JSON](./{selected['file']}) |"
            ),
            "",
        ]
    )

    for category, title in (("app", "Codex App"), ("cli", "Codex CLI")):
        lines.extend(
            [
                f"## {title}",
                "",
                "| 版本（新到旧） | 来源 | 模型数 | SHA-256 | 归档 |",
                "| --- | --- | ---: | --- | --- |",
            ]
        )
        records = index["archives"][category]
        if records:
            for record in records:
                lines.append(
                    f"| `{record['version']}` | `{record['source']}` | "
                    f"{record['models']} | `{record['sha256'][:12]}` | "
                    f"[JSON](./{record['file']}) |"
                )
        else:
            lines.append("| - | 尚无归档 | - | - | - |")
        lines.append("")

    lines.extend(
        [
            "## GitHub main",
            "",
            "`main` 没有固定版本号，因此按目录内容哈希归档；相同内容不会重复保存。",
            "",
            "| 首次归档时间（UTC） | 模型数 | SHA-256 | 归档 |",
            "| --- | ---: | --- | --- |",
        ]
    )
    upstream = index["archives"]["upstream"]
    if upstream:
        for record in upstream:
            lines.append(
                f"| `{record['archived_at']}` | {record['models']} | "
                f"`{record['sha256'][:12]}` | [JSON](./{record['file']}) |"
            )
    else:
        lines.append("| - | - | 尚无归档 | - |")
    lines.extend(["", f"索引更新时间：`{index['updated_at']}`", ""])
    return "\n".join(lines)


def update_archives(
    archive_dir: Path,
    selected: SourceResult,
    results: dict[str, SourceResult],
) -> dict[str, Any]:
    index_path = archive_dir / "index.json"
    existing = load_archive_index(index_path)
    observed_at = utc_now()
    incoming: dict[str, list[dict[str, Any]]] = {
        "app": [],
        "cli": [],
        "upstream": [],
    }
    current_records: dict[str, dict[str, Any]] = {}
    for result in results.values():
        if result.ok:
            category, record = archive_catalog(archive_dir, result, observed_at)
            incoming[category].append(record)
            current_records[result.name] = record

    archives: dict[str, list[dict[str, Any]]] = {}
    for category in ("app", "cli", "upstream"):
        records = merge_archive_records(
            existing["archives"][category], incoming[category]
        )
        if category in {"app", "cli"}:
            records = sort_archive_records(records)
        else:
            records = sorted(
                records, key=lambda record: str(record["archived_at"]), reverse=True
            )
        archives[category] = records

    selected_record = current_records[selected.name]
    selected_base = {
        key: selected_record[key]
        for key in ("source", "version", "file", "models", "sha256")
        if key in selected_record
    }
    last_sync: dict[str, Any] = {}
    for name in SOURCE_NAMES:
        result = results[name]
        item: dict[str, Any] = {"status": result.status, "origin": result.origin}
        if result.version:
            item["version"] = result.version
        if result.ok:
            record = current_records[name]
            item.update(
                {
                    "models": record["models"],
                    "sha256": record["sha256"],
                    "archive": record["file"],
                }
            )
        if result.error:
            item["error"] = result.error
        last_sync[name] = item

    candidate = {
        "schema_version": 1,
        "classification": "official",
        "catalog_kind": "openai-source-archive",
        "selected_base": selected_base,
        "archives": archives,
        "last_sync": last_sync,
    }
    existing_without_time = {
        key: value for key, value in existing.items() if key != "updated_at"
    }
    candidate["updated_at"] = (
        existing.get("updated_at", observed_at)
        if candidate == existing_without_time
        else observed_at
    )
    write_if_changed(index_path, serialized_json(candidate))
    write_if_changed(
        archive_dir / "INDEX.md", render_archive_index(candidate).encode("utf-8")
    )
    return candidate


def print_source_summary(
    selected: SourceResult, results: dict[str, SourceResult]
) -> None:
    selected_digest = catalog_digest(selected.catalog) if selected.catalog else ""
    for name in SOURCE_NAMES:
        result = results[name]
        if result.ok:
            assert result.catalog is not None
            digest = catalog_digest(result.catalog)
            relation = " = base" if digest == selected_digest else ""
            version = f" ({result.version})" if result.version else ""
            print(
                f"[ok]      {name}{version}: {len(result.catalog['models'])} models, "
                f"sha256 {digest[:12]}{relation}"
            )
        elif result.status == "skipped":
            reason = result.error or result.origin
            print(f"[skipped] {name}: {reason}")
        else:
            print(f"[error]   {name}: {result.error}")


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        cli = discover_cli(args.cli_codex, args.timeout)
        app = discover_app_binary(args.app_codex, args.timeout)
        results = collect_sources(
            cli, app, timeout=args.timeout, offline=args.offline
        )
        selected = choose_base(args.base, results)
        print_source_summary(selected, results)

        errors = [result for result in results.values() if result.status == "error"]
        if args.strict and errors:
            raise SyncError(f"{len(errors)} source(s) failed in strict mode")

        assert selected.catalog is not None
        preset_names = selected_preset_names(args.preset)
        override_documents = []
        if not args.no_overrides:
            override_documents.append(load_overrides(args.overrides))
        override_documents.extend(
            load_overrides(THIRD_PARTY_PRESETS[name]) for name in preset_names
        )

        if not override_documents:
            final_catalog = copy.deepcopy(selected.catalog)
            changes = {"added": [], "updated": [], "removed": []}
        else:
            overrides = combine_overrides(override_documents)
            final_catalog, changes = merge_overrides(selected.catalog, overrides)

        if preset_names:
            print(f"[preset]  {', '.join(preset_names)}")

        final_catalog, compatibility_fixed = normalize_catalog_compatibility(
            final_catalog
        )
        if compatibility_fixed:
            print(
                "[compat]  filled required CLI fields for: "
                f"{', '.join(compatibility_fixed)}"
            )

        pricing_changes = {"updated": [], "skipped": []}
        if not args.no_pricing_enrichment:
            final_catalog, pricing_changes = enrich_catalog_descriptions(final_catalog)
            if pricing_changes["updated"]:
                print(
                    f"[pricing] updated descriptions: "
                    f"{', '.join(pricing_changes['updated'])}"
                )
            if pricing_changes["skipped"]:
                print(
                    f"[pricing] no metadata for: "
                    f"{', '.join(pricing_changes['skipped'])}"
                )

        route_catalogs = {} if args.no_routes else build_route_catalogs()
        output_payload = serialized_json(final_catalog)
        if args.check:
            outdated = False
            current = args.output.read_bytes() if args.output.is_file() else None
            if current != output_payload:
                print(f"[outdated] {args.output}", file=sys.stderr)
                outdated = True
            else:
                print(f"[current]  {args.output}")
            for route_path, route_catalog in route_catalogs.items():
                route_payload = serialized_json(route_catalog)
                current = route_path.read_bytes() if route_path.is_file() else None
                if current != route_payload:
                    print(f"[outdated] {route_path}", file=sys.stderr)
                    outdated = True
            if not outdated and route_catalogs:
                print(f"[current]  {ROUTES_DIR}: {len(route_catalogs)} catalogs")
            return 1 if outdated else 0

        archive_index = update_archives(args.archive_dir, selected, results)
        changed = write_if_changed(args.output, output_payload)
        route_updates = sum(
            write_if_changed(path, serialized_json(catalog))
            for path, catalog in route_catalogs.items()
        )

        action = "updated" if changed else "unchanged"
        print(
            f"[{action}] {args.output}: {len(final_catalog['models'])} models, "
            f"base={selected.name}, sha256={catalog_digest(final_catalog)[:12]}"
        )
        print(
            f"[archive] {args.archive_dir}: "
            f"{sum(len(items) for items in archive_index['archives'].values())} records"
        )
        if route_catalogs:
            print(
                f"[routes]  {ROUTES_DIR}: {len(route_catalogs)} catalogs, "
                f"{route_updates} updated"
            )
        for change_type in ("added", "updated", "removed"):
            if changes[change_type]:
                print(f"[override] {change_type}: {', '.join(changes[change_type])}")
        return 0
    except SyncError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
