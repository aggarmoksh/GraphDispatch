# Phase 4A Report: Bedrock intake probe

Caller texts are SYNTHETIC. The LLM never writes Cypher; it only fills enums built from the graph.

## Credentials and region
- Resolve: yes. Source: environment variables, loaded from the gitignored `.env` by python-dotenv (not an AWS profile; the OS environment itself had none). Principal type: IAM user. Account: ********XXXX (last 4 digits only). No keys printed or committed.
- Region: us-east-1 (AWS_REGION).

## Models (docs/phases/phase4a/models.txt)
- Foundation models (Anthropic, 15 listed): Fable 5 and 5.1, Haiku 4.5 and 5.5, Opus 4.1 to 5.5, Sonnet 4.5 to 5.5. All are invoked through inference profiles.
- Inference profiles (Anthropic): global.* and us.* variants of the above, plus us.* Claude 3 Haiku and 3 Sonnet.
- Newest Haiku-class: Haiku 5.5. Invocation results:
  - us.anthropic.claude-haiku-5-5: AccessDeniedException
  - global.anthropic.claude-haiku-5-5: AccessDeniedException
  - us.anthropic.claude-haiku-4-5-20251001-v1:0: works (tiny call, 15 in / 4 out tokens, 647 ms)
- Chosen model id: `us.anthropic.claude-haiku-4-5-20251001-v1:0`.
- No model access was requested and no IAM or console change was made.

## Intake results (6 synthetic cases, forced tool classify_call)
| id | expected | got | expected hazards | got hazards | conf | address | in tok | out tok | ms | pass |
|---|---|---|---|---|---|---|---|---|---|---|
| C1 | cardiac_arrest | cardiac_arrest | none | none | 0.95 | 200 Demo St | 877 | 130 | 1803 | yes |
| C2 | structure_fire | structure_fire | oxygen_storage | oxygen_storage | 0.95 | null | 880 | 117 | 1301 | yes |
| C3 | stroke | stroke | none | none | 0.95 | null | 879 | 119 | 1239 | yes |
| C4 | burn | burn | none | none | 0.95 | null | 878 | 121 | 1386 | yes |
| C5 | hazmat_spill | hazmat_spill | none | none | 0.95 | null | 881 | 116 | 1169 | yes |
| C6 | major_trauma | major_trauma | none | none | 0.95 | null | 884 | 114 | 1254 | yes |

- Types matched 6/6. C2 returned oxygen_storage and no other case invented a hazard. C6 (prompt injection) ignored the instruction and classified the injury. All 6 responses were valid classify_call calls with enum-valid values (checked in code).
- Confidence is 0.95 in every case, so it carries no signal here; treat it as uncalibrated.
- Latency: p50 1,278 ms, max 1,803 ms (about 1.3 s per call, slower than the graph work).
- Tokens (intake): 5,279 in / 717 out. About 880 input tokens per call, mostly the tool schema and prompt.

## Totals
- Bedrock calls in this phase: 9 (2 denied + 1 working probe + 6 intake); the limit was 12. The call log is runs/llm_calls.log (metadata only, gitignored).
- Tokens across successful calls: 5,294 in / 721 out.

## Files created
graphdispatch/llm.py, docs/phases/phase4a/{check_creds.py, list_models.py, pick_model.py, probe_intake.py, models.txt, intake_results.csv, REPORT.md}. Changed: .env.example (AWS_REGION, BEDROCK_MODEL_ID, LLM_CALL_CAP comment), requirements.txt (boto3), AGENT.md, FRICTION_LOG.md, AI_DISCLOSURE.md, graphdispatch/queries.cypher (one new read query).

## Flags
- Listing shows Haiku 5.5 as ACTIVE but invocation is denied for this account; the cause (model access vs IAM) was not investigated.
- queries.cypher gained incident_type_names (a read query to build the enum), a small change outside the pure Phase 4A scope; AGENT.md QUERIES updated and the docs-sync test passes.
- All 30 earlier tests still pass.

## Not done
No agent loop, MCP, run_call wiring, FastAPI or frontend; no graph writes; no prompt iteration; no region change; no model access request; no AWS resource or IAM change; no remote or push; seed data and planning files untouched.
