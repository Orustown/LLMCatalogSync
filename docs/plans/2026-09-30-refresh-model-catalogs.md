# 更新模型目录 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 根据 2026-09-30 前后各厂商官方资料，更新 OpenAI 和第三方厂商模型基线、路由目录、定价元数据与文档，并遵守“无法确认是否删除时先询问”的规则。

**Architecture:** 保留现有 `sync_model_catalog.py` 生成链路，以官方 OpenAI Codex 上游目录作为 OpenAI 基线，以 `third_party/*.json` 作为其他厂商的可审计基线。所有生成的根目录和路由目录通过同步器重建，模型 ID 的去留记录在基线及测试中。

**Display order:** 最终目录固定按厂商分组排列：OpenAI、Claude、Grok、Gemini、Meta、Qwen、Hunyuan、DeepSeek、GLM、Kimi、MiniMax、Xiaomi。Codex 当前 schema 只接受 `text`、`image`、`audio` 输入模态；厂商的 `video` 能力不得直接写入 Codex 目录。

**Tech Stack:** Python 3 标准库、JSON、unittest、官方文档和官方上游模型目录。

---

### Task 1: 核验模型来源和去留

**Files:**
- Read: `sync_model_catalog.py`
- Read: `third_party/*.json`
- Read: `pricing_metadata.json`
- Read: 官方厂商模型文档

**Step 1:** 记录每个厂商的官方当前模型 ID、能力、上下文、价格和退役状态。

**Step 2:** 将明确新增、明确退役和用户明确要求移除的 ID 与仍然存在但去留不确定的 ID 分开。

**Step 3:** 对不确定的删除项向用户确认后再继续依赖该决定的修改。

### Task 2: 更新厂商基线

**Files:**
- Modify: `third_party/*.json`
- Modify: `pricing_metadata.json`
- Modify: `model_overrides.json`

**Step 1:** 更新 OpenAI 上游归档和覆盖字段，按每个模型系列保留最新 ID。

**Step 2:** 将 xAI 更新为 Grok 4.7，并移除用户明确指定的 Grok 4.5 与 4.6；其余不确定条目先保留。

**Step 3:** 更新其他厂商明确已发布或已退役的模型及定价，保留不确定旧 ID 并在交付说明中列出；重点确认 Google 当前主推的 Gemini Flash 型号。

### Task 3: 重建生成目录和文档

**Files:**
- Modify: `model_catalog.json`
- Modify: `third_party/routes/**/model_catalog.json`
- Modify: `README.md`
- Modify: `catalogs/INDEX.md`

**Step 1:** 运行同步器生成 OpenAI 当前目录及全部第三方路由目录。

**Step 2:** 检查模型 ID、固定厂商排序、路由命名空间、描述和价格元数据一致。

### Task 4: 验证

**Files:**
- Modify: `tests/test_sync_model_catalog.py`（仅在现有断言需要随目录更新时修改）

**Step 1:** 运行 `python -B -m unittest discover -s tests -v`。

**Step 2:** 运行 `python -B .\sync_model_catalog.py --preset all --strict --check`。

**Step 3:** 检查 JSON 解析、重复模型 ID、所有路由目录和工作区差异。
