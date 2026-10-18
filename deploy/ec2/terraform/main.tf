provider "aws" {
  region = var.region

  default_tags {
    tags = local.tags
  }
}

locals {
  tags = merge({ Project = "regops-ai", Stack = "ec2", ManagedBy = "terraform" }, var.tags)

  ssm_prefix = "/${var.name}"

  # Optional secrets are only stored when set (SSM rejects empty values). nonsensitive() exposes
  # just "is it empty", never the value.
  has_vite_api_key = nonsensitive(var.vite_api_key != "")
  has_github_token = nonsensitive(var.github_token != "")

  site_address = var.domain_name != "" ? var.domain_name : ":80"
}

# ── Network ──────────────────────────────────────────────────────────────────────────────────
# Default: the first subnet of the account's default VPC. If the account has none (and an
# organisation policy may forbid creating one), set var.subnet_id to an existing PUBLIC subnet --
# one whose route table sends 0.0.0.0/0 to an internet gateway. The VPC is taken from the subnet.

data "aws_vpc" "default" {
  count   = var.subnet_id == "" ? 1 : 0
  default = true
}

data "aws_subnets" "default" {
  count = var.subnet_id == "" ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default[0].id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

locals {
  subnet_id = var.subnet_id != "" ? var.subnet_id : sort(data.aws_subnets.default[0].ids)[0]
}

data "aws_subnet" "selected" {
  id = local.subnet_id
}

locals {
  vpc_id = data.aws_subnet.selected.vpc_id
}

# Latest Amazon Linux 2023 (ships the SSM agent and AWS CLI v2).
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "aws_security_group" "app" {
  name_prefix = "${var.name}-app-"
  description = "RegOps web (80/443); everything else closed"
  vpc_id      = local.vpc_id

  ingress {
    description = "HTTP (redirects to HTTPS when a domain is set)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  ingress {
    description = "HTTP/3"
    from_port   = 443
    to_port     = 443
    protocol    = "udp"
    cidr_blocks = var.allowed_cidrs
  }

  dynamic "ingress" {
    for_each = var.ssh_cidr != "" ? [var.ssh_cidr] : []
    content {
      description = "SSH"
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }

  egress {
    description = "All outbound (Groq API, package and image downloads)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

# ── Secrets: SSM Parameter Store (SecureString). The instance reads them at boot, so they never
#    appear in user_data / the EC2 console. They do live in Terraform state. ───────────────────

resource "random_password" "postgres" {
  length  = 32
  special = false
}

resource "aws_ssm_parameter" "postgres_password" {
  name  = "${local.ssm_prefix}/POSTGRES_PASSWORD"
  type  = "SecureString"
  value = random_password.postgres.result
}

resource "aws_ssm_parameter" "groq_api_key" {
  name  = "${local.ssm_prefix}/GROQ_API_KEY"
  type  = "SecureString"
  value = var.groq_api_key
}

resource "aws_ssm_parameter" "api_keys" {
  name  = "${local.ssm_prefix}/API_KEYS"
  type  = "SecureString"
  value = var.api_keys
}

resource "aws_ssm_parameter" "vite_api_key" {
  count = local.has_vite_api_key ? 1 : 0
  name  = "${local.ssm_prefix}/VITE_API_KEY"
  type  = "SecureString"
  value = var.vite_api_key
}

resource "aws_ssm_parameter" "github_token" {
  count = local.has_github_token ? 1 : 0
  name  = "${local.ssm_prefix}/GITHUB_TOKEN"
  type  = "SecureString"
  value = var.github_token
}

# ── Instance role: Session Manager (no SSH needed) + read its own parameters ────────────────

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "app" {
  name_prefix        = "${var.name}-ec2-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.app.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "read_params" {
  statement {
    actions   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
    resources = ["arn:aws:ssm:${var.region}:${data.aws_caller_identity.current.account_id}:parameter${local.ssm_prefix}/*"]
  }
}

resource "aws_iam_role_policy" "read_params" {
  name   = "read-${var.name}-parameters"
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.read_params.json
}

resource "aws_iam_instance_profile" "app" {
  name_prefix = "${var.name}-ec2-"
  role        = aws_iam_role.app.name
}

# ── Persistent data volume (Docker root: images, Postgres, Qdrant, uploads) ─────────────────

resource "aws_ebs_volume" "data" {
  availability_zone = data.aws_subnet.selected.availability_zone
  size              = var.data_volume_gb
  type              = "gp3"
  encrypted         = true

  tags = {
    Name   = "${var.name}-data"
    Backup = var.name
  }
}

resource "aws_eip" "app" {
  domain = "vpc"

  tags = {
    Name = "${var.name}-app"
  }
}

resource "aws_instance" "app" {
  ami                         = nonsensitive(data.aws_ssm_parameter.al2023.value)
  instance_type               = var.instance_type
  subnet_id                   = local.subnet_id
  vpc_security_group_ids      = [aws_security_group.app.id]
  iam_instance_profile        = aws_iam_instance_profile.app.name
  key_name                    = var.key_name != "" ? var.key_name : null
  associate_public_ip_address = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required" # IMDSv2 only
    http_put_response_hop_limit = 1          # containers cannot reach instance credentials
  }

  root_block_device {
    volume_size = var.root_volume_gb
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    region           = var.region
    ssm_prefix       = local.ssm_prefix
    volume_id_nodash = replace(aws_ebs_volume.data.id, "-", "")
    repo_url         = var.repo_url
    repo_branch      = var.repo_branch
    site_address     = local.site_address
  })

  # Secrets must exist before the instance boots and tries to read them.
  depends_on = [
    aws_ssm_parameter.postgres_password,
    aws_ssm_parameter.groq_api_key,
    aws_ssm_parameter.api_keys,
    aws_ssm_parameter.vite_api_key,
    aws_ssm_parameter.github_token,
    aws_iam_role_policy.read_params,
  ]

  tags = {
    Name = "${var.name}-app"
  }

  lifecycle {
    # A newer AMI or a bootstrap-script tweak must not replace a host that holds the app.
    # Change the stack by SSM-ing in and running /opt/regops/redeploy.sh, or taint on purpose.
    ignore_changes = [ami, user_data]
  }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.app.id
}

resource "aws_eip_association" "app" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.app.id
}

# ── Optional DNS ────────────────────────────────────────────────────────────────────────────

resource "aws_route53_record" "app" {
  count   = var.domain_name != "" && var.route53_zone_id != "" ? 1 : 0
  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"
  ttl     = 300
  records = [aws_eip.app.public_ip]
}

# ── Daily snapshots of the data volume ──────────────────────────────────────────────────────

data "aws_iam_policy_document" "dlm_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["dlm.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "dlm" {
  name_prefix        = "${var.name}-dlm-"
  assume_role_policy = data.aws_iam_policy_document.dlm_assume.json
}

resource "aws_iam_role_policy_attachment" "dlm" {
  role       = aws_iam_role.dlm.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSDataLifecycleManagerServiceRole"
}

resource "aws_dlm_lifecycle_policy" "data" {
  description        = "${var.name}: daily snapshots of the data volume"
  execution_role_arn = aws_iam_role.dlm.arn
  state              = "ENABLED"

  policy_details {
    resource_types = ["VOLUME"]
    target_tags = {
      Backup = var.name
    }

    schedule {
      name = "daily"

      create_rule {
        interval      = 24
        interval_unit = "HOURS"
        times         = ["21:30"] # 03:00 IST
      }

      retain_rule {
        count = var.snapshot_retention_days
      }

      copy_tags = true
    }
  }
}
