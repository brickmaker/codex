# Stack

生成日期：2026-06-18  
范围：`/Users/xiaodong/Desktop/learn/codex`

## Summary

Codex 是一个以 Rust workspace 为核心的多入口 agent 运行时。仓库外层有 Node/pnpm 包装、发布和少量 TypeScript 生态文件；真正的 CLI、TUI、app-server、agent loop、工具执行、MCP、插件、持久化和测试主要在 `codex-rs/`。

## Evidence

- 扫描结果：4,993 个文件，约 1,172,210 行；Rust 2,272 个文件，TypeScript 603 个文件，Python 125 个文件。来源：`docs/codebase/.codebase-scan.txt`。
- Rust workspace：`codex-rs/Cargo.toml` 使用 edition 2024，并列出大量 `codex-*` crate。
- Node workspace：根目录 `package.json` 是私有 `codex-monorepo`，要求 Node >=22、pnpm >=10.33.0。
- 统一命令入口：`justfile` 将工作目录切到 `codex-rs`，`just test` 使用 `cargo nextest`。

## Languages

- Rust：核心实现语言。关键路径包括 `codex-rs/cli`、`codex-rs/tui`、`codex-rs/app-server`、`codex-rs/core`、`codex-rs/codex-api`、`codex-rs/codex-mcp`、`codex-rs/rollout`、`codex-rs/state`。
- TypeScript：主要用于协议 schema 产物、前端/扩展生态和 npm 包装；app-server v2 API 使用 `ts-rs` 导出 TS 类型。
- Python：维护脚本、技能扫描脚本和若干工具脚本；不是运行时主路径。
- Shell/Just：本地开发命令编排。

## Rust Runtime Stack

- Async runtime：`tokio`。
- HTTP/WebSocket/SSE：`reqwest`、`tokio-tungstenite`、`eventsource-stream`、`axum`。
- CLI parsing：`clap`。
- TUI：`ratatui`、`crossterm`。
- Serialization/schema：`serde`、`serde_json`、`schemars`、`ts-rs`。
- MCP：`rmcp` 与本仓库封装的 `codex-mcp`。
- Storage：`sqlx` with SQLite bundled、JSONL rollout files。
- Git/filesystem：`gix`、`ignore`、`notify`、路径 URI/absolute path helper crates。
- Observability：`tracing`、OpenTelemetry、Sentry 相关 crate。

## Workspace Shape

仓库将大的 agent 系统拆成多个 crate，以避免所有逻辑落入 `codex-core`：

- Entry crates：`codex-cli`、`codex-exec`、`codex-app-server`、`codex-tui`。
- Runtime/core crates：`codex-core`、`codex-protocol`、`codex-tools`、`codex-api`、`codex-mcp`。
- Extension crates：`codex-core-skills`、`codex-core-plugins`、`codex-plugin`、`codex-extension-api`。
- Persistence crates：`codex-rollout`、`codex-state`、`codex-thread-store`。
- Platform/sandbox crates：`codex-sandboxing`、`codex-linux-sandbox`、`codex-windows-sandbox`、`codex-exec-server`。
- Test support：`core_test_support` appears through workspace dependencies and tests under `codex-rs/core/tests/common`.

## Protocol And API Stack

- Internal protocol：`codex-rs/protocol` defines the core/TUI/event types shared across runtime boundaries.
- App-server protocol：`codex-rs/app-server-protocol` defines v2 request/response/notification shapes, schema generation, and experimental API markers.
- App-server transport：`codex-rs/app-server` supports in-process, stdio, websocket, and Unix socket style transport paths.
- Model API：`codex-rs/codex-api` and `codex-rs/core/src/client.rs` send Responses API requests over HTTP SSE or WebSocket.

## Build And Test Tools

- `just fmt` runs Rust formatting from `codex-rs`.
- `just test` runs `cargo nextest run --no-fail-fast`.
- `just fix -p <crate>` runs scoped lint fixes.
- `just write-config-schema` regenerates config schema.
- `just write-app-server-schema` regenerates app-server schema fixtures.
- `just argument-comment-lint` checks positional literal argument comments.
- `cargo insta` is used for snapshot review in UI-heavy crates.
- Bazel appears in lockfile/update workflows and runfile-aware test helpers.

## Runtime Dependencies By Concern

- Agent loop：`tokio`, `serde`, `codex-protocol`, `codex-api`, `codex-tools`.
- Model streaming：`reqwest`, `eventsource-stream`, `tokio-tungstenite`.
- Tool execution：`codex-tools`, `codex-exec-server`, `codex-sandboxing`, platform sandbox crates.
- MCP/tools/apps：`rmcp`, `codex-mcp`, `codex-core-plugins`, `codex-core-skills`.
- TUI rendering：`ratatui`, `crossterm`, `insta` tests.
- Persistence：`codex-rollout`, `codex-state`, `codex-thread-store`, `sqlx`.

## Unknowns

- [TODO] Server-side behavior behind OpenAI Responses, cloud Codex, marketplace metadata, and remote app-server endpoints is only represented by local client contracts in this repo.
- [TODO] Generated schema and vendored artifacts were not line-by-line audited; this pass focuses on handwritten runtime and tests.

