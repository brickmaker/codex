#!/usr/bin/env python3
"""Step 8: expose the mini agent through a JSON Lines app-server protocol."""

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
from mini_llm import Message, ToolCall, add_model_args, build_model, function_tool


SYSTEM_PROMPT = (
    "You are Mini Codex behind a tiny app-server protocol. Use tools when local work is needed, "
    "then return a concise final answer."
)


@dataclass
class Config:
    cwd: Path
    codex_home: Path
    sandbox: str = "workspace-write"


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


def simple_patch(path: str, content: str) -> str:
    return "\n".join(["*** Begin Patch", f"*** Add File: {path}", f"+{content}", "*** End Patch"])


def apply_simple_patch(cwd: Path, patch: str) -> ToolResult:
    try:
        lines = patch.splitlines()
        if len(lines) < 4 or lines[0] != "*** Begin Patch" or lines[-1] != "*** End Patch":
            raise ValueError("invalid patch envelope")
        header = lines[1]
        if not header.startswith("*** Add File: "):
            raise ValueError("step8 supports Add File patches only")
        path = header.removeprefix("*** Add File: ")
        content = "\n".join(line[1:] for line in lines[2:-1] if line.startswith("+")) + "\n"
        target = ensure_inside(cwd, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return ToolResult("apply_patch", True, f"added {path}")
    except Exception as exc:
        return ToolResult("apply_patch", False, str(exc))


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

    def records(self, thread_id: str) -> list[dict]:
        path = self.path(thread_id)
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def history(self, thread_id: str) -> list[Message]:
        messages: list[Message] = []
        for record in self.records(thread_id):
            if record.get("type") in {"user_message", "assistant_message", "tool_message"}:
                messages.append(
                    Message(
                        record["role"],
                        record.get("content", ""),
                        tool_call_id=record.get("tool_call_id"),
                        name=record.get("name"),
                        tool_calls=record.get("tool_calls"),
                    )
                )
        return messages

    def list_threads(self) -> list[dict]:
        rows: list[dict] = []
        for path in sorted(self.threads_dir.glob("*.jsonl"), reverse=True):
            first = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
            rows.append({"threadId": path.stem, "cwd": first.get("cwd"), "createdAt": first.get("created_at")})
        return rows


class ToolRegistry:
    def __init__(self, config: Config) -> None:
        self.config = config

    def tool_specs(self) -> list[dict]:
        return [
            function_tool(
                "shell",
                "Run a shell command in the thread workspace.",
                {"command": {"type": "string", "description": "Command to execute."}},
                ["command"],
            ),
            function_tool(
                "apply_patch",
                "Apply a simple Add File patch inside the workspace.",
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
        if call.name == "shell":
            command = str(call.arguments.get("command", ""))
            completed = subprocess.run(command, shell=True, cwd=self.config.cwd, text=True, capture_output=True, timeout=20)
            return ToolResult("shell", completed.returncode == 0, (completed.stdout + completed.stderr).rstrip())
        if call.name == "apply_patch":
            if self.config.sandbox == "read-only":
                return ToolResult("apply_patch", False, "blocked by read-only sandbox")
            return apply_simple_patch(self.config.cwd, str(call.arguments.get("patch", "")))
        return ToolResult(call.name, False, f"unknown tool: {call.name}")


class Agent:
    def __init__(self, thread_id: str, config: Config, store: RolloutStore, model_args: argparse.Namespace | None = None) -> None:
        self.thread_id = thread_id
        self.config = config
        self.store = store
        self.history = store.history(thread_id)
        self.model = build_model(model_args, SYSTEM_PROMPT)
        self.tools = ToolRegistry(config)

    def record(self, message: Message) -> None:
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
        self.record(user_message)
        yield Event("turn_started", {"threadId": self.thread_id, "input": user_text})
        while True:
            action = self.model.next_action(self.history, self.tools.tool_specs())
            if action.kind == "final":
                assistant_message = Message("assistant", action.text)
                self.history.append(assistant_message)
                self.record(assistant_message)
                for word in action.text.split(" "):
                    yield Event("assistant_delta", {"threadId": self.thread_id, "delta": word + " "})
                yield Event("turn_completed", {"threadId": self.thread_id, "answer": action.text})
                return
            call = action.tool_call
            assert call is not None
            if action.assistant_message is not None:
                self.history.append(action.assistant_message)
                self.record(action.assistant_message)
            yield Event("tool_call_started", {"threadId": self.thread_id, **asdict(call)})
            result = self.tools.run(call)
            yield Event("tool_call_finished", {"threadId": self.thread_id, **asdict(result)})
            tool_message = Message("tool", result.output, tool_call_id=call.id, name=call.name)
            self.history.append(tool_message)
            self.record(tool_message)


class ThreadManager:
    def __init__(self, codex_home: Path, model_args: argparse.Namespace | None = None) -> None:
        self.codex_home = codex_home
        self.model_args = model_args
        self.store = RolloutStore(codex_home)
        self.configs: dict[str, Config] = {}
        self.last_thread_id: str | None = None

    def start_thread(self, cwd: str | None = None, sandbox: str = "workspace-write") -> str:
        resolved = Path(cwd or ".").resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        thread_id = self.store.create(resolved)
        self.configs[thread_id] = Config(cwd=resolved, codex_home=self.codex_home, sandbox=sandbox)
        self.last_thread_id = thread_id
        return thread_id

    def get_agent(self, thread_id: str) -> Agent:
        if thread_id == "LAST":
            if self.last_thread_id is None:
                raise KeyError("no LAST thread")
            thread_id = self.last_thread_id
        config = self.configs.get(thread_id)
        if config is None:
            records = self.store.records(thread_id)
            if not records:
                raise KeyError(f"unknown thread: {thread_id}")
            config = Config(cwd=Path(records[0].get("cwd", ".")).resolve(), codex_home=self.codex_home)
            self.configs[thread_id] = config
        return Agent(thread_id, config, self.store, self.model_args)


class MiniAppServer:
    def __init__(self, manager: ThreadManager) -> None:
        self.manager = manager

    def handle(self, request: dict) -> list[dict]:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        try:
            if method == "thread/start":
                thread_id = self.manager.start_thread(params.get("cwd"), params.get("sandbox", "workspace-write"))
                return [self.response(request_id, {"threadId": thread_id})]
            if method == "thread/list":
                return [self.response(request_id, {"data": self.manager.store.list_threads()})]
            if method == "thread/read":
                thread_id = params["threadId"]
                return [self.response(request_id, {"records": self.manager.store.records(thread_id)})]
            if method == "turn/start":
                agent = self.manager.get_agent(params["threadId"])
                outputs = [self.notification("turn/event", asdict(event)) for event in agent.turn_events(params["input"])]
                outputs.append(self.response(request_id, {"threadId": agent.thread_id, "status": "completed"}))
                return outputs
            return [self.error(request_id, f"unknown method: {method}")]
        except Exception as exc:
            return [self.error(request_id, str(exc))]

    @staticmethod
    def response(request_id: object, result: dict) -> dict:
        return {"id": request_id, "result": result}

    @staticmethod
    def notification(method: str, params: dict) -> dict:
        return {"method": method, "params": params}

    @staticmethod
    def error(request_id: object, message: str) -> dict:
        return {"id": request_id, "error": {"message": message}}


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


def server_main(codex_home: Path, model_args: argparse.Namespace | None = None) -> None:
    server = MiniAppServer(ThreadManager(codex_home, model_args))
    for line in sys.stdin:
        if not line.strip():
            continue
        for output in server.handle(json.loads(line)):
            print(json.dumps(output, ensure_ascii=False), flush=True)


def chat_once(prompt: str, cwd: str, codex_home: Path, jsonl: bool, model_args: argparse.Namespace | None = None) -> None:
    manager = ThreadManager(codex_home, model_args)
    thread_id = manager.start_thread(cwd)
    agent = manager.get_agent(thread_id)
    for event in agent.turn_events(prompt):
        render_event(event, jsonl)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", nargs="?", choices=["chat", "server"], default="chat")
    parser.add_argument("--once")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--codex-home", default=".mini-codex")
    parser.add_argument("--jsonl", action="store_true")
    add_model_args(parser)
    args = parser.parse_args()

    codex_home = Path(args.codex_home).expanduser()
    if args.mode == "server":
        server_main(codex_home, args)
    elif args.once is not None:
        chat_once(args.once, args.cwd, codex_home, args.jsonl, args)
    else:
        raise SystemExit("step8 supports --once chat or server mode")


if __name__ == "__main__":
    main()
