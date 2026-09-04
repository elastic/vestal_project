"""
tina — reference Tina harness for ARA tracks M1–M3.

Exports:
  llm_client()         OpenAI-compatible client via LLM_PROXY_URL (route A)
  es_client()          Elasticsearch client from ES_URL + ES_API_KEY
  ToolRegistry         Register and dispatch tools
  react_loop()         ReAct loop with trace capture
  MemoryStore          Interface the learner implements in track 1.4

Environment variables consumed (set by challenge 01 setup or by the learner outside Instruqt):
  LLM_PROXY_URL              LiteLLM proxy base URL (route A)
  LLM_APIKEY                 Proxy API key
  ARA_MODEL_FAST             Fast-tier model name (e.g. gpt-4o-mini)
  ARA_MODEL_STRONG           Strong-tier model name (e.g. claude-sonnet-5)
  ARA_INFERENCE_COMPLETION_ID  Elasticsearch _inference endpoint id (route B)
  ES_URL                     Elasticsearch base URL
  ES_API_KEY                 Elasticsearch API key
  ARA_TRACE_DIR              Where to write trace files (default: /home/elastic/.traces)
"""

from tina.client import llm_client, es_client
from tina.tools import ToolRegistry
from tina.loop import react_loop
from tina.memory import MemoryStore

__all__ = ["llm_client", "es_client", "ToolRegistry", "react_loop", "MemoryStore"]
