# Step 1: Basic Agent Loop

本章从最小的 agent loop 开始：用户输入一条消息，agent 把它加入历史，模型根据历史生成回答，然后进入下一轮。

## 本步目标

- 实现一个可以运行的 REPL。
- 引入 `Message`、`History`、`Agent`、`Model` 四个概念。
- 理解 Codex 里的 `turn`：一次用户输入到一次最终回答。

```mermaid
sequenceDiagram
    participant U as User
    participant A as Agent
    participant M as Model
    U->>A: user message
    A->>A: append to history
    A->>M: generate(history)
    M-->>A: assistant message
    A->>A: append to history
    A-->>U: final answer
```

## 相对真实 Codex 的位置

真实 Codex 不会把所有逻辑写在一个 REPL 里，但核心概念相同：

- `TurnStartParams`：`codex-rs/app-server-protocol/src/protocol/v2/turn.rs`
- `Op::UserInput`：`codex-rs/protocol/src/protocol.rs`
- `submission_loop`：`codex-rs/core/src/session/handlers.rs`
- `run_turn`：`codex-rs/core/src/session/turn.rs`

真实路径是 UI/app-server 提交 turn，core session 创建 task，再进入 `run_turn`。本章先把这些压缩成一个函数，方便看到“输入、历史、输出”的骨架。

## 运行

本步骤从一开始就调用真实模型。它使用 OpenAI 兼容的 `POST /v1/chat/completions` 协议，不依赖第三方 Python 包，只需要配置环境变量：

```bash
export OPENAI_API_KEY="你的 API key"
export OPENAI_MODEL="你的模型名"
export OPENAI_BASE_URL="https://api.openai.com/v1"  # 使用兼容服务时改成对应 base URL

python3 mini_codex.py --once "hello codex"
python3 mini_codex.py
```

REPL 中输入 `/history` 可以查看历史，输入 `/quit` 退出。

可选环境变量：

- `OPENAI_SYSTEM_PROMPT`：覆盖默认 system prompt。
- `OPENAI_TEMPERATURE`：设置采样温度；不设置则不传该字段。
- `OPENAI_MAX_TOKENS`：设置最大输出 token；不设置则不传该字段。
- `OPENAI_TIMEOUT`：HTTP 超时时间，单位秒，默认 `60`。

也可以用命令行参数覆盖部分配置：

```bash
python3 mini_codex.py --model "你的模型名" --base-url "https://api.openai.com/v1"
```

## 实现逻辑

`OpenAIChatModel` 是一个最小模型适配器。它把 `history` 转成 OpenAI 兼容的 `messages`，发送到 `/chat/completions`，再从 `choices[0].message.content` 取出 assistant 文本。这里先不做工具调用、流式输出、重试和复杂错误恢复，只保留真实对话最需要的模型请求链路。

`Agent.turn()` 是本章最重要的函数：

1. 记录用户消息。
2. 调用模型。
3. 记录 assistant 消息。
4. 返回最终文本。

## 下一步

真实 Codex 会把模型输出、工具状态、错误和完成状态都转成事件流，让 TUI/exec/app-server 可以实时渲染。下一章会加入流式事件。
