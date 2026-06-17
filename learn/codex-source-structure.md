# Codex 源码目录结构与学习路线

生成日期：2026-06-17  
仓库路径：`/Users/xiaodong/Desktop/learn/codex`

## 统计口径

- “主实现 Rust 行”统计 `.rs` 非空行，排除 `tests/`、`benches/`、`examples/`、`*_tests.rs`、`tests.rs`、`test_support.rs`、快照和 `target/`。
- “Rust 行（含测试）”统计 `.rs` 非空行，排除快照和 `target/`，但包含测试代码。
- 顶层目录的“源码/配置行”统计常见源码和配置文件非空行，排除 `.git`、`target`、`node_modules`、`vendor`、`third_party`、`schema`、`fixtures`、`snapshots`、`.snap`、lockfile。`codex-rs/` 的详细数字以 crate 表为准。
- 这些数字适合做阅读成本和模块规模对比，不等价于严格语义 SLOC。

## 一句话架构

Codex CLI 的主体在 `codex-rs/`：用户通过 npm 包装层或 Rust CLI 进入 `codex-cli`，交互模式进入 `codex-tui`，无交互命令进入 `codex-exec`，IDE/桌面/远程控制走 `codex-app-server`。这些前端最终都围绕 `codex-core` 的线程、会话、turn、上下文和工具调度运行，再通过 `codex-api`、`codex-client` 和模型 provider 访问模型，并把 shell、patch、MCP、插件、技能、子代理等动作交给工具和执行层。

```text
codex-cli npm wrapper / native binary
        |
        v
codex-rs/cli
   |-- interactive --> codex-tui --> codex-app-server-client
   |-- non-interactive --> codex-exec --> codex-app-server-client
   |-- app/server mode --> codex-app-server
        |
        v
codex-core: thread/session/turn/context/tools
        |
        +--> codex-api / codex-client / model-provider
        +--> exec, exec-server, sandboxing, apply-patch
        +--> codex-mcp, core-plugins, core-skills, ext/*
        +--> rollout, state, thread-store
```

## 顶层目录

| 路径 | 代码量 | 作用 |
| --- | ---: | --- |
| `.codex/` | 636 源码/配置行 | 本仓库自带的 Codex 环境、技能和本地运行配置。 |
| `.devcontainer/` | 399 源码/配置行 | Devcontainer 安装和开发环境配置。 |
| `.github/` | 8,778 源码/配置行 | CI、issue 模板、GitHub Actions 和仓库自动化脚本。 |
| `.vscode/` | 61 源码/配置行 | VS Code 工作区建议配置。 |
| `bazel/` | 1,019 源码/配置行 | Bazel 平台、规则和测试辅助定义。 |
| `codex-cli/` | 759 源码/配置行 | npm 包装层，负责发布 `@openai/codex`、定位并启动平台 native binary。 |
| `codex-rs/` | 955,576 源码/配置行；workspace 主实现 Rust 574,686 行，含测试 919,976 行 | Codex 的核心 Rust monorepo，包含 CLI、TUI、agent 核心、app server、执行、沙箱、MCP、插件、技能、协议和 SDK 相关实现。 |
| `docs/` | 文档未计入代码量 | 仓库贡献、安装、维护类文档。产品文档不在这里。 |
| `learn/` | 0 行（写入本文前） | 本次分析文档所在目录。 |
| `patches/` | 30 源码/配置行 | 仓库维护用 patch。 |
| `scripts/` | 4,504 源码/配置行 | 安装、打包、发布和辅助脚本。 |
| `sdk/` | 20,302 源码/配置行 | Python、Python runtime、TypeScript SDK。 |
| `third_party/` | 外部依赖未计入 | 大型第三方源码或预置依赖，如 V8、wezterm、wine、PowerShell。阅读 Codex 实现时通常跳过。 |
| `tools/` | 1,379 源码/配置行 | 仓库级工具，例如 argument-comment-lint。 |
| 根目录文件 | 5,482 源码/配置行 | `README.md`、`justfile`、Bazel 根配置、许可证、变更日志、workspace 配置等。 |

## `codex-rs/` 结构总览

`codex-rs/` 是一个 Rust workspace，当前 `members` 中有 121 个 crate。还有少数 path dependency 不在 workspace members 中，例如 `chatgpt/`、`message-history/`、`windows-sandbox-rs/` 和若干测试支持 crate。

从职责上可以分成这些层：

