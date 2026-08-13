# Lásd a cloud-do/outputs.tf-et: a gyökér ezekből épít inventoryt, hogy a
# szolgáltató-választás egy helyen legyen.
output "cloud_ip" {
  description = "Public IPv4 of mother-001"
  value       = hcloud_server.mother.ipv4_address
}

output "cloud_id" {
  description = "Server id — the ansible trigger re-runs when this changes"
  value       = hcloud_server.mother.id
}
