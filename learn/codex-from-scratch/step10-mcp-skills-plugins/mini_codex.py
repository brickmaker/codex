#!/usr/bin/env python3
"""Step 10: load skills and plugin-provided MCP-like tools."""

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
    "You are Mini Codex with extension support. Use runtime context to understand available capabilities, "
    "and answer directly when no local action is needed."
)


@dataclass
class Config:
    cwd: Path
    codex_home: Path


@dataclass
class Event:
    type: str
    data: dict


@dataclass
class ToolResult:
    name: str
    ok: bool
    output: str


class ExtensionManager:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.skills_dir = home / "skills"
        self.plugins_dir = home / "plugins"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.plugins_dir.mkdir(parents=True, exist_ok=True)

    def init_sample(self) -> None:
        skill = self.skills_dir / "code-review" / "SKILL.md"
        skill.parent.mkdir(parents=True, exist_ok=True)
        skill.write_text(
            "# Code Review\n\nUse this skill when the user asks for a review. Lead with findings.\n",
            encoding="utf-8",
        )
        plugin = self.plugins_dir / "demo-tools" / "plugin.json"
        plugin.parent.mkdir(parents=True, exist_ok=True)
        plugin.write_text(
            json.dumps(
                {
                    "name": "demo-tools",
                    "tools": [
                        {"name": "reverse", "description": "Reverse text"},
                        {"name": "word_count", "description": "Count words"},
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def skills(self) -> list[dict]:
        rows: list[dict] = []
        for path in sorted(self.skills_dir.glob("*/SKILL.md")):
            rows.append({"name": path.parent.name, "path": str(path), "body": path.read_text(encoding="utf-8")})
        return rows

    def plugins(self) -> list[dict]:
        rows: list[dict] = []
        for path in sorted(self.plugins_dir.glob("*/plugin.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            data["path"] = str(path)
            rows.append(data)
        return rows

    def plugin_tools(self) -> list[dict]:
        tools: list[dict] = []
        for plugin in self.plugins():
            for tool in plugin.get("tools", []):
                tools.append({"plugin": plugin["name"], **tool})
        return tools


class ContextManager:
    def __init__(self, config: Config, extensions: ExtensionManager) -> None:
        self.config = config
        self.extensions = extensions

    def build(self, history: list[Message]) -> str:
        skill_catalog = "\n".join(f"- {skill['name']}" for skill in self.extensions.skills()) or "(none)"
        tool_catalog = "\n".join(f"- {tool['name']}: {tool.get('description', '')}" for tool in self.extensions.plugin_tools()) or "(none)"
        recent = "\n".join(f"{message.role}: {message.content}" for message in history[-6:])
        return "\n\n".join(
            [
                "You are Mini Codex with skills and MCP-like plugin tools.",
                f"cwd: {self.config.cwd}",
                "skills:\n" + skill_catalog,
                "plugin tools:\n" + tool_catalog,
                "recent history:\n" + recent,
            ]
        )


class ToolRegistry:
    def __init__(self, config: Config, extensions: ExtensionManager) -> None:
        self.config = config
        self.extensions = extensions

    def list_tools(self) -> list[dict]:
        builtins = [
            {"name": "shell", "description": "Run a shell command"},
            {"name": "apply_patch", "description": "Write a file"},
        ]
        return builtins + self.extensions.plugin_tools()

    def tool_specs(self) -> list[dict]:
        specs = [
            function_tool(
                "shell",
                "Run a shell command in the workspace.",
                {"command": {"type": "string", "description": "Command to execute."}},
                ["command"],
            ),
            function_tool(
                "apply_patch",
                "Write a file inside the workspace.",
                {
                    "path": {"type": "string", "description": "Workspace-relative path."},
                    "content": {"type": "string", "description": "Complete file content to write."},
                },
                ["path", "content"],
            ),
        ]
        for tool in self.extensions.plugin_tools():
            if tool["name"] == "reverse":
                specs.append(
                    function_tool(
                        "reverse",
                        tool.get("description", "Reverse text."),
                        {"text": {"type": "string", "description": "Text to reverse."}},
                        ["text"],
                    )
                )
            elif tool["name"] == "word_count":
                specs.append(
                    function_tool(
                        "word_count",
                        tool.get("description", "Count words."),
                        {"text": {"type": "string", "description": "Text to count."}},
                        ["text"],
                    )
                )
        return specs

    def run(self, call: ToolCall) -> ToolResult:
        if call.name == "shell":
            command = str(call.arguments.get("command", ""))
            completed = subprocess.run(command, shell=True, cwd=self.config.cwd, text=True, capture_output=True, timeout=20)
            return ToolResult("shell", completed.returncode == 0, (completed.stdout + completed.stderr).rstrip())
        if call.name == "apply_patch":
            path = str(call.arguments.get("path", ""))
            content = str(call.arguments.get("content", ""))
            target = (self.config.cwd / path).resolve()
            if self.config.cwd.resolve() not in (target, *target.parents):
                return ToolResult("apply_patch", False, "path escapes workspace")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return ToolResult("apply_patch", True, f"wrote {path}")
        if call.name == "reverse":
            text = str(call.arguments.get("text", ""))
            return ToolResult("reverse", True, text[::-1])
        if call.name == "word_count":
            text = str(call.arguments.get("text", ""))
            return ToolResult("word_count", True, str(len(text.split())))
        return ToolResult(call.name, False, f"unknown tool: {call.name}")


class Agent:
    def __init__(self, model: OpenAIChatModel, tools: ToolRegistry, context: ContextManager) -> None:
        self.model = model
        self.tools = tools
        self.context_manager = context
        self.history: list[Message] = []

    def turn_events(self, prompt: str) -> Iterable[Event]:
        self.history.append(Message("user", prompt))
        yield Event("turn_started", {"input": prompt})
        while True:
            action = None
            for model_event in self.model.stream_action(
                self.history,
                self.tools.tool_specs(),
                context=self.context_manager.build(self.history),
            ):
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


def render(events: Iterable[Event], jsonl: bool) -> None:
    for event in events:
        if jsonl:
            print(json.dumps(asdict(event), ensure_ascii=False))
        elif event.type == "assistant_delta":
            print(event.data["delta"], end="", flush=True)
        elif event.type == "tool_call_started":
            print(f"[tool] {event.data['name']} {event.data['arguments']}")
        elif event.type == "tool_call_finished":
            print(event.data["output"])
        elif event.type == "turn_completed":
            print()


def build_agent(args: argparse.Namespace) -> Agent:
    home = Path(args.codex_home).expanduser()
    cwd = Path(getattr(args, "cwd", ".")).resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    config = Config(cwd=cwd, codex_home=home)
    extensions = ExtensionManager(home)
    return Agent(build_model(args, SYSTEM_PROMPT), ToolRegistry(config, extensions), ContextManager(config, extensions))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init-sample-extension")
    init_parser.add_argument("--codex-home", default=".mini-codex")

    skills_parser = sub.add_parser("skills/list")
    skills_parser.add_argument("--codex-home", default=".mini-codex")

    plugins_parser = sub.add_parser("plugins/list")
    plugins_parser.add_argument("--codex-home", default=".mini-codex")

    mcp_parser = sub.add_parser("mcp/list-tools")
    mcp_parser.add_argument("--codex-home", default=".mini-codex")

    exec_parser = sub.add_parser("exec")
    exec_parser.add_argument("prompt")
    exec_parser.add_argument("--codex-home", default=".mini-codex")
    exec_parser.add_argument("--cwd", default=".")
    exec_parser.add_argument("--jsonl", action="store_true")
    add_model_args(exec_parser)

    args = parser.parse_args()
    extensions = ExtensionManager(Path(args.codex_home).expanduser())
    if args.command == "init-sample-extension":
        extensions.init_sample()
        print(f"created sample extension under {extensions.home}")
    elif args.command == "skills/list":
        for skill in extensions.skills():
            print(f"{skill['name']}  {skill['path']}")
    elif args.command == "plugins/list":
        for plugin in extensions.plugins():
            print(f"{plugin['name']}  tools={len(plugin.get('tools', []))}")
    elif args.command == "mcp/list-tools":
        for tool in extensions.plugin_tools():
            print(f"{tool['name']}  plugin={tool['plugin']}  {tool.get('description', '')}")
    elif args.command == "exec":
        render(build_agent(args).turn_events(args.prompt), args.jsonl)


if __name__ == "__main__":
    main()
