#!/usr/bin/env bash
# Build + push the API image, apply Terraform, publish the frontend, and roll the ECS service.
#
# Prerequisites: terraform >= 1.5, AWS CLI v2 with credentials, docker, node 20+/npm.
#
#   cp terraform/terraform.tfvars.example terraform/terraform.tfvars   # then edit
#   export VITE_API_KEY=<one of your api_keys>   # compiled into the PUBLIC JS bundle
#   ./deploy.sh
#
# Environment:
#   IMAGE_TAG      image tag (default: git short SHA, "-dirty-<ts>" if the tree has changes)
#   AUTO_APPROVE=1 pass -auto-approve to terraform (default: terraform asks first)
#   SKIP_IMAGE=1   skip the docker build/push (infra or frontend-only change)
#   SKIP_FRONTEND=1 skip the frontend build/upload
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
TF_DIR="$HERE/terraform"
TF=(terraform "-chdir=$TF_DIR")
APPROVE=()
[ "${AUTO_APPROVE:-}" = "1" ] && APPROVE=(-auto-approve)

for tool in terraform aws; do
  command -v "$tool" >/dev/null || { echo "missing required tool: $tool" >&2; exit 1; }
done
[ "${SKIP_IMAGE:-}" = "1" ] || command -v docker >/dev/null || { echo "missing required tool: docker" >&2; exit 1; }
[ "${SKIP_FRONTEND:-}" = "1" ] || command -v npm >/dev/null || { echo "missing required tool: npm" >&2; exit 1; }
[ -f "$TF_DIR/terraform.tfvars" ] || [ -n "${TF_VAR_groq_api_key:-}" ] || {
  echo "no $TF_DIR/terraform.tfvars (copy terraform.tfvars.example) and no TF_VAR_groq_api_key" >&2; exit 1; }

TAG="${IMAGE_TAG:-$(git -C "$REPO_ROOT" rev-parse --short HEAD)}"
if [ -z "${IMAGE_TAG:-}" ] && ! git -C "$REPO_ROOT" diff --quiet HEAD --; then
  TAG="$TAG-dirty-$(date +%s)"
fi

echo "==> terraform init"
"${TF[@]}" init -input=false

if [ "${SKIP_IMAGE:-}" != "1" ]; then
  echo "==> creating the ECR repository first (the ECS service needs an image to start)"
  "${TF[@]}" apply -input=false "${APPROVE[@]}" -target=aws_ecr_repository.api

  REPO_URL="$("${TF[@]}" output -raw ecr_repository_url)"
  REGION="$("${TF[@]}" output -raw region 2>/dev/null || echo "${AWS_REGION:-ap-south-1}")"

  echo "==> docker login + build + push $REPO_URL:$TAG (linux/amd64)"
  aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "${REPO_URL%%/*}"
  # The task definition is X86_64; build for it explicitly (matters on Apple Silicon).
  docker build --platform linux/amd64 -t "$REPO_URL:$TAG" "$REPO_ROOT"
  docker push "$REPO_URL:$TAG"

  # Pin the tag Terraform deploys, and keep it pinned for later plain `terraform apply` runs.
  printf 'image_tag = "%s"\n' "$TAG" > "$TF_DIR/image.auto.tfvars"
fi

echo "==> terraform apply"
"${TF[@]}" apply -input=false "${APPROVE[@]}"

BUCKET="$("${TF[@]}" output -raw web_bucket)"
DIST_ID="$("${TF[@]}" output -raw cloudfront_distribution_id)"
CLUSTER="$("${TF[@]}" output -raw ecs_cluster)"
SERVICE="$("${TF[@]}" output -raw ecs_service)"
REGION="$("${TF[@]}" output -raw region)"
APP_URL="$("${TF[@]}" output -raw app_url)"

if [ "${SKIP_FRONTEND:-}" != "1" ]; then
  echo "==> building the frontend (same-origin API at /api)"
  (
    cd "$REPO_ROOT/frontend"
    npm ci
    VITE_API_URL=/api VITE_API_KEY="${VITE_API_KEY:-}" npm run build
  )
  echo "==> uploading to s3://$BUCKET"
  # Hashed assets are immutable; index.html must always be revalidated.
  aws s3 sync "$REPO_ROOT/frontend/dist" "s3://$BUCKET" --delete --exclude index.html \
    --cache-control "public,max-age=31536000,immutable"
  aws s3 cp "$REPO_ROOT/frontend/dist/index.html" "s3://$BUCKET/index.html" \
    --cache-control "no-cache" --content-type "text/html"
  aws cloudfront create-invalidation --distribution-id "$DIST_ID" --paths "/*" >/dev/null
fi

echo "==> waiting for $SERVICE to become stable (stop-then-start deploy, ~2-4 min)"
aws ecs wait services-stable --region "$REGION" --cluster "$CLUSTER" --services "$SERVICE"

echo
echo "Deployed $TAG"
echo "  App:    $APP_URL"
echo "  Health: $APP_URL/api/livez"
echo "  Logs:   $("${TF[@]}" output -raw logs_command)"
