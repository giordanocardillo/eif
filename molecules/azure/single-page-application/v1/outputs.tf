output "frontdoor_endpoint_hostname" { value = module.frontdoor.endpoint_hostname }
output "storage_account_name"        { value = module.blob.storage_account_name }
output "primary_web_endpoint"        { value = module.blob.primary_web_endpoint }
