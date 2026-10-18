resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/${var.name}-api"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_cluster" "main" {
  name = var.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

data "aws_iam_policy_document" "ecs_tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

# Execution role: what ECS itself needs to start the task (pull the image, write logs, read the secret).
resource "aws_iam_role" "execution" {
  name_prefix        = "${var.name}-exec-"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

data "aws_iam_policy_document" "read_secret" {
  statement {
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.app.arn]
  }
}

resource "aws_iam_role_policy" "execution_secret" {
  name   = "read-app-secret"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.read_secret.json
}

# Task role: what the running app may do in AWS. The app calls no AWS APIs; the only grant is
# the SSM channel that `aws ecs execute-command` (a shell in the container) needs.
resource "aws_iam_role" "task" {
  name_prefix        = "${var.name}-task-"
  assume_role_policy = data.aws_iam_policy_document.ecs_tasks_assume.json
}

data "aws_iam_policy_document" "exec_channel" {
  statement {
    actions = [
      "ssmmessages:CreateControlChannel",
      "ssmmessages:CreateDataChannel",
      "ssmmessages:OpenControlChannel",
      "ssmmessages:OpenDataChannel",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "task_exec_channel" {
  name   = "ecs-exec"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.exec_channel.json
}

locals {
  secret_ref = aws_secretsmanager_secret.app.arn
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${var.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_cpu
  memory                   = var.api_memory
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  # The image is built for linux/amd64 (CPU-only torch wheels); match it explicitly.
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([{
    name      = "api"
    image     = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
    essential = true

    portMappings = [{ containerPort = 8000, protocol = "tcp" }]

    environment = [
      { name = "QDRANT_URL", value = local.qdrant_url },
      { name = "GROQ_MODEL", value = var.groq_model },
      { name = "CORS_ORIGINS", value = "https://${aws_cloudfront_distribution.web.domain_name}" },
      { name = "MAX_UPLOAD_MB", value = tostring(var.max_upload_mb) },
      { name = "LOG_LEVEL", value = "INFO" },
      # The embedding model is baked into the image.
      { name = "HF_HUB_OFFLINE", value = "1" },
    ]

    secrets = concat(
      [
        { name = "DATABASE_URL", valueFrom = "${local.secret_ref}:DATABASE_URL::" },
        { name = "GROQ_API_KEY", valueFrom = "${local.secret_ref}:GROQ_API_KEY::" },
        { name = "API_KEYS", valueFrom = "${local.secret_ref}:API_KEYS::" },
      ],
      local.has_qdrant_api_key ? [{ name = "QDRANT_API_KEY", valueFrom = "${local.secret_ref}:QDRANT_API_KEY::" }] : [],
    )

    # ECS ignores the Dockerfile HEALTHCHECK, so it is repeated here.
    healthCheck = {
      command     = ["CMD-SHELL", "python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/livez', timeout=4).status == 200 else 1)\""]
      interval    = 15
      timeout     = 6
      retries     = 4
      startPeriod = 90
    }

    linuxParameters = { initProcessEnabled = true }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.api.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "api"
      }
    }
  }])
}

resource "aws_ecs_service" "api" {
  name            = "${var.name}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.api_desired_count
  launch_type     = "FARGATE"

  # Stop-then-start, never overlap: two API processes would each run their own audit-chain lock
  # and in-process upload jobs. The price is ~1-2 minutes of downtime per deploy.
  deployment_minimum_healthy_percent = 0
  deployment_maximum_percent         = 100

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  health_check_grace_period_seconds = 180
  enable_execute_command            = true

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.api.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [
    aws_lb_listener_rule.from_cloudfront,
    aws_db_instance.main,
    aws_secretsmanager_secret_version.app,
    aws_iam_role_policy.execution_secret,
    aws_iam_role_policy_attachment.execution,
  ]
}
