resource "random_password" "db" {
  length  = 32
  special = false # keeps the password URL-safe inside DATABASE_URL
}

resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "main" {
  identifier = var.name

  engine         = "postgres"
  engine_version = "16"
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage_gb
  max_allocated_storage = var.db_allocated_storage_gb * 4
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "regops"
  username = "regops"
  password = random_password.db.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = var.db_multi_az

  backup_retention_period    = var.db_backup_retention_days
  backup_window              = "21:00-22:00" # 02:30-03:30 IST
  maintenance_window         = "sun:22:00-sun:23:00"
  auto_minor_version_upgrade = true

  deletion_protection       = var.db_deletion_protection
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.name}-final"
  copy_tags_to_snapshot     = true

  lifecycle {
    # "16" means "latest 16.x"; AWS reports the concrete minor version after creation.
    ignore_changes = [engine_version]
  }
}