| 层 | 主要目录 | 主实现 Rust 行 | 作用 |
| --- | --- | ---: | --- |
| 用户入口和界面 | `cli`、`tui`、`exec`、`cloud-tasks`、`codex-cli/` | 约 180k | 解析命令、启动交互 TUI、无交互执行、云任务命令和用户可见输出。 |
| Agent 核心 | `core`、`protocol`、`config`、`tools`、`prompts` | 约 113k | 线程和会话生命周期、上下文构建、模型请求、工具注册和执行、配置和协议对象。 |
| App Server | `app-server*` | 约 70k | 给 IDE、桌面 app、远程控制和 in-process 客户端提供 JSON-RPC API。 |
| 模型和网络 | `codex-api`、`codex-client`、`model-provider*`、`login`、`backend-client`、`network-proxy` | 约 31k | HTTP/SSE/WebSocket、认证、模型 provider、后端接口和代理。 |
| 执行与沙箱 | `exec-server`、`exec`、`sandboxing`、`linux-sandbox`、`windows-sandbox-rs`、`execpolicy*`、`shell-*` | 约 52k | shell 执行、文件系统/进程隔离、策略检查、跨环境执行。 |
| MCP、插件、技能和扩展 | `codex-mcp`、`mcp-server`、`core-plugins`、`core-skills`、`skills`、`plugin`、`ext/*` | 约 35k | MCP 连接、插件加载、技能发现/渲染、内置扩展工具。 |
| 状态和历史 | `rollout`、`rollout-trace`、`state`、`thread-store`、`agent-graph-store` | 约 39k | 会话 JSONL、trace bundle、SQLite 索引、线程存储和子代理拓扑。 |
| 支撑库 | `utils/*`、`git-utils`、`file-*`、`otel`、`terminal-detection` 等 | 约 50k | 路径、PTY、缓存、模板、终端能力、Git、文件搜索、观测性等。 |

## 关键模块下钻

### `codex-core`

`codex-core` 是 agent 运行时核心。它不直接负责 TUI 绘制，也不负责 app-server JSON-RPC 协议形状，而是负责“一个 Codex 线程如何接受输入、构造上下文、调用模型、处理流式事件、执行工具、落盘历史和结束 turn”。

| 子模块 | 主实现 Rust 行 | 作用 |
| --- | ---: | --- |
| `core/src/tools/` | 21,129 | 工具注册、路由、并行工具、工具 handler、runtime、工具调用 trace。shell、apply_patch、MCP、subagent、plan、permission、image/view 等工具入口都在这里汇合。 |
| `core/src/session/` | 10,536 | 会话状态、turn 生命周期、输入队列、MCP 初始化、review、multi-agent、token budget 和 rollout 重建。 |
| `core/src/config/` | 7,367 | core 层配置、权限 profile、auth keyring、配置 schema、网络代理 spec。 |
| `core/src/guardian/` | 4,379 | Guardian 审核、审批请求、review session、指标和提示词。 |
| `core/src/agent/` | 2,510 | 子代理和 agent role、registry、控制、驻留与 spawn 逻辑。 |
| `core/src/unified_exec/` | 2,481 | 统一执行路径相关实现。 |
| `core/src/client.rs` | 2,147 | 模型客户端封装，发送请求并接收 Responses 流。 |
| `core/src/mcp_tool_call.rs` | 2,030 | MCP tool call 的执行、审批、结果映射和错误处理。 |
| `core/src/tasks/` | 1,746 | regular/review/compact/user shell 等任务类型的生命周期。 |
| `core/src/context/` | 1,638 | 注入模型上下文的片段类型，例如环境、技能、插件、权限、用户指令。 |
| `core/src/thread_manager.rs` | 1,627 | 线程管理入口，创建、恢复、关闭线程并连接 thread store。 |
| `core/src/realtime_conversation.rs` | 1,611 | 实时对话路径。 |
| `core/src/exec.rs` | 1,446 | core 层 shell/命令执行协调。 |
| `core/src/context_manager/` | 1,232 | 历史上下文维护、normalize、增量更新，避免无界上下文和缓存抖动。 |
| `core/src/exec_policy.rs` | 958 | exec policy 加载、检查和错误格式化。 |
| `core/src/hook_runtime.rs` | 859 | Hook 运行时调度。 |
| `core/src/codex_delegate.rs` | 850 | core 与上层 delegate 的桥接。 |
| `core/src/compact*.rs` | 1,837 | 本地/远程 compaction 逻辑。 |
| `core/src/state/` | 767 | core 内部状态服务与 turn/session 状态。 |
| `core/src/plugins/` | 284 | core 内插件渲染、mention、discoverable 入口。更完整的插件逻辑在 `core-plugins`。 |

