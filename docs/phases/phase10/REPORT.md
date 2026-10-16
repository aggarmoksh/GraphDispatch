# Phase 10 Report: docs and a fast-forward public update

No code behaviour change, no new feature, no push, no remote added anywhere, no AWS change, no Bedrock call (the call log stayed at 50 lines), no force operation, no change to the pre-registered eval files.

## 1. README (17 sections)
What the graph decides; Live demo; Why a graph; **Road closures (demonstration)**; Graph model; Cypher queries; Architecture; **Use the graph tools from Claude Desktop**; Setup; Deployment; Data sources and licenses; Limitations; AI assistance; Friction log; Hackathon tracks entered; Next; License. A "Demo video: [VIDEO LINK]" line sits under the prototype note and "Demo clip: [DEMO CLIP LINK]" ends the Claude Desktop section; both are placeholders for the operator.
- The live demo link is the HTTPS CloudFront address only; the bare-IP link is gone from every tracked file (a test enforces it). The Deployment section now says the browser connection is HTTPS through CloudFront; the "plain HTTP" limitation was removed and replaced by a closures limitation. The graph-model diagram gained Closure, CLOSED_ROAD and REROUTED_AROUND; the architecture diagram gained CloudFront. The first bullet of "What the graph decides" now says routing skips a closed road. "Next" lists only mutual aid.

### Track 01 text, in full (replaces the old line; the Track 02 line is unchanged)
> - **Track 01, Agents That Act on Connected Data:** An LLM intake step turns the caller's words into one forced tool call whose values must come from the graph's own lists. The same graph operations are exposed as six typed MCP tools (five read-only, one that records a hazard); an MCP client such as Claude Desktop chooses among them. Dispatch stays a human action, and no tool accepts Cypher.

### Road closures section, in full
> Closing a road retypes its `ROAD` edges to `CLOSED_ROAD`, and routing follows `ROAD` only, so a closed road is skipped with no new algorithm. A decision that was affected records "rerouted around <road>, +m:ss" and whether the chosen unit or hospital changed; the same legs are also computed ignoring the closure, so the cost is measured, not guessed.
>
> The demo preset "Road closed on the stroke route" closes two synthetic segments on the stroke route and takes the same call. The trip to Regional gets 1:24 longer (9:11 becomes 10:34). Station 7 becomes 158 s from the incident and station 10 is 157 s (1.7 s apart before rounding), so E10 and M10 are sent instead of E7 and M7. That unit change is a difference of about one second of travel time, not a large effect. On the live site at most 3 closures are active, and each reopens by itself after 30 minutes.
>
> Closures were not part of the pre-registered evaluation above: this is a demonstration of the mechanism, not evidence of benefit. The numbers come from [docs/phases/phase9/REPORT.md](docs/phases/phase9/REPORT.md) and [docs/phases/phase10/REPORT.md](docs/phases/phase10/REPORT.md).

The numbers behind it, recomputed from the road snapshot with the independent oracle (`docs/phases/phase10/closure_numbers.py`): with both demo closures station 7 is 158.39 s from the incident and station 10 is 156.66 s (158 s and 157 s rounded, 1.73 s apart; 132.29 s for station 7 without closures); the hospital leg goes from 550.50 s to 634.35 s, a detour of 83.85 s, which the panel shows as +1:24 (the brief said 1:23, which is the difference of two rounded values; the README follows the product). The unit change is a difference of under two seconds and the README says so.

## 2. AI disclosure
`AI_DISCLOSURE.md` has a new section "Who did what", worded exactly as specified:
> The author set the goal and scope, approved every phase before it ran, ran the field checks on the real product, did all AWS setup and deployment, and decided what was published. Claude (chat) acted as an advisor: it drafted the phase briefs, the research and the evaluation design, and independently re-checked results against the data. Claude Code wrote the code, tests and docs from those briefs. Amazon Bedrock (Claude Haiku 4.5) classifies caller text at runtime.
The README AI section mirrors the sentence about the author ("The author set the goal and scope, approved every phase before it ran, ran the field checks on the real product, did all AWS setup and deployment, and decided what was published.") and links the file. A test checks both texts. The original first line of the disclosure file ("Built with Claude Code as the coding assistant; design decisions and verification by the author.") was left as it was; it is shorter than, and slightly in tension with, the new section, so the operator may want to reword it.

