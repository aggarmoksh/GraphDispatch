"""Read-only: do AWS credentials resolve, from where, and which region. Never prints keys."""
import os

import boto3
from dotenv import load_dotenv

load_dotenv()
s = boto3.Session()
c = s.get_credentials()
if c is None:
    print("credentials: NOT FOUND")
    raise SystemExit(1)
print("source method:", c.method)  # e.g. env, shared-credentials-file, sso, assume-role
print("profile:", s.profile_name, "| AWS_PROFILE env set:", bool(os.getenv("AWS_PROFILE")),
      "| AWS_ACCESS_KEY_ID env set:", bool(os.getenv("AWS_ACCESS_KEY_ID")))
print("region (env AWS_REGION):", os.getenv("AWS_REGION"), "| session region:", s.region_name)
ident = s.client("sts", region_name=os.getenv("AWS_REGION") or s.region_name or "us-east-1").get_caller_identity()
print("account: ********" + ident["Account"][-4:])
print("principal type:", ident["Arn"].split(":")[5].split("/")[0])
