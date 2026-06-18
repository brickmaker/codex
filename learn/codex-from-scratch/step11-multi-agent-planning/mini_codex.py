#!/usr/bin/env python3
"""Step 11: plan, dynamic tools, and subagents."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
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


class ToolRegistry:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd
        self.plan: list[dict] = []
        self.loaded_tools = {"shell", "update_plan", "spawn_agent", "tool_search"}
        self.discoverable = {
            "reverse": "Reverse text",
            "word_count": "Count words",
        }

    def run(self, call: ToolCall) -> ToolResult:
        if call.name == "shell":
            command = str(call.arguments.get("command", ""))
            completed = subprocess.run(command, shell=True, cwd=self.cwd, text=True, capture_output=True, timeout=20)
            return ToolResult("shell", completed.returncode == 0, (completed.stdout + completed.stderr).rstrip())
        if call.name == "update_plan":
            self.plan = list(call.arguments.get("items", []))
            rendered = "\n".join(f"- [{item.get('status', 'pending')}] {item.get('step')}" for item in self.plan)
            return ToolResult("update_plan", True, rendered)
        if call.name == "tool_search":
            query = str(call.arguments.get("query", "")).lower()
            matches = [
                {"name": name, "description": description}
                for name, description in self.discoverable.items()
                if query in name or query in description.lower()
            ]
            for match in matches:
                self.loaded_tools.add(match["name"])
            return ToolResult("tool_search", True, json.dumps(matches))
        if call.name == "spawn_agent":
            role = str(call.arguments.get("role", "explorer"))
            task = str(call.arguments.get("task", ""))
            child = Agent(role=role, tools=ToolRegistry(self.cwd))
            child_events = list(child.turn_events(task))
            final = next((event.data["answer"] for event in reversed(child_events) if event.type == "turn_completed"), "")
            return ToolResult("spawn_agent", True, f"{role} completed: {final}")
        if call.name == "reverse" and "reverse" in self.loaded_tools:
            return ToolResult("reverse", True, str(call.arguments.get("text", ""))[::-1])
        if call.name == "word_count" and "word_count" in self.loaded_tools:
            return ToolResult("word_count", True, str(len(str(call.arguments.get("text", "")).split())))
        return ToolResult(call.name, False, f"unknown or unloaded tool: {call.name}")


class RuleBasedModel:
    def __init__(self, role: str) -> None:
        self.role = role

    def next_action(self, history: list[Message]) -> ModelAction:
        last = history[-1]
        if last.role == "tool":
            return ModelAction("final", text=f"{self.role} observed:\n{last.content}")
        text = last.content.strip()
        lowered = text.lower()
        if lowered.startswith("plan "):
            topic = text[5:]
            return ModelAction(
                "tool_call",
                tool_call=ToolCall(
                    "update_plan",
                    {
                        "items": [
                            {"step": f"Understand {topic}", "status": "completed"},
                            {"step": f"Implement {topic}", "status": "in_progress"},
                            {"step": f"Verify {topic}", "status": "pending"},
                        ]
                    },
                ),
            )
        if lowered.startswith("ask explorer "):
            return ModelAction("tool_call", tool_call=ToolCall("spawn_agent", {"role": "explorer", "task": text.removeprefix("ask explorer ")}))
        if lowered.startswith("find tool "):
            return ModelAction("tool_call", tool_call=ToolCall("tool_search", {"query": text.removeprefix("find tool ")}))
        if lowered.startswith("reverse "):
            return ModelAction("tool_call", tool_call=ToolCall("reverse", {"text": text.split(maxsplit=1)[1]}))
        if lowered.startswith("count words "):
            return ModelAction("tool_call", tool_call=ToolCall("word_count", {"text": text.removeprefix("count words ")}))
        if lowered.startswith("run "):
            return ModelAction("tool_call", tool_call=ToolCall("shell", {"command": text[4:]}))
        return ModelAction("final", text=f"{self.role} says: {text}")


class Agent:
    def __init__(self, role: str, tools: ToolRegistry) -> None:
        self.role = role
        self.tools = tools
        self.model = RuleBasedModel(role)
        self.history: list[Message] = []

    def turn_events(self, prompt: str) -> Iterable[Event]:
        self.history.append(Message("user", prompt))
        yield Event("turn_started", {"role": self.role, "input": prompt})
        while True:
            action = self.model.next_action(self.history)
            if action.kind == "final":
                self.history.append(Message("assistant", action.text))
                yield Event("assistant_message", {"text": action.text})
                yield Event("turn_completed", {"answer": action.text})
                return
            call = action.tool_call
            assert call is not None
            yield Event("tool_call_started", asdict(call))
            result = self.tools.run(call)
            yield Event("tool_call_finished", asdict(result))
            self.history.append(Message("tool", result.output))


def render(events: Iterable[Event], jsonl: bool) -> None:
    for event in events:
        if jsonl:
            print(json.dumps(asdict(event), ensure_ascii=False))
        elif event.type == "assistant_message":
            print(event.data["text"])
        elif event.type == "tool_call_started":
            print(f"[tool] {event.data['name']} {event.data['arguments']}")
        elif event.type == "tool_call_finished":
            print(event.data["output"])


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    exec_parser = sub.add_parser("exec")
    exec_parser.add_argument("prompt")
    exec_parser.add_argument("--cwd", default=".")
    exec_parser.add_argument("--jsonl", action="store_true")
    args = parser.parse_args()

    if args.command == "exec":
        cwd = Path(args.cwd).resolve()
        cwd.mkdir(parents=True, exist_ok=True)
        render(Agent("main", ToolRegistry(cwd)).turn_events(args.prompt), args.jsonl)


if __name__ == "__main__":
    main()
