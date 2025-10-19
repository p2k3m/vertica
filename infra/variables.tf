variable "project" {
  description = "Project name used for tagging resources"
  type        = string
  default     = "vertica-mcp"
}

variable "region" {
  description = "AWS region"
  type        = string
  default     = "ap-south-1"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "t3.xlarge"
}

variable "use_spot" {
  description = "Whether to run the EC2 instance on Spot"
  type        = bool
  default     = true
}

variable "ebs_size_gb" {
  description = "Size of the attached Vertica data volume"
  type        = number
  default     = 100
}

variable "allowed_cidrs" {
  description = "List of CIDR blocks allowed to reach the instance"
  type        = list(string)
  default     = ["127.0.0.1/32"]
}

variable "mcp_http_token" {
  description = "API token for the MCP HTTP endpoint"
  type        = string
  default     = ""
  sensitive   = true
}

variable "vertica_image_uri" {
  description = "ECR image URI for Vertica CE"
  type        = string
  default     = "957650740525.dkr.ecr.ap-south-1.amazonaws.com/vertica-ce:v1.0"
}

variable "mcp_image_repo" {
  description = "ECR repository name for the MCP server"
  type        = string
  default     = "mcp-vertica"
}

variable "aws_account_id" {
  description = "AWS account identifier"
  type        = string
}

variable "ssh_key_name" {
  description = "Optional SSH key pair to attach to the instance"
  type        = string
  default     = ""
}
