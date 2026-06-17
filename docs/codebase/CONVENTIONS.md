# Conventions

生成日期：2026-06-18  
范围：`/Users/xiaodong/Desktop/learn/codex`

## Summary

本仓库的约定重心是：Rust API 清晰、app-server v2 wire shape 稳定、TUI 快照可审查、agent 上下文有边界、不要继续膨胀 `codex-core`。这些约定来自根 `AGENTS.md`、crate README、源码形态和测试结构。

## Rust Style

- Crate names are prefixed with `codex-` even when folders are short, e.g. `core` crate is `codex-core`。
- Prefer inline format args: `format!("{name}")` over `format!("{}", name)`。
- Collapse nested `if` statements where Clippy would flag `collapsible_if`。
- Prefer method references over redundant closures.
- Prefer exhaustive `match` arms over wildcard arms when practical.
- Avoid ambiguous bool/`Option` positional parameters. If unavoidable, use exact `/*param_name*/` comments for opaque literals.
- New traits need doc comments explaining their role and implementation expectations.
- Avoid `#[async_trait]` and `#[allow(async_fn_in_trait)]`; prefer RPITIT future signatures with explicit `Send` bounds.
- Prefer private modules with explicit public crate API exports.
- Do not create helper methods that are referenced only once.

## Core Boundary

- Resist adding code to `codex-core`; first look for an existing crate or a new focused crate.
- If MCP tool call behavior changes, prefer existing abstractions in `codex-rs/codex-mcp/src/connection_manager.rs`.
- Do not call `reset_client_session` unless incremental request logic genuinely requires it.
- If adding compile-time file reads (`include_str!`, migrations, etc.), update Bazel data wiring.

## Context Rules

Model-visible context must obey the repo’s context discipline:

- No history rewrite; context grows incrementally.
- Avoid frequent context changes that cause prompt-cache misses.
- Injected items must have bounded size and hard caps.
- No injected item larger than 10K tokens.
- New fragments that can cross 1K tokens require careful manual review.
- Fragments injected into model context should be structs under `core/context` implementing `ContextualUserFragment`.

Implementation anchors:

- Context fragments registry：`codex-rs/core/src/context/contextual_user_message.rs:20`。
- Initial context builder：`codex-rs/core/src/session/mod.rs:2861`。
- Context updates：`codex-rs/core/src/context_manager/updates.rs:214`。

## App-Server API Rules

- Active API development should happen in app-server v2, not v1.
- Method names use `<resource>/<method>` with singular resource, e.g. `thread/start`, `turn/start`.
- Request payloads are `*Params`; responses are `*Response`; notifications are `*Notification`.
- v2 wire fields use camelCase unless config payloads intentionally mirror config keys.
- v2 request/response/notification types should export TS under `v2/`.
- Avoid `skip_serializing_if = "Option::is_none"` for v2 payload fields, except intentional no-param requests.
- Optional client-to-server fields use `#[ts(optional = nullable)]`.
- New list methods should use cursor pagination.
- Experimental fields/methods use experimental markers and schema generation support.

Implementation anchors:

- request macro and `ClientRequest`：`codex-rs/app-server-protocol/src/protocol/common.rs:209`。
- `ThreadStartParams`：`codex-rs/app-server-protocol/src/protocol/v2/thread.rs:52`。
- `TurnStartParams`：`codex-rs/app-server-protocol/src/protocol/v2/turn.rs:67`。
- schema fixture tests：`codex-rs/app-server-protocol/tests/schema_fixtures.rs:11`。

## TUI Style

- Prefer ratatui `Stylize` helpers such as `"text".dim()` and `"text".red()` over manual `Style`/`Span::styled` when simple.
- Do not hardcode white; prefer default foreground.
- Follow file-local style and avoid churn between equivalent forms.
- Use `textwrap::wrap` for plain strings.
- Use `tui/src/wrapping.rs` helpers for wrapping `ratatui::Line`.
- New/changed user-visible UI needs `insta` snapshot coverage.

## Testing Conventions

- Do not run `cargo test` directly; use `just test`.
- Run project-specific tests first, e.g. `just test -p codex-tui`.
- Ask before running complete `just test` after common/core/protocol changes.
- Before finalizing large `codex-rs` code changes, run scoped `just fix -p <project>`.
- Use `pretty_assertions::assert_eq` for better diffs.
- Prefer equality over field-by-field assertions.
- Avoid mutating process environment in tests.
- Prefer integration tests for agent behavior under `codex-rs/core/tests/suite`.
- Use `core_test_support::responses` helpers instead of manual JSON digging.
- TUI snapshots are reviewed with `cargo insta pending-snapshots -p codex-tui` and accepted intentionally.

## Documentation Rules

- Do not add broad product/user-facing docs to `docs/`; official Codex docs live elsewhere.
- App-server API docs are an exception.
- This `docs/codebase/` directory is local codebase-knowledge output from an explicit user request, not public product docs.

## Dependency Rules

- If `Cargo.toml` or `Cargo.lock` changes, run `just bazel-lock-update` from repo root and include `MODULE.bazel.lock`.
- Then run `just bazel-lock-check`.
- Avoid `--all-features` in routine local runs unless needed.

## Protected Areas

- Do not add or modify code related to `CODEX_SANDBOX_NETWORK_DISABLED_ENV_VAR` or `CODEX_SANDBOX_ENV_VAR`.
- Existing sandbox environment checks are deliberate because local/CI sandboxing affects which tests can run.

