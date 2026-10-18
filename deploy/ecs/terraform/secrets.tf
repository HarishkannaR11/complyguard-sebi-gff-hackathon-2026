locals {
  # nonsensitive() exposes only "is it set", never the value.
  has_qdrant_api_key = nonsensitive(var.qdrant_api_key != "")
}

# One Secrets Manager secret holding everything sensitive. ECS injects individual keys into the
# container at start; they never appear in the task definition. They DO live in Terraform state.
resource "aws_secretsmanager_secret" "app" {
  name                    = "${var.name}/app"
  recovery_window_in_days = var.secret_recovery_window_days
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id

  secret_string = jsonencode(merge(
    {
      # sslmode=require: RDS Postgres 16 enforces TLS by default.
      DATABASE_URL = "postgresql://${aws_db_instance.main.username}:${random_password.db.result}@${aws_db_instance.main.address}:${aws_db_instance.main.port}/${aws_db_instance.main.db_name}?sslmode=require"
      GROQ_API_KEY = var.groq_api_key
      API_KEYS     = var.api_keys
    },
    local.has_qdrant_api_key ? { QDRANT_API_KEY = var.qdrant_api_key } : {},
  ))
}
