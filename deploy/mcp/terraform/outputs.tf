output "mcp_instance_id" {
  value = aws_instance.mcp.id
}

output "mcp_public_url" {
  value = "http://${aws_instance.mcp.public_ip}:8000"
}

output "db_private_ip" {
  value = local.db_host
}
