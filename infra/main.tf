terraform {
  required_version = ">= 1.6.0"
  backend "s3" {
    bucket         = "vertica-mcp-tfstate"
    key            = "state/infra.tfstate"
    region         = "ap-south-1"
    dynamodb_table = "vertica-mcp-tflock"
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
  region = var.region
}

data "aws_caller_identity" "current" {}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnet_ids" "default" {
  vpc_id = data.aws_vpc.default.id
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-kernel-6.1*x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

resource "aws_ecr_repository" "mcp" {
  name                 = var.mcp_image_repo
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  encryption_configuration {
    encryption_type = "AES256"
  }
  image_scanning_configuration {
    scan_on_push = true
  }
  tags = {
    Project = var.project
  }
}

resource "aws_iam_role" "ec2" {
  name = "${var.project}-ec2-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })
  tags = { Project = var.project }
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "ecr_pull" {
  name = "${var.project}-ecr-pull"
  role = aws_iam_role.ec2.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"],
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project}-instance-profile"
  role = aws_iam_role.ec2.name
}

resource "aws_security_group" "mcp" {
  name        = "${var.project}-sg"
  description = "Allow Vertica and MCP access"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "Vertica"
    from_port   = 5433
    to_port     = 5433
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  ingress {
    description = "MCP HTTP"
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  ingress {
    description = "SSH"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = var.allowed_cidrs
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Project = var.project }
}

locals {
  mcp_image_uri = "${aws_ecr_repository.mcp.repository_url}:latest"
  compose_yaml  = templatefile("${path.module}/compose.remote.yml", {
    VERTICA_IMAGE_URI = var.vertica_image_uri
    MCP_IMAGE_URI     = local.mcp_image_uri
    MCP_HTTP_TOKEN    = var.mcp_http_token
  })
}

resource "aws_instance" "mcp" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = var.instance_type
  subnet_id                   = data.aws_subnet_ids.default.ids[0]
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.ec2.name
  vpc_security_group_ids      = [aws_security_group.mcp.id]
  key_name                    = var.ssh_key_name != "" ? var.ssh_key_name : null
  user_data = templatefile("${path.module}/user_data.sh", {
    region          = var.region
    aws_account_id  = var.aws_account_id
    vertica_image_uri = var.vertica_image_uri
    mcp_image_uri     = local.mcp_image_uri
    mcp_http_token    = var.mcp_http_token
    compose_yaml      = local.compose_yaml
  })

  lifecycle {
    precondition {
      condition     = !(contains(var.allowed_cidrs, "0.0.0.0/0") && var.mcp_http_token == "")
      error_message = "MCP_HTTP_TOKEN must be set when allowed_cidrs includes 0.0.0.0/0"
    }
  }

  dynamic "instance_market_options" {
    for_each = var.use_spot ? [1] : []
    content {
      market_type = "spot"
      spot_options {
        instance_interruption_behavior = "stop"
      }
    }
  }

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  tags = {
    Name    = "${var.project}-ec2"
    Project = var.project
  }
}

resource "aws_ebs_volume" "data" {
  availability_zone = aws_instance.mcp.availability_zone
  size              = var.ebs_size_gb
  type              = "gp3"
  encrypted         = true
  tags = {
    Name    = "${var.project}-data"
    Project = var.project
  }
}

resource "aws_volume_attachment" "data" {
  device_name = "/dev/xvdf"
  volume_id   = aws_ebs_volume.data.id
  instance_id = aws_instance.mcp.id
}
