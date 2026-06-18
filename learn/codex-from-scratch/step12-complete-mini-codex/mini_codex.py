#!/usr/bin/env python3
"""Step 12: a complete teaching-sized Codex clone."""

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
    "You are Mini Codex, a teaching-sized local coding agent. Use runtime context and available capabilities "
    "when useful. Return concise final answers after local work."
)


@dataclass
class Config:
    cwd: Path
    codex_home: Path
    approval: str = "never"
    sandbox: str = "workspace-write"
    context_limit: int = 4000


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
            lines = path.read_text(encoding="utf-8").splitlines()
            if not lines:
                continue
            first = json.loads(lines[0])
            rows.append(
                {
                    "threadId": path.stem,
                    "cwd": first.get("cwd"),
                    "createdAt": first.get("created_at"),
                    "records": len(lines),
                }
            )
        return rows


class ExtensionManager:
    def __init__(self, home: Path) -> None:
        self.home = home
        self.skills_dir = home / "skills"
        self.plugins_dir = home / "plugins"
        self.auth_file = home / "auth.json"
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

    def login(self, token: str) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        self.auth_file.write_text(json.dumps({"token": token, "createdAt": int(time.time())}), encoding="utf-8")

    def logout(self) -> None:
        self.auth_file.unlink(missing_ok=True)

    def auth_status(self) -> str:
        return "logged in" if self.auth_file.exists() else "not logged in"

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
        self.project_instructions = load_agents_md(config.cwd)

    def build(self, history: list[Message], plan: list[dict]) -> str:
        skills = "\n".join(f"- {skill['name']}" for skill in self.extensions.skills()) or "(none)"
        plugin_tools = "\n".join(
            f"- {tool['name']}: {tool.get('description', '')}" for tool in self.extensions.plugin_tools()
        ) or "(none)"
        plan_text = "\n".join(f"- [{item.get('status')}] {item.get('step')}" for item in plan) or "(none)"
        recent = "\n".join(f"{message.role}: {message.content}" for message in history[-10:])
        parts = [
            "You are Mini Codex, a local coding agent.",
            f"cwd: {self.config.cwd}",
            f"sandbox: {self.config.sandbox}",
            f"approval: {self.config.approval}",
            f"auth: {self.extensions.auth_status()}",
            "Use the attached tool schemas for currently available tools.",
            "skills:\n" + skills,
            "plugin tools:\n" + plugin_tools,
            "plan:\n" + plan_text,
        ]
        if self.project_instructions:
            parts.append("project instructions:\n" + self.project_instructions)
        if recent:
            parts.append("recent history:\n" + recent)
        context = "\n\n".join(parts)
        return context[-self.config.context_limit :]


class PermissionPolicy:
    def __init__(self, config: Config) -> None:
        self.config = config

    def check(self, call: ToolCall) -> PermissionDecision:
        if call.name == "apply_patch" and self.config.sandbox == "read-only":
            return PermissionDecision("deny", "read-only sandbox blocks file edits")
        if call.name == "shell":
            command = str(call.arguments.get("command", ""))
            dangerous = ["rm ", "sudo", "curl ", "wget ", "chmod ", "chown ", ">"]
            if any(marker in command for marker in dangerous):
                if self.config.approval == "on-request":
                    return PermissionDecision("ask", f"potentially dangerous command: {command}")
                return PermissionDecision("deny", f"approval disabled for: {command}")
        return PermissionDecision("allow", "allowed")

    def approved(self, decision: PermissionDecision) -> bool:
        if decision.status == "allow":
            return True
        if decision.status == "deny" or not sys.stdin.isatty():
            return False
        answer = input(f"Allow tool call? {decision.reason} [y/N] ")
        return answer.lower() in {"y", "yes"}


