output "public_ip"       { value = aws_instance.this.public_ip }
output "mcp_url"         { value = "http://${aws_instance.this.public_ip}:8000" }
output "vertica_address" { value = "${aws_instance.this.public_ip}:5433" }
output "ecr_mcp_repo"    { value = aws_ecr_repository.mcp.repository_url }
