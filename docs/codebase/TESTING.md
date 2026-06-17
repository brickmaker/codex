# Testing

生成日期：2026-06-18  
范围：`/Users/xiaodong/Desktop/learn/codex`

## Summary

Testing is layered: `just test` drives nextest for Rust crates; core and app-server use integration suites with mocked Responses API; TUI uses extensive `insta` snapshots; protocol crates validate generated schema fixtures; sandbox/process tests are gated by platform and serialized where needed.

## Primary Commands

- `cd codex-rs && just fmt`：format Rust after code changes.
- `cd codex-rs && just test -p <crate>`：run scoped tests.
- `cd codex-rs && just test`：run the broader suite through nextest; ask before doing this after shared/core/protocol changes.
- `cd codex-rs && just fix -p <crate>`：run scoped lint fixes for large Rust changes.
- `cd codex-rs && just write-config-schema`：regenerate config schema after `ConfigToml` changes.
- `cd codex-rs && just write-app-server-schema`：regenerate app-server protocol fixtures after API shape changes.
- `cd codex-rs && just argument-comment-lint`：check opaque positional literal comments.

Implementation anchors:

- nextest command in `justfile:71`。
- schema commands in `justfile:144` and `justfile:148`。
- local nextest profile in `codex-rs/.config/nextest.toml:11`。

## Core Integration Tests

`codex-rs/core/tests/suite/mod.rs:1` aggregates formerly standalone integration tests. It covers:

- agent execution and subagents;
- AGENTS.md and contextual user fragments;
- apply_patch, shell command, unified exec;
- approvals, permission messages, sandbox behavior;
- MCP, plugins, skills, dynamic/search tools;
- prompt caching, token budgets, compression, resume/fork;
- Responses API WebSocket fallback and stream errors.

Test harness:

- `codex-rs/core/tests/common/responses.rs:38` defines `ResponseMock` for captured model requests.
- `ResponsesRequest` helpers at `codex-rs/core/tests/common/responses.rs:101` inspect body JSON, input items, tool outputs, headers, and paths.
- `codex-rs/core/tests/common/test_codex.rs:1` builds local/remote test Codex instances.
- `TestEnv` at `codex-rs/core/tests/common/test_codex.rs:115` supports local temp dirs and remote exec server environments.

## App-Server Tests

`codex-rs/app-server/tests/suite/mod.rs:1` groups app-server tests. v2 coverage is in `codex-rs/app-server/tests/suite/v2/mod.rs:1` and includes:

- thread start/read/list/resume/fork/archive/delete/status;
- turn start/interrupt/steer;
- config RPC, models, permissions, output schema;
- MCP tool/resource/status/elicitation;
- plugin install/list/read/share/uninstall and marketplace flows;
- dynamic tools, skills, apps, hooks, remote control;
- websocket and unix websocket connection handling.

These tests exercise the API boundary rather than calling core internals directly.

## TUI Snapshot Tests

TUI code uses `insta` heavily:

- `codex-rs/tui/src/app/tests.rs` for app-level rendering snapshots.
- `codex-rs/tui/src/chatwidget/tests.rs` and submodules for chat history, approvals, popups, settings.
- `codex-rs/tui/src/bottom_pane/**` for composer, footer, approval overlay, skill/app/link views.
- `codex-rs/tui/src/markdown_render_tests.rs` for markdown rendering.

Workflow for intentional UI/text changes:

- run `just test -p codex-tui`;
- inspect `cargo insta pending-snapshots -p codex-tui`;
- review `.snap.new` files or `cargo insta show`;
- accept intentionally with `cargo insta accept -p codex-tui`.

## Protocol Schema Tests

App-server protocol shape is guarded by schema fixture tests:

- `codex-rs/app-server-protocol/tests/schema_fixtures.rs:11` checks TypeScript fixtures.
- `codex-rs/app-server-protocol/tests/schema_fixtures.rs:23` checks JSON fixtures.
- Failure messages tell maintainers to run `just write-app-server-schema`。

## Sandbox And Platform Tests

- Some integration modules are gated with `#[cfg(not(target_os = "windows"))]` or `#[cfg(unix)]` in `codex-rs/core/tests/suite/mod.rs:30` and app-server v2 tests.
- nextest serializes or limits resource-heavy groups in `codex-rs/.config/nextest.toml:14` onward.
- Windows process-heavy tests get dedicated limits in `codex-rs/.config/nextest.toml:78`。

## Test Authoring Guidance

- Prefer integration tests for agent behavior.
- Use response constructors such as `ev_response_created`, `ev_function_call`, `ev_completed`, and `sse(...)` from test support.
- Hold `ResponseMock` and assert captured `/responses` requests using helper methods.
- Prefer `wait_for_event` style helpers over raw sleeps or arbitrary timeouts.
- Compare whole objects where possible.
- Put new test modules in sibling `*_tests.rs` files when introducing new unit-test modules.

## Current Validation For This Documentation Change

- This change only adds Markdown documentation and a scan artifact.
- No Rust code, generated schema, Cargo manifests, or snapshots were changed.
- Therefore `just fmt`, `just fix`, and `just test` were not run for this docs-only update.

