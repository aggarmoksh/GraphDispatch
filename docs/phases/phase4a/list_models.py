"""List Anthropic foundation models and inference profiles in the region (no invocations)."""
import os
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv()
region = os.getenv("AWS_REGION")
br = boto3.client("bedrock", region_name=region)
lines = [f"region: {region}", "", "== foundation models (byProvider=anthropic): modelId | name | inference types | lifecycle"]
for m in sorted(br.list_foundation_models(byProvider="anthropic")["modelSummaries"], key=lambda m: m["modelId"]):
    lines.append(f"{m['modelId']} | {m['modelName']} | {','.join(m.get('inferenceTypesSupported', []))} | {m.get('modelLifecycle', {}).get('status')}")
lines += ["", "== inference profiles (anthropic): profileId | name | type | status"]
token = None
while True:
    kw = {"maxResults": 100}
    if token:
        kw["nextToken"] = token
    r = br.list_inference_profiles(**kw)
    for p in sorted(r["inferenceProfileSummaries"], key=lambda p: p["inferenceProfileId"]):
        if "anthropic" in p["inferenceProfileId"].lower():
            lines.append(f"{p['inferenceProfileId']} | {p['inferenceProfileName']} | {p['type']} | {p['status']}")
    token = r.get("nextToken")
    if not token:
        break
Path(__file__).with_name("models.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