## 3. Phase folders moved
13 folders (`phase0` to `phase9` including `0b`, `4a`, `4b`, `5b`, `6a`) moved with `git mv` into `docs/phases/` with their names kept (62 files renamed; `phase10` was created there). Updated: 58 text references in 23 files (AGENT.md, POSTLAUNCH.md, FRICTION_LOG.md and the phase reports and scripts); 9 scripts that found the repo root with `parent.parent` now use `parents[3]` (the offline ones were re-run and regenerated byte-identical files); one path string that the rewrite doubled was fixed; the README links to the Phase 9 and Phase 10 reports resolve. No tests, scripts, Dockerfile or compose file pointed at the old paths.

## 4. QUERIES.md
Nothing in `queries.cypher` changed, so QUERIES.md was not regenerated; its sync test passes.

## 5. Tests
- Private repo: 104 passed, 0 failed (the earlier 102 plus 2 new docs tests: the README track and disclosure wording, and the absence of the old IP). The call log did not move.
- The staged public copy (`graphdispatch-public-next`, 17 commits): 104 passed, 0 failed. The same suite is run again in `graphdispatch-public` after the fast-forward; the result is in the session summary.
- README link check: 16 local links and images, 0 missing; the HTTPS live address answered 200 on the page and `/api/health` ok.

## 6. Scan of the staged public copy (17 commits, counts only)
| rule | hits |
|---|---|
| private values from the local env files (AWS key id and secret) | 0 |
| the 12-digit account id | 0 |
| AWS access key ids, private key headers | 0 |
| email addresses in files, phone numbers | 0 |
| Windows user paths, EC2 instance ids | 0 |
| machine or user name; the drive-folder string in all three forms | 0 |
| the author's name or email inside files | 0 |
| gitleaks over all commits | 0 findings |
| `.env`, `.pem`, `data/`, `runs/` in any commit | none |
| commit messages | only the attribution trailer address (kept by design) |
| author identities | unchanged (kept by the operator's decision; shown in the session summary, not here) |

## 7. Public update (no rewrite, no push)
- Built a fresh filtered copy with the private build tool into `graphdispatch-public-next` (the tool now refuses to run without an explicit new target name, so the existing public folder can never be rebuilt by accident).
- **Hash comparison:** the first 15 commits of `graphdispatch-public-next` have exactly the same hashes as `graphdispatch-public` (15 of 15 identical).
- Then in `graphdispatch-public`: `git fetch` from the staged folder by path (no remote added) and `git merge --ff-only`. The result, the public head and the post-merge test and link results are in the session summary because they depend on this commit's own hash.

## 8. Flags
- **Public history keeps the old bare-IP link** in earlier commits (README and a report); a fast-forward cannot remove it, and rewriting public history would change its hashes. Operator's decision.
- Placeholders still present for the operator: `[VIDEO LINK]`, `[DEMO CLIP LINK]` and, in the Claude Desktop snippet, `<path-to>`; the copyright holder was filled earlier.
- The README says 1:24, not the brief's 1:23, and "158 s versus 157 s, 1.7 s apart", not "exactly one second" (see section 1).
- The `graphdispatch-public-next` staging folder is left in place; it can be deleted after the merge.
- Open items outside this phase: the live site does not yet have the Phase 9 closure code unless the operator shipped it; a CloudFront origin setting `TRUST_PROXY=1` is a deployment matter I did not touch.

## 9. Not done
No push, no new remote, no force or history rewrite, no AWS change, no Bedrock call, no behaviour change or new feature. Author identities were not rewritten. Planning files untouched.
