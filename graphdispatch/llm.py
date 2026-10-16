"""Amazon Bedrock adapter (Converse API). The only module that talks to the LLM provider.

Design rule: the LLM never writes Cypher. It may only output values from enums derived from the graph.
Credentials come from the standard AWS chain (env vars / profile); this module never reads, prints or logs them.
"""
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv()
_CALLS = 0
_CLIENT = None
_LOG = Path(__file__).resolve().parent.parent / "runs" / "llm_calls.log"


class CallCapExceeded(RuntimeError):
    """The per-process LLM call cap (LLM_CALL_CAP, default 20) was reached."""


def call_count():
    return _CALLS


def _client():
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = boto3.client("bedrock-runtime", region_name=os.getenv("AWS_REGION"))
    return _CLIENT


def _log(model_id, status):
    """Append call metadata only (time, model, status): never prompts, responses or credentials."""
    try:
        _LOG.parent.mkdir(exist_ok=True)
        with _LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} {model_id} {status}\n")
    except OSError:
        pass


def converse(system, messages, tools=None, max_tokens=300, force_tool=None, model_id=None):
    """One Bedrock Converse call.

    system: str. messages: list of {"role", "content": [{"text": ...}]} (plain str content is wrapped).
    tools: list of {"name", "description", "input_schema"} dicts. force_tool: tool name the model must call.
    Returns dict: tool_name, tool_input, text, stop_reason, input_tokens, output_tokens, latency_ms.
    """
    global _CALLS
    cap = int(os.getenv("LLM_CALL_CAP", "20"))
    if _CALLS >= cap:
        raise CallCapExceeded(f"LLM call cap of {cap} reached in this process")
    model_id = model_id or os.getenv("BEDROCK_MODEL_ID")
    if not model_id:
        raise RuntimeError("BEDROCK_MODEL_ID is not set")
    msgs = [{"role": m["role"], "content": [{"text": m["content"]}] if isinstance(m["content"], str) else m["content"]}
            for m in messages]
    kwargs = {"modelId": model_id, "system": [{"text": system}], "messages": msgs,
              "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0}}
    if tools:
        cfg = {"tools": [{"toolSpec": {"name": t["name"], "description": t["description"],
                                       "inputSchema": {"json": t["input_schema"]}}} for t in tools]}
        if force_tool:
            cfg["toolChoice"] = {"tool": {"name": force_tool}}
        kwargs["toolConfig"] = cfg
    _CALLS += 1  # counted before the call: failed attempts count against the cap
    t0 = time.perf_counter()
    try:
        resp = _client().converse(**kwargs)
    except Exception as e:
        code = getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
        _log(model_id, f"ERROR {code}")
        raise
    ms = (time.perf_counter() - t0) * 1000
    _log(model_id, "ok")
    tool_name, tool_input, text = None, None, ""
    for block in resp["output"]["message"]["content"]:
        if "toolUse" in block:
            tool_name, tool_input = block["toolUse"]["name"], block["toolUse"]["input"]
        elif "text" in block:
            text += block["text"]
    return {"tool_name": tool_name, "tool_input": tool_input, "text": text, "stop_reason": resp["stopReason"],
            "input_tokens": resp["usage"]["inputTokens"], "output_tokens": resp["usage"]["outputTokens"],
            "latency_ms": ms}
