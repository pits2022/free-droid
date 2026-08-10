variable "ssh_public_key_path" {
  description = "Path to the public SSH key. Its matching private key (same path minus .pub) must be passphrase-less for the provisioner's file() read."
  type        = string
}

variable "cloud_server_type" {
  description = "Hetzner Cloud server type (ARM64, CPU-only) — e.g. cax31 or cax41."
  type        = string
  default     = "cax31"
}

variable "cloud_location" {
  description = "Hetzner location (eu-central zone: nbg1/fsn1/hel1)."
  type        = string
  default     = "nbg1"
}
# A Pi-t az Ansible ezen a néven éri el. A korábbi hardkódolt `child-001.local`
# mDNS-név NEM oldódott fel (sem a fejlesztői gépen, sem a 4G routeren), tehát az
# első futás elakadt volna rajta. Az itthoni DNS a `free-droid-001.home`-ot adja.
#
# ⚠️ Egyik név sem univerzális: a `.home` az itthoni router DNS-e, a Wifi196-on
# nem biztos, hogy feloldódik, adatkapcsolaton pedig a WireGuard `10.0.0.2` a
# helyes érték. Ezért VÁLTOZÓ, nem konstans — hálózatonként átállítható:
#   terraform apply -var edge_ansible_host=10.0.0.2
variable "edge_ansible_host" {
  description = "Ansible host for the Pi: home DNS name, hotspot IP, or the WireGuard 10.0.0.2"
  type        = string
  default     = "free-droid-001.home"
}
