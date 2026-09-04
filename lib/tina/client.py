"""LLM and Elasticsearch client factories honoring the two-route rule."""

from __future__ import annotations

import os


def llm_client(route: str = "A"):
    """
    Return an OpenAI-compatible client.

    Route A (default): curriculum LiteLLM proxy. Used by standalone notebooks
    that are not exercising Elasticsearch inference.

    Route B: caller is responsible for using the Elasticsearch _inference API
    directly; this function does not support route B.
    """
    if route != "A":
        raise ValueError(
            "llm_client() only supports route A (LiteLLM proxy). "
            "For route B, call the Elasticsearch _inference API directly."
        )
    from openai import OpenAI
    return OpenAI(
        base_url=os.environ["LLM_PROXY_URL"],
        api_key=os.environ.get("LLM_APIKEY", "unused"),
    )


def es_client():
    """Elasticsearch client from environment variables."""
    from elasticsearch import Elasticsearch
    return Elasticsearch(
        os.environ["ES_URL"],
        api_key=os.environ["ES_API_KEY"],
        request_timeout=30,
    )


def model_fast() -> str:
    return os.environ.get("ARA_MODEL_FAST", "gpt-4o-mini")


def model_strong() -> str:
    return os.environ.get("ARA_MODEL_STRONG", "claude-sonnet-5")
