"""Shared OpenAI-compatible model adapter for the Mini Codex tutorial."""

import argparse
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable, Literal, Optional


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_SYSTEM_PROMPT = (
    "You are Mini Codex, a tiny teaching agent. Keep the conversation helpful, "
    "direct, and aware of the prior messages."
)


@dataclass
class Message:
    role: str
    content: str = ""
    tool_call_id: str | None = None
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    id: str = "call_manual"


@dataclass
class ModelAction:
    kind: Literal["final", "tool_call"]
    text: str = ""
    tool_call: ToolCall | None = None
    assistant_message: Message | None = None


@dataclass
class ModelConfig:
    api_key: str
    model: str
    base_url: str
    system_prompt: str
    temperature: Optional[float]
    max_tokens: Optional[int]
    timeout: float


class OpenAIChatModel:
    """Minimal OpenAI-compatible /chat/completions client using only stdlib."""

    def __init__(self, config: ModelConfig) -> None:
        self.config = config

    def complete(self, history: list[Message], context: str = "") -> str:
        payload = self._payload(history, context)
        return extract_assistant_content(self._post_json(payload)["choices"][0]["message"])

    def stream(self, history: list[Message], context: str = "") -> Iterable[str]:
        payload = self._payload(history, context)
        payload["stream"] = True
        for event in self._post_stream(payload):
            choices = event.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            delta = choices[0].get("delta", {})
            if isinstance(delta, dict):
                content = delta.get("content")
                if isinstance(content, str):
                    yield content

    def next_action(self, history: list[Message], tools: list[dict[str, Any]], context: str = "") -> ModelAction:
        payload = self._payload(history, context)
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        data = self._post_json(payload)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"model response did not include choices: {data}")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise RuntimeError(f"model choice did not include a message: {choices[0]}")

        content = extract_assistant_content(message)
        raw_tool_calls = message.get("tool_calls")
        if isinstance(raw_tool_calls, list) and raw_tool_calls:
            tool_call = parse_tool_call(raw_tool_calls[0])
            assistant_message = Message("assistant", content, tool_calls=raw_tool_calls)
            return ModelAction("tool_call", text=content, tool_call=tool_call, assistant_message=assistant_message)
        return ModelAction("final", text=content)

    def _payload(self, history: list[Message], context: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": build_messages(self.config.system_prompt, context, history),
        }
        if self.config.temperature is not None:
            payload["temperature"] = self.config.temperature
        if self.config.max_tokens is not None:
            payload["max_tokens"] = self.config.max_tokens
        return payload

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = self._post(payload).decode("utf-8")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"model returned invalid JSON: {raw}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"model returned a non-object JSON response: {parsed!r}")
        return parsed

    def _post_stream(self, payload: dict[str, Any]) -> Iterable[dict[str, Any]]:
        for raw_line in self._post_lines(payload):
            line = raw_line.decode("utf-8", errors="replace").strip()
            if not line.startswith("data: "):
                continue
            data = line.removeprefix("data: ")
            if data == "[DONE]":
                return
            try:
                event = json.loads(data)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"model returned invalid stream event: {data}") from exc
            if isinstance(event, dict):
                yield event

    def _post(self, payload: dict[str, Any]) -> bytes:
        with self._open(payload) as response:
            return response.read()

    def _post_lines(self, payload: dict[str, Any]) -> Iterable[bytes]:
        with self._open(payload) as response:
            for line in response:
                yield line

    def _open(self, payload: dict[str, Any]):
        body = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self._chat_completions_url(),
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            return urllib.request.urlopen(request, timeout=self.config.timeout)
        except urllib.error.HTTPError as exc:
            raw_error = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"model request failed with HTTP {exc.code}: {raw_error}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"model request failed: {exc.reason}") from exc

    def _chat_completions_url(self) -> str:
        base_url = self.config.base_url.rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"


def build_messages(system_prompt: str, context: str, history: list[Message]) -> list[dict[str, Any]]:
    prompt = system_prompt
    if context:
        prompt = f"{prompt}\n\nRuntime context:\n{context}"
    messages: list[dict[str, Any]] = [{"role": "system", "content": prompt}] if prompt else []
    messages.extend(message_to_openai(message) for message in history)
    return messages


