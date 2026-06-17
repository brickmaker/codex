# Concerns

生成日期：2026-06-18  
范围：`/Users/xiaodong/Desktop/learn/codex`

## Summary

This repo is healthy but large. The biggest maintenance risks are central-crate growth, high-churn orchestration files, model-context regressions, protocol compatibility, generated schema drift, sandbox/platform divergence, and the complexity of integrating tools/MCP/plugins/apps without surprising the user or model.

## High-Churn Files

From `docs/codebase/.codebase-scan.txt`, high-churn files in the last 90 days include:

- `codex-rs/Cargo.lock`
- `codex-rs/app-server-protocol/schema/typescript/v2/items.ts`
- `codex-rs/app-server-protocol/schema/json/codex_app_server_protocol.schemas.json`
- `codex-rs/tui/src/chatwidget.rs`
- `codex-rs/core/src/session/tests.rs`
- `codex-rs/core/src/config/mod.rs`
- `codex-rs/app-server/src/codex_message_processor.rs`
- `codex-rs/core/src/config/config_tests.rs`
- `codex-rs/core/src/session/mod.rs`
- `codex-rs/app-server/README.md`
- `codex-rs/core/config.schema.json`
- `codex-rs/tui/src/app.rs`
- `codex-rs/protocol/src/protocol.rs`
- `codex-rs/Cargo.toml`
- `codex-rs/app-server-protocol/src/protocol/v2.rs`
- `codex-rs/app-server/src/message_processor.rs`
- `codex-rs/tui/src/lib.rs`
- `codex-rs/core/src/session/session.rs`
- `codex-rs/core/src/session/turn.rs`
- `codex-rs/app-server-protocol/src/protocol/common.rs`

Risk：many of these files sit on behavior boundaries; conflicts and regressions can occur even for small changes.

## Large Central Modules

Observed central files include:

- `codex-rs/core/src/session/mod.rs`：startup, context, rollout and session orchestration.
- `codex-rs/core/src/session/turn.rs`：turn loop, tool setup, model streaming.
- `codex-rs/app-server/src/message_processor.rs`：all client request routing.
- `codex-rs/tui/src/app.rs` and `codex-rs/tui/src/chatwidget.rs`：large UI orchestration.
- `codex-rs/tui/src/bottom_pane/chat_composer.rs`：very large composer implementation.

Repo convention already says to avoid growing these files where possible and to extract new functionality into focused modules.

## Context And Prompt-Cache Risks

Context is a product-critical surface:

- Initial context is large and constructed in `codex-rs/core/src/session/mod.rs:2861`。
- Diff updates are in `codex-rs/core/src/context_manager/updates.rs:214`。
- `ContextManager` stores and estimates history in `codex-rs/core/src/context_manager/history.rs:32`。

Risks:

- unbounded injected fragments can degrade cost, latency, or correctness;
- frequent stable-context churn can cause prompt-cache misses;
- incomplete diff coverage can leave the model with stale or duplicated settings.

## Protocol Compatibility Risks

app-server v2 is the main external API:

- `ClientRequest` is generated in `codex-rs/app-server-protocol/src/protocol/common.rs:209`。
- `ThreadStartParams` and `TurnStartParams` are broad payloads with many optional settings.
- schema fixtures must be regenerated and reviewed when API shapes change.

Risks:

- accidental wire rename or optionality changes break clients;
- adding API to v1 would violate current development rules;
- experimental fields need correct gating and schema output.

## Tool And Permission Risks

Tool execution crosses security boundaries:

- tool spec/registry planning: `codex-rs/core/src/tools/spec_plan.rs:167`;
- dispatch/hook/telemetry path: `codex-rs/core/src/tools/registry.rs:403`;
- shell execution: `codex-rs/core/src/tools/handlers/shell.rs:60`;
- sandbox exec construction: `codex-rs/core/src/exec.rs:331`;
- MCP approvals: `codex-rs/core/src/mcp_tool_call.rs:109`.

Risks:

- exposing too many tools to the model can degrade behavior;
- bypassing approval/sandbox path can create security issues;
- inconsistent tool output formatting can break follow-up model calls.

## MCP/Plugin/App Complexity

MCP, plugins, apps, and skills all alter turn-time capabilities:

- MCP runtime config is dynamic: `codex-rs/core/src/mcp.rs:78`;
- plugin loading is cached and auth-aware: `codex-rs/core-plugins/src/manager.rs:462`;
- skills are discovered from config and plugin roots: `codex-rs/core-skills/src/service.rs:102`;
- turn-time injection happens in `codex-rs/core/src/session/turn.rs:470`.

Risks:

- startup failures can be partial and must be surfaced clearly;
- name collisions and visibility policies need central handling;
- large skill bodies must not be injected casually.

## Persistence Risks

Persistence uses both JSONL rollout and SQLite metadata:

- `RolloutRecorder` writes canonical JSONL in `codex-rs/rollout/src/recorder.rs:66`;
- local live writer flushes state in `codex-rs/thread-store/src/local/live_writer.rs:77`;
- state extraction is in `codex-rs/state/src/extract.rs:14`.

Risks:

- SQLite metadata can drift from rollout unless flush/reconcile paths are correct;
- resume/fork depends on canonical history reconstruction;
- large or corrupted rollout files need bounded handling.

## Scan Limitations

- The scan reported no container configs, but `.devcontainer/` exists. Treat scan output as a starting index, not the final truth.
- Generated files dominate some churn metrics; review handwritten sources separately from generated schema/output.

## Open Questions

1. [ASK USER] Which surface should future deep dives prioritize: CLI/TUI behavior, app-server API contracts, plugin/MCP authoring, or model-context internals?
2. [ASK USER] Should cloud/remote Codex behavior be documented only from this repository, or should future docs include server-side/public documentation when available?
3. [ASK USER] For future maintenance docs, should generated schema files be included in diagrams, or treated as build artifacts unless API shape changes?
4. [ASK USER] Do you want a second pass that turns this analysis into a navigable tutorial with exercises and “read these files in order” checkpoints?

