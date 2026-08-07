import copy
import json
import tempfile
import unittest
from pathlib import Path

import sync_model_catalog as sync


class CatalogTests(unittest.TestCase):
    def test_all_committed_json_files_parse(self) -> None:
        paths = [
            sync.PROJECT_DIR / "model_catalog.json",
            sync.PROJECT_DIR / "model_overrides.json",
            *sorted((sync.PROJECT_DIR / "catalogs").rglob("*.json")),
            *sorted((sync.PROJECT_DIR / "third_party").rglob("*.json")),
        ]
        self.assertTrue(paths)
        for path in paths:
            with self.subTest(path=path.relative_to(sync.PROJECT_DIR)):
                json.loads(path.read_text(encoding="utf-8-sig"))

    def test_extract_version_accepts_codex_prerelease(self) -> None:
        self.assertEqual(
            sync.extract_version("codex-cli 0.147.0-alpha.1.2\n"),
            "0.147.0-alpha.1.2",
        )

    def test_versions_sort_in_semver_descending_order(self) -> None:
        versions = [
            "0.147.0-alpha.1.2",
            "0.144.1",
            "0.147.0",
            "0.147.0-alpha.1.10",
        ]
        self.assertEqual(
            sorted(versions, key=sync.version_sort_key, reverse=True),
            [
                "0.147.0",
                "0.147.0-alpha.1.10",
                "0.147.0-alpha.1.2",
                "0.144.1",
            ],
        )

    def test_validate_catalog_rejects_duplicate_slugs(self) -> None:
        with self.assertRaisesRegex(sync.SyncError, "duplicate model slug"):
            sync.validate_catalog({"models": [{"slug": "x"}, {"slug": "x"}]})

    def test_merge_overrides_updates_adds_and_removes(self) -> None:
        base = {
            "models": [
                {"slug": "keep", "nested": {"left": 1, "right": 2}},
                {"slug": "remove", "value": 1},
            ]
        }
        original = copy.deepcopy(base)
        overrides = {
            "models": [
                {"slug": "keep", "nested": {"right": 3}},
                {"slug": "new", "value": 4},
            ],
            "remove_models": ["remove"],
        }

        merged, changes = sync.merge_overrides(base, overrides)

        self.assertEqual(base, original)
        self.assertEqual(
            merged["models"],
            [
                {"slug": "keep", "nested": {"left": 1, "right": 3}},
                {"slug": "new", "value": 4},
            ],
        )
        self.assertEqual(changes["updated"], ["keep"])
        self.assertEqual(changes["added"], ["new"])
        self.assertEqual(changes["removed"], ["remove"])

    def test_load_overrides_rejects_unknown_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "overrides.json"
            path.write_text('{"models": [], "typo": []}', encoding="utf-8")
            with self.assertRaisesRegex(sync.SyncError, "unknown override keys"):
                sync.load_overrides(path)

    def test_load_overrides_rejects_invalid_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "overrides.json"
            path.write_text(
                '{"metadata": {"provider": "xAI"}, "models": []}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(sync.SyncError, "metadata.verified_on"):
                sync.load_overrides(path)

    def test_choose_base_prefers_app_bundle(self) -> None:
        catalog = {"models": [{"slug": "x"}]}
        results = {
            name: sync.SourceResult(name, "skipped", "test")
            for name in sync.SOURCE_NAMES
        }
        results["cli-bundled"] = sync.SourceResult(
            "cli-bundled", "ok", "test", catalog=catalog
        )
        results["app-bundled"] = sync.SourceResult(
            "app-bundled", "ok", "test", catalog=catalog
        )
        self.assertEqual(sync.choose_base("auto", results).name, "app-bundled")

    def test_third_party_presets_are_valid_additions(self) -> None:
        expected = {
            "grok": ["grok-4.5", "grok-build-0.1"],
            "deepseek": ["deepseek-v4-pro", "deepseek-v4-flash"],
            "kimi": [
                "kimi-k3",
                "kimi-k2.7-code",
                "kimi-k2.7-code-highspeed",
                "kimi-k2.6",
            ],
        }
        for preset, slugs in expected.items():
            with self.subTest(preset=preset):
                overrides = sync.load_overrides(sync.THIRD_PARTY_PRESETS[preset])
                merged, changes = sync.merge_overrides(
                    {"models": [{"slug": "base"}]}, overrides
                )
                self.assertEqual(changes["added"], slugs)
                self.assertEqual(
                    [model["slug"] for model in merged["models"]], ["base", *slugs]
                )

    def test_vendor_presets_are_marked_as_official_baselines(self) -> None:
        for provider, path in sync.THIRD_PARTY_PRESETS.items():
            with self.subTest(provider=provider):
                document = json.loads(path.read_text(encoding="utf-8-sig"))
                metadata = document["metadata"]
                self.assertEqual(metadata["classification"], "official")
                self.assertEqual(metadata["catalog_kind"], "vendor-baseline")
                self.assertEqual(metadata["codex_adapter"], "repository-maintained")

    def test_route_catalogs_are_standard_and_current(self) -> None:
        route_catalogs = sync.build_route_catalogs()
        self.assertEqual(len(route_catalogs), 9)
        for path, catalog in route_catalogs.items():
            with self.subTest(path=path.relative_to(sync.PROJECT_DIR)):
                self.assertEqual(set(catalog), {"models"})
                self.assertEqual(path.read_bytes(), sync.serialized_json(catalog))

        openrouter_grok = (
            sync.ROUTES_DIR / "openrouter" / "grok" / "model_catalog.json"
        )
        self.assertEqual(
            [model["slug"] for model in route_catalogs[openrouter_grok.resolve()]["models"]],
            ["x-ai/grok-4.5", "x-ai/grok-build-0.1"],
        )

    def test_all_preset_expands_in_stable_order(self) -> None:
        self.assertEqual(
            sync.selected_preset_names(["kimi", "all", "grok"]),
            ["grok", "deepseek", "kimi"],
        )

    def test_normalize_catalog_compatibility_fills_missing_reasoning_flag(self) -> None:
        catalog = {
            "models": [
                {"slug": "gpt-5.6-sol", "display_name": "Sol"},
                {
                    "slug": "kimi-k3",
                    "supports_reasoning_summaries": False,
                },
            ]
        }
        normalized, fixed = sync.normalize_catalog_compatibility(catalog)
        self.assertEqual(fixed, ["gpt-5.6-sol"])
        self.assertTrue(normalized["models"][0]["supports_reasoning_summaries"])
        self.assertFalse(normalized["models"][1]["supports_reasoning_summaries"])

        again, fixed_again = sync.normalize_catalog_compatibility(normalized)
        self.assertEqual(fixed_again, [])
        self.assertEqual(again, normalized)

    def test_app_archive_needs_compatibility_fill_for_cli(self) -> None:
        app_catalog = json.loads(
            (sync.PROJECT_DIR / "catalogs/app/0.147.0-alpha.1.2/bundled.json").read_text(
                encoding="utf-8-sig"
            )
        )
        missing = [
            model["slug"]
            for model in app_catalog["models"]
            if "supports_reasoning_summaries" not in model
        ]
        self.assertTrue(missing)
        normalized, fixed = sync.normalize_catalog_compatibility(app_catalog)
        self.assertEqual(fixed, missing)
        self.assertTrue(
            all("supports_reasoning_summaries" in model for model in normalized["models"])
        )

    def test_pricing_metadata_is_valid(self) -> None:
        metadata = sync.load_pricing_metadata()
        self.assertEqual(metadata["schema_version"], 1)
        self.assertIn("gpt-5.6-sol", metadata["models"])
        self.assertIn("kimi-k3", metadata["models"])

    def test_format_helpers_match_picker_style(self) -> None:
        self.assertEqual(sync.format_context_window(272_000), "272K context")
        self.assertEqual(sync.format_context_window(262_144), "262K context")
        self.assertEqual(sync.format_context_window(1_048_576), "1M context")
        self.assertEqual(sync.format_context_window(1_000_000), "1M context")
        self.assertEqual(sync.format_price_per_million(5.0), "$5/M")
        self.assertEqual(sync.format_price_per_million(0.435), "$0.435/M")
        self.assertEqual(sync.format_modality_label(["text", "image"]), "Vision")
        self.assertEqual(sync.format_modality_label(["text"]), "Text")

    def test_enrich_catalog_descriptions_uses_pricing_metadata(self) -> None:
        catalog = {
            "models": [
                {
                    "slug": "gpt-5.6-sol",
                    "description": "Latest frontier agentic coding model.",
                    "context_window": 272000,
                    "input_modalities": ["text", "image"],
                },
                {
                    "slug": "moonshotai/kimi-k3",
                    "description": "Moonshot AI flagship model with a 1M context window.",
                    "context_window": 1048576,
                    "input_modalities": ["text", "image"],
                },
                {
                    "slug": "unknown-model",
                    "description": "keep me",
                    "context_window": 1000,
                    "input_modalities": ["text"],
                },
            ]
        }
        enriched, changes = sync.enrich_catalog_descriptions(catalog)
        self.assertEqual(
            enriched["models"][0]["description"],
            "OpenAI · 272K context · $5/M input · $30/M output · Vision",
        )
        self.assertEqual(
            enriched["models"][1]["description"],
            "Moonshot AI · 1M context · $3/M input · $15/M output · Vision",
        )
        self.assertEqual(enriched["models"][2]["description"], "keep me")
        self.assertEqual(changes["updated"], ["gpt-5.6-sol", "moonshotai/kimi-k3"])
        self.assertEqual(changes["skipped"], ["unknown-model"])

    def test_enrich_is_idempotent(self) -> None:
        catalog = {
            "models": [
                {
                    "slug": "deepseek-v4-flash",
                    "description": "placeholder",
                    "context_window": 1048576,
                    "input_modalities": ["text"],
                }
            ]
        }
        first, first_changes = sync.enrich_catalog_descriptions(catalog)
        second, second_changes = sync.enrich_catalog_descriptions(first)
        self.assertEqual(first, second)
        self.assertEqual(first_changes["updated"], ["deepseek-v4-flash"])
        self.assertEqual(second_changes["updated"], [])

    def test_combine_overrides_deep_merges_duplicate_models(self) -> None:
        combined = sync.combine_overrides(
            [
                {
                    "models": [{"slug": "x", "nested": {"left": 1}}],
                    "remove_models": ["old"],
                },
                {
                    "models": [{"slug": "x", "nested": {"right": 2}}],
                    "remove_models": ["old", "older"],
                },
            ]
        )
        self.assertEqual(
            combined,
            {
                "models": [{"slug": "x", "nested": {"left": 1, "right": 2}}],
                "remove_models": ["old", "older"],
            },
        )

    def test_archive_is_versioned_and_second_sync_is_stable(self) -> None:
        catalog = {"models": [{"slug": "x"}]}
        results = {
            name: sync.SourceResult(name, "skipped", "test")
            for name in sync.SOURCE_NAMES
        }
        selected = sync.SourceResult(
            "app-bundled",
            "ok",
            "test app",
            version="0.147.0-alpha.1.2",
            catalog=catalog,
        )
        results["app-bundled"] = selected

        with tempfile.TemporaryDirectory() as temp_dir:
            archive_dir = Path(temp_dir) / "catalogs"
            first = sync.update_archives(archive_dir, selected, results)
            index_before = (archive_dir / "index.json").read_bytes()
            markdown_before = (archive_dir / "INDEX.md").read_bytes()
            second = sync.update_archives(archive_dir, selected, results)

            self.assertEqual(first["classification"], "official")
            self.assertEqual(first["catalog_kind"], "openai-source-archive")
            self.assertTrue(
                (archive_dir / "app/0.147.0-alpha.1.2/bundled.json").is_file()
            )
            self.assertEqual(first, second)
            self.assertEqual(index_before, (archive_dir / "index.json").read_bytes())
            self.assertEqual(markdown_before, (archive_dir / "INDEX.md").read_bytes())


if __name__ == "__main__":
    unittest.main()
