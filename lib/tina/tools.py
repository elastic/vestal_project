"""Tool registry and dispatcher for Tina."""

from __future__ import annotations

import json
from typing import Callable, Any


class ToolRegistry:
    """Register Python functions as OpenAI-format tools and dispatch calls."""

    def __init__(self):
        self._tools: dict[str, tuple[Callable, dict]] = {}

    def register(self, name: str, description: str, parameters: dict):
        """Decorator to register a function as a tool."""
        def decorator(fn: Callable) -> Callable:
            self._tools[name] = (fn, {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            })
            return fn
        return decorator

    def schema(self) -> list[dict]:
        """Return tool definitions for the OpenAI tools parameter."""
        return [spec for _, spec in self._tools.values()]

    def dispatch(self, name: str, arguments_json: str) -> str:
        """Call the named tool with the given JSON arguments, return result as string."""
        if name not in self._tools:
            return json.dumps({"error": f"Unknown tool: {name}"})
        fn, _ = self._tools[name]
        try:
            args = json.loads(arguments_json)
            result = fn(**args)
            return json.dumps(result) if not isinstance(result, str) else result
        except Exception as exc:
            return json.dumps({"error": str(exc)})

    def registered_names(self) -> list[str]:
        return list(self._tools.keys())
