variable "aws_region" {
  type = string
}

variable "aws_account_id" {
  type = string
}

variable "name_prefix" {
  type    = string
  default = "vertica-db"
}

variable "instance_type" {
  type    = string
  default = "t3.xlarge"
}

variable "use_spot" {
  type    = bool
  default = true
}

variable "allowed_cidrs" {
  type    = list(string)
  default = []
}

variable "volume_gb" {
  type    = number
  default = 50
}

variable "vertica_ecr_image" {
  type    = string
  default = "957650740525.dkr.ecr.ap-south-1.amazonaws.com/vertica-ce:v1.0"
}
