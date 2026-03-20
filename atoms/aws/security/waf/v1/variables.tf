variable "name" {
  description = "Name for the WAF WebACL."
  type        = string
}

variable "environment" {
  description = "Deployment environment."
  type        = string
}

variable "managed_rule_group_name" {
  description = "Name of the AWS managed rule group to attach."
  type        = string
  default     = "AWSManagedRulesCommonRuleSet"
}
