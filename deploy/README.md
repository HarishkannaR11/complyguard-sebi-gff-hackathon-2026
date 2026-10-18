# Deploying RegOps AI on AWS

Two ready-made stacks. Both run the same containers; pick by how much you want to operate.

| | **EC2** (`deploy/ec2`) | **ECS Fargate** (`deploy/ecs`) |
|---|---|---|
| Good for | demo, hackathon, staging | a real environment |
| Shape | one `t3.large`: Caddy + API + Postgres + Qdrant in Docker Compose | CloudFront → ALB → Fargate task; RDS Postgres; Qdrant on a small EC2; S3 for the frontend |
| HTTPS | automatic Let's Encrypt on your domain (or plain HTTP on the IP) | free `*.cloudfront.net` certificate, no domain needed |
| Data safety | EBS volume + daily snapshots | RDS automated backups, encrypted storage |
| Ops | `ssh`-less shell via SSM, `redeploy.sh` | CloudWatch logs, ECS Exec, circuit-breaker rollback |
| Rough cost* | ~$65/month | ~$170-250/month |

\*Ballpark for `ap-south-1`, always-on; check the AWS pricing calculator.

Files: `Dockerfile` (API image), `frontend/Dockerfile` (web image), `deploy/ec2/*`, `deploy/ecs/*`.

## Two rules that apply to both

1. **Run exactly one API instance.** The audit hash chain's lock is per process and upload jobs run
   in-process; a second API process can fork the chain. The ECS stack enforces `api_desired_count ∈ {0,1}`
   and deploys stop-then-start (about 1-2 min of downtime per deploy); the EC2 stack has one container.
2. **`VITE_API_KEY` is public.** It is compiled into the JavaScript bundle, so anyone who opens the site can
   read it. It stops casual API use, not a determined user. For real multi-user access put an identity
   provider (e.g. Cognito) in front and validate its tokens in `app/api/security.py`.

## Option A: EC2 (single host)

```bash
cd deploy/ec2/terraform
cp terraform.tfvars.example terraform.tfvars      # set groq_api_key, api_keys, vite_api_key, repo_*
terraform init
terraform apply
```

The instance clones the repo, builds both images and starts the stack; **allow 10-15 minutes**. Follow it with:

```bash
terraform output ssm_session_command        # run it, then:
sudo tail -f /var/log/regops-bootstrap.log
```

Then open `terraform output app_url`. With `domain_name` set, point its A record at `public_ip` (or give
`route53_zone_id`) and Caddy obtains the certificate on first request.

* **The branch must contain `deploy/ec2/`.** `repo_branch` defaults to `main`; merge this work first or set
  `repo_branch` to the branch that has it. Private repo: set `github_token`.
* **Update the app:** shell in via SSM and run `sudo /opt/regops/redeploy.sh` (pulls code, re-reads secrets from
  SSM Parameter Store, rebuilds, restarts, waits for health).
* **Where data lives:** a separate encrypted EBS volume mounted at `/data` holds all of Docker (images,
  Postgres, Qdrant, uploads). It survives instance replacement and is snapshotted daily (`snapshot_retention_days`).
* **Manual run without Terraform:** `cd deploy/ec2 && cp env.example .env && docker compose -f docker-compose.prod.yml up -d --build`.
* Secrets are in SSM Parameter Store, not in user-data. They are in Terraform state; protect it.

## Option B: ECS Fargate

```bash
cd deploy/ecs
cp terraform/terraform.tfvars.example terraform/terraform.tfvars   # set groq_api_key, api_keys
export VITE_API_KEY=<one of your api_keys>
./deploy.sh
```

`deploy.sh` creates the ECR repository, builds and pushes the API image (`linux/amd64`, tagged with the git
SHA), applies the full stack, builds and uploads the frontend, invalidates CloudFront, and waits for the ECS
service to stabilise. The first run takes ~20 minutes (RDS + CloudFront creation dominate). Re-run it for every
release; `SKIP_IMAGE=1` / `SKIP_FRONTEND=1` skip those parts.

How a request flows: browser → CloudFront (`/` → S3; `/api/*` → ALB, with `/api` stripped) → ALB → Fargate.
The ALB only accepts CloudFront (managed prefix list + a secret `X-Origin-Verify` header).

* **CloudFront → ALB is plain HTTP by default** (the ALB has no certificate of its own). To encrypt that hop set
  `alb_certificate_arn` + `origin_domain_name` (a DNS name you CNAME to the `alb_dns_name` output).
* **Qdrant:** a small private EC2 by default (unauthenticated, reachable only from the API's security group). To
  use Qdrant Cloud instead set `qdrant_url` and `qdrant_api_key`. Vectors are derived data: if they are lost,
  `POST /api/admin/reconcile-vectors` rebuilds them from Postgres.
* **Logs:** `terraform output logs_command`. **Shell in the container:** `terraform output shell_command`.
* **Rollback:** a failed deploy rolls back automatically (deployment circuit breaker). To go back deliberately,
  set `image_tag` to an older SHA in `image.auto.tfvars` and `terraform apply`.
* **Tear down:** set `db_deletion_protection = false` and apply, then `terraform destroy`. A final RDS snapshot is
  taken. Secrets stay recoverable for `secret_recovery_window_days`.
* **Not included (add as needed):** a custom domain on CloudFront (needs an ACM certificate in `us-east-1`), WAF,
  CloudWatch alarms, and an S3/DynamoDB Terraform backend (see the comment in `versions.tf`).

## Verifying a deployment

```bash
curl -s $APP_URL/api/livez                       # {"status":"ok"}   (public, shallow)
curl -s $APP_URL/api/health                      # database + qdrant (public, deep)
curl -s -H "X-API-Key: <key>" $APP_URL/api/audit_log/verify
```

`/api/livez` is what load balancers use. `/api/health` returns 503 when Postgres or Qdrant is unreachable and
`degraded` if Qdrant has fallen back to its local file store.

## What was and was not tested

**Verified (in a sandbox):**

* Both Terraform stacks pass `terraform fmt` and `validate` against AWS provider 6.x with no dependency cycles.
  The user-data scripts render and parse (`bash -n`).
* The Dockerfiles lint clean and the API image builds. A test image (torch from PyPI, no embedding model) was
  then run under the **real `docker-compose.prod.yml`** (Postgres 16, Qdrant v1.19.2, API, Caddy) and checked
  through Caddy on port 80: the frontend and SPA fallback are served; `/api/*` reaches the API with the prefix
  stripped; auth returns 401/401/200 for no/wrong/right key; `/api/livez` and `/api/health` report healthy; the
  API runs as a non-root user; Alembic reaches revision 0002 and the LangGraph checkpoint tables are created at
  startup; an upload runs as a background job that completes and can be polled; a non-PDF upload is rejected;
  data and jobs survive `docker compose down` + `up`, and the second start applies no migrations.
* The real build and run also found and fixed a Dockerfile bug (`chown` of a directory that did not exist).

**Not verified:** `terraform plan/apply` against a real AWS account; the CPU-only torch wheel index
(`download.pytorch.org` was blocked in the sandbox, so the sandbox build used PyPI's torch); baking the embedding
model into the image (HuggingFace was blocked, so the test containers could not embed clauses and each clause
failed with the expected offline-mode error); Let's Encrypt issuance; and a live Groq call. Run a first deploy in
a throwaway account before relying on these files, and expect small fixes.
