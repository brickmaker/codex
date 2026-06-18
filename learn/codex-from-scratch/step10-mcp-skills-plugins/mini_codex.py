#!/usr/bin/env python3
"""Step 10: load skills and plugin-provided MCP-like tools."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Literal


@dataclass
class Config:
    cwd: Path
    codex_home: Path


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


class RuleBasedModel:
    def next_action(self, context: str, history: list[Message]) -> ModelAction:
        last = history[-1]
        if last.role == "tool":
            return ModelAction("final", text=f"Tool finished:\n{last.content or '(no output)'}")
        text = last.content.strip()
        lowered = text.lower()
        if "skills" in lowered:
            return ModelAction("final", text="Visible context:\n" + context)
        if lowered.startswith("reverse "):
            return ModelAction("tool_call", tool_call=ToolCall("reverse", {"text": text.split(maxsplit=1)[1]}))
        if lowered.startswith("count words "):
            return ModelAction("tool_call", tool_call=ToolCall("word_count", {"text": text.removeprefix("count words ")}))
        if lowered.startswith("run "):
            return ModelAction("tool_call", tool_call=ToolCall("shell", {"command": text[4:]}))
        if lowered.startswith("write "):
            parts = text.split(maxsplit=2)
            if len(parts) < 3:
                return ModelAction("final", text="Usage: write <path> <content>")
            return ModelAction("tool_call", tool_call=ToolCall("apply_patch", {"path": parts[1], "content": parts[2] + "\n"}))
        return ModelAction("final", text=f"You said: {text}")


class Agent:
    def __init__(self, model: RuleBasedModel, tools: ToolRegistry, context: ContextManager) -> None:
        self.model = model
        self.tools = tools
        self.context_manager = context
        self.history: list[Message] = []

    def turn_events(self, prompt: str) -> Iterable[Event]:
        self.history.append(Message("user", prompt))
        yield Event("turn_started", {"input": prompt})
        while True:
            action = self.model.next_action(self.context_manager.build(self.history), self.history)
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


def build_agent(args: argparse.Namespace) -> Agent:
    home = Path(args.codex_home).expanduser()
    cwd = Path(getattr(args, "cwd", ".")).resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    config = Config(cwd=cwd, codex_home=home)
    extensions = ExtensionManager(home)
    return Agent(RuleBasedModel(), ToolRegistry(config, extensions), ContextManager(config, extensions))


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