### `codex-tui`

`codex-tui` 是终端交互界面，负责绘制聊天历史、输入框、弹窗、审批、状态、快捷键、markdown、diff、会话恢复和与 app-server/core 的交互。它是最大的单个前端 crate。

| 子模块 | 主实现 Rust 行 | 作用 |
| --- | ---: | --- |
| `tui/src/bottom_pane/` | 45,991 | 输入框、footer、弹窗、slash command、技能/插件/MCP/审批/设置视图。阅读 UI 时最大的一块。 |
| `tui/src/chatwidget/` | 17,989 | 聊天主控件的事件处理、turn 生命周期、工具请求、审批、状态、协议请求、设置弹窗。 |
| `tui/src/app/` | 14,566 | App 级状态和事件分发，线程路由、session 生命周期、app-server 事件、后台请求。 |
| `tui/src/resume_picker.rs` | 5,763 | 会话恢复选择界面。 |
| `tui/src/history_cell/` | 4,229 | 历史消息、工具结果、patch、approval、plan 等单元格渲染。 |
| `tui/src/pets/` | 3,489 | TUI 内的 pet/status 相关 UI。 |
| `tui/src/lib.rs` | 2,856 | TUI crate 导出和总体组装。 |
| `tui/src/keymap.rs` | 2,738 | 键位映射模型。 |
| `tui/src/streaming/` | 2,630 | 流式输出处理。 |
| `tui/src/onboarding/` | 2,612 | 初次使用、登录、信任目录等 onboarding 流程。 |
| `tui/src/markdown_render.rs` | 2,551 | Markdown 到 ratatui 渲染。 |
| `tui/src/app_server_session.rs` | 2,409 | TUI 与 app-server session 的桥接。 |
| `tui/src/diff_render.rs` | 2,324 | diff 渲染。 |
| `tui/src/render/` | 1,992 | 通用渲染辅助。 |
| `tui/src/chatwidget.rs` | 1,906 | chatwidget 顶层编排。 |
| `tui/src/wrapping.rs` | 1,481 | 文本换行辅助。 |

### App Server 和协议

App Server 是 Codex 面向 IDE、桌面应用、远程控制、in-process 客户端的 JSON-RPC 服务层。它把外部 API 请求映射到 thread、turn、config、MCP、filesystem、feedback、git、account 等处理器。

| 模块 | 主实现 Rust 行 | 作用 |
| --- | ---: | --- |
| `app-server-protocol/src/protocol/` | 17,308 | v1/v2 JSON-RPC request、response、notification、event mapping、thread history 等 wire type。 |
| `app-server/src/request_processors/` | 16,189 | 各类 RPC 方法处理器：thread、turn、config、MCP、git、fs、feedback、environment、marketplace 等。 |
| `app-server/src/bespoke_event_handling.rs` | 3,851 | 将 core/app 事件转换成 app-server 需要的通知和状态。 |
| `app-server-transport/src/transport/` | 9,114 | stdio、websocket、control socket、remote-control 传输层。 |
| `app-server-client/` | 3,175 | TUI/exec 使用的 in-process app-server 客户端 facade。 |
| `app-server-daemon/` | 2,762 | app-server 后台生命周期管理、托管安装、远程控制客户端。 |
| `app-server/src/message_processor.rs` | 1,440 | JSON-RPC 消息分发主循环。 |
| `app-server/src/thread_state.rs` | 509 | app-server 视角的线程状态。 |

### 模型、网络和工具定义

| 模块 | 主实现 Rust 行 | 作用 |
| --- | ---: | --- |
| `codex-api/src/endpoint/` | 6,027 | Responses、models、images、memories、search、compact、realtime 等 API endpoint client。 |
| `codex-api/src/sse/` | 1,277 | Responses SSE 流解析。 |
| `codex-client/` | 1,902 | HTTP transport、retry、SSE、custom CA、请求体封装。 |
| `model-provider/` | 1,839 | 模型 provider 抽象、auth provider、Bedrock 等 provider 适配。 |
| `tools/src/json_schema.rs` | 716 | 工具 input schema 解析和压缩。 |
| `tools/src/tool_*` | 约 1,100 | 通用工具定义、配置、调用、输出、发现、搜索。 |

## Workspace crate 清单

下面按职责分组列出 `codex-rs/Cargo.toml` 的 workspace members。行数为 Rust 非空行。

### 入口、界面和用户命令

