#!/usr/bin/env python3
"""Step 3: add a shell tool and feed results back to the model."""

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

sys.path.append(str(Path(__file__).resolve().parents[1]))
from mini_llm import (
    Message,
    ModelAction,
    OpenAIChatModel,
    ToolCall,
    add_model_args,
    build_model,
    function_tool,
)


@dataclass
class Event:
    type: str
    data: dict


@dataclass
class ToolResult:
    name: str
    ok: bool
    output: str


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

    def tool_specs(self) -> list[dict]:
        return [
            function_tool(
                "shell",
                "Run a shell command and return stdout, stderr, and exit status.",
                {"command": {"type": "string", "description": "Command to execute."}},
                ["command"],
            )
        ]

    def run(self, call: ToolCall) -> ToolResult:
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(call.name, False, f"unknown tool: {call.name}")
        return tool.run(call.arguments)


class Agent:
    def __init__(self, model: OpenAIChatModel, tools: ToolRegistry) -> None:
        self.model = model
        self.tools = tools
        self.history: list[Message] = []

    def turn_events(self, user_text: str) -> Iterable[Event]:
        self.history.append(Message("user", user_text))
        yield Event("turn_started", {"input": user_text})

        while True:
            action: ModelAction | None = None
            for model_event in self.model.stream_action(self.history, self.tools.tool_specs()):
                if model_event.kind == "delta":
                    yield Event("assistant_delta", {"delta": model_event.delta})
                elif model_event.action is not None:
                    action = model_event.action

            if action is None:
                raise RuntimeError("model stream ended without an action")

            if action.kind == "final":
                self.history.append(Message("assistant", action.text))
                yield Event("turn_completed", {"answer": action.text})
                return

            call = action.tool_call
            assert call is not None
            if action.assistant_message is not None:
                self.history.append(action.assistant_message)
            yield Event("tool_call_started", asdict(call))
            result = self.tools.run(call)
            yield Event("tool_call_finished", asdict(result))
            self.history.append(Message("tool", result.output, tool_call_id=call.id, name=call.name))

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
    add_model_args(parser)
    args = parser.parse_args()

    agent = Agent(build_model(args), ToolRegistry())
    if args.once is not None:
        run_turn(agent, args.once, args.jsonl)
    else:
        repl(agent, args.jsonl)


if __name__ == "__main__":
    main()