def message_to_openai(message: Message) -> dict[str, Any]:
    if message.role == "tool":
        return {
            "role": "tool",
            "tool_call_id": message.tool_call_id or "call_manual",
            "content": message.content,
        }
    item: dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        item["tool_calls"] = message.tool_calls
    return item


def parse_tool_call(raw_tool_call: dict[str, Any]) -> ToolCall:
    function = raw_tool_call.get("function")
    if not isinstance(function, dict):
        raise RuntimeError(f"tool call did not include a function: {raw_tool_call}")
    name = function.get("name")
    if not isinstance(name, str) or not name:
        raise RuntimeError(f"tool call did not include a function name: {raw_tool_call}")
    raw_arguments = function.get("arguments") or "{}"
    if not isinstance(raw_arguments, str):
        raise RuntimeError(f"tool call arguments were not a JSON string: {raw_tool_call}")
    try:
        arguments = json.loads(raw_arguments)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"tool call arguments were invalid JSON: {raw_arguments}") from exc
    if not isinstance(arguments, dict):
        raise RuntimeError(f"tool call arguments must decode to an object: {raw_arguments}")
    return ToolCall(name=name, arguments=arguments, id=str(raw_tool_call.get("id", "call_manual")))


def extract_assistant_content(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    raise RuntimeError(f"model message did not include text content: {message}")


def function_tool(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


def add_model_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", help="Model name. Defaults to OPENAI_MODEL.")
    parser.add_argument("--base-url", help=f"OpenAI-compatible base URL. Defaults to {DEFAULT_BASE_URL}.")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY", help="Environment variable that stores the API key.")
    parser.add_argument("--system-prompt", help="System prompt. Defaults to OPENAI_SYSTEM_PROMPT or a built-in prompt.")
    parser.add_argument("--temperature", type=float, help="Sampling temperature. Defaults to OPENAI_TEMPERATURE if set.")
    parser.add_argument("--max-tokens", type=int, help="Max completion tokens. Defaults to OPENAI_MAX_TOKENS if set.")
    parser.add_argument("--timeout", type=float, help="HTTP timeout in seconds. Defaults to OPENAI_TIMEOUT or 60.")


def build_model(args: argparse.Namespace | None = None, default_system_prompt: str = DEFAULT_SYSTEM_PROMPT) -> OpenAIChatModel:
    api_key_env = getattr(args, "api_key_env", "OPENAI_API_KEY") if args is not None else "OPENAI_API_KEY"
    api_key = required_text(
        os.environ.get(api_key_env),
        f"Missing API key. Set {api_key_env}=... before running mini_codex.py.",
    )
    model_arg = getattr(args, "model", None) if args is not None else None
    model = required_text(model_arg or os.environ.get("OPENAI_MODEL"), "Missing model. Set OPENAI_MODEL=... or pass --model.")
    base_url_arg = getattr(args, "base_url", None) if args is not None else None
    base_url = base_url_arg or os.environ.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL
    system_prompt = getattr(args, "system_prompt", None) if args is not None else None
    if system_prompt is None:
        system_prompt = os.environ.get("OPENAI_SYSTEM_PROMPT", default_system_prompt)

    temperature = getattr(args, "temperature", None) if args is not None else None
    if temperature is None:
        temperature = optional_float(os.environ.get("OPENAI_TEMPERATURE"), "OPENAI_TEMPERATURE")

    max_tokens = getattr(args, "max_tokens", None) if args is not None else None
    if max_tokens is None:
        max_tokens = optional_int(os.environ.get("OPENAI_MAX_TOKENS"), "OPENAI_MAX_TOKENS")

    timeout = getattr(args, "timeout", None) if args is not None else None
    if timeout is None:
        timeout = optional_float(os.environ.get("OPENAI_TIMEOUT"), "OPENAI_TIMEOUT") or 60.0

    return OpenAIChatModel(
        ModelConfig(
            api_key=api_key,
            model=model,
            base_url=base_url,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )
    )


def optional_float(value: Optional[str], name: str) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be a number, got {value!r}") from exc


def optional_int(value: Optional[str], name: str) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer, got {value!r}") from exc


def required_text(value: Optional[str], message: str) -> str:
    if value is None or value == "":
        raise SystemExit(message)
    return value