| 路径 | crate | 主实现 | 含测试 | 作用 |
| --- | --- | ---: | ---: | --- |
| `cli` | `codex-cli` | 17,797 | 20,153 | native `codex` 命令入口，解析顶层子命令，启动 TUI、exec、app server、登录、诊断等。 |
| `tui` | `codex-tui` | 154,963 | 191,213 | 终端交互 UI，承载聊天、审批、工具状态、配置弹窗、会话恢复和历史渲染。 |
| `exec` | `codex-exec` | 3,594 | 8,402 | 非交互执行模式，输出 human 或 JSONL 事件，适合脚本/CI。 |
| `cloud-tasks` | `codex-cloud-tasks` | 4,506 | 4,541 | 云端任务相关 CLI/TUI 流程，创建、查看、应用任务 diff。 |
| `thread-manager-sample` | `codex-thread-manager-sample` | 376 | 376 | ThreadManager 使用示例/样例二进制。 |
| `app-server-test-client` | `codex-app-server-test-client` | 3,297 | 3,379 | 用于测试或手动调试 app-server 的客户端。 |
| `bwrap` | `codex-bwrap` | 135 | 135 | bubblewrap 辅助二进制。 |
| `code-mode-host` | `codex-code-mode-host` | 1 | 1 | code mode host 的极薄入口。 |

### Agent 核心、协议和配置

| 路径 | crate | 主实现 | 含测试 | 作用 |
| --- | --- | ---: | ---: | --- |
| `core` | `codex-core` | 78,702 | 229,418 | Agent 核心：线程、会话、turn、上下文、模型调用、工具调度、执行、MCP、compaction、rollout。 |
| `protocol` | `codex-protocol` | 16,740 | 17,374 | core/TUI/app-server 共享的协议对象、事件、权限、模型、配置类型、thread/session id。 |
| `config` | `codex-config` | 14,136 | 17,042 | config.toml、profile、权限、MCP、hooks、cloud config、配置层合并和校验。 |
| `core-api` | `codex-core-api` | 93 | 93 | core API 的轻量边界类型。 |
| `tools` | `codex-tools` | 2,484 | 6,012 | 可脱离 core 复用的工具定义、Responses API tool primitive、schema、tool search。 |
| `code-mode` | `codex-code-mode` | 2,603 | 4,076 | code mode 的 in-process service、cell actor 和 runtime。 |
| `code-mode-protocol` | `codex-code-mode-protocol` | 1,277 | 1,293 | code mode session/runtime 协议、exec/wait nested tool 描述和响应类型。 |
| `prompts` | `codex-prompts` | 641 | 1,249 | 内置 prompt 和 prompt 相关常量。 |
| `features` | `codex-features` | 1,503 | 2,173 | 功能开关枚举、解析和配置。 |
| `context-fragments` | `codex-context-fragments` | 195 | 195 | 注入模型上下文的 fragment trait 和公共类型。 |
| `collaboration-mode-templates` | `codex-collaboration-mode-templates` | 4 | 4 | 协作模式模板占位/导出 crate。 |
| `feedback` | `codex-feedback` | 939 | 939 | 用户反馈、doctor report 等结构和发送辅助。 |
| `analytics` | `codex-analytics` | 5,067 | 9,568 | analytics 事件、事实、reducer、accepted line 指纹和客户端。 |
| `hooks` | `codex-hooks` | 8,569 | 10,041 | hooks 声明、配置规则、事件、执行引擎和 schema。 |

### App Server

| 路径 | crate | 主实现 | 含测试 | 作用 |
| --- | --- | ---: | ---: | --- |
| `app-server` | `codex-app-server` | 33,877 | 97,930 | JSON-RPC app server，实现 IDE/桌面/远程控制和 in-process API 的服务端逻辑。 |
| `app-server-protocol` | `codex-app-server-protocol` | 20,719 | 24,465 | app-server v1/v2 协议类型、schema/TS 生成、JSON-RPC lite。 |
| `app-server-transport` | `codex-app-server-transport` | 9,195 | 13,552 | stdio、websocket、control socket、remote-control 传输层。 |
| `app-server-client` | `codex-app-server-client` | 3,175 | 3,175 | CLI/TUI/exec 内嵌 app-server 的客户端 facade。 |
| `app-server-daemon` | `codex-app-server-daemon` | 2,762 | 3,007 | app-server 后台进程生命周期、托管安装、更新循环和 remote control client。 |

### 模型、认证、后端和网络

