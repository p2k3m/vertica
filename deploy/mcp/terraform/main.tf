terraform {
  required_version = ">= 1.7"
  backend "s3" {
    bucket         = "vertica-mcp-tf-${var.aws_account_id}-${var.aws_region}"
    key            = "mcp/terraform.tfstate"
    region         = var.aws_region
    dynamodb_table = "vertica-mcp-tf-locks"
    encrypt        = true
  }
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["137112412989"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnet_ids" "default" {
  vpc_id = data.aws_vpc.default.id
}

data "terraform_remote_state" "db" {
  backend = "s3"
  config = {
    bucket = "vertica-mcp-tf-${var.aws_account_id}-${var.aws_region}"
    key    = "db/terraform.tfstate"
    region = var.aws_region
  }
}

locals {
  db_host = data.terraform_remote_state.db.outputs.db_private_ip
  subnet  = data.aws_subnet_ids.default.ids[0]
}

resource "aws_security_group" "mcp" {
  name   = "${var.name_prefix}-sg"
  vpc_id = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  dynamic "ingress" {
    for_each = var.allowed_cidrs
    content {
      description = "MCP HTTP"
      from_port   = 8000
      to_port     = 8000
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }
}

resource "aws_iam_role" "mcp" {
  name               = "${var.name_prefix}-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.mcp.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "ecr_read" {
  role       = aws_iam_role.mcp.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_instance_profile" "mcp" {
  name = "${var.name_prefix}-profile"
  role = aws_iam_role.mcp.name
}

resource "aws_instance" "mcp" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = local.subnet
  vpc_security_group_ids = [aws_security_group.mcp.id]
  iam_instance_profile   = aws_iam_instance_profile.mcp.name
  associate_public_ip_address = true

  dynamic "instance_market_options" {
    for_each = var.use_spot ? [1] : []
    content {
      market_type = "spot"
    }
  }

  user_data = templatefile("${path.module}/user_data_mcp.sh", {
    db_host        = local.db_host
    mcp_http_token = var.mcp_http_token
    aws_region     = var.aws_region
    aws_account_id = var.aws_account_id
    mcp_image_repo = var.mcp_image_repo
  })

  tags = {
    Name = var.name_prefix
  }
}
