output "function_arn" {
  description = "ARN of the Lambda function."
  value       = aws_lambda_function.this.arn
}

output "function_name" {
  description = "Name of the Lambda function."
  value       = aws_lambda_function.this.function_name
}

output "invoke_arn" {
  description = "ARN to be used for invoking the function (e.g. from API Gateway)."
  value       = aws_lambda_function.this.invoke_arn
}

output "role_arn" {
  description = "ARN of the IAM execution role."
  value       = aws_iam_role.this.arn
}
