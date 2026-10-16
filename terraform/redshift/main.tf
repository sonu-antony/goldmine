# Infrastructure for the warehouse: the cluster, its network, the S3 bucket the loader stages files in,
# and the IAM role Redshift uses to read that bucket during COPY.
# Users, groups and grants live in ../../redshift/access_management.sql, because they are database
# objects and not AWS resources.

locals {
  cluster_id = "${var.name}-warehouse"
}

# ---------- staging bucket for COPY ----------

resource "aws_s3_bucket" "staging" {
  bucket = "${var.name}-warehouse-staging"
}

resource "aws_s3_bucket_public_access_block" "staging" {
  bucket                  = aws_s3_bucket.staging.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "staging" {
  bucket = aws_s3_bucket.staging.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Staged files are only needed until COPY has loaded them. Expire them so storage does not grow forever.
resource "aws_s3_bucket_lifecycle_configuration" "staging" {
  bucket = aws_s3_bucket.staging.id

  rule {
    id     = "expire-staged-files"
    status = "Enabled"

    filter {}

    expiration {
      days = 14
    }
  }
}

# ---------- IAM role Redshift assumes to read the bucket ----------

data "aws_iam_policy_document" "redshift_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["redshift.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "copy_from_staging" {
  statement {
    actions   = ["s3:GetObject", "s3:GetBucketLocation", "s3:ListBucket"]
    resources = [aws_s3_bucket.staging.arn, "${aws_s3_bucket.staging.arn}/*"]
  }
}

resource "aws_iam_role" "redshift_copy" {
  name               = "${local.cluster_id}-copy"
  assume_role_policy = data.aws_iam_policy_document.redshift_assume.json
}

resource "aws_iam_role_policy" "redshift_copy" {
  name   = "read-staging-bucket"
  role   = aws_iam_role.redshift_copy.id
  policy = data.aws_iam_policy_document.copy_from_staging.json
}

# ---------- network ----------

resource "aws_redshift_subnet_group" "this" {
  name       = local.cluster_id
  subnet_ids = var.subnet_ids
}

resource "aws_security_group" "redshift" {
  name        = local.cluster_id
  description = "Redshift access from known networks only"
  vpc_id      = var.vpc_id

  ingress {
    description = "Redshift port"
    from_port   = 5439
    to_port     = 5439
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidr_blocks
  }
}

# ---------- cluster configuration ----------

resource "aws_redshift_parameter_group" "this" {
  name   = local.cluster_id
  family = "redshift-1.0"

  parameter {
    name  = "require_ssl"
    value = "true"
  }

  # Logs every query by user, which is what you read when someone asks who ran the expensive query.
  parameter {
    name  = "enable_user_activity_logging"
    value = "true"
  }

  parameter {
    name  = "max_concurrency_scaling_clusters"
    value = "1"
  }
}

resource "aws_redshift_cluster" "this" {
  cluster_identifier = local.cluster_id
  database_name      = "warehouse"
  node_type          = var.node_type
  number_of_nodes    = var.number_of_nodes
  cluster_type       = var.number_of_nodes > 1 ? "multi-node" : "single-node"

  master_username        = "admin"
  manage_master_password = true # AWS keeps the password in Secrets Manager, never in Terraform state

  cluster_subnet_group_name    = aws_redshift_subnet_group.this.name
  vpc_security_group_ids       = [aws_security_group.redshift.id]
  cluster_parameter_group_name = aws_redshift_parameter_group.this.name
  iam_roles                    = [aws_iam_role.redshift_copy.arn]

  publicly_accessible                 = false
  encrypted                           = true
  enhanced_vpc_routing                = true
  automated_snapshot_retention_period = 7
  final_snapshot_identifier           = "${local.cluster_id}-final"
  skip_final_snapshot                 = false

  # Stop surprise downtime during business hours: maintenance on Sunday night.
  preferred_maintenance_window = "sun:23:00-mon:00:00"
}

# ---------- cost management ----------

resource "aws_redshift_usage_limit" "concurrency_scaling" {
  cluster_identifier = aws_redshift_cluster.this.id
  feature_type       = "concurrency-scaling"
  limit_type         = "time"
  amount             = var.concurrency_scaling_limit_minutes
  period             = "monthly"
  breach_action      = "log"
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["scheduler.redshift.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  count              = var.pause_outside_business_hours ? 1 : 0
  name               = "${local.cluster_id}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "scheduler" {
  count = var.pause_outside_business_hours ? 1 : 0
  name  = "pause-resume"
  role  = aws_iam_role.scheduler[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["redshift:PauseCluster", "redshift:ResumeCluster"]
      Resource = aws_redshift_cluster.this.arn
    }]
  })
}

resource "aws_redshift_scheduled_action" "pause" {
  count    = var.pause_outside_business_hours ? 1 : 0
  name     = "${local.cluster_id}-pause"
  schedule = "cron(0 19 ? * MON-FRI *)"
  iam_role = aws_iam_role.scheduler[0].arn

  target_action {
    pause_cluster {
      cluster_identifier = aws_redshift_cluster.this.id
    }
  }
}

resource "aws_redshift_scheduled_action" "resume" {
  count    = var.pause_outside_business_hours ? 1 : 0
  name     = "${local.cluster_id}-resume"
  schedule = "cron(0 5 ? * MON-FRI *)"
  iam_role = aws_iam_role.scheduler[0].arn

  target_action {
    resume_cluster {
      cluster_identifier = aws_redshift_cluster.this.id
    }
  }
}
