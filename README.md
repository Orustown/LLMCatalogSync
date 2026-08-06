# Codex Model Catalog

同步 Codex 官方 `model_catalog.json`，维护厂商官方模型基线，并生成第三方路由可直接使用的标准目录。脚本仅依赖 Python 标准库。

[同步](#sync) · [官方厂商基线](#third-party) · [第三方路由](#routes) · [Provider 共存](#providers) · [来源](#sources) · [归档](#archives) · [验证](#verify)

查看当前 **[版本归档索引](catalogs/INDEX.md)**。

<a id="sync"></a>
## 同步

双击 `sync.cmd`，或执行：

```powershell
python .\sync_model_catalog.py
```

默认同步 5 个官方来源，优先用 App 内置目录生成 [`model_catalog.json`](model_catalog.json)，未找到 App 时回退到 PATH 中的 CLI。长期自定义字段放在 [`model_overrides.json`](model_overrides.json)，不要直接修改生成文件。

`catalogs/` 中的 GPT 目录来自 OpenAI Codex CLI、App 或 [`openai/codex`](https://github.com/openai/codex)，索引统一标记为 `classification: official`，归档 JSON 保持官方原始内容。归档记录的是某个来源的历史快照，不表示该版本中的模型仍是当前默认推荐模型。

常用选项：

```powershell
python .\sync_model_catalog.py --offline                 # 只读本机 bundled
python .\sync_model_catalog.py --base cli-bundled       # 使用 PATH CLI
python .\sync_model_catalog.py --base github-main       # 使用上游 main
python .\sync_model_catalog.py --strict --check         # 发布前检查
```

<a id="third-party"></a>
## 官方厂商基线

`third_party/{grok,deepseek,kimi}.json` 中的模型 ID、上下文和接口能力以各厂商官方资料为准，统一标记为 `classification: official`。其中 Codex 专用字段仍由本仓库适配，因此同时标记为 `codex_adapter: repository-maintained`，不宣称是厂商发布的原始 `model_catalog.json`。

这些基线不会默认写入最终目录。选择预设后重新生成：

| 预设 | 当前模型 | 接口要求 | 一键生成 |
| --- | --- | --- | --- |
| [Grok](third_party/grok.json) | `grok-4.5`、`grok-build-0.1` | xAI 支持 Responses，可直连 | `python .\sync_model_catalog.py --preset grok` |
| [DeepSeek](third_party/deepseek.json) | `deepseek-v4-pro`、`deepseek-v4-flash` | V4 Flash 原生 Responses；V4 Pro 需协议网关 | `python .\sync_model_catalog.py --preset deepseek` |
| [Kimi](third_party/kimi.json) | `kimi-k3`、`kimi-k2.7-code`、`kimi-k2.7-code-highspeed`、`kimi-k2.6` | 官方 Codex 指南使用协议网关 | `python .\sync_model_catalog.py --preset kimi` |
| 全部 | 上述全部 | 按各厂商要求配置 | `python .\sync_model_catalog.py --preset all` |

`sync.cmd --preset all` 同样可用。`--preset` 可以重复，例如 `--preset grok --preset kimi`。`--no-overrides` 只跳过 [`model_overrides.json`](model_overrides.json)，不会跳过显式选择的预设。

模型参数依据厂商当前文档维护；每份 JSON 的 `metadata.verified_on`、协议和来源也会随模型一起校验：[xAI 模型](https://docs.x.ai/developers/models)、[DeepSeek 定价与模型](https://api-docs.deepseek.com/quick_start/pricing)、[Kimi 模型列表](https://platform.kimi.ai/docs/models)。当前 DeepSeek V4 Flash 可使用原生 Responses 集成；V4 Pro、Kimi 以及其他 Chat Completions 端点仍应通过支持协议转换的网关使用。

<a id="routes"></a>
## 第三方路由

`third_party/routes/` 维护社区或聚合渠道。每个路由的 `route.json` 保存 Base URL、协议、官方模型到路由模型的映射、核验日期和来源；每个厂商子目录里的 `model_catalog.json` 只包含标准 `{"models": [...]}`，可以直接配置给 Codex。

| 路由 | 标准目录 | 规则 |
| --- | --- | --- |
| [CC Switch](third_party/routes/cc-switch/route.json) | `cc-switch/<vendor>/model_catalog.json` | 保留厂商 slug；按当前 Provider 决定原生 Responses 或本地转换 |
| [LiteLLM](third_party/routes/litellm/route.json) | `litellm/<vendor>/model_catalog.json` | 保留厂商 slug；LiteLLM `model_list` 必须配置同名 `model_name` alias |
| [OpenRouter](third_party/routes/openrouter/route.json) | `openrouter/<vendor>/model_catalog.json` | 使用 `x-ai/...`、`deepseek/...`、`moonshotai/...` 命名空间 slug |

普通同步会从官方厂商基线重建全部 9 份 route catalogs；`--strict --check` 也会检查它们是否过期。`--no-routes` 可只处理主目录。路由目录是生成文件，修改模型能力应回到官方厂商基线，修改 slug 或路由限制应修改对应 `route.json`。

<a id="sources"></a>
## 来源怎么选

| 来源 | 适合用途 | 注意事项 |
| --- | --- | --- |
| `app-bundled` | Codex App 当前实际内置版本；默认优先 | 最贴近当前 App，离线可用 |
| `cli-bundled` | PATH 中 Codex CLI 当前实际内置版本 | 最贴近当前 CLI，离线可用 |
| `app-github-tag` | 审核 App 版本对应源码 | alpha / 内部构建不一定有公开 tag |
| `cli-github-tag` | 可追溯、可复现的 CLI 对应源码 | 安装包与 tag 发布可能有时间差 |
| `github-main` | 查看上游最新模型和字段 | 可能领先本机客户端 |

默认 `--base auto` 的顺序是 App bundled、CLI bundled、App tag、CLI tag、GitHub main。

<a id="archives"></a>
## 版本与文件

```text
catalogs/
├── app/<version>/{bundled,github-tag}.json
├── cli/<version>/{bundled,github-tag}.json
├── upstream/main/<content-hash>.json
├── INDEX.md
└── index.json
third_party/{grok,deepseek,kimi}.json
third_party/routes/<route>/<vendor>/model_catalog.json
third_party/routes/<route>/route.json
```

App / CLI 使用完整语义版本号并按新到旧排序；`main` 按内容哈希保存。相同内容不会重复归档，同版本内容变化时不会覆盖旧文件。完整版本、哈希和来源见 [`catalogs/INDEX.md`](catalogs/INDEX.md)。

<a id="providers"></a>
## Provider 共存

模型目录只描述模型，不会按模型自动切换 Provider。官方号与第三方 API 可以同时定义，启动时用 Provider 和模型一起选择：

```toml
model_catalog_json = "C:\\absolute\\path\\to\\model_catalog.json"

[model_providers.xai]
name = "xAI"
base_url = "https://api.x.ai/v1"
env_key = "XAI_API_KEY"
wire_api = "responses"
```

```powershell
codex --model gpt-5.6-sol -c 'model_provider="openai"'
codex --model grok-build-0.1 -c 'model_provider="xai"'
```

使用第三方路由时，把 `model_catalog_json` 改为对应的标准目录，并让 `model_provider` 指向同一个路由。例如 OpenRouter Grok 使用 `third_party/routes/openrouter/grok/model_catalog.json`，模型 slug 为 `x-ai/grok-4.5`。不要把一个路由的目录配给另一个 Provider。

DeepSeek V4 Pro / Kimi 需要把 `model_provider` 指向能接收 Responses 的网关；网关地址、认证和模型映射由网关维护。Codex App 对非 GPT slug 的菜单显示可能是 `Custom`，先用 `codex debug models` 验证；不要把第三方模型伪装成 GPT slug，否则 Provider 和能力元数据会错位。

<a id="config"></a>
## Codex 配置

在用户级 `~/.codex/config.toml` 引用最终目录：

```toml
model_catalog_json = "C:\\absolute\\path\\to\\model_catalog.json"
```

Provider 地址、认证和 `model_provider` 也放在用户级配置，不要提交密钥。Codex 当前 `wire_api` 只支持 `responses`，详见 [官方配置参考](https://developers.openai.com/codex/config-reference/)。配置后重启 Codex，并执行 `codex debug models` 检查有效目录。

<a id="verify"></a>
## 验证

```powershell
python -B -m unittest discover -s tests -v
python -B .\sync_model_catalog.py --strict --check
```

GitHub Actions 会运行单元测试并校验 JSON、官方分类、route manifests 和所有生成目录。项目只保留同步脚本、测试、当前目录、版本归档和第三方预设；不要提交 `auth.json`、`models_cache.json` 或用户级 `config.toml`。

上游：[OpenAI/codex](https://github.com/openai/codex) · [models.json](https://github.com/openai/codex/blob/main/codex-rs/models-manager/models.json)
