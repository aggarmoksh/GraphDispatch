# Deploy runbook (plain HTTP, one EC2 t3.micro)

Every step below is **operator-only**: it needs your AWS account or your SSH key. Nothing in this repository performs any of them. The advisor reviews this file before anyone uses it. Placeholders are in `<ANGLE_BRACKETS>`.

What runs: one host, two containers (the app and FalkorDB) from `docker-compose.yml`. The app has no access keys; it reaches Amazon Bedrock through the EC2 instance role. FalkorDB publishes no ports.

## 0. Before you start (operator-only)
- [ ] You have the AWS account id `<ACCOUNT_ID>` and the AWS credits applied to that account.
- [ ] You decided the demo window (dates) so you can stop the host afterwards.
- [ ] Bedrock model access for Claude Haiku 4.5 is already enabled in `us-east-1` (it worked from your laptop with the same account).

## 1. Budget alert first (operator-only, AWS console)
- [ ] Billing, Budgets, create a cost budget of `<USD_LIMIT>` per month with email alerts at 50 percent and 80 percent of the budget to `<YOUR_EMAIL>`.
- [ ] Optional: a second budget on the Amazon Bedrock service only.

## 2. IAM role from the policy file (operator-only, AWS console)
- [ ] IAM, Policies, create policy, JSON tab, paste `deploy/iam-bedrock-policy.json`, replace `<ACCOUNT_ID>` with your account id. It allows only `bedrock:InvokeModel` on the Haiku 4.5 US inference profile and the three Haiku 4.5 foundation-model ARNs that profile routes to (us-east-1, us-east-2, us-west-2). Name it `graphdispatch-bedrock-invoke`.
- [ ] IAM, Roles, create role, trusted entity EC2, attach only that policy, name it `graphdispatch-ec2-role`. An instance profile with the same name is created for you.
- [ ] Do not create access keys for any user for this deployment, and do not put keys in `.env.server`.

## 3. Launch the instance (operator-only, AWS console)
- [ ] EC2, Launch instance, name `graphdispatch-demo`.
- [ ] AMI: Amazon Linux 2023 or Ubuntu 24.04 LTS, **x86_64** (not Arm). Instance type `t3.micro`.
- [ ] Key pair: create or choose `<KEY_NAME>`; keep the `.pem` file private on your machine (`KEY_FILE`).
- [ ] Storage: 20 GB gp3.
- [ ] IAM instance profile: `graphdispatch-ec2-role`.
- [ ] Advanced details: metadata version "V2 only" (IMDSv2 required) and hop limit 2 (containers read the role through the host metadata service).
- [ ] Security group `graphdispatch-sg`: inbound **22 from `<YOUR_IP>/32` only** and **80 from anywhere (0.0.0.0/0)**. No other inbound rules. Do not open 6379 or 3000.
- [ ] Optionally attach an Elastic IP so the address does not change.

## 4. Prepare the host (operator-only, over SSH)
SSH in: `ssh -i <KEY_FILE> <ec2-user|ubuntu>@<PUBLIC_IP>`.
- [ ] Add 2 GB of swap (the host has 1 GB RAM; the two containers are limited to 750 MB in total):
  `sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab`
- [ ] Install Docker and the compose plugin.
  - Amazon Linux 2023: `sudo dnf install -y docker git && sudo systemctl enable --now docker`, then install the compose plugin from the Docker documentation for your distribution.
  - Ubuntu 24.04: follow Docker's official apt repository instructions and install `docker-ce docker-compose-plugin`.
- [ ] `sudo usermod -aG docker $USER`, log out and back in, then check `docker compose version`.
- [ ] Create the env file on the host (never on your laptop, never in git):
  `mkdir -p ~/graphdispatch && nano ~/graphdispatch/.env.server`
  Paste the contents of `.env.server.example` from the repository. Check: `GRAPH_NAME=sjfd`, `FALKORDB_HOST=falkordb`, `TRUST_PROXY=0` (plain HTTP straight to the instance, so nobody can choose their own rate-limit key), `LLM_DAILY_CAP=150` (or lower), and **no** `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` lines.
  `chmod 600 ~/graphdispatch/.env.server`

## 5. Ship (operator-only, from your laptop)
- [ ] Commit everything you want live (`git status` clean): only committed files are shipped.
- [ ] Dry run first and read every line: `HOST=<ec2-user|ubuntu>@<PUBLIC_IP> KEY_FILE=<KEY_FILE> deploy/ship.sh`
- [ ] Ship: `HOST=... KEY_FILE=... deploy/ship.sh --yes`. It archives HEAD, copies it, extracts to `~/graphdispatch/releases/<short-hash>`, points `~/graphdispatch/current` at it, copies the host's `.env.server` in, runs `docker compose up -d --build`, then calls `/api/health` on the host.
- [ ] The first build on a t3.micro can take several minutes. If the build runs out of memory, check that swap is on (`swapon --show`).

## 6. Verify (operator-only)
- [ ] `curl http://<PUBLIC_IP>/api/health` returns `{"ok": true, ...}`.
- [ ] Open `http://<PUBLIC_IP>/`, use the Graph only mode, run "Stroke, west side": Regional is chosen and O'Connor is shown as skipped.
- [ ] Try one AI call. If it fails with an access error, check the instance role (step 2/3) and that IMDSv2 hop limit is 2. Check the cap counter: `docker compose exec app cat /app/runs/llm_daily.json`.
- [ ] `docker stats --no-stream` shows both containers under their limits; `free -m` shows swap barely used.

## 7. Operate (operator-only)
- Logs: `cd ~/graphdispatch/current && docker compose logs -f app`.
- Restart: `docker compose restart`. The graph is kept (named volume) and the seed loader is idempotent.
- Demo state heals itself: incidents older than `DEMO_EXPIRE_MIN` (30) are expired and their units freed every 5 minutes. Hazards and decisions stay.
- Lower the AI cap quickly: edit `~/graphdispatch/.env.server` (`LLM_DAILY_CAP`), then `docker compose up -d`.
- Roll back: `ln -sfn ~/graphdispatch/releases/<older-hash> ~/graphdispatch/current && cd ~/graphdispatch/current && docker compose up -d --build`.

## 8. Tear down after the demo (operator-only)
- [ ] Stop or terminate the instance, release the Elastic IP, delete the security group if unused.
- [ ] Detach and delete the role and policy if you will not reuse them. Delete the key pair if it was created only for this.
- [ ] Check the bill for Bedrock and EC2 the next day.

## Known limits (plain HTTP first)
- Traffic is not encrypted. Do not type anything real: the data is synthetic by design. HTTPS (CloudFront or a load balancer with a certificate) is a later step; when you add it, set `TRUST_PROXY=1` so the per-IP limit uses the viewer address the proxy sets.
- The per-IP limiter lives in memory in one worker, so it resets when the app restarts. The daily cap file survives restarts and is the real cost guard.