| 路径 | crate | 主实现 | 含测试 | 作用 |
| --- | --- | ---: | ---: | --- |
| `codex-api` | `codex-api` | 9,291 | 10,906 | OpenAI/ChatGPT API client，高层 endpoint、Responses SSE/WS、models、images、memories、search。 |
| `codex-client` | `codex-client` | 1,902 | 2,375 | HTTP transport、retry、SSE stream、custom CA、请求/响应封装。 |
| `model-provider` | `codex-model-provider` | 1,839 | 1,839 | 模型 provider 抽象与 provider-specific auth/capability。 |
| `model-provider-info` | `codex-model-provider-info` | 480 | 898 | 模型 provider 元数据和静态信息。 |
| `models-manager` | `codex-models-manager` | 842 | 1,850 | 模型目录刷新、缓存和 app 可用模型管理。 |
| `login` | `codex-login` | 5,088 | 10,071 | ChatGPT/API key 登录、token 管理、默认 HTTP client user-agent。 |
| `backend-client` | `codex-backend-client` | 1,435 | 1,501 | Codex/ChatGPT 后端接口 client，账号、任务、配置 bundle、限额等。 |
| `codex-backend-openapi-models` | `codex-backend-openapi-models` | 885 | 885 | 后端 OpenAPI 模型类型。 |
| `cloud-config` | `codex-cloud-config` | 1,013 | 2,145 | 云端下发配置的拉取、缓存、刷新和校验。 |
| `cloud-tasks-client` | `codex-cloud-tasks-client` | 1,028 | 1,028 | 云任务后端 API client 抽象。 |
| `cloud-tasks-mock-client` | `codex-cloud-tasks-mock-client` | 248 | 248 | 云任务测试/mock client。 |
| `aws-auth` | `codex-aws-auth` | 334 | 334 | AWS/Bedrock 相关认证辅助。 |
| `network-proxy` | `codex-network-proxy` | 10,142 | 10,433 | 网络代理、隧道、请求转发和策略相关实现。 |
| `responses-api-proxy` | `codex-responses-api-proxy` | 875 | 875 | Responses API 代理服务。 |
| `lmstudio` | `codex-lmstudio` | 389 | 389 | LM Studio 本地模型集成。 |
| `ollama` | `codex-ollama` | 770 | 807 | Ollama 本地模型集成。 |
| `realtime-webrtc` | `codex-realtime-webrtc` | 278 | 278 | Realtime WebRTC 辅助。 |

### 执行、沙箱和文件系统

| 路径 | crate | 主实现 | 含测试 | 作用 |
| --- | --- | ---: | ---: | --- |
| `exec-server` | `codex-exec-server` | 16,212 | 23,343 | 本地/远程执行环境、文件系统和进程 RPC，支持 executor filesystem/process 抽象。 |
| `sandboxing` | `codex-sandboxing` | 1,907 | 4,723 | 跨平台 sandbox 配置和摘要。 |
| `linux-sandbox` | `codex-linux-sandbox` | 5,544 | 7,286 | Linux sandbox 运行时。 |
| `execpolicy` | `codex-execpolicy` | 1,603 | 2,497 | 新 exec policy 引擎，基于 prefix/Starlark 规则决策命令。 |
| `execpolicy-legacy` | `codex-execpolicy-legacy` | 1,638 | 2,268 | 旧 exec policy 引擎。 |
| `shell-command` | `codex-shell-command` | 5,847 | 5,847 | shell 命令解析、展示、安全摘要和结构化表示。 |
| `shell-escalation` | `codex-shell-escalation` | 2,076 | 2,076 | shell 权限提升包装和 execve wrapper。 |
| `apply-patch` | `codex-apply-patch` | 4,139 | 4,563 | `apply_patch` patch 格式解析和文件修改执行。 |
| `file-system` | `codex-file-system` | 232 | 232 | executor 文件系统 trait、读写/复制/删除抽象。 |
| `file-search` | `codex-file-search` | 1,178 | 1,178 | 文件搜索实现和二进制入口。 |
| `file-watcher` | `codex-file-watcher` | 817 | 1,318 | 文件监听。 |
| `process-hardening` | `codex-process-hardening` | 165 | 165 | 进程硬化辅助。 |
| `stdio-to-uds` | `codex-stdio-to-uds` | 55 | 197 | stdio 与 Unix domain socket 桥接。 |
| `uds` | `codex-uds` | 276 | 380 | Unix domain socket 辅助。 |

### MCP、插件、技能和扩展

