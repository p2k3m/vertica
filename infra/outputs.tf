output "instance_id" {
  description = "ID of the Vertica MCP instance"
  value       = aws_instance.mcp.id
}

output "public_ip" {
  description = "Public IP of the Vertica MCP instance"
  value       = aws_instance.mcp.public_ip
}

output "mcp_repository_url" {
  description = "URI of the ECR repository hosting the MCP image"
  value       = aws_ecr_repository.mcp.repository_url
}
