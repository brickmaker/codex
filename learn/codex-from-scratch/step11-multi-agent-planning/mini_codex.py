#!/usr/bin/env python3
"""Step 11: plan, dynamic tools, and subagents."""

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
    "You are Mini Codex. For complex work, use update_plan. Use tool_search to discover optional tools, "
    "spawn_agent for delegated exploration, and shell for local commands."
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


class ToolRegistry:
    def __init__(self, cwd: Path, model: OpenAIChatModel) -> None:
        self.cwd = cwd
        self.model = model
        self.plan: list[dict] = []
        self.loaded_tools = {"shell", "update_plan", "spawn_agent", "tool_search"}
        self.discoverable = {
            "reverse": "Reverse text",
            "word_count": "Count words",
        }

    def tool_specs(self) -> list[dict]:
        specs = [
            function_tool(
                "shell",
                "Run a shell command in the workspace.",
                {"command": {"type": "string", "description": "Command to execute."}},
                ["command"],
            ),
            function_tool(
                "update_plan",
                "Replace the current plan checklist.",
                {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step": {"type": "string"},
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                            },
                            "required": ["step", "status"],
                            "additionalProperties": False,
                        },
                    }
                },
                ["items"],
            ),
            function_tool(
                "tool_search",
                "Search for optional tools and load matching tools into the registry.",
                {"query": {"type": "string", "description": "Tool search query."}},
                ["query"],
            ),
            function_tool(
                "spawn_agent",
                "Start a child agent for a small delegated task.",
                {
                    "role": {"type": "string", "description": "Child agent role name."},
                    "task": {"type": "string", "description": "Task for the child agent."},
                },
                ["role", "task"],
            ),
        ]
        if "reverse" in self.loaded_tools:
            specs.append(
                function_tool(
                    "reverse",
                    "Reverse text.",
                    {"text": {"type": "string", "description": "Text to reverse."}},
                    ["text"],
                )
            )
        if "word_count" in self.loaded_tools:
            specs.append(
                function_tool(
                    "word_count",
                    "Count words in text.",
                    {"text": {"type": "string", "description": "Text to count."}},
                    ["text"],
                )
            )
        return specs

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
            child = Agent(role=role, tools=ToolRegistry(self.cwd, self.model), model=self.model)
            child_events = list(child.turn_events(task))
            final = next((event.data["answer"] for event in reversed(child_events) if event.type == "turn_completed"), "")
            return ToolResult("spawn_agent", True, f"{role} completed: {final}")
        if call.name == "reverse" and "reverse" in self.loaded_tools:
            return ToolResult("reverse", True, str(call.arguments.get("text", ""))[::-1])
        if call.name == "word_count" and "word_count" in self.loaded_tools:
            return ToolResult("word_count", True, str(len(str(call.arguments.get("text", "")).split())))
        return ToolResult(call.name, False, f"unknown or unloaded tool: {call.name}")


class Agent:
    def __init__(self, role: str, tools: ToolRegistry, model: OpenAIChatModel) -> None:
        self.role = role
        self.tools = tools
        self.model = model
        self.history: list[Message] = []

    def context(self) -> str:
        loaded = ", ".join(sorted(self.tools.loaded_tools))
        plan = "\n".join(f"- [{item.get('status')}] {item.get('step')}" for item in self.tools.plan) or "(none)"
        return f"role: {self.role}\nloaded tools: {loaded}\nplan:\n{plan}"

    def turn_events(self, prompt: str) -> Iterable[Event]:
        self.history.append(Message("user", prompt))
        yield Event("turn_started", {"role": self.role, "input": prompt})
        while True:
            action = self.model.next_action(self.history, self.tools.tool_specs(), context=self.context())
            if action.kind == "final":
                self.history.append(Message("assistant", action.text))
                yield Event("assistant_message", {"text": action.text})
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
    add_model_args(exec_parser)
    args = parser.parse_args()

    if args.command == "exec":
        cwd = Path(args.cwd).resolve()
        cwd.mkdir(parents=True, exist_ok=True)
        model = build_model(args, SYSTEM_PROMPT)
        render(Agent("main", ToolRegistry(cwd, model), model).turn_events(args.prompt), args.jsonl)


if __name__ == "__main__":
    main()
