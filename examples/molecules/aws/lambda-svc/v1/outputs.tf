output "function_arn" {
  description = "ARN of the Lambda function."
  value       = module.lambda.function_arn
}

output "function_name" {
  description = "Name of the Lambda function."
  value       = module.lambda.function_name
}

output "invoke_arn" {
  description = "ARN for invoking the Lambda function."
  value       = module.lambda.invoke_arn
}

output "security_group_id" {
  description = "ID of the Lambda security group."
  value       = module.sg.security_group_id
}
