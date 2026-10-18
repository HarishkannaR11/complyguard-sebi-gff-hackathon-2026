# The ALB is internet-facing but only CloudFront can talk to it: the security group allows the
# CloudFront origin-facing prefix list, and the listener rejects any request that lacks the secret
# header CloudFront adds. Together they stop direct access to the API that bypasses CloudFront.
resource "random_password" "origin_verify" {
  length  = 40
  special = false
}

resource "aws_lb" "api" {
  name                       = var.name
  load_balancer_type         = "application"
  internal                   = false
  subnets                    = aws_subnet.public[*].id
  security_groups            = [aws_security_group.alb.id]
  drop_invalid_header_fields = true
  idle_timeout               = 60
}

resource "aws_lb_target_group" "api" {
  name        = "${var.name}-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip" # Fargate (awsvpc)
  vpc_id      = aws_vpc.main.id

  deregistration_delay = 30

  # /livez does not touch Postgres or Qdrant, so a dependency blip cannot get a healthy task killed.
  health_check {
    path                = "/livez"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 4
  }
}

resource "aws_lb_listener" "api" {
  load_balancer_arn = aws_lb.api.arn
  port              = local.alb_port
  protocol          = local.alb_https ? "HTTPS" : "HTTP"
  ssl_policy        = local.alb_https ? "ELBSecurityPolicy-TLS13-1-2-2021-06" : null
  certificate_arn   = local.alb_https ? var.alb_certificate_arn : null

  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Forbidden"
      status_code  = "403"
    }
  }
}

resource "aws_lb_listener_rule" "from_cloudfront" {
  listener_arn = aws_lb_listener.api.arn
  priority     = 10

  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [random_password.origin_verify.result]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
