output "db_instance_id" {
  value = aws_instance.db.id
}

output "db_public_ip" {
  value = aws_instance.db.public_ip
}

output "db_private_ip" {
  value = aws_instance.db.private_ip
}

output "db_port" {
  value = 5433
}

output "db_conn" {
  value = "HOST=${aws_instance.db.public_ip} PORT=5433 USER=dbadmin DB=VMart"
}
