#!/usr/bin/env python3
"""Step 9: add exec and TUI-like frontends on top of the step8 app server."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


STEP8_PATH = Path(__file__).resolve().parents[1] / "step8-app-server-protocol" / "mini_codex.py"
SPEC = importlib.util.spec_from_file_location("step8_runtime", STEP8_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load step8 runtime")
step8_runtime = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = step8_runtime
SPEC.loader.exec_module(step8_runtime)


class MiniClient:
    def __init__(self, codex_home: Path, model_args: argparse.Namespace | None = None) -> None:
        self.server = step8_runtime.MiniAppServer(step8_runtime.ThreadManager(codex_home, model_args))

    def request(self, method: str, params: dict) -> list[dict]:
        return self.server.handle({"id": method, "method": method, "params": params})

    def start_thread(self, cwd: str) -> str:
        outputs = self.request("thread/start", {"cwd": cwd})
        return outputs[-1]["result"]["threadId"]

    def turn(self, thread_id: str, prompt: str) -> list[dict]:
        return self.request("turn/start", {"threadId": thread_id, "input": prompt})


def render_outputs(outputs: list[dict], jsonl: bool) -> None:
    for item in outputs:
        if jsonl:
            print(json.dumps(item, ensure_ascii=False))
            continue
        if item.get("method") != "turn/event":
            continue
        event = item["params"]
        event_type = event["type"]
        data = event["data"]
        if event_type == "assistant_delta":
            print(data["delta"], end="", flush=True)
        elif event_type == "tool_call_started":
            print(f"[tool] {data['name']} {data['arguments']}")
        elif event_type == "tool_call_finished":
            print(data["output"])
        elif event_type == "turn_completed":
            print()


def exec_main(args: argparse.Namespace) -> None:
    client = MiniClient(Path(args.codex_home).expanduser(), args)
    thread_id = client.start_thread(args.cwd)
    render_outputs(client.turn(thread_id, args.prompt), args.jsonl)


def tui_main(args: argparse.Namespace) -> None:
    client = MiniClient(Path(args.codex_home).expanduser(), args)
    thread_id = client.start_thread(args.cwd)
    print(f"mini-codex step9 TUI-lite thread={thread_id}. Type /quit.")
    while True:
        try:
            prompt = input("> ")
        except EOFError:
            print()
            return
        if prompt == "/quit":
            return
        render_outputs(client.turn(thread_id, prompt), args.jsonl)


def server_main(args: argparse.Namespace) -> None:
    step8_runtime.server_main(Path(args.codex_home).expanduser(), args)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--codex-home", default=".mini-codex")
    sub = parser.add_subparsers(dest="command", required=True)

    exec_parser = sub.add_parser("exec")
    exec_parser.add_argument("prompt")
    exec_parser.add_argument("--cwd", default=".")
    exec_parser.add_argument("--jsonl", action="store_true")
    step8_runtime.add_model_args(exec_parser)

    tui_parser = sub.add_parser("tui")
    tui_parser.add_argument("--cwd", default=".")
    tui_parser.add_argument("--jsonl", action="store_true")
    step8_runtime.add_model_args(tui_parser)

    server_parser = sub.add_parser("server")
    step8_runtime.add_model_args(server_parser)
    args = parser.parse_args()

    if args.command == "exec":
        exec_main(args)
    elif args.command == "tui":
        tui_main(args)
    elif args.command == "server":
        server_main(args)
    else:
        raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
