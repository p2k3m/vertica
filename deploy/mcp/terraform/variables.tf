variable "aws_region" {
  type = string
}

variable "aws_account_id" {
  type = string
}

variable "name_prefix" {
  type    = string
  default = "mcp-vertica"
}

variable "instance_type" {
  type    = string
  default = "t3.small"
}

variable "use_spot" {
  type    = bool
  default = true
}

variable "allowed_cidrs" {
  type    = list(string)
  default = []
}

variable "mcp_image_repo" {
  type    = string
  default = "mcp-vertica"
}

variable "mcp_http_token" {
  type    = string
  default = ""
}