| 路径 | crate | 主实现 | 含测试 | 作用 |
| --- | --- | ---: | ---: | --- |
| `codex-mcp` | `codex-mcp` | 4,791 | 7,099 | MCP 连接管理、Codex apps MCP server、插件配置、工具/resource client。 |
| `mcp-server` | `codex-mcp-server` | 2,273 | 3,213 | Codex 暴露给 MCP 的 server，实现工具 runner 和审批桥接。 |
| `rmcp-client` | `codex-rmcp-client` | 7,615 | 9,149 | RMCP client、stdio/HTTP server 测试辅助。 |
| `core-plugins` | `codex-core-plugins` | 13,687 | 23,602 | 插件 marketplace、安装、加载、bundle、远程/本地 provider、startup sync。 |
| `plugin` | `codex-plugin` | 653 | 775 | 插件 manifest、id、provider、加载结果等共享模型。 |
| `core-skills` | `codex-core-skills` | 3,951 | 6,957 | 技能加载、渲染、注入、系统技能、远程技能和隐式调用检测。 |
| `skills` | `codex-skills` | 171 | 171 | 基础技能模型/资源入口。 |
| `ext/extension-api` | `codex-extension-api` | 1,048 | 1,699 | 扩展 API：工具、上下文、配置、MCP server、生命周期 contributor trait。 |
| `ext/goal` | `codex-goal-extension` | 2,554 | 3,952 | `/goal` 扩展：goal runtime、工具、预算、事件和 steering。 |
| `ext/guardian` | `codex-guardian` | 69 | 69 | Guardian 扩展入口。 |
| `ext/image-generation` | `codex-image-generation-extension` | 590 | 896 | 图像生成工具扩展。 |
| `ext/memories` | `codex-memories-extension` | 1,682 | 2,182 | memories 工具扩展：list/read/search/add note、本地/后端实现。 |
| `ext/mcp` | `codex-mcp-extension` | 310 | 932 | hosted plugin runtime MCP server 和 executor plugin MCP 发现。 |
| `ext/skills` | `codex-skills-extension` | 2,232 | 3,069 | 技能 provider、catalog、selection、state 和工具扩展。 |
| `ext/web-search` | `codex-web-search-extension` | 673 | 673 | web search 工具扩展、history 和输出 schema。 |
| `connectors` | `codex-connectors` | 1,525 | 2,207 | app connector 目录、可访问性、过滤、合并、tool policy。 |

### 状态、历史和线程存储

| 路径 | crate | 主实现 | 含测试 | 作用 |
| --- | --- | ---: | ---: | --- |
| `rollout` | `codex-rollout` | 6,065 | 9,961 | session JSONL rollout 持久化、压缩、搜索、索引和元数据。 |
| `rollout-trace` | `codex-rollout-trace` | 8,474 | 11,883 | trace bundle 格式、writer、reducer 和 rollouts 语义回放。 |
| `state` | `codex-state` | 15,933 | 16,277 | SQLite 状态库，镜像 rollout 元数据、agent jobs、审计和查询。 |
| `thread-store` | `codex-thread-store` | 7,712 | 7,812 | storage-neutral thread persistence trait、本地/in-memory 实现、thread metadata sync。 |
| `agent-graph-store` | `codex-agent-graph-store` | 409 | 409 | 线程 spawn 出的 agent parent/child 拓扑存储。 |
| `agent-identity` | `codex-agent-identity` | 667 | 667 | agent identity key、JWT/JWKS、任务注册身份。 |
| `external-agent-migration` | `codex-external-agent-migration` | 2,004 | 2,004 | 从外部 agent 配置迁移 hooks、MCP、skills 等。 |
| `external-agent-sessions` | `codex-external-agent-sessions` | 1,604 | 1,681 | 外部 agent session 历史检测、导入、导出和 ledger。 |
| `memories/read` | `codex-memories-read` | 145 | 205 | memories 读取辅助。 |
| `memories/write` | `codex-memories-write` | 2,576 | 3,796 | memories 写入、索引或存储辅助。 |

### 观测、终端、平台和小工具

