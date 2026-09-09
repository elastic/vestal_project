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
    proxy_url = os.environ["LLM_PROXY_URL"]
    if proxy_url and not proxy_url.startswith(("http://", "https://")):
        proxy_url = f"https://{proxy_url}"
    return OpenAI(
        base_url=proxy_url,
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
    val = os.environ.get("ARA_MODEL_FAST")
    if not val:
        raise EnvironmentError(
            "ARA_MODEL_FAST is not set. Run the harness setup cell or source /home/elastic/env."
        )
    return val


def model_strong() -> str:
    val = os.environ.get("ARA_MODEL_STRONG")
    if not val:
        raise EnvironmentError(
            "ARA_MODEL_STRONG is not set. Run the harness setup cell or source /home/elastic/env."
        )
    return val
