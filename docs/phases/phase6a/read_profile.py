"""Read-only: print the model ARNs the Haiku 4.5 US inference profile routes to (bedrock:GetInferenceProfile).
Account id is masked. Credentials come from the default chain (here, the gitignored .env). Never prints keys.
"""
import os
from pathlib import Path

import boto3
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")
PROFILE = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
br = boto3.client("bedrock", region_name=os.getenv("AWS_REGION"))
r = br.get_inference_profile(inferenceProfileIdentifier=PROFILE)


def mask(arn):
    parts = arn.split(":")
    if len(parts) > 4 and parts[4]:
        parts[4] = "<ACCOUNT_ID>"
    return ":".join(parts)


print("profile arn:", mask(r["inferenceProfileArn"]))
print("type/status:", r["type"], r["status"])
for m in r["models"]:
    print("model arn:", m["modelArn"])