class ToolRegistry:
    def __init__(self, config: Config, extensions: ExtensionManager, agent_factory) -> None:
        self.config = config
        self.extensions = extensions
        self.agent_factory = agent_factory
        self.policy = PermissionPolicy(config)
        self.plan: list[dict] = []
        self.loaded_tools = {
            "shell",
            "apply_patch",
            "update_plan",
            "tool_search",
            "spawn_agent",
            "compact_context",
            "get_context_remaining",
            "request_user_input",
        }
        self.discoverable = {
            "reverse": "Reverse text from the demo plugin",
            "word_count": "Count words from the demo plugin",
            "web_search": "Offline teaching stub for web search",
            "view_image": "Validate an image path and report metadata",
            "generate_image": "Create a placeholder image artifact",
            "browser_open": "Offline teaching stub for browser navigation",
        }
        for tool in self.extensions.plugin_tools():
            self.loaded_tools.add(tool["name"])

    def list_tools(self) -> list[dict]:
        builtins = [{"name": name, "description": "built-in"} for name in sorted(self.loaded_tools)]
        discovered = [{"name": name, "description": desc, "status": "discoverable"} for name, desc in self.discoverable.items()]
        return builtins + self.extensions.plugin_tools() + discovered

    def tool_specs(self) -> list[dict]:
        specs: list[dict] = []
        if "shell" in self.loaded_tools:
            specs.append(
                function_tool(
                    "shell",
                    "Run a shell command in the workspace.",
                    {"command": {"type": "string", "description": "Command to execute."}},
                    ["command"],
                )
            )
        if "apply_patch" in self.loaded_tools:
            specs.append(
                function_tool(
                    "apply_patch",
                    "Write a file inside the workspace.",
                    {
                        "path": {"type": "string", "description": "Workspace-relative path."},
                        "content": {"type": "string", "description": "Complete file content to write."},
                    },
                    ["path", "content"],
                )
            )
        if "update_plan" in self.loaded_tools:
            specs.append(
                function_tool(
                    "update_plan",
                    "Replace the current task plan checklist.",
                    {
                        "items": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "step": {"type": "string"},
                                    "status": {
                                        "type": "string",
                                        "enum": ["pending", "in_progress", "completed"],
                                    },
                                },
                                "required": ["step", "status"],
                                "additionalProperties": False,
                            },
                        }
                    },
                    ["items"],
                )
            )
        if "tool_search" in self.loaded_tools:
            specs.append(
                function_tool(
                    "tool_search",
                    "Search for optional tools and load matching tools into the registry.",
                    {"query": {"type": "string", "description": "Tool search query."}},
                    ["query"],
                )
            )
        if "spawn_agent" in self.loaded_tools:
            specs.append(
                function_tool(
                    "spawn_agent",
                    "Start a child agent for a small delegated task.",
                    {
                        "role": {"type": "string", "description": "Child agent role name."},
                        "task": {"type": "string", "description": "Task for the child agent."},
                    },
                    ["role", "task"],
                )
            )
        if "compact_context" in self.loaded_tools:
            specs.append(function_tool("compact_context", "Compact context into a short summary.", {}, []))
        if "get_context_remaining" in self.loaded_tools:
            specs.append(function_tool("get_context_remaining", "Return remaining context budget.", {}, []))
        if "request_user_input" in self.loaded_tools:
            specs.append(
                function_tool(
                    "request_user_input",
                    "Ask the user a short question.",
                    {"question": {"type": "string", "description": "Question to ask."}},
                    ["question"],
                )
            )
        if "reverse" in self.loaded_tools:
            specs.append(
                function_tool("reverse", "Reverse text.", {"text": {"type": "string", "description": "Text to reverse."}}, ["text"])
            )
        if "word_count" in self.loaded_tools:
            specs.append(
                function_tool("word_count", "Count words.", {"text": {"type": "string", "description": "Text to count."}}, ["text"])
            )
        if "web_search" in self.loaded_tools:
            specs.append(
                function_tool("web_search", "Offline teaching stub for web search.", {"query": {"type": "string"}}, ["query"])
            )
        if "view_image" in self.loaded_tools:
            specs.append(function_tool("view_image", "Check whether an image path exists.", {"path": {"type": "string"}}, ["path"]))
        if "generate_image" in self.loaded_tools:
            specs.append(
                function_tool("generate_image", "Create a placeholder image artifact.", {"path": {"type": "string"}}, ["path"])
            )
        if "browser_open" in self.loaded_tools:
            specs.append(function_tool("browser_open", "Offline teaching stub for opening a URL.", {"url": {"type": "string"}}, ["url"]))
        return specs

    def run(self, call: ToolCall, context: str = "") -> ToolResult:
        decision = self.policy.check(call)
        if not self.policy.approved(decision):
            return ToolResult(call.name, False, f"blocked: {decision.reason}")
        if call.name == "shell":
            command = str(call.arguments.get("command", ""))
            completed = subprocess.run(command, shell=True, cwd=self.config.cwd, text=True, capture_output=True, timeout=20)
            return ToolResult("shell", completed.returncode == 0, (completed.stdout + completed.stderr).rstrip())
        if call.name == "apply_patch":
            return self.apply_patch(call.arguments)
        if call.name == "update_plan":
            self.plan = list(call.arguments.get("items", []))
            rendered = "\n".join(f"- [{item.get('status', 'pending')}] {item.get('step')}" for item in self.plan)
            return ToolResult("update_plan", True, rendered)
        if call.name == "tool_search":
            query = str(call.arguments.get("query", "")).lower()
            matches = [
                {"name": name, "description": desc}
                for name, desc in self.discoverable.items()
                if query in name or query in desc.lower()
            ]
            for match in matches:
                self.loaded_tools.add(match["name"])
            return ToolResult("tool_search", True, json.dumps(matches))
        if call.name == "spawn_agent":
            role = str(call.arguments.get("role", "explorer"))
            task = str(call.arguments.get("task", ""))
            child = self.agent_factory(role)
            events = list(child.turn_events(task))
            final = next((event.data["answer"] for event in reversed(events) if event.type == "turn_completed"), "")
            return ToolResult("spawn_agent", True, f"{role} completed: {final}")
        if call.name == "compact_context":
            return ToolResult("compact_context", True, "Context compacted into a short teaching summary.")
        if call.name == "get_context_remaining":
            remaining = max(self.config.context_limit - len(context), 0)
            return ToolResult("get_context_remaining", True, str(remaining))
        if call.name == "request_user_input":
            question = str(call.arguments.get("question", "Continue?"))
            if sys.stdin.isatty():
                return ToolResult("request_user_input", True, input(question + " "))
            return ToolResult("request_user_input", True, "(no tty; default response)")
        if call.name == "reverse" and "reverse" in self.loaded_tools:
            return ToolResult("reverse", True, str(call.arguments.get("text", ""))[::-1])
        if call.name == "word_count" and "word_count" in self.loaded_tools:
            return ToolResult("word_count", True, str(len(str(call.arguments.get("text", "")).split())))
        if call.name == "web_search" and "web_search" in self.loaded_tools:
            query = str(call.arguments.get("query", ""))
            return ToolResult("web_search", True, f"offline search result for: {query}")
        if call.name == "view_image" and "view_image" in self.loaded_tools:
            path = ensure_inside(self.config.cwd, str(call.arguments.get("path", "")))
            return ToolResult("view_image", path.exists(), f"{path} exists={path.exists()}")
        if call.name == "generate_image" and "generate_image" in self.loaded_tools:
            target = ensure_inside(self.config.cwd, str(call.arguments.get("path", "generated-image.txt")))
            target.write_text("placeholder image artifact\n", encoding="utf-8")
            return ToolResult("generate_image", True, f"created {target}")
        if call.name == "browser_open" and "browser_open" in self.loaded_tools:
            return ToolResult("browser_open", True, f"would open {call.arguments.get('url')}")
        return ToolResult(call.name, False, f"unknown or unloaded tool: {call.name}")

    def apply_patch(self, arguments: dict) -> ToolResult:
        try:
            path = str(arguments.get("path", ""))
            content = str(arguments.get("content", ""))
            target = ensure_inside(self.config.cwd, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return ToolResult("apply_patch", True, f"wrote {path}")
        except Exception as exc:
            return ToolResult("apply_patch", False, str(exc))


class Agent:
    def __init__(
        self,
        thread_id: str | None,
        config: Config,
        extensions: ExtensionManager,
        store: RolloutStore | None,
        role: str = "main",
        model_args: argparse.Namespace | None = None,
    ) -> None:
        self.thread_id = thread_id
        self.config = config
        self.extensions = extensions
        self.store = store
        self.role = role
        self.model_args = model_args
        self.history = store.history(thread_id) if store and thread_id else []
        self.model = build_model(model_args, SYSTEM_PROMPT)
        self.context_manager = ContextManager(config, extensions)
        self.tools = ToolRegistry(config, extensions, self.child_agent)

    def child_agent(self, role: str) -> "Agent":
        return Agent(None, self.config, self.extensions, None, role, self.model_args)

    def record(self, message: Message) -> None:
        if self.store and self.thread_id:
            record = {"type": f"{message.role}_message", "role": message.role, "content": message.content, "ts": time.time()}
            if message.tool_call_id:
                record["tool_call_id"] = message.tool_call_id
            if message.name:
                record["name"] = message.name
            if message.tool_calls:
                record["tool_calls"] = message.tool_calls
            self.store.append(self.thread_id, record)

    def context(self) -> str:
        return self.context_manager.build(self.history, self.tools.plan)

    def turn_events(self, prompt: str) -> Iterable[Event]:
        user_message = Message("user", prompt)
        self.history.append(user_message)
        self.record(user_message)
        yield Event("turn_started", {"threadId": self.thread_id, "role": self.role, "input": prompt})
        while True:
            context = self.context()
            action = None
            for model_event in self.model.stream_action(self.history, self.tools.tool_specs(), context=context):
                if model_event.kind == "delta":
                    yield Event("assistant_delta", {"delta": model_event.delta})
                elif model_event.action is not None:
                    action = model_event.action

            if action is None:
                raise RuntimeError("model stream ended without an action")

            if action.kind == "final":
                assistant_message = Message("assistant", action.text)
                self.history.append(assistant_message)
                self.record(assistant_message)
                yield Event("turn_completed", {"threadId": self.thread_id, "answer": action.text})
                return
            call = action.tool_call
            assert call is not None
            if action.assistant_message is not None:
                self.history.append(action.assistant_message)
                self.record(action.assistant_message)
            yield Event("tool_call_started", asdict(call))
            result = self.tools.run(call, context)
            yield Event("tool_call_finished", asdict(result))
            tool_message = Message("tool", result.output, tool_call_id=call.id, name=call.name)
            self.history.append(tool_message)
            self.record(tool_message)


class ThreadManager:
    def __init__(self, codex_home: Path, model_args: argparse.Namespace | None = None) -> None:
        self.codex_home = codex_home
        self.model_args = model_args
        self.store = RolloutStore(codex_home)
        self.extensions = ExtensionManager(codex_home)
        self.configs: dict[str, Config] = {}
        self.last_thread_id: str | None = None

    def start_thread(self, cwd: str, approval: str = "never", sandbox: str = "workspace-write") -> str:
        resolved = Path(cwd).resolve()
        resolved.mkdir(parents=True, exist_ok=True)
        thread_id = self.store.create(resolved)
        self.configs[thread_id] = Config(cwd=resolved, codex_home=self.codex_home, approval=approval, sandbox=sandbox)
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
        return Agent(thread_id, config, self.extensions, self.store, model_args=self.model_args)


class MiniAppServer:
    def __init__(self, manager: ThreadManager) -> None:
        self.manager = manager

    def handle(self, request: dict) -> list[dict]:
        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}
        try:
            if method == "thread/start":
                thread_id = self.manager.start_thread(
                    params.get("cwd", "."),
                    params.get("approval", "never"),
                    params.get("sandbox", "workspace-write"),
                )
                return [self.response(request_id, {"threadId": thread_id})]
            if method == "thread/list":
                return [self.response(request_id, {"data": self.manager.store.list_threads()})]
            if method == "thread/read":
                return [self.response(request_id, {"records": self.manager.store.records(params["threadId"])})]
            if method == "turn/start":
                agent = self.manager.get_agent(params["threadId"])
                outputs = [self.notification("turn/event", asdict(event)) for event in agent.turn_events(params["input"])]
                outputs.append(self.response(request_id, {"threadId": agent.thread_id, "status": "completed"}))
                return outputs
            if method == "turn/interrupt":
                return [self.response(request_id, {"status": "no active async turn in teaching runtime"})]
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