| 路径 | crate | 主实现 | 含测试 | 作用 |
| --- | --- | ---: | ---: | --- |
| `otel` | `codex-otel` | 3,596 | 6,036 | OpenTelemetry/tracing 初始化、导出和指标辅助。 |
| `terminal-detection` | `codex-terminal-detection` | 485 | 1,377 | 终端能力检测。 |
| `ansi-escape` | `codex-ansi-escape` | 55 | 55 | ANSI escape 处理。 |
| `async-utils` | `codex-async-utils` | 70 | 70 | 异步辅助函数。 |
| `arg0` | `codex-arg0` | 671 | 671 | 根据 argv[0] 做多二进制/别名分发。 |
| `codex-home` | `codex-home` | 72 | 201 | Codex home 目录定位。 |
| `install-context` | `codex-install-context` | 563 | 563 | 安装来源/上下文检测。 |
| `keyring-store` | `codex-keyring-store` | 201 | 201 | 系统 keyring 存储。 |
| `secrets` | `codex-secrets` | 702 | 702 | secret 管理相关模型/辅助。 |
| `response-debug-context` | `codex-response-debug-context` | 148 | 148 | Responses debug context。 |
| `codex-experimental-api-macros` | `codex-experimental-api-macros` | 281 | 281 | experimental API 标注/派生宏。 |
| `v8-poc` | `codex-v8-poc` | 73 | 73 | V8 proof-of-concept。 |
| `test-binary-support` | `codex-test-binary-support` | 70 | 70 | 测试二进制辅助。 |

### `utils/*`

| 路径 | crate | 主实现 | 含测试 | 作用 |
| --- | --- | ---: | ---: | --- |
| `utils/absolute-path` | `codex-utils-absolute-path` | 758 | 758 | 绝对路径类型和校验。 |
| `utils/path-uri` | `codex-utils-path-uri` | 853 | 1,804 | path URI 转换。 |
| `utils/cargo-bin` | `codex-utils-cargo-bin` | 215 | 215 | 测试中定位 workspace 二进制，兼容 Cargo/Bazel。 |
| `utils/cache` | `codex-utils-cache` | 168 | 168 | 缓存辅助。 |
| `utils/image` | `codex-utils-image` | 436 | 910 | 图片处理辅助。 |
| `utils/json-to-toml` | `codex-utils-json-to-toml` | 73 | 73 | JSON 到 TOML 转换。 |
| `utils/home-dir` | `codex-utils-home-dir` | 123 | 123 | home 目录查找。 |
| `utils/pty` | `codex-utils-pty` | 2,095 | 3,058 | PTY 抽象和跨平台处理。 |
| `utils/readiness` | `codex-utils-readiness` | 290 | 290 | 服务 readiness 等待/探测。 |
| `utils/rustls-provider` | `codex-utils-rustls-provider` | 35 | 71 | rustls provider 初始化。 |
| `utils/string` | `codex-utils-string` | 381 | 487 | 字符串辅助。 |
| `utils/cli` | `codex-utils-cli` | 598 | 598 | CLI 输出和参数辅助。 |
| `utils/elapsed` | `codex-utils-elapsed` | 60 | 60 | elapsed 时间格式化。 |
| `utils/sandbox-summary` | `codex-utils-sandbox-summary` | 215 | 215 | sandbox 摘要格式化。 |
| `utils/sleep-inhibitor` | `codex-utils-sleep-inhibitor` | 558 | 558 | 阻止系统睡眠的跨平台辅助。 |
| `utils/approval-presets` | `codex-utils-approval-presets` | 73 | 73 | 审批 preset。 |
| `utils/oss` | `codex-utils-oss` | 54 | 54 | OSS 构建相关辅助。 |
| `utils/output-truncation` | `codex-utils-output-truncation` | 137 | 428 | 输出截断辅助。 |
| `utils/path-utils` | `codex-utils-path` | 210 | 303 | 路径工具函数。 |
| `utils/plugins` | `codex-utils-plugins` | 173 | 173 | 插件命名/mention 辅助。 |
| `utils/fuzzy-match` | `codex-utils-fuzzy-match` | 154 | 154 | 模糊匹配。 |
| `utils/stream-parser` | `codex-utils-stream-parser` | 1,315 | 1,315 | 流式 parser。 |
| `utils/template` | `codex-utils-template` | 382 | 382 | 模板渲染。 |
| `git-utils` | `codex-git-utils` | 3,052 | 3,177 | Git 仓库、分支、diff、工作区信息辅助。 |

## 非 workspace 但重要的 Rust 目录

| 路径 | 主实现 Rust 行 | 含测试 Rust 行 | 作用 |
| --- | ---: | ---: | --- |
| `codex-rs/chatgpt` | 557 | 734 | ChatGPT app/入口相关辅助，作为 path dependency 存在但不在 workspace members。 |
| `codex-rs/message-history` | 369 | 547 | 消息历史读写辅助，作为 path dependency 存在但不在 workspace members。 |
| `codex-rs/windows-sandbox-rs` | 15,375 | 16,150 | Windows sandbox、ACL、WFP、command runner、elevated runner 和 setup 二进制。 |
| `codex-rs/app-server/tests/common` | 2,399 | 2,399 | app-server 测试支持 crate。 |
| `codex-rs/core/tests/common` | 5,424 | 5,534 | core 集成测试支持 crate。 |
| `codex-rs/mcp-server/tests/common` | 458 | 458 | MCP server 测试支持 crate。 |

