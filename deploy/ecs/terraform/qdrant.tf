# Qdrant on a small EC2 instance in a private subnet, unless var.qdrant_url points at an existing one
# (e.g. Qdrant Cloud). Its vectors are derived data: if the volume is ever lost, POST
# /admin/reconcile-vectors rebuilds them from the clause text in Postgres.
locals {
  create_qdrant = var.qdrant_url == ""
  qdrant_ip     = cidrhost(aws_subnet.private[0].cidr_block, 10)
  qdrant_url    = local.create_qdrant ? "http://${local.qdrant_ip}:6333" : var.qdrant_url
}

data "aws_ssm_parameter" "al2023" {
  count = local.create_qdrant ? 1 : 0
  name  = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "qdrant" {
  count              = local.create_qdrant ? 1 : 0
  name_prefix        = "${var.name}-qdrant-"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "qdrant_ssm" {
  count      = local.create_qdrant ? 1 : 0
  role       = aws_iam_role.qdrant[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "qdrant" {
  count       = local.create_qdrant ? 1 : 0
  name_prefix = "${var.name}-qdrant-"
  role        = aws_iam_role.qdrant[0].name
}

resource "aws_ebs_volume" "qdrant" {
  count             = local.create_qdrant ? 1 : 0
  availability_zone = local.azs[0]
  size              = var.qdrant_volume_gb
  type              = "gp3"
  encrypted         = true

  tags = { Name = "${var.name}-qdrant-data" }
}

resource "aws_instance" "qdrant" {
  count                  = local.create_qdrant ? 1 : 0
  ami                    = nonsensitive(data.aws_ssm_parameter.al2023[0].value)
  instance_type          = var.qdrant_instance_type
  subnet_id              = aws_subnet.private[0].id
  private_ip             = local.qdrant_ip
  vpc_security_group_ids = [aws_security_group.qdrant.id]
  iam_instance_profile   = aws_iam_instance_profile.qdrant[0].name

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_size = 12
    volume_type = "gp3"
    encrypted   = true
  }

  user_data = templatefile("${path.module}/qdrant_user_data.sh.tftpl", {
    volume_id_nodash = replace(aws_ebs_volume.qdrant[0].id, "-", "")
  })

  tags = { Name = "${var.name}-qdrant" }

  # NAT must be up first: the instance pulls the Qdrant image from Docker Hub at boot.
  depends_on = [aws_nat_gateway.main, aws_route_table_association.private]

  lifecycle {
    ignore_changes = [ami, user_data]
  }
}

resource "aws_volume_attachment" "qdrant" {
  count       = local.create_qdrant ? 1 : 0
  device_name = "/dev/sdf"
  volume_id   = aws_ebs_volume.qdrant[0].id
  instance_id = aws_instance.qdrant[0].id
}
