output "mcp_http_url" { value = "http://${aws_instance.mcp.public_dns}:8000" }
