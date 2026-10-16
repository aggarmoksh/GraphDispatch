"""Try candidate model ids with one tiny Converse call each (max 20 output tokens); stop at the first that works."""
import os
os.environ["LLM_CALL_CAP"] = "5"  # model probing budget

from graphdispatch import llm

CANDIDATES = ["us.anthropic.claude-haiku-5-5", "global.anthropic.claude-haiku-5-5",
              "us.anthropic.claude-haiku-4-5-20251001-v1:0", "global.anthropic.claude-haiku-4-5-20251001-v1:0",
              "us.anthropic.claude-sonnet-5-5"]
for mid in CANDIDATES:
    try:
        r = llm.converse("Reply with one word.", [{"role": "user", "content": "Say OK."}], max_tokens=20, model_id=mid)
        print("WORKS", mid, "| stop:", r["stop_reason"], "| tokens in/out:", r["input_tokens"], r["output_tokens"],
              "| %.0f ms" % r["latency_ms"], "| text:", r["text"][:40].strip())
        break
    except llm.CallCapExceeded as e:
        print("cap:", e)
        break
    except Exception as e:
        code = getattr(e, "response", {}).get("Error", {}).get("Code", type(e).__name__)
        print("FAIL", mid, "|", type(e).__name__, code)
print("calls this process:", llm.call_count())
