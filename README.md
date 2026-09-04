# Codex Model Catalog

同步 Codex 官方 `model_catalog.json`，维护厂商官方模型基线，并生成第三方路由可直接使用的标准目录。脚本仅依赖 Python 标准库。

[同步](#sync) · [快速安装](#install) · [官方厂商基线](#third-party) · [第三方路由](#routes) · [来源](#sources) · [归档](#archives) · [价格展示](#pricing) · [验证](#verify)

查看当前 **[版本归档索引](catalogs/INDEX.md)**。

<a id="sync"></a>
## 同步

双击 `sync.cmd`，或执行：

```powershell
python .\sync_model_catalog.py
```

默认同步 5 个官方来源，优先用 App 内置目录生成 [`model_catalog.json`](model_catalog.json)，未找到 App 时回退到 PATH 中的 CLI。长期自定义字段放在 [`model_overrides.json`](model_overrides.json)，不要直接修改生成文件。同步时会读取 [`pricing_metadata.json`](pricing_metadata.json)，把厂商、上下文、价格和 Vision/Text 写入每个模型的 `description`，以便 Codex `/model` 选择器显示类似：

```text
OpenAI      · 272K context · $5/M     input · $30/M output · Vision
xAI         · 500K context · $2/M     input · $6/M  output · Vision
Moonshot AI · 1M context   · $3/M     input · $15/M output · Vision
```

同步还会为缺失字段做 CLI 兼容补齐。当前常见问题是 Codex App 目录可能省略 `supports_reasoning_summaries`，而 Codex CLI 0.144.x 加载 `model_catalog_json` 时会把它当作必填字段；脚本会自动补上，避免 `failed to parse model_catalog_json`。

价格展示会按当前 catalog 内所有带定价的模型统一列宽对齐（provider / context / input / output），让 monospaced `/model` 列表更整齐。

`catalogs/` 中的 GPT 目录来自 OpenAI Codex CLI、App 或 [`openai/codex`](https://github.com/openai/codex)，索引统一标记为 `classification: official`，归档 JSON 保持官方原始内容。归档记录的是某个来源的历史快照，不表示该版本中的模型仍是当前默认推荐模型。

常用选项：

```powershell
python .\sync_model_catalog.py --offline                 # 只读本机 bundled
python .\sync_model_catalog.py --base cli-bundled       # 使用 PATH CLI
python .\sync_model_catalog.py --base github-main       # 使用上游 main
python .\sync_model_catalog.py --strict --check         # 发布前检查
python .\sync_model_catalog.py --no-pricing-enrichment  # 保留上游原始 description
```

<a id="install"></a>
## 最省事的安装

Codex 启动时加载 `model_catalog_json` 指向的一份目录。直接使用项目根目录的 [`model_catalog.json`](model_catalog.json) 即可。

只使用 OpenAI 模型时无需额外生成。要把第三方模型一起合并到根目录，执行对应预设：

```powershell
python .\sync_model_catalog.py --preset grok       # 加入 Grok，包含 grok-4.6
python .\sync_model_catalog.py --preset deepseek   # 加入 DeepSeek
python .\sync_model_catalog.py --preset kimi       # 加入 Kimi K3
python .\sync_model_catalog.py --preset glm        # 加入 GLM-5.3、GLM-5.3 Flash
python .\sync_model_catalog.py --preset gemini     # 加入 Gemini 3.7 Flash
python .\sync_model_catalog.py --preset minimax    # 加入 MiniMax M3
python .\sync_model_catalog.py --preset hunyuan    # 加入 Hy4 Preview
python .\sync_model_catalog.py --preset claude     # 加入 Claude Opus 5、Opus 4.8、Opus 4.6、Sonnet 4.6
python .\sync_model_catalog.py --preset all        # 加入全部第三方模型
```

`--preset` 会把第三方模型合并进根目录的 `model_catalog.json`。以后同步时继续带上同一个预设，否则根目录会恢复为默认 OpenAI 目录。

然后复制生成的根目录文件：

```powershell
$codexConfigDir = Join-Path ([Environment]::GetFolderPath("UserProfile")) ".codex"
$codexCatalogDir = Join-Path $codexConfigDir "model-catalogs"
New-Item -ItemType Directory -Force -Path $codexCatalogDir | Out-Null
Copy-Item .\model_catalog.json (Join-Path $codexCatalogDir "model_catalog.json") -Force
```

在用户级 `~/.codex/config.toml` 中引用它：

```toml
model_catalog_json = "C:/Users/<username>/.codex/model-catalogs/model_catalog.json"
```

重启 Codex 后检查目录：

```powershell
codex debug models
```

`third_party/{grok,deepseek,kimi,glm,gemini,minimax,hunyuan,claude}.json` 是同步器使用的厂商基线，不要直接复制给 Codex。合并 catalog 只增加模型条目，不修改现有 API 连接设置。长期要从官方 OpenAI 目录里拿掉的模型写在 [`model_overrides.json`](model_overrides.json) 的 `remove_models`，当前会移除 `gpt-5.2`。

<a id="third-party"></a>
## 官方厂商基线

`third_party/{grok,deepseek,kimi,glm,gemini,minimax,hunyuan,claude}.json` 中的模型 ID、上下文和接口能力以各厂商官方资料为准，统一标记为 `classification: official`。其中 Codex 专用字段仍由本仓库适配，因此同时标记为 `codex_adapter: repository-maintained`，不宣称是厂商发布的原始 `model_catalog.json`。

这些基线不会默认写入最终目录。选择预设后重新生成：

| 预设 | 当前模型 | 接口要求 | 一键生成 |
| --- | --- | --- | --- |
| [Grok](third_party/grok.json) | `grok-4.6`、`grok-4.5`、`grok-4.20-multi-agent-0309`、`grok-build-0.1` | xAI 支持 Responses，可直连；Grok 4.6 支持 `xhigh`；Multi Agent 的 `xhigh` 使用 16 个协作代理 | `python .\sync_model_catalog.py --preset grok` |
| [DeepSeek](third_party/deepseek.json) | `deepseek-v4-pro`、`deepseek-v4-flash` | V4 Flash 原生 Responses；V4 Pro 需协议网关 | `python .\sync_model_catalog.py --preset deepseek` |
| [Kimi](third_party/kimi.json) | `kimi-k3` | 官方 Codex 指南使用协议网关 | `python .\sync_model_catalog.py --preset kimi` |
| [GLM](third_party/glm.json) | `glm-5.3`、`glm-5.3-flash` | Z.ai 支持 Responses；始终启用思考，编码任务推荐 `max` | `python .\sync_model_catalog.py --preset glm` |
| [Gemini](third_party/gemini.json) | `gemini-3.7-flash` | 官方 Chat Completions / Vertex，Codex 需协议网关 | `python .\sync_model_catalog.py --preset gemini` |
| [MiniMax](third_party/minimax.json) | `MiniMax-M3` | 官方推荐 Anthropic Messages 或 Chat Completions，需协议网关 | `python .\sync_model_catalog.py --preset minimax` |
| [Hunyuan](third_party/hunyuan.json) | `hy4-preview` | 腾讯云 TokenHub Chat Completions，需协议网关；仍为 Preview | `python .\sync_model_catalog.py --preset hunyuan` |
| [Claude](third_party/claude.json) | `claude-opus-5`、`claude-opus-4.8`、`claude-opus-4.6`、`claude-sonnet-4.6` | Anthropic Messages，需协议网关或 OpenRouter | `python .\sync_model_catalog.py --preset claude` |
| 全部 | 上述全部 | 按各厂商要求配置 | `python .\sync_model_catalog.py --preset all` |

`sync.cmd --preset all` 同样可用。`--preset` 可以重复，例如 `--preset grok --preset kimi`。`--no-overrides` 只跳过 [`model_overrides.json`](model_overrides.json)，不会跳过显式选择的预设。

模型参数依据厂商当前文档维护；每份 JSON 的 `metadata.verified_on`、协议和来源也会随模型一起校验：[xAI 模型](https://docs.x.ai/developers/models)、[DeepSeek 定价与模型](https://api-docs.deepseek.com/quick_start/pricing)、[Kimi 模型列表](https://platform.kimi.ai/docs/models)、[Z.ai 模型与价格](https://docs.z.ai/guides/overview/pricing)、[Gemini 3.7 Flash](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-7-flash)、[MiniMax 文本模型](https://platform.minimaxi.com/docs/guides/text-generation)、[Hy4 Preview API](https://www.tencentcloud.com/techpedia/147981)、[Claude 模型概览](https://platform.claude.com/docs/en/models/overview)。当前 DeepSeek V4 Flash 和 GLM 可使用原生 Responses 集成；V4 Pro、Kimi、Gemini、MiniMax、Hy4、Claude 以及其他 Chat Completions / Messages 端点仍应通过支持协议转换的网关使用。

<a id="routes"></a>
## 第三方路由

`third_party/routes/` 维护社区或聚合渠道。每个路由的 `route.json` 保存 Base URL、协议、官方模型到路由模型的映射、核验日期和来源；每个厂商子目录里的 `model_catalog.json` 只包含标准 `{"models": [...]}`，可以直接配置给 Codex。

| 路由 | 标准目录 | 规则 |
| --- | --- | --- |
| [CC Switch](third_party/routes/cc-switch/route.json) | `cc-switch/<vendor>/model_catalog.json` | 保留厂商 slug；按当前 Provider 决定原生 Responses 或本地转换 |
| [LiteLLM](third_party/routes/litellm/route.json) | `litellm/<vendor>/model_catalog.json` | 保留厂商 slug；LiteLLM `model_list` 必须配置同名 `model_name` alias |
| [OpenRouter](third_party/routes/openrouter/route.json) | `openrouter/<vendor>/model_catalog.json` | 使用 `x-ai/...`、`deepseek/...`、`moonshotai/...`、`z-ai/...`、`google/...`、`minimax/...`、`tencent/...`、`anthropic/...` 命名空间 slug；未上架模型不生成 |

普通同步会从官方厂商基线重建全部 24 份 route catalogs；`--strict --check` 也会检查它们是否过期。`--no-routes` 可只处理主目录。路由目录是生成文件，修改模型能力应回到官方厂商基线，修改 slug 或路由限制应修改对应 `route.json`。

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
third_party/{grok,deepseek,kimi,glm,gemini,minimax,hunyuan,claude}.json
third_party/routes/<route>/<vendor>/model_catalog.json
third_party/routes/<route>/route.json
```

App / CLI 使用完整语义版本号并按新到旧排序；`main` 按内容哈希保存。相同内容不会重复归档，同版本内容变化时不会覆盖旧文件。完整版本、哈希和来源见 [`catalogs/INDEX.md`](catalogs/INDEX.md)。

<a id="config"></a>
## Codex 配置

在用户级 `~/.codex/config.toml` 引用最终目录：

```toml
model_catalog_json = "C:\\absolute\\path\\to\\model_catalog.json"
```

详见 [官方配置参考](https://developers.openai.com/codex/config-reference/)。配置后重启 Codex，并执行 `codex debug models` 检查有效目录。

<a id="pricing"></a>
## 厂商 / 价格展示从哪里来

Codex 官方 `model_catalog` **没有**结构化的 provider / price 字段。`/model` 选择器只会渲染：

- 左侧：`slug`
- 右侧：`description`

因此本仓库用 [`pricing_metadata.json`](pricing_metadata.json) 维护展示用定价，并在同步时把 `description` 重写为：

`{provider} · {context} · ${input}/M input · ${output}/M output · Vision|Text`

| 优先级 | 来源 | 用途 |
| --- | --- | --- |
| 1 | 厂商官方定价页 | 默认写入价格：OpenAI、xAI、DeepSeek、Kimi、Z.ai、MiniMax、Anthropic |
| 2 | [models.dev](https://models.dev/api.json) | 开源社区聚合目录，适合发现渠道、模型 ID 和价格差异；写入前仍需回查厂商官方资料 |
| 3 | [LiteLLM `model_prices_and_context_window.json`](https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json) | 社区聚合兜底；新模型可能滞后 |
| 4 | 网关报价（OpenRouter 等） | 本仓库默认**不**采用，避免把中转加价写成“官方价” |

来源裁决规则：优先采用厂商官方文档和官方定价页；`models.dev` 用于发现模型、渠道和模型 ID，并做交叉验证，但不能覆盖厂商官方字段；LiteLLM 等社区目录仅在官方资料不可用时兜底；OpenRouter 等网关的价格只表示该网关渠道的实际报价，不作为厂商官方价格。来源冲突时保留官方来源，并在 `verified_on`、`source_url` 和备注中记录核验依据。

当前策略：

- 货币：USD
- 单位：每 100 万 tokens（`$/M`）
- 档位：标准短上下文、未命中缓存（cache-miss）API 价
- 上下文：来自 catalog 的 `context_window`
- Vision/Text：来自 catalog 的 `input_modalities`
- OpenRouter / LiteLLM / CC Switch 路由目录会显示同样的官方基线价，并在 `display_name` 上保留路由后缀

价格会变。更新时请改 `pricing_metadata.json` 的 `models`、`verified_on` 和 `source_url`，然后重新 `python .\sync_model_catalog.py --preset all`。

<a id="verify"></a>
## 验证

```powershell
python -B -m unittest discover -s tests -v
python -B .\sync_model_catalog.py --strict --check
```

GitHub Actions 会运行单元测试并校验 JSON、官方分类、route manifests 和所有生成目录。项目只保留同步脚本、测试、当前目录、版本归档和第三方预设；不要提交 `auth.json`、`models_cache.json` 或用户级 `config.toml`。

上游：[OpenAI/codex](https://github.com/openai/codex) · [models.json](https://github.com/openai/codex/blob/main/codex-rs/models-manager/models.json)
