terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.60, < 7.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # Local state by default. For a team, keep state in S3 (with a DynamoDB or S3 lock):
  #   backend "s3" { bucket = "..." key = "regops/ecs.tfstate" region = "ap-south-1" }
  # State contains the secrets below in plain text -- protect it accordingly.
}
