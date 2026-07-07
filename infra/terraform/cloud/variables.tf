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