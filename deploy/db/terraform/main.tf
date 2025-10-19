terraform {
  required_version = ">= 1.7"
  backend "s3" {
    bucket         = "vertica-mcp-tf-${var.aws_account_id}-${var.aws_region}"
    key            = "db/terraform.tfstate"
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

data "aws_caller_identity" "current" {}

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

locals {
  subnet_id = data.aws_subnet_ids.default.ids[0]
}

resource "aws_iam_role" "db" {
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
  role       = aws_iam_role.db.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy_attachment" "cw" {
  role       = aws_iam_role.db.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}

resource "aws_iam_role_policy_attachment" "ecr_read" {
  role       = aws_iam_role.db.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_instance_profile" "db" {
  name = "${var.name_prefix}-profile"
  role = aws_iam_role.db.name
}

resource "aws_security_group" "db" {
  name        = "${var.name_prefix}-sg"
  description = "Vertica 5433 exposed only to allowed CIDRs"
  vpc_id      = data.aws_vpc.default.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  dynamic "ingress" {
    for_each = var.allowed_cidrs
    content {
      description = "Vertica client"
      from_port   = 5433
      to_port     = 5433
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }
}

resource "aws_instance" "db" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = local.subnet_id
  iam_instance_profile   = aws_iam_instance_profile.db.name
  vpc_security_group_ids = [aws_security_group.db.id]
  associate_public_ip_address = true
  monitoring             = false

  root_block_device {
    volume_size = var.volume_gb
    volume_type = "gp3"
  }

  dynamic "instance_market_options" {
    for_each = var.use_spot ? [1] : []
    content {
      market_type = "spot"
    }
  }

  user_data = templatefile("${path.module}/user_data_db.sh", {
    vertica_ecr_image = var.vertica_ecr_image
  })

  tags = {
    Name = var.name_prefix
  }
}
