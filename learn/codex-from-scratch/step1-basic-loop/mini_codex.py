#!/usr/bin/env python3
"""Step 1: a tiny agent loop backed by an OpenAI-compatible LLM."""

import argparse
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))
from mini_llm import Message, OpenAIChatModel, add_model_args, build_model


class Agent:
    def __init__(self, model: OpenAIChatModel) -> None:
        self.model = model
        self.history: list[Message] = []

    def turn(self, user_text: str) -> str:
        self.history.append(Message("user", user_text))
        try:
            answer = self.model.complete(self.history)
        except Exception:
            self.history.pop()
            raise
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
    add_model_args(parser)
    args = parser.parse_args()

    agent = Agent(build_model(args))
    if args.once is not None:
        print(agent.turn(args.once))
    else:
        repl(agent)


if __name__ == "__main__":
    main()
