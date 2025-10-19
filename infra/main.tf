terraform {
  required_version = ">= 1.6.0"
}

provider "aws" {
  region = var.region
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_security_group" "mcp" {
  name_prefix = "${var.resource_prefix}-sg-"
  description = "Ingress for Vertica and MCP"
  vpc_id      = data.aws_vpc.default.id

  dynamic "ingress" {
    for_each = toset(var.allowed_cidrs)
    content {
      from_port   = 5433
      to_port     = 5433
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }
  dynamic "ingress" {
    for_each = toset(var.allowed_cidrs)
    content {
      from_port   = 8000
      to_port     = 8000
      protocol    = "tcp"
      cidr_blocks = [ingress.value]
    }
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "ec2" {
  name_prefix = "${var.resource_prefix}-ec2-role-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}
resource "aws_iam_policy" "ecr_read" {
  name_prefix = "${var.resource_prefix}-ecr-read-"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect   = "Allow",
      Action   = ["ecr:GetAuthorizationToken","ecr:BatchGetImage","ecr:GetDownloadUrlForLayer","ecr:DescribeImages","ecr:DescribeRepositories"],
      Resource = "*"
    }]
  })
}
resource "aws_iam_role_policy_attachment" "ecr_attach" {
  role       = aws_iam_role.ec2.name
  policy_arn = aws_iam_policy.ecr_read.arn
}
resource "aws_iam_instance_profile" "ec2" {
  name_prefix = "${var.resource_prefix}-profile-"
  role = aws_iam_role.ec2.name
}

resource "tls_private_key" "this" {
  algorithm = "RSA"
  rsa_bits  = 2048
}
resource "aws_key_pair" "this" {
  key_name_prefix = "${var.resource_prefix}-key-"
  public_key = tls_private_key.this.public_key_openssh
}

data "aws_ami" "al2023" {
  owners      = ["137112412989"]
  most_recent = true

  filter {
    name   = "name"
    values = ["al2023-ami-*-kernel-6.1-x86_64"]
  }
}

resource "aws_instance" "mcp" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  key_name               = aws_key_pair.this.key_name
  subnet_id              = element(data.aws_subnets.default.ids, 0)
  vpc_security_group_ids = [aws_security_group.mcp.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  user_data = templatefile("${path.module}/user_data.sh", {
    REGION            = var.region
    AWS_ACCOUNT_ID    = var.aws_account_id
    VERTICA_IMAGE_URI = var.vertica_image_uri
    MCP_IMAGE_URI     = "${var.aws_account_id}.dkr.ecr.${var.region}.amazonaws.com/${var.mcp_image_repo}:${var.mcp_image_tag}"
    MCP_IMAGE_REPO    = var.mcp_image_repo
    MCP_IMAGE_TAG     = var.mcp_image_tag
    MCP_HTTP_TOKEN    = var.mcp_http_token
  })

  capacity_reservation_specification {
    capacity_reservation_preference = "open"
  }

  dynamic "instance_market_options" {
    for_each = var.use_spot ? [1] : []
    content {
      market_type = "spot"
      spot_options {
        instance_interruption_behavior = "stop"
        spot_instance_type             = "persistent"
      }
    }
  }

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  ebs_block_device {
    device_name           = "/dev/sdh"
    volume_size           = var.volume_size_gb
    volume_type           = "gp3"
    delete_on_termination = true
  }

  tags = { Name = "vertica-mcp" }

  provisioner "local-exec" {
    command = "echo Deploying EC2 ${self.public_ip}"
  }
}

output "public_ip" { value = aws_instance.mcp.public_ip }
output "public_dns" { value = aws_instance.mcp.public_dns }