def render_events(events: Iterable[Event], jsonl: bool) -> None:
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


def server_main(args: argparse.Namespace) -> None:
    server = MiniAppServer(ThreadManager(Path(args.codex_home).expanduser(), args))
    for line in sys.stdin:
        if not line.strip():
            continue
        for output in server.handle(json.loads(line)):
            print(json.dumps(output, ensure_ascii=False), flush=True)


def exec_main(args: argparse.Namespace) -> None:
    manager = ThreadManager(Path(args.codex_home).expanduser(), args)
    thread_id = args.resume or manager.start_thread(args.cwd, args.approval, args.sandbox)
    render_events(manager.get_agent(thread_id).turn_events(args.prompt), args.jsonl)


def chat_main(args: argparse.Namespace) -> None:
    manager = ThreadManager(Path(args.codex_home).expanduser(), args)
    thread_id = args.resume or manager.start_thread(args.cwd, args.approval, args.sandbox)
    print(f"mini-codex full chat thread={thread_id}. Type /quit.")
    while True:
        try:
            prompt = input("> ")
        except EOFError:
            print()
            return
        if prompt == "/quit":
            return
        render_events(manager.get_agent(thread_id).turn_events(prompt), args.jsonl)


def review_main(args: argparse.Namespace) -> None:
    path = Path(args.path).resolve()
    findings: list[str] = []
    files = [path] if path.is_file() else sorted(path.rglob("*.py"))
    for file_path in files[:50]:
        text = file_path.read_text(errors="replace")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "TODO" in line or "pass" == line.strip():
                findings.append(f"{file_path}:{lineno}: review finding: {line.strip()}")
    if findings:
        print("\n".join(findings))
    else:
        print("No obvious teaching-runtime findings.")


