provider "aws" { region = var.aws_region }

data "aws_caller_identity" "me" {}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["137112412989"]
  filter { name = "name" values = ["al2023-ami-*-x86_64"] }
}

data "aws_vpc" "default" { default = true }

data "aws_subnet_ids" "default" { vpc_id = data.aws_vpc.default.id }

resource "aws_iam_role" "ec2" {
  name               = "vertica-mcp-ec2-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect = "Allow",
      Principal = { Service = "ec2.amazonaws.com" },
      Action   = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
resource "aws_iam_role_policy_attachment" "cw" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy"
}
resource "aws_iam_role_policy_attachment" "ecr_ro" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly"
}

resource "aws_iam_instance_profile" "this" { name = "vertica-mcp-ec2-profile" role = aws_iam_role.ec2.name }

resource "aws_security_group" "this" {
  name        = "vertica-mcp-sg"
  description = "Allow Vertica 5433 + MCP 8000 from specific CIDRs"
  vpc_id      = data.aws_vpc.default.id

  egress { from_port = 0 to_port = 0 protocol = "-1" cidr_blocks = ["0.0.0.0/0"] }

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
  dynamic "ingress" {
    for_each = var.allowed_cidrs
    content {
      description = "Vertica SQL"
      from_port   = 5433
      to_port     = 5433
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }
}

locals {
  subnet_id = data.aws_subnet_ids.default.ids[0]
}

resource "aws_ecr_repository" "mcp" {
  name                 = "mcp-vertica"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_instance" "this" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = var.instance_type
  subnet_id                   = local.subnet_id
  vpc_security_group_ids      = [aws_security_group.this.id]
  iam_instance_profile        = aws_iam_instance_profile.this.name
  associate_public_ip_address = true

  root_block_device { volume_size = var.volume_size_gb volume_type = "gp3" }

  user_data = templatefile("${path.module}/userdata.sh", {
    region             = var.aws_region,
    account_id         = var.aws_account_id,
    vertica_image_uri  = var.vertica_image_uri,
    mcp_repo_uri       = aws_ecr_repository.mcp.repository_url,
    vertica_user       = var.vertica_user,
    vertica_password   = var.vertica_password,
    vertica_database   = var.vertica_database,
    mcp_http_token     = var.mcp_http_token,
    ttl_hours          = var.ttl_hours
  })

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  monitoring = false

  lifecycle { create_before_destroy = true }
  dynamic "instance_market_options" {
    for_each = var.use_spot ? [1] : []
    content {
      market_type = "spot"
    }
  }
  tags = { Name = "vertica-mcp" }
}
