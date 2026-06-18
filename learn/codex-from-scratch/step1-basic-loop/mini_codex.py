#!/usr/bin/env python3
"""Step 1: a tiny agent loop with history."""

from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass
class Message:
    role: str
    content: str


class RuleBasedModel:
    """A deterministic stand-in for an LLM."""

    def generate(self, history: list[Message]) -> str:
        last = history[-1].content.strip()
        if not last:
            return "I need a prompt before I can help."
        if "history" in last.lower():
            return f"I can see {len(history)} message(s) in this thread."
        return f"You said: {last}"


class Agent:
    def __init__(self, model: RuleBasedModel) -> None:
        self.model = model
        self.history: list[Message] = []

    def turn(self, user_text: str) -> str:
        self.history.append(Message("user", user_text))
        answer = self.model.generate(self.history)
        self.history.append(Message("assistant", answer))
        return answer

    def render_history(self) -> str:
        if not self.history:
            return "(empty)"
        return "\n".join(f"{message.role}: {message.content}" for message in self.history)


def repl(agent: Agent) -> None:
    print("mini-codex step1. Type /history or /quit.")
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
        print(agent.turn(user_text))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", help="Run one turn and exit.")
    args = parser.parse_args()

    agent = Agent(RuleBasedModel())
    if args.once is not None:
        print(agent.turn(args.once))
    else:
        repl(agent)


if __name__ == "__main__":
    main()
