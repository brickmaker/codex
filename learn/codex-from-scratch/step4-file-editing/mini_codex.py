#!/usr/bin/env python3
"""Step 4: add a small apply_patch tool."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

sys.path.append(str(Path(__file__).resolve().parents[1]))
from mini_llm import Message, OpenAIChatModel, ToolCall, add_model_args, build_model, function_tool


SYSTEM_PROMPT = (
    "You are Mini Codex, a local coding agent. Answer directly when no local action is needed. "
    "Use the available tool schemas to decide whether to inspect or change the workspace."
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


def ensure_inside(root: Path, user_path: str) -> Path:
    target = (root / user_path).resolve()
    if root.resolve() not in (target, *target.parents):
        raise ValueError(f"path escapes workspace: {user_path}")
    return target


def parse_patch(text: str) -> list[tuple[str, str, str]]:
    lines = text.splitlines()
    if not lines or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
        raise ValueError("patch must start with *** Begin Patch and end with *** End Patch")

    operations: list[tuple[str, str, str]] = []
    i = 1
    while i < len(lines) - 1:
        header = lines[i]
        if header.startswith("*** Add File: "):
            op = "add"
            path = header.removeprefix("*** Add File: ")
        elif header.startswith("*** Update File: "):
            op = "update"
            path = header.removeprefix("*** Update File: ")
        elif header.startswith("*** Delete File: "):
            operations.append(("delete", header.removeprefix("*** Delete File: "), ""))
            i += 1
            continue
        else:
            raise ValueError(f"unknown patch header: {header}")

        i += 1
        body: list[str] = []
        while i < len(lines) - 1 and not lines[i].startswith("*** "):
            line = lines[i]
            if line.startswith("+"):
                body.append(line[1:])
            elif line.startswith(" "):
                body.append(line[1:])
            elif line.startswith("-"):
                pass
            else:
                body.append(line)
            i += 1
        operations.append((op, path, "\n".join(body) + ("\n" if body else "")))
    return operations


class ShellTool:
    name = "shell"

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd

    def run(self, arguments: dict) -> ToolResult:
        command = str(arguments.get("command", ""))
        completed = subprocess.run(
            command,
            shell=True,
            cwd=self.cwd,
            text=True,
            capture_output=True,
            timeout=20,
        )
        output = completed.stdout
        if completed.stderr:
            output += completed.stderr
        return ToolResult(self.name, completed.returncode == 0, output.rstrip())


class ApplyPatchTool:
    name = "apply_patch"

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd

    def run(self, arguments: dict) -> ToolResult:
        try:
            operations = parse_patch(str(arguments.get("patch", "")))
            summaries: list[str] = []
            for op, path, content in operations:
                target = ensure_inside(self.cwd, path)
                if op == "delete":
                    target.unlink(missing_ok=True)
                    summaries.append(f"deleted {path}")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(content)
                    summaries.append(f"{op}ed {path}")
            return ToolResult(self.name, True, "\n".join(summaries))
        except Exception as exc:
            return ToolResult(self.name, False, str(exc))


class ToolRegistry:
    def __init__(self, cwd: Path) -> None:
        self.tools = {
            ShellTool.name: ShellTool(cwd),
            ApplyPatchTool.name: ApplyPatchTool(cwd),
        }

    def tool_specs(self) -> list[dict]:
        return [
            function_tool(
                "shell",
                "Run a shell command in the workspace.",
                {"command": {"type": "string", "description": "Command to execute."}},
                ["command"],
            ),
            function_tool(
                "apply_patch",
                "Apply a Codex-style patch inside the workspace.",
                {
                    "patch": {
                        "type": "string",
                        "description": "Patch text enclosed by *** Begin Patch and *** End Patch.",
                    }
                },
                ["patch"],
            ),
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
            action = None
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
    print("mini-codex step4. Try: write hello.txt Hello. Type /quit.")
    while True:
        try:
            user_text = input("> ")
        except EOFError:
            print()
            return
        if user_text == "/quit":
            return
        run_turn(agent, user_text, jsonl)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", help="Run one turn and exit.")
    parser.add_argument("--jsonl", action="store_true", help="Render events as JSON lines.")
    parser.add_argument("--cwd", default=".", help="Workspace directory.")
    add_model_args(parser)
    args = parser.parse_args()

    cwd = Path(args.cwd).resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    agent = Agent(build_model(args, SYSTEM_PROMPT), ToolRegistry(cwd))
    if args.once is not None:
        run_turn(agent, args.once, args.jsonl)
    else:
        repl(agent, args.jsonl)


if __name__ == "__main__":
    main()
