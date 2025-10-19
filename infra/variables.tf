variable "region" { default = "ap-south-1" }
variable "use_spot" {
  type    = bool
  default = true
}
variable "instance_type" { default = "t3.xlarge" }
variable "volume_size_gb" { default = 100 }
variable "allowed_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
}

variable "resource_prefix" {
  type    = string
  default = "vertica-mcp"
}
variable "aws_account_id" { type = string }
variable "mcp_http_token" {
  type    = string
  default = ""
}

variable "vertica_image_uri" {
  type    = string
  default = "957650740525.dkr.ecr.ap-south-1.amazonaws.com/vertica-ce:v1.0"
}

variable "mcp_image_repo" {
  type    = string
  default = "mcp-vertica"
}

variable "mcp_image_tag" {
  type    = string
  default = "latest"
}
