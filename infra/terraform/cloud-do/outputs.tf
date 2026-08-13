# A gyökér-modul ebből építi az inventoryt és ezen futtatja az Ansible-t — így a
# szolgáltató-váltás egyetlen ponton dől el, és nem szivárog a konfigba.
output "cloud_ip" {
  description = "Public IPv4 of mother-001"
  value       = digitalocean_droplet.mother.ipv4_address
}

output "cloud_id" {
  description = "Droplet id — the ansible trigger re-runs when this changes"
  value       = digitalocean_droplet.mother.id
}
