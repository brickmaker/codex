# Integrations

生成日期：2026-06-18  
范围：`/Users/xiaodong/Desktop/learn/codex`

## Summary

Codex 的 runtime 价值主要来自 integrations：模型流式 API、MCP servers、插件/skills/apps、shell/apply_patch/sandbox、state/rollout、auth/config、telemetry、remote environments。核心设计是把这些能力统一成 model-visible context、tool specs、tool outputs 和 app-server notifications。

## OpenAI Responses API

Local code treats model access as a streaming client:

- `codex-rs/core/src/client.rs:782` builds the Responses request from prompt, tools, reasoning config, output schema, metadata, and service tier.
- `codex-rs/core/src/client.rs:1246` streams over HTTP/SSE.
- `codex-rs/core/src/client.rs:1366` streams over WebSocket.
- `codex-rs/core/src/client.rs:1610` chooses WebSocket first when enabled and falls back to HTTP.
- `codex-rs/codex-api/src/common.rs:73` defines local `ResponseEvent` variants used by the turn loop.
- `codex-rs/codex-api/src/sse/responses.rs:298` maps SSE event names into local events.

Problem solved：the core turn loop can be transport-agnostic. It only consumes `ResponseEvent` and does not need to know whether a response came from HTTP SSE or WebSocket.

## MCP

MCP integration is split into configuration, lifecycle, and tool-call handling:

- Runtime config is assembled in `codex-rs/core/src/mcp.rs:78` from config, plugins, apps, and extension contributors.
- `codex-rs/codex-mcp/src/connection_manager.rs:106` owns running clients and aggregate metadata.
- `list_all_tools` at `codex-rs/codex-mcp/src/connection_manager.rs:446` gathers server tools and model-visibility metadata.
- `call_tool` at `codex-rs/codex-mcp/src/connection_manager.rs:676` routes a tool invocation to the selected MCP server.
- Core MCP tool handler starts at `codex-rs/core/src/tools/handlers/mcp.rs:32`。
- Approval and policy flow for MCP calls is in `codex-rs/core/src/mcp_tool_call.rs:109`。

Problem solved：external tool providers can participate in the same model-visible tool pipeline as built-in tools, while startup status, approval, and naming conflicts remain centrally managed.

## Plugins

Plugins package optional skills, MCP servers, apps, and hooks:

- Manifest shape is in `codex-rs/plugin/src/manifest.rs:3`。
- Plugin manager loads and caches plugin outcomes in `codex-rs/core-plugins/src/manager.rs:462`。
- Plugin skill roots are exposed through `effective_skill_roots_for_layer_stack` at `codex-rs/core-plugins/src/manager.rs:594`。
- Plugin-derived MCP servers feed into `McpManager` via runtime config in `codex-rs/core/src/mcp.rs:78`。

Problem solved：Codex can grow through local/remote extension bundles without hard-coding every capability into `codex-core`.

## Skills

Skills are local instruction bundles discovered before or during a turn:

- `SkillsService` in `codex-rs/core-skills/src/service.rs:53` owns discovery, caching, and roots.
- Skill metadata rendering is in `codex-rs/core-skills/src/render.rs:135`。
- Full `SKILL.md` injection is modeled in `codex-rs/core-skills/src/skill_instructions.rs:5`。
- Turn-time explicit skill/plugin detection and injection happens in `codex-rs/core/src/session/turn.rs:470`。

Problem solved：the model sees a compact catalog first, then only receives large skill bodies when explicitly selected or routed by extensions.

## Apps And Connectors

Apps/connectors are surfaced as tools and context:

- app/server plugins and apps are merged into MCP runtime config in `codex-rs/core/src/mcp.rs:78`。
- Tool exposure is decided by `codex-rs/core/src/session/turn.rs:1153` and `codex-rs/core/src/tools/spec_plan.rs:167`。
- App tool permissions are checked in `codex-rs/core/src/mcp_tool_call.rs:153`。

Problem solved：installed apps can expose capabilities through the same MCP/tool path while keeping auth and visibility rules explicit.

## Shell, Apply Patch, And Sandbox

Shell and patching are first-class tools:

- Shell handler：`codex-rs/core/src/tools/handlers/shell/shell_command.rs:40`。
- Shared exec-like path：`codex-rs/core/src/tools/handlers/shell.rs:60`。
- Exec request construction：`codex-rs/core/src/exec.rs:331`。
- Sandbox request model：`codex-rs/core/src/sandboxing/mod.rs:42`。
- Apply patch handler：`codex-rs/core/src/tools/handlers/apply_patch.rs:327`。

Problem solved：model-suggested commands go through a consistent policy path: parse args, compute permissions, request approval if needed, apply sandbox, execute, emit structured events, return tool output.

## Persistence

Codex persists both chronological rollout and queryable metadata:

- `RolloutRecorder` writes JSONL in `codex-rs/rollout/src/recorder.rs:66`。
- Canonical response items are recorded in `codex-rs/rollout/src/recorder.rs:790`。
- Local live writer flushes rollout and state in `codex-rs/thread-store/src/local/live_writer.rs:77`。
- SQLite metadata extraction is in `codex-rs/state/src/extract.rs:14`。

Problem solved：resume/fork/list can use durable JSONL for exact history and SQLite for indexed metadata without making the SQLite DB the only source of truth.

## Config And Auth

- CLI/TUI/exec parse config overrides before starting app-server/core.
- app-server startup loads config/auth managers in `codex-rs/app-server/src/lib.rs:434`。
- `ThreadProcessor` resolves per-thread config overrides in `codex-rs/app-server/src/request_processors/thread_processor.rs:871`。
- `TurnProcessor` applies per-turn overrides in `codex-rs/app-server/src/request_processors/turn_processor.rs:381`。

Problem solved：global config, CLI flags, profiles, per-thread settings, and per-turn steering can coexist.

## Telemetry And Diagnostics

- app-server initializes telemetry around startup in `codex-rs/app-server/src/lib.rs:434`。
- tool registry wraps dispatch with telemetry and start/finish notifications in `codex-rs/core/src/tools/registry.rs:403`。
- nextest and CI settings tune slow tests in `codex-rs/.config/nextest.toml:1`。

## Remote And Platform Integrations

- `codex-rs/exec-server` abstracts local/remote filesystem and process execution.
- Sandbox implementation varies by OS: macOS Seatbelt, Linux sandbox/bubblewrap/Landlock, Windows sandbox.
- Core test support can create local or remote test environments in `codex-rs/core/tests/common/test_codex.rs:115`。

## Integration Unknowns

- [TODO] Cloud-side session semantics, model-side cache behavior, and marketplace service contracts are not fully represented in local source.
- [TODO] Third-party MCP server behavior is only testable through protocol mocks unless the real server is installed.

