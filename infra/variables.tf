variable "aws_region" { type = string, default = "ap-south-1" }
variable "aws_account_id" { type = string }
variable "allowed_cidrs" { type = list(string) }
variable "instance_type" { type = string, default = "t3.xlarge" }
variable "use_spot" { type = bool, default = true }
variable "volume_size_gb" { type = number, default = 50 }
variable "ttl_hours" { type = number, default = 0 }
variable "tf_backend_bucket" { type = string }
variable "tf_backend_ddb_table" { type = string }

variable "vertica_image_uri" { type = string }
variable "mcp_http_token" { type = string }
variable "vertica_user" { type = string }
variable "vertica_password" { type = string }
variable "vertica_database" { type = string }
