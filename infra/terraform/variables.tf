
# Lásd a cloud modul azonos nevű változóját: a Pi Ansible-hosztneve hálózatonként más.
variable "edge_ansible_host" {
  description = "Ansible host for the Pi (home DNS name, hotspot IP, or WireGuard 10.0.0.2)"
  type        = string
  default     = "free-droid-001.home"
}
