variable "ssh_public_key_path" {
  description = "Path to the public SSH key used to access the cloud instance."
  type        = string
}

variable "cloud_server_type" {
  description = "Hetzner Cloud server type (ARM64, CPU-only) — e.g. cax31 or cax41."
  type        = string
  default     = "cax31"
}