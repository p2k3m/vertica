terraform {
  backend "s3" {
    bucket         = var.tf_backend_bucket
    key            = "vertica-mcp/terraform.tfstate"
    region         = var.aws_region
    dynamodb_table = var.tf_backend_ddb_table
    encrypt        = true
  }
}
