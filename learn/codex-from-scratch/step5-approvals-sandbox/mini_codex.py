#!/usr/bin/env python3
"""Step 5: approvals and sandbox checks around tools."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Literal


@dataclass
class Config:
    cwd: Path
    approval: str
    sandbox: str


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


@dataclass
class PermissionDecision:
    status: Literal["allow", "ask", "deny"]
    reason: str


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
            if line.startswith("+") or line.startswith(" "):
                body.append(line[1:])
            i += 1
        operations.append((op, path, "\n".join(body) + ("\n" if body else "")))
    return operations


class PermissionPolicy:
    def __init__(self, config: Config) -> None:
        self.config = config

    def check(self, call: ToolCall) -> PermissionDecision:
        if call.name == "apply_patch":
            if self.config.sandbox == "read-only":
                return PermissionDecision("deny", "read-only sandbox blocks file edits")
            return PermissionDecision("allow", "workspace file edit")

        if call.name == "shell":
            command = str(call.arguments.get("command", ""))
            dangerous = ["rm ", "sudo", "curl ", "wget ", "chmod ", "chown ", ">"]
            if any(marker in command for marker in dangerous):
                if self.config.approval == "on-request":
                    return PermissionDecision("ask", f"potentially dangerous command: {command}")
                return PermissionDecision("deny", f"approval disabled for: {command}")
            if self.config.sandbox == "read-only" and not command.split(" ")[0] in {"pwd", "ls", "cat", "echo"}:
                return PermissionDecision("deny", "read-only sandbox allows only simple read commands")
            return PermissionDecision("allow", "safe shell command")

        return PermissionDecision("deny", f"unknown tool: {call.name}")

    def approved(self, decision: PermissionDecision) -> bool:
        if decision.status == "allow":
            return True
        if decision.status == "deny":
            return False
        if not sys.stdin.isatty():
            return False
        answer = input(f"Allow tool call? {decision.reason} [y/N] ")
        return answer.lower() in {"y", "yes"}


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
    def __init__(self, config: Config) -> None:
        self.policy = PermissionPolicy(config)
        self.tools = {
            ShellTool.name: ShellTool(config.cwd),
            ApplyPatchTool.name: ApplyPatchTool(config.cwd),
        }

    def run(self, call: ToolCall) -> ToolResult:
        decision = self.policy.check(call)
        if not self.policy.approved(decision):
            return ToolResult(call.name, False, f"blocked: {decision.reason}")
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(call.name, False, f"unknown tool: {call.name}")
        return tool.run(call.arguments)


class RuleBasedModel:
    def next_action(self, history: list[Message]) -> ModelAction:
        last = history[-1]
        if last.role == "tool":
            return ModelAction("final", text=f"Tool finished:\n{last.content or '(no output)'}")

        text = last.content.strip()
        lowered = text.lower()
        if lowered == "pwd":
            return ModelAction("tool_call", tool_call=ToolCall("shell", {"command": "pwd"}))
        if lowered.startswith("run "):
            return ModelAction("tool_call", tool_call=ToolCall("shell", {"command": text[4:]}))
        if lowered.startswith("show "):
            filename = text.split(maxsplit=1)[1]
            return ModelAction("tool_call", tool_call=ToolCall("shell", {"command": f"cat {filename}"}))
        if lowered.startswith("write "):
            parts = text.split(maxsplit=2)
            if len(parts) < 3:
                return ModelAction("final", text="Usage: write <path> <content>")
            _, path, content = parts
            patch = "\n".join(["*** Begin Patch", f"*** Add File: {path}", f"+{content}", "*** End Patch"])
            return ModelAction("tool_call", tool_call=ToolCall("apply_patch", {"patch": patch}))
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


def render_event(event: Event, jsonl: bool) -> None:
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


def run_turn(agent: Agent, prompt: str, jsonl: bool) -> None:
    for event in agent.turn_events(prompt):
        render_event(event, jsonl)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", help="Run one turn and exit.")
    parser.add_argument("--jsonl", action="store_true")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--approval", choices=["never", "on-request"], default="never")
    parser.add_argument(
        "--sandbox",
        choices=["read-only", "workspace-write", "danger-full-access"],
        default="workspace-write",
    )
    args = parser.parse_args()

    cwd = Path(args.cwd).resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    config = Config(cwd=cwd, approval=args.approval, sandbox=args.sandbox)
    agent = Agent(RuleBasedModel(), ToolRegistry(config))

    if args.once is not None:
        run_turn(agent, args.once, args.jsonl)
        return

    print("mini-codex step5. Try: run echo safe, write file.txt hi. Type /quit.")
    while True:
        try:
            prompt = input("> ")
        except EOFError:
            print()
            return
        if prompt == "/quit":
            return
        run_turn(agent, prompt, args.jsonl)


if __name__ == "__main__":
    main()
