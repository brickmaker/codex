#!/usr/bin/env python3
"""Step 7: persist threads as JSONL rollout files and resume them."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

sys.path.append(str(Path(__file__).resolve().parents[1]))
from mini_llm import Message, OpenAIChatModel, ToolCall, add_model_args, build_model, function_tool


SYSTEM_PROMPT = (
    "You are Mini Codex, a resumable local coding agent. Use persisted history and runtime context "
    "to continue the thread accurately."
)


@dataclass
class Config:
    cwd: Path
    approval: str
    sandbox: str
    codex_home: Path
    context_limit: int = 3000


@dataclass
class Event:
    type: str
    data: dict


@dataclass
class ToolResult:
    name: str
    ok: bool
    output: str


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


def load_agents_md(cwd: Path) -> str:
    files = [parent / "AGENTS.md" for parent in [cwd, *cwd.parents] if (parent / "AGENTS.md").exists()]
    return "\n\n".join(f"# {path}\n{path.read_text(errors='replace').strip()}" for path in reversed(files))


class RolloutStore:
    def __init__(self, home: Path) -> None:
        self.threads_dir = home / "threads"
        self.threads_dir.mkdir(parents=True, exist_ok=True)

    def path(self, thread_id: str) -> Path:
        return self.threads_dir / f"{thread_id}.jsonl"

    def create(self, cwd: Path) -> str:
        thread_id = uuid.uuid4().hex[:12]
        self.append(thread_id, {"type": "thread_started", "cwd": str(cwd), "created_at": int(time.time())})
        return thread_id

    def append(self, thread_id: str, record: dict) -> None:
        with self.path(thread_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load_history(self, thread_id: str) -> list[Message]:
        history: list[Message] = []
        if not self.path(thread_id).exists():
            raise SystemExit(f"unknown thread: {thread_id}")
        for line in self.path(thread_id).read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record.get("type") in {"user_message", "assistant_message", "tool_message"}:
                history.append(
                    Message(
                        record["role"],
                        record.get("content", ""),
                        tool_call_id=record.get("tool_call_id"),
                        name=record.get("name"),
                        tool_calls=record.get("tool_calls"),
                    )
                )
        return history

    def list_threads(self) -> list[dict]:
        rows: list[dict] = []
        for path in sorted(self.threads_dir.glob("*.jsonl"), reverse=True):
            first = path.read_text(encoding="utf-8").splitlines()[0]
            rows.append({"thread_id": path.stem, **json.loads(first)})
        return rows


class ContextManager:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.project_instructions = load_agents_md(config.cwd)

    def build(self, history: list[Message]) -> str:
        parts = [
            "You are Mini Codex, a local coding agent.",
            f"cwd: {self.config.cwd}",
            f"sandbox: {self.config.sandbox}",
            f"approval: {self.config.approval}",
            "Use the attached tool schemas for currently available tools.",
        ]
        if self.project_instructions:
            parts.append("project instructions:\n" + self.project_instructions)
        recent = "\n".join(f"{message.role}: {message.content}" for message in history[-8:])
        if recent:
            parts.append("recent history:\n" + recent)
        context = "\n\n".join(parts)
        return context[-self.config.context_limit :]


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
            if any(marker in command for marker in ["rm ", "sudo", "curl ", "wget ", "chmod ", "chown ", ">"]):
                if self.config.approval == "on-request":
                    return PermissionDecision("ask", f"potentially dangerous command: {command}")
                return PermissionDecision("deny", f"approval disabled for: {command}")
            return PermissionDecision("allow", "safe shell command")
        return PermissionDecision("deny", f"unknown tool: {call.name}")

    def approved(self, decision: PermissionDecision) -> bool:
        if decision.status == "allow":
            return True
        if decision.status == "deny" or not sys.stdin.isatty():
            return False
        answer = input(f"Allow tool call? {decision.reason} [y/N] ")
        return answer.lower() in {"y", "yes"}


class ShellTool:
    name = "shell"

    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd

    def run(self, arguments: dict) -> ToolResult:
        command = str(arguments.get("command", ""))
        completed = subprocess.run(command, shell=True, cwd=self.cwd, text=True, capture_output=True, timeout=20)
        return ToolResult(self.name, completed.returncode == 0, (completed.stdout + completed.stderr).rstrip())


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
        self.tools = {ShellTool.name: ShellTool(config.cwd), ApplyPatchTool.name: ApplyPatchTool(config.cwd)}

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
        decision = self.policy.check(call)
        if not self.policy.approved(decision):
            return ToolResult(call.name, False, f"blocked: {decision.reason}")
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(call.name, False, f"unknown tool: {call.name}")
        return tool.run(call.arguments)


class Agent:
    def __init__(self, thread_id: str, model: OpenAIChatModel, tools: ToolRegistry, context_manager: ContextManager, store: RolloutStore) -> None:
        self.thread_id = thread_id
        self.model = model
        self.tools = tools
        self.context_manager = context_manager
        self.store = store
        self.history = store.load_history(thread_id)

    def context(self) -> str:
        return self.context_manager.build(self.history)

    def record_message(self, message: Message) -> None:
        record = {"type": f"{message.role}_message", "role": message.role, "content": message.content, "ts": time.time()}
        if message.tool_call_id:
            record["tool_call_id"] = message.tool_call_id
        if message.name:
            record["name"] = message.name
        if message.tool_calls:
            record["tool_calls"] = message.tool_calls
        self.store.append(self.thread_id, record)

    def turn_events(self, user_text: str) -> Iterable[Event]:
        user_message = Message("user", user_text)
        self.history.append(user_message)
        self.record_message(user_message)
        yield Event("turn_started", {"thread_id": self.thread_id, "input": user_text})
        while True:
            action = None
            for model_event in self.model.stream_action(
                self.history,
                self.tools.tool_specs(),
                context=self.context(),
            ):
                if model_event.kind == "delta":
                    yield Event("assistant_delta", {"delta": model_event.delta})
                elif model_event.action is not None:
                    action = model_event.action

            if action is None:
                raise RuntimeError("model stream ended without an action")

            if action.kind == "final":
                assistant_message = Message("assistant", action.text)
                self.history.append(assistant_message)
                self.record_message(assistant_message)
                yield Event("turn_completed", {"answer": action.text, "thread_id": self.thread_id})
                return
            call = action.tool_call
            assert call is not None
            if action.assistant_message is not None:
                self.history.append(action.assistant_message)
                self.record_message(action.assistant_message)
            yield Event("tool_call_started", asdict(call))
            result = self.tools.run(call)
            yield Event("tool_call_finished", asdict(result))
            tool_message = Message("tool", result.output, tool_call_id=call.id, name=call.name)
            self.history.append(tool_message)
            self.record_message(tool_message)


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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once")
    parser.add_argument("--jsonl", action="store_true")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--codex-home", default=".mini-codex")
    parser.add_argument("--resume")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--approval", choices=["never", "on-request"], default="never")
    parser.add_argument("--sandbox", choices=["read-only", "workspace-write", "danger-full-access"], default="workspace-write")
    add_model_args(parser)
    args = parser.parse_args()

    cwd = Path(args.cwd).resolve()
    cwd.mkdir(parents=True, exist_ok=True)
    store = RolloutStore(Path(args.codex_home).expanduser())
    if args.list:
        for row in store.list_threads():
            print(f"{row['thread_id']}  cwd={row.get('cwd')}")
        return

    thread_id = args.resume or store.create(cwd)
    config = Config(cwd=cwd, approval=args.approval, sandbox=args.sandbox, codex_home=Path(args.codex_home))
    agent = Agent(thread_id, build_model(args, SYSTEM_PROMPT), ToolRegistry(config), ContextManager(config), store)

    if args.once is not None:
        for event in agent.turn_events(args.once):
            render_event(event, args.jsonl)
        return

    print(f"mini-codex step7 thread={thread_id}. Type /quit.")
    while True:
        try:
            prompt = input("> ")
        except EOFError:
            print()
            return
        if prompt == "/quit":
            return
        for event in agent.turn_events(prompt):
            render_event(event, args.jsonl)


if __name__ == "__main__":
    main()
