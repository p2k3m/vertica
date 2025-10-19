output "mcp_http_url" { value = "http://${aws_instance.mcp.public_dns}:8000" }

output "instance_id" { value = aws_instance.mcp.id }
