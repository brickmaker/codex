#!/usr/bin/env python3
"""Step 3: add a shell tool and feed results back to the model."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from typing import Iterable, Literal


@dataclass
class Message:
    role: str
    content: str


@dataclass
class Event:
    type: str
    data: dict


@dataclass
class ToolCall:
    name: str
    arguments: dict


@dataclass
class ToolResult:
    name: str
    ok: bool
    output: str


@dataclass
class ModelAction:
    kind: Literal["final", "tool_call"]
    text: str = ""
    tool_call: ToolCall | None = None


class ShellTool:
    name = "shell"

    def run(self, arguments: dict) -> ToolResult:
        command = str(arguments.get("command", ""))
        completed = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
            timeout=20,
        )
        output = completed.stdout
        if completed.stderr:
            output += completed.stderr
        return ToolResult(self.name, completed.returncode == 0, output.rstrip())


class ToolRegistry:
    def __init__(self) -> None:
        self.tools = {ShellTool.name: ShellTool()}

    def run(self, call: ToolCall) -> ToolResult:
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(call.name, False, f"unknown tool: {call.name}")
        return tool.run(call.arguments)


class RuleBasedModel:
    def next_action(self, history: list[Message]) -> ModelAction:
        last = history[-1]
        if last.role == "tool":
            return ModelAction(
                "final",
                text=f"Command finished. Output:\n{last.content or '(no output)'}",
            )

        text = last.content.strip()
        lowered = text.lower()
        if lowered == "pwd":
            return ModelAction("tool_call", tool_call=ToolCall("shell", {"command": "pwd"}))
        if lowered.startswith("run "):
            return ModelAction(
                "tool_call",
                tool_call=ToolCall("shell", {"command": text[4:]}),
            )
        return ModelAction("final", text=f"You said: {text}")


class Agent:
    def __init__(self, model: RuleBasedModel, tools: ToolRegistry) -> None:
        self.model = model
        self.tools = tools
        self.history: list[Message] = []

    def turn_events(self, user_text: str) -> Iterable[Event]:
        self.history.append(Message("user", user_text))
        yield Event("turn_started", {"input": user_text})

        while True:
            action = self.model.next_action(self.history)
            if action.kind == "final":
                assert action.text is not None
                self.history.append(Message("assistant", action.text))
                for word in action.text.split(" "):
                    yield Event("assistant_delta", {"delta": word + " "})
                yield Event("turn_completed", {"answer": action.text})
                return

            call = action.tool_call
            assert call is not None
            yield Event("tool_call_started", asdict(call))
            result = self.tools.run(call)
            yield Event("tool_call_finished", asdict(result))
            self.history.append(Message("tool", result.output))

    def render_history(self) -> str:
        if not self.history:
            return "(empty)"
        return "\n".join(f"{message.role}: {message.content}" for message in self.history)


def render_event(event: Event, jsonl: bool) -> None:
    if jsonl:
        print(json.dumps(asdict(event), ensure_ascii=False))
        return
    if event.type == "assistant_delta":
        print(event.data["delta"], end="", flush=True)
    elif event.type == "tool_call_started":
        print(f"[tool] {event.data['name']} {event.data['arguments']}")
    elif event.type == "tool_call_finished":
        print(event.data["output"])
    elif event.type == "turn_completed":
        print()


def run_turn(agent: Agent, prompt: str, jsonl: bool) -> None:
    for event in agent.turn_events(prompt):
        render_event(event, jsonl)


def repl(agent: Agent, jsonl: bool) -> None:
    print("mini-codex step3. Try: run echo hello. Type /history or /quit.")
    while True:
        try:
            user_text = input("> ")
        except EOFError:
            print()
            return
        if user_text == "/quit":
            return
        if user_text == "/history":
            print(agent.render_history())
            continue
        run_turn(agent, user_text, jsonl)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", help="Run one turn and exit.")
    parser.add_argument("--jsonl", action="store_true", help="Render events as JSON lines.")
    args = parser.parse_args()

    agent = Agent(RuleBasedModel(), ToolRegistry())
    if args.once is not None:
        run_turn(agent, args.once, args.jsonl)
    else:
        repl(agent, args.jsonl)


if __name__ == "__main__":
    main()
