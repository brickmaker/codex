#!/usr/bin/env python3
"""Step 2: stream turn events to a renderer."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from typing import Iterable


@dataclass
class Message:
    role: str
    content: str


@dataclass
class Event:
    type: str
    data: dict


class RuleBasedModel:
    def complete(self, history: list[Message]) -> str:
        last = history[-1].content.strip()
        if not last:
            return "I need a prompt before I can help."
        if "stream" in last.lower():
            return "Streaming lets the UI render progress while the agent is still working."
        return f"You said: {last}"

    def stream(self, history: list[Message]) -> Iterable[str]:
        text = self.complete(history)
        for word in text.split(" "):
            yield word + " "


class Agent:
    def __init__(self, model: RuleBasedModel) -> None:
        self.model = model
        self.history: list[Message] = []

    def turn_events(self, user_text: str) -> Iterable[Event]:
        self.history.append(Message("user", user_text))
        yield Event("turn_started", {"input": user_text})

        chunks: list[str] = []
        for delta in self.model.stream(self.history):
            chunks.append(delta)
            yield Event("assistant_delta", {"delta": delta})

        answer = "".join(chunks).rstrip()
        self.history.append(Message("assistant", answer))
        yield Event("turn_completed", {"answer": answer})

    def render_history(self) -> str:
        if not self.history:
            return "(empty)"
        return "\n".join(f"{message.role}: {message.content}" for message in self.history)


def render_event(event: Event, jsonl: bool) -> None:
    if jsonl:
        print(json.dumps(asdict(event), ensure_ascii=False))
        return
    if event.type == "assistant_delta":
        print(event.data["delta"], end="", flush=True)
    elif event.type == "turn_completed":
        print()


def run_turn(agent: Agent, prompt: str, jsonl: bool) -> None:
    for event in agent.turn_events(prompt):
        render_event(event, jsonl)


def repl(agent: Agent, jsonl: bool) -> None:
    print("mini-codex step2. Type /history or /quit.")
    while True:
        try:
            user_text = input("> ")
        except EOFError:
            print()
            return
        if user_text == "/quit":
            return
        if user_text == "/history":
            print(agent.render_history())
            continue
        run_turn(agent, user_text, jsonl)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", help="Run one turn and exit.")
    parser.add_argument("--jsonl", action="store_true", help="Render events as JSON lines.")
    args = parser.parse_args()

    agent = Agent(RuleBasedModel())
    if args.once is not None:
        run_turn(agent, args.once, args.jsonl)
    else:
        repl(agent, args.jsonl)


if __name__ == "__main__":
    main()
