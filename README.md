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

同步还会为缺失字段做 CLI 兼容补齐。当前常见问题是 Codex App 目录可能省略 `supports_reasoning_summaries` 或 `supports_parallel_tool_calls`，而 Codex CLI 0.144.x 加载 `model_catalog_json` 时会把它们当作必填字段；脚本会自动补上，避免 `failed to parse model_catalog_json`。

价格展示会按当前 catalog 内所有带定价的模型统一列宽对齐（provider / context / input / output），让 monospaced `/model` 列表更整齐。

`catalogs/` 中的 GPT 目录来自 OpenAI Codex CLI、App 或 [`openai/codex`](https://github.com/openai/codex)，索引统一标记为 `classification: official`，归档 JSON 保持官方原始内容。归档记录的是某个来源的历史快照，不表示该版本中的模型仍是当前默认推荐模型。

常用选项：

```powershell
python .\sync_model_catalog.py --offline                 # 只读本机 bundled
python .\sync_model_catalog.py --base cli-bundled       # 使用 PATH CLI
python .\sync_model_catalog.py --base github-main       # 使用上游 main
python .\sync_model_catalog.py --base github-main --preset all --strict --check  # 发布前检查当前全量目录
python .\sync_model_catalog.py --no-pricing-enrichment  # 保留上游原始 description
```

Windows 上若 `python` 指向 Microsoft Store 占位命令，可改用 `py`；macOS / Linux 使用 `python3` 和 `./sync_model_catalog.py`。

<a id="install"></a>
## 最省事的安装

Codex 启动时加载 `model_catalog_json` 指向的一份目录。直接使用项目根目录的 [`model_catalog.json`](model_catalog.json) 即可。

仓库当前提交的根目录已按 `--preset all` 合并现有厂商；只使用 OpenAI 时，重新同步且不带 `--preset` 即可。根目录模型按以下固定厂商顺序排列：

**OpenAI、Claude、Grok、Gemini、Meta、Qwen、Hunyuan、DeepSeek、GLM、Kimi、MiniMax、Xiaomi**。

要把第三方模型一起合并到根目录，执行对应预设：

```powershell
python .\sync_model_catalog.py --preset claude     # 加入 Claude Opus、Fable、Sonnet、Haiku
python .\sync_model_catalog.py --preset grok       # 加入 Grok 4.7、4.20 Multi-Agent、Build
python .\sync_model_catalog.py --preset gemini     # 加入 Gemini 4 Argon、Flash、Flash Lite、Pro Preview
python .\sync_model_catalog.py --preset muse       # 保留 Meta Muse 渠道专属 Contributor 条目
python .\sync_model_catalog.py --preset qwen       # 加入 Qwen Max、Plus、Flash
python .\sync_model_catalog.py --preset hunyuan    # 加入 Hy4 Preview
python .\sync_model_catalog.py --preset deepseek   # 加入 DeepSeek
python .\sync_model_catalog.py --preset glm        # 加入 GLM-5.3、GLM-5.3 Flash
python .\sync_model_catalog.py --preset kimi       # 加入 Kimi K3、K2.7 Code、K2.6
python .\sync_model_catalog.py --preset minimax    # 加入 MiniMax M3、M3.1 Flash Preview
python .\sync_model_catalog.py --preset mimo       # 加入 Xiaomi MiMo V2.6 Pro
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

### macOS / Linux

同一份 `model_catalog.json` 可直接复制使用，不需要转换格式。所有生成目录均为 UTF-8（无 BOM）、LF 换行的标准 `{"models": [...]}` JSON，不包含用于定位文件的 Windows 绝对路径。`shell_command` / `unified_exec` 是 Codex 工具类型，不是 Windows shell 路径。

在项目根目录执行：

```bash
# 可选：离线重新生成现有厂商的全量目录
python3 ./sync_model_catalog.py --offline --preset all
mkdir -p "$HOME/.codex/model-catalogs"
cp ./model_catalog.json "$HOME/.codex/model-catalogs/model_catalog.json"
printf 'model_catalog_json = "%s/.codex/model-catalogs/model_catalog.json"\n' "$HOME"
```

把最后一条命令输出的配置行放到 `~/.codex/config.toml` 的顶层，替换原有同名项；不要放进 `[model_providers.*]` 等表中，也不要重复添加。不依赖 TOML 自动展开 `~` 或 `$HOME`。配置示例：

```toml
model_catalog_json = "/Users/<username>/.codex/model-catalogs/model_catalog.json"
```

重启后执行 `codex debug models`。也可不修改用户配置，直接验证项目目录：

```bash
python3 -B ./verify_codex_catalogs.py
```

`third_party/{grok,deepseek,kimi,glm,gemini,minimax,hunyuan,claude,qwen,muse,mimo}.json` 是同步器使用的厂商基线，不要直接复制给 Codex。合并 catalog 只增加模型条目，不修改现有 API 连接设置。长期要从官方 OpenAI 目录里拿掉的模型写在 [`model_overrides.json`](model_overrides.json) 的 `remove_models`；当前保留 GPT-6 Astra、GPT-6.1 Sol、GPT-6 Luna，以及仍在售的 GPT-5.6 Sol（API 别名 `gpt-5.6`，目录只显示规范 ID），同时保留现有 Terra 等条目。移除旧 GPT-6 Sol、旧 GPT-5.6 Luna、Daybreak 和 Codex Auto Review。GPT-6.1 Sol 还有显式兼容条目，避免旧版 CLI bundled 基线缺少此模型。

当前根目录还会通过 [`model_overrides.json`](model_overrides.json) 显示 GPT-6 Astra（`gpt-6-astra`）。该模型来自 OpenAI API 文档和 Codex 上游目录，支持 Responses、图片输入、工具调用以及 `low` 到 `ultra` 的 Codex 推理级别。

<a id="third-party"></a>
## 官方厂商基线

`third_party/{grok,deepseek,kimi,glm,gemini,minimax,hunyuan,claude,qwen,muse,mimo}.json` 中的模型 ID、上下文和接口能力以各厂商官方资料为准，统一标记为 `codex_adapter: repository-maintained`。除 Meta / Muse 外使用 `classification: official`；Meta 在用户提供的信息中没有统一云 API ID，现有 `muse-spark-1.3-contributor` 只作为 `classification: third-party` 的渠道兼容条目保留。

这些基线不会默认写入最终目录。选择预设后重新生成：

| 预设 | 当前模型 | 接口要求 | 一键生成 |
| --- | --- | --- | --- |
| [Claude](third_party/claude.json) | `claude-fable-5-1`、`claude-opus-5-5`、`claude-sonnet-5-5`、`claude-haiku-5-5` | Anthropic Messages，需协议网关或 OpenRouter | `python .\sync_model_catalog.py --preset claude` |
| [Grok](third_party/grok.json) | `grok-4.7`、`grok-4.20-multi-agent`、`grok-build-0.1` | xAI 支持 Responses，可直连；Multi-Agent 和 Build 是独立用途例外 | `python .\sync_model_catalog.py --preset grok` |
| [Gemini](third_party/gemini.json) | `gemini-4-argon`、`gemini-3.8-flash`、`gemini-3.5-flash-lite`、`gemini-3.5-flash`、`gemini-3.1-pro` | Argon 最新旗舰；其余 Flash、低成本和 Preview Pro 保留；Codex 需协议网关 | `python .\sync_model_catalog.py --preset gemini` |
| [Meta / Muse](third_party/muse.json) | `muse-spark-1.3-contributor`（渠道兼容） | 没有统一官方云 API ID；需协议网关 | `python .\sync_model_catalog.py --preset muse` |
| [Qwen](third_party/qwen.json) | `qwen3.8-max`、`qwen3.7-plus`、`qwen3.8-flash` | Alibaba Cloud Model Studio，支持 OpenAI / Anthropic 兼容协议 | `python .\sync_model_catalog.py --preset qwen` |
| [Hunyuan](third_party/hunyuan.json) | `hy4-preview` | 腾讯云 TokenHub Chat Completions，需协议网关；仍为 Preview | `python .\sync_model_catalog.py --preset hunyuan` |
| [DeepSeek](third_party/deepseek.json) | `deepseek-v4-pro`、`deepseek-flash` | Base URL：`https://api.deepseek.com`；旧 `deepseek-v4-flash` 请求转到 `deepseek-flash` | `python .\sync_model_catalog.py --preset deepseek` |
| [GLM](third_party/glm.json) | `glm-5.3`、`glm-5.3-flash` | Z.ai 支持 Responses；始终启用思考，编码任务推荐 `max` | `python .\sync_model_catalog.py --preset glm` |
| [Kimi](third_party/kimi.json) | `kimi-k3`、`kimi-k2.7-code`、`kimi-k2.6` | Base URL：`https://api.moonshot.cn/v1`；官方 API 支持 OpenAI / Anthropic 兼容协议 | `python .\sync_model_catalog.py --preset kimi` |
| [MiniMax](third_party/minimax.json) | `MiniMax-M3.1-Flash-Preview`、`MiniMax-M3` | 官方推荐 Anthropic Messages 或 Chat Completions；Preview 目前仅 Token Plan / MiniMax Code | `python .\sync_model_catalog.py --preset minimax` |
| [Xiaomi / MiMo](third_party/mimo.json) | `mimo-v2.6-pro` | Xiaomi API / OpenAI 兼容协议，需协议网关 | `python .\sync_model_catalog.py --preset mimo` |
| 全部 | 上述全部 | 按各厂商要求配置 | `python .\sync_model_catalog.py --preset all` |

`sync.cmd --preset all` 同样可用。`--preset` 可以重复，例如 `--preset grok --preset kimi`。`--no-overrides` 只跳过 [`model_overrides.json`](model_overrides.json)，不会跳过显式选择的预设。

2026-10-14 的 ID 更新按用户提供的官方清单执行，记录在 `metadata.model_ids_updated_on`，不把原有 `verified_on` 冒充为重新核验的能力或价格日期。新增 Sonnet/Haiku、Gemini 3.5/3.1、Qwen Plus 和 Kimi K2.6 使用保守的 128K、文本输入适配预算以及单一 `medium` 网关默认 effort；这些不是厂商上下文上限或官方推理档位声明，使用前需确认网关支持。未提供可靠价格的新增条目保留说明，不编造定价。

另于 2026-10-14 联网核验并加入 **Gemini 4 Argon**（官方发布文章标注 2026-10-13）：[Google Cloud 官方模型页](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/4-argon) 明确 ID 为 `gemini-4-argon`，统一输入输出 token 上限为 1,048,576，thinking 为 `low` / `medium`（默认）/ `high`。[Google 官方发布文章](https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-4-argon/) 公布首发价为 $2/M 输入、$10/M 输出。生成目录保留文本、图片、音频输入，按 Codex schema 过滤视频。Argon 单独记录核验日期，不改变其他模型的旧核验日期。官方支持不代表所有网关都支持相同模态与工具能力，需确认实际路由配置。

模型参数依据厂商当前文档维护；每份 JSON 的 `metadata.verified_on`、协议和来源也会随模型一起校验：[Claude 模型概览](https://platform.claude.com/docs/en/models/overview)、[xAI 模型](https://docs.x.ai/developers/models)、[Gemini 3.8 Flash](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash)、[Meta Muse](https://openrouter.ai/meta/muse-spark-1.3-contributor)、[Qwen](https://www.alibabacloud.com/help/en/model-studio/qwen3-8-max)、[DeepSeek 定价与模型](https://api-docs.deepseek.com/quick_start/pricing)、[Kimi 模型列表](https://platform.kimi.ai/docs/models)、[Z.ai 模型与价格](https://docs.z.ai/guides/overview/pricing)、[MiniMax 文本模型](https://platform.minimaxi.com/docs/guides/text-generation)、[Hy4 Preview API](https://www.tencentcloud.com/techpedia/147981)、[MiMo](https://mimo.xiaomi.com/)。当前 DeepSeek 两个模型、GLM 和 Qwen3.8 Flash 可使用相应原生兼容接口；Kimi、Gemini、MiniMax、Hy4、Claude、Muse、MiMo 以及其他 Chat Completions / Messages 端点仍应通过支持协议转换的网关使用。

<a id="routes"></a>
## 第三方路由

`third_party/routes/` 维护社区或聚合渠道。每个路由的 `route.json` 保存 Base URL、协议、官方模型到路由模型的映射、核验日期和来源；每个厂商子目录里的 `model_catalog.json` 只包含标准 `{"models": [...]}`，可以直接配置给 Codex。

| 路由 | 标准目录 | 规则 |
| --- | --- | --- |
| [CC Switch](third_party/routes/cc-switch/route.json) | `cc-switch/<vendor>/model_catalog.json` | 保留厂商 slug；按当前 Provider 决定原生 Responses 或本地转换 |
| [LiteLLM](third_party/routes/litellm/route.json) | `litellm/<vendor>/model_catalog.json` | 保留厂商 slug；LiteLLM `model_list` 必须配置同名 `model_name` alias |
| [OpenRouter](third_party/routes/openrouter/route.json) | `openrouter/<vendor>/model_catalog.json` | 使用经 `/api/v1/models` 核验的渠道 slug；MiniMax Preview 未列入 OpenRouter 路由 |

普通同步会从官方厂商基线重建全部 33 份 route catalogs；`--strict --check` 也会检查它们是否过期。`--no-routes` 可只处理主目录。路由目录是生成文件，修改模型能力应回到官方厂商基线，修改 slug 或路由限制应修改对应 `route.json`。

官方 ID 与渠道 ID 分开维护：例如 Gemini Pro 在根目录、CC Switch 和 LiteLLM 为 `gemini-3.1-pro`，OpenRouter 为实时模型列表核验得到的 `google/gemini-3.1-pro-preview`。本次未新增厂商，豆包不在现有预设中，因此不新增豆包目录。

Argon 在根目录、CC Switch 和 LiteLLM 使用 `gemini-4-argon`，OpenRouter 使用实时 `/api/v1/models` 已核验的 `google/gemini-4-argon`。LiteLLM 需配置同名 `model_name`，CC Switch 的上游也需已支持该模型。

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
third_party/{grok,deepseek,kimi,glm,gemini,minimax,hunyuan,claude,qwen,muse,mimo}.json
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
- Codex 当前只接受 `text`、`image`、`audio` 三种输入模态；厂商支持但 Codex schema 尚不接受的 `video` 会在生成目录中自动过滤，避免客户端启动失败
- OpenRouter / LiteLLM / CC Switch 路由目录会显示同样的官方基线价，并在 `display_name` 上保留路由后缀
- 没有可靠官方价格的模型（例如 Kimi K2.7 Code、MiniMax M3.1 Flash Preview）不编造价格；MiniMax Preview 的官方文档还限制为 Token Plan / MiniMax Code

价格会变。更新时请改 `pricing_metadata.json` 的 `models`、`verified_on` 和 `source_url`，然后重新 `python .\sync_model_catalog.py --preset all`。

<a id="verify"></a>
## 验证

```powershell
python -B -m unittest discover -s tests -v
python -B .\sync_model_catalog.py --base github-main --preset all --strict --check
```

本次根目录以本机 CLI 0.158.0 的 bundled 为基线生成；GitHub TLS 握手超时后使用离线来源，未宣称获得最新 main 快照。可按相同来源复验：

```powershell
py -B .\sync_model_catalog.py --offline --base cli-bundled --preset all --strict --check
py -B .\verify_codex_catalogs.py
```

[`verify_codex_catalogs.py`](verify_codex_catalogs.py) 使用隔离的临时 `CODEX_HOME`，让本机 `codex debug models` 逐份加载根目录和 33 份路由目录，并对比 ID 和关键字段。它不读取用户凭据、不修改用户配置、不发送模型推理请求，因此验证的是客户端格式和加载兼容性，不代表所有厂商 API 已端到端调用成功。macOS 用 `python3 -B ./verify_codex_catalogs.py` 执行同样验证；本次实际 CLI 验证运行于 Windows。

GitHub Actions 会运行单元测试并校验 JSON、官方分类、route manifests 和所有生成目录。项目只保留同步脚本、测试、当前目录、版本归档和第三方预设；不要提交 `auth.json`、`models_cache.json` 或用户级 `config.toml`。

上游：[OpenAI/codex](https://github.com/openai/codex) · [models.json](https://github.com/openai/codex/blob/main/codex-rs/models-manager/models.json)
