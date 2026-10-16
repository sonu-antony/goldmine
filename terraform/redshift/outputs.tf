output "endpoint" {
  value = aws_redshift_cluster.this.endpoint
}

output "copy_role_arn" {
  description = "Use as IAM_ROLE in COPY statements."
  value       = aws_iam_role.redshift_copy.arn
}

output "staging_bucket" {
  value = aws_s3_bucket.staging.bucket
}

output "master_password_secret_arn" {
  value = aws_redshift_cluster.this.master_password_secret_arn
}