def compact_main(args: argparse.Namespace) -> None:
    store = RolloutStore(Path(args.codex_home).expanduser())
    records = store.records(args.thread_id)
    summary = f"Compacted {len(records)} rollout record(s) for thread {args.thread_id}."
    store.append(args.thread_id, {"type": "assistant_message", "role": "assistant", "content": summary, "ts": time.time()})
    print(summary)


def add_runtime_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--codex-home", default=".mini-codex")
    parser.add_argument("--cwd", default=".")
    parser.add_argument("--approval", choices=["never", "on-request"], default="never")
    parser.add_argument("--sandbox", choices=["read-only", "workspace-write", "danger-full-access"], default="workspace-write")
    parser.add_argument("--resume")
    parser.add_argument("--jsonl", action="store_true")
    add_model_args(parser)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    exec_parser = sub.add_parser("exec")
    add_runtime_args(exec_parser)
    exec_parser.add_argument("prompt")

    chat_parser = sub.add_parser("chat")
    add_runtime_args(chat_parser)

    server_parser = sub.add_parser("server")
    server_parser.add_argument("--codex-home", default=".mini-codex")
    add_model_args(server_parser)

    threads_parser = sub.add_parser("threads")
    threads_parser.add_argument("--codex-home", default=".mini-codex")

    review_parser = sub.add_parser("review")
    review_parser.add_argument("--codex-home", default=".mini-codex")
    review_parser.add_argument("path")

    compact_parser = sub.add_parser("compact")
    compact_parser.add_argument("--codex-home", default=".mini-codex")
    compact_parser.add_argument("thread_id")

    init_parser = sub.add_parser("init-sample-extension")
    init_parser.add_argument("--codex-home", default=".mini-codex")

    skills_parser = sub.add_parser("skills/list")
    skills_parser.add_argument("--codex-home", default=".mini-codex")

    plugins_parser = sub.add_parser("plugins/list")
    plugins_parser.add_argument("--codex-home", default=".mini-codex")

    mcp_parser = sub.add_parser("mcp/list-tools")
    mcp_parser.add_argument("--codex-home", default=".mini-codex")

    login_parser = sub.add_parser("login")
    login_parser.add_argument("--codex-home", default=".mini-codex")
    login_parser.add_argument("--token", default="teaching-token")

    logout_parser = sub.add_parser("logout")
    logout_parser.add_argument("--codex-home", default=".mini-codex")

    config_parser = sub.add_parser("config/show")
    config_parser.add_argument("--codex-home", default=".mini-codex")

    args = parser.parse_args()
    home = Path(getattr(args, "codex_home", ".mini-codex")).expanduser()
    extensions = ExtensionManager(home)

    if args.command == "exec":
        exec_main(args)
    elif args.command == "chat":
        chat_main(args)
    elif args.command == "server":
        server_main(args)
    elif args.command == "threads":
        for row in RolloutStore(home).list_threads():
            print(f"{row['threadId']}  records={row['records']}  cwd={row['cwd']}")
    elif args.command == "review":
        review_main(args)
    elif args.command == "compact":
        compact_main(args)
    elif args.command == "init-sample-extension":
        extensions.init_sample()
        print(f"created sample extension under {home}")
    elif args.command == "skills/list":
        for skill in extensions.skills():
            print(f"{skill['name']}  {skill['path']}")
    elif args.command == "plugins/list":
        for plugin in extensions.plugins():
            print(f"{plugin['name']}  tools={len(plugin.get('tools', []))}")
    elif args.command == "mcp/list-tools":
        for tool in extensions.plugin_tools():
            print(f"{tool['name']}  plugin={tool['plugin']}  {tool.get('description', '')}")
    elif args.command == "login":
        extensions.login(args.token)
        print("logged in")
    elif args.command == "logout":
        extensions.logout()
        print("logged out")
    elif args.command == "config/show":
        print(json.dumps({"codexHome": str(home), "auth": extensions.auth_status()}, indent=2))


if __name__ == "__main__":
    main()
