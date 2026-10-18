variable "region" {
  description = "AWS region. ap-south-1 (Mumbai) keeps data in India."
  type        = string
  default     = "ap-south-1"
}

variable "name" {
  description = "Name prefix for every resource."
  type        = string
  default     = "regops"
}

# ── Network ─────────────────────────────────────────────────────────────────────────────────

variable "vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "az_count" {
  description = "Availability zones to spread subnets over (the ALB and RDS subnet group need at least 2)."
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 3
    error_message = "az_count must be 2 or 3."
  }
}

variable "single_nat_gateway" {
  description = "One shared NAT gateway (cheaper) vs one per AZ (survives an AZ outage). The tasks need NAT to reach the Groq API."
  type        = bool
  default     = true
}

# ── API service ─────────────────────────────────────────────────────────────────────────────

variable "image_tag" {
  description = "Tag of the API image in ECR to run. deploy.sh sets this (git SHA) via image.auto.tfvars."
  type        = string
  default     = "latest"
}

variable "api_cpu" {
  description = "Fargate vCPU units (1024 = 1 vCPU). 2048 is comfortable for the embedding model."
  type        = number
  default     = 2048
}

variable "api_memory" {
  description = "Fargate memory in MiB. torch + the bge-base model need ~3 GiB; 6144 leaves headroom. Must be a valid Fargate pairing for api_cpu."
  type        = number
  default     = 6144
}

variable "api_desired_count" {
  description = "Number of API tasks: 1 (run) or 0 (stopped). More than one is unsafe: the audit hash chain's lock is per process and upload jobs run in-process."
  type        = number
  default     = 1

  validation {
    condition     = contains([0, 1], var.api_desired_count)
    error_message = "api_desired_count must be 0 or 1. Running several API tasks can fork the audit hash chain."
  }
}

variable "groq_api_key" {
  description = "Groq API key used by the extraction / diff nodes."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.groq_api_key) > 0
    error_message = "groq_api_key must not be empty."
  }
}

variable "groq_model" {
  type    = string
  default = "llama-3.3-70b-versatile"
}

variable "api_keys" {
  description = "Comma-separated key:user pairs enabling X-API-Key auth, e.g. \"k3y-abc:alice,k3y-def:bob\". Required: empty would leave the API open."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.api_keys) > 0
    error_message = "api_keys must not be empty; with it empty the API runs without authentication."
  }
}

variable "max_upload_mb" {
  type    = number
  default = 25
}

variable "log_retention_days" {
  type    = number
  default = 30
}

# ── Postgres (RDS) ──────────────────────────────────────────────────────────────────────────

variable "db_instance_class" {
  type    = string
  default = "db.t4g.small"
}

variable "db_allocated_storage_gb" {
  type    = number
  default = 20
}

variable "db_multi_az" {
  type    = bool
  default = false
}

variable "db_backup_retention_days" {
  type    = number
  default = 7
}

variable "db_deletion_protection" {
  description = "Blocks terraform destroy / accidental deletion of the database. Set false only to tear the stack down."
  type        = bool
  default     = true
}

# ── Qdrant ──────────────────────────────────────────────────────────────────────────────────

variable "qdrant_url" {
  description = "URL of an existing Qdrant (e.g. Qdrant Cloud). Empty = run Qdrant on a small EC2 instance in the private subnet."
  type        = string
  default     = ""
}

variable "qdrant_api_key" {
  description = "API key for an external Qdrant (qdrant_url). Leave empty for the built-in instance, which is unauthenticated and protected by its security group only."
  type        = string
  default     = ""
  sensitive   = true
}

variable "qdrant_instance_type" {
  type    = string
  default = "t3.small"
}

variable "qdrant_volume_gb" {
  type    = number
  default = 20
}

# ── Edge: CloudFront (frontend + /api) in front of an ALB ───────────────────────────────────

variable "alb_certificate_arn" {
  description = "ACM certificate (in var.region) for the ALB. Together with origin_domain_name this makes the CloudFront -> ALB hop HTTPS. Empty = HTTP between CloudFront and the ALB (locked to CloudFront by prefix list + secret header)."
  type        = string
  default     = ""
}

variable "origin_domain_name" {
  description = "DNS name covered by alb_certificate_arn that you point (CNAME) at the ALB, e.g. origin.example.com. Required when alb_certificate_arn is set."
  type        = string
  default     = ""
}

variable "cloudfront_price_class" {
  description = "PriceClass_200 includes Indian edge locations; PriceClass_100 does not."
  type        = string
  default     = "PriceClass_200"
}

variable "secret_recovery_window_days" {
  description = "Days a deleted Secrets Manager secret stays recoverable (0 = delete immediately, handy for throwaway stacks)."
  type        = number
  default     = 7
}

variable "tags" {
  type    = map(string)
  default = {}
}
