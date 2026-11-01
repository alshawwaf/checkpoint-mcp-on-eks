terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.59"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # Local state by default (gitignored). For a team, copy backend.tf.example
  # to backend.tf and point it at an S3 bucket (native S3 locking, TF >= 1.10).
}

provider "aws" {
  region = var.region

  default_tags {
    tags = merge({
      project    = "chkp-mcp-eks"
      stack      = var.prefix == "" ? "default" : var.prefix
      managed-by = "terraform"
      component  = "platform"
    }, var.extra_tags)
  }
}
