variable "region" {
  description = "AWS region. ap-south-1 (Mumbai) keeps data in India."
  type        = string
  default     = "ap-south-1"
}

variable "name" {
  description = "Name prefix for every resource (and the SSM parameter path /<name>/...)."
  type        = string
  default     = "regops"
}

variable "instance_type" {
  description = "t3.large (2 vCPU / 8 GB) runs the API + embedding model, Postgres and Qdrant. Go to t3.xlarge for heavier use."
  type        = string
  default     = "t3.large"
}

variable "root_volume_gb" {
  description = "OS disk. Docker images and data live on the separate data volume."
  type        = number
  default     = 30
}

variable "data_volume_gb" {
  description = "Persistent EBS volume holding Docker (images, Postgres, Qdrant, uploads). Survives instance replacement."
  type        = number
  default     = 60
}

variable "subnet_id" {
  description = "Existing PUBLIC subnet to launch into (its route table must send 0.0.0.0/0 to an internet gateway). Empty = the first subnet of the account's default VPC, which must exist."
  type        = string
  default     = ""
}

variable "allowed_cidrs" {
  description = "Who may reach ports 80/443. Narrow this (e.g. your office IP) for anything but a public demo."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "ssh_cidr" {
  description = "CIDR allowed to SSH (port 22). Empty = SSH closed; use SSM Session Manager instead (recommended)."
  type        = string
  default     = ""
}

variable "key_name" {
  description = "Existing EC2 key pair, only needed if ssh_cidr is set."
  type        = string
  default     = ""
}

variable "domain_name" {
  description = "Public hostname (e.g. regops.example.com). Empty = plain HTTP on the Elastic IP. Point its A record at the output public_ip, or set route53_zone_id."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Optional Route 53 hosted zone ID; with domain_name set, creates the A record for you."
  type        = string
  default     = ""
}

variable "repo_url" {
  description = "Git repository the instance clones and builds."
  type        = string
  default     = "https://github.com/harishkannar11/complyguard-sebi-gff-hackathon-2026.git"
}

variable "repo_branch" {
  description = "Branch to deploy."
  type        = string
  default     = "main"
}

variable "github_token" {
  description = "Read-only token, only needed if the repository is private."
  type        = string
  default     = ""
  sensitive   = true
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

variable "api_keys" {
  description = "Comma-separated key:user pairs enabling X-API-Key auth, e.g. \"k3y-abc:alice,k3y-def:bob\". Required: an empty value would leave the API open to the internet."
  type        = string
  sensitive   = true

  validation {
    condition     = length(var.api_keys) > 0
    error_message = "api_keys must not be empty; with it empty the API runs without authentication."
  }
}

variable "vite_api_key" {
  description = "Key the web UI sends. It is compiled into the public JavaScript bundle, so use one of the api_keys meant for the UI."
  type        = string
  default     = ""
  sensitive   = true
}

variable "snapshot_retention_days" {
  description = "Daily EBS snapshots of the data volume (Postgres + Qdrant) are kept this many days."
  type        = number
  default     = 7
}

variable "tags" {
  description = "Extra tags for every resource."
  type        = map(string)
  default     = {}
}
