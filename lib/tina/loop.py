"""ReAct loop with trace capture."""

from __future__ import annotations

import json
import os
import pathlib
import time
from typing import Any

from tina.client import llm_client, model_fast
from tina.tools import ToolRegistry

TRACE_DIR = pathlib.Path(os.environ.get("ARA_TRACE_DIR", "/home/elastic/.traces"))


def react_loop(
    user_message: str,
    system_prompt: str,
    tools: ToolRegistry,
    model: str | None = None,
    max_iterations: int = 8,
    temperature: float = 0.0,
    trace_name: str | None = None,
) -> dict[str, Any]:
    """
    Run a ReAct loop and return a trace dict.

    Returns:
      {
        "answer": str,              # final assistant text
        "tool_calls": [...],        # list of {name, arguments, result} per iteration
        "messages": [...],          # full message history
        "iterations": int,
        "model": str,
        "input_tokens": int,        # approximate
        "output_tokens": int,
      }
    """
    client = llm_client()
    model = model or model_fast()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": user_message},
    ]

    tool_calls_log: list[dict] = []
    iterations = 0

    while iterations < max_iterations:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools.schema() if tools.registered_names() else [],
            tool_choice="auto",
            temperature=temperature,
        )
        iterations += 1
        msg = response.choices[0].message

        if msg.tool_calls:
            # Append assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })
            # Dispatch each tool call
            for tc in msg.tool_calls:
                result = tools.dispatch(tc.function.name, tc.function.arguments)
                tool_calls_log.append({
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                    "result": result,
                })
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            # Final answer
            answer = msg.content or ""
            messages.append({"role": "assistant", "content": answer})
            trace = {
                "answer": answer,
                "tool_calls": tool_calls_log,
                "messages": messages,
                "iterations": iterations,
                "model": model,
                "input_tokens": _count_tokens(messages[:-1]),
                "output_tokens": _count_tokens([messages[-1]]),
            }
            _save_trace(trace, trace_name)
            return trace

    # Max iterations reached
    trace = {
        "answer": "(max iterations reached)",
        "tool_calls": tool_calls_log,
        "messages": messages,
        "iterations": iterations,
        "model": model,
        "input_tokens": _count_tokens(messages),
        "output_tokens": 0,
    }
    _save_trace(trace, trace_name)
    return trace


def _count_tokens(messages: list[dict]) -> int:
    """Rough token estimate."""
    total = 0
    for m in messages:
        content = m.get("content") or ""
        total += int(len(content.split()) * 1.3)
    return total


def _save_trace(trace: dict, name: str | None) -> None:
    """Write trace to ARA_TRACE_DIR for check scripts to read."""
    try:
        TRACE_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{name or 'trace'}-{int(time.time())}.json"
        (TRACE_DIR / filename).write_text(json.dumps(trace, indent=2))
    except Exception:
        pass  # trace capture is best-effort; never break the loop