## 推荐学习顺序

下面的顺序适合想理解“Codex 是怎么实现的”的第一遍阅读。代码量按主实现 Rust 行统计，少量非 Rust 包装层另行标注。

| 顺序 | 阅读范围 | 代码量 | 为什么先读 |
| ---: | --- | ---: | --- |
| 1 | 根目录 `README.md`、`codex-rs/Cargo.toml`、`codex-rs/README.md`、`justfile` | 约 5.5k 源码/配置行 | 先建立仓库边界、workspace 成员和常用命令。 |
| 2 | `codex-rs/protocol` + `codex-rs/config` | 30,876 行 | 先读共享数据结构、事件、权限、配置层，后面看 core/TUI/app-server 会少很多陌生名词。 |
| 3 | `codex-rs/cli` + `codex-cli/` | 17,797 Rust 行 + 759 源码/配置行 | 看 `codex` 命令如何从包装层进入 Rust，如何分派到 TUI、exec、app-server、login、doctor。 |
| 4 | `codex-rs/tui` 的入口、`app`、`chatwidget`、`bottom_pane`、`history_cell` | 约 89,016 行 | 理解交互模式的用户事件、输入、审批、工具状态和历史渲染。第一遍可先读 `main.rs`、`lib.rs`、`app.rs`、`chatwidget.rs`，再下钻目录。 |
| 5 | `codex-rs/core` 的主干：`client.rs`、`thread_manager.rs`、`session/`、`tasks/`、`context/`、`context_manager/`、`tools/`、`exec.rs`、`mcp_tool_call.rs`、`agent/` | 约 44,607 行 | 这是 agent 的执行闭环：用户输入到模型请求，再到工具调用、结果回传、turn 结束。 |
| 6 | `codex-rs/codex-api`、`codex-rs/codex-client`、`model-provider*`、`models-manager` | 14,354 行 | 理解模型请求、SSE/WS、认证 provider 和模型目录。 |
| 7 | `exec`、`exec-server`、`sandboxing`、`linux-sandbox`、`windows-sandbox-rs`、`execpolicy`、`shell-command`、`shell-escalation` | 52,158 行 | 理解 shell/tool 执行到底如何落到进程、文件系统、权限策略和平台沙箱。 |
| 8 | `codex-mcp`、`mcp-server`、`core-plugins`、`core-skills`、`skills`、`plugin`、`ext/*` | 34,684 行 | 理解 Codex 如何扩展工具能力：MCP、插件 marketplace、技能加载和内置扩展。 |
| 9 | `rollout`、`rollout-trace`、`state`、`thread-store`、`message-history` | 38,553 行 + 369 行 | 理解会话历史、线程列表、SQLite 索引、trace 和恢复机制。 |
| 10 | `app-server-protocol`、`app-server`、`app-server-transport`、`app-server-client`、`app-server-daemon` | 69,728 行 | 当你要理解 IDE/桌面/远程控制集成时再读。核心 CLI agent 可先跳过这层。 |
| 11 | `analytics`、`otel`、`feedback`、`hooks`、`cloud-config`、`backend-client`、`login` | 约 30k 行 | 最后补上观测、反馈、hooks、云配置、账号和后端能力。 |

第一遍最小闭环可以按 2 -> 3 -> 5 -> 6 -> 7 读，约 160k 主实现行；如果要理解终端交互体验，加上第 4 步；如果要理解 IDE/桌面集成，加上第 10 步。

## 阅读提示

- 先从类型和事件读起：`protocol` 里的名字会出现在 TUI、core、app-server 三层。
- 看 core 时抓住 turn 生命周期：`ThreadManager` 创建线程，`CodexThread`/`session` 接收输入，`client` 发模型请求，`tools` 处理模型发起的 tool call，结果再回到模型上下文。
- 看 TUI 时不要从最大的 `bottom_pane` 开始硬啃。先读 `tui/src/main.rs`、`lib.rs`、`app.rs`、`chatwidget.rs`，理解事件流，再进 `bottom_pane` 和 `history_cell`。
- 看 app-server 时先读 `app-server-protocol/src/protocol/v2.rs` 和 `app-server/src/request_processors/`，再回头看 transport。
- 如果只是改工具或 MCP 行为，优先看 `core/src/tools/`、`core/src/mcp_tool_call.rs`、`codex-mcp/`、`tools/`，通常不需要先读完整 TUI。
