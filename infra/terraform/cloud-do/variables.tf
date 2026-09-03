variable "ssh_public_key_path" {
  description = "Public key registered on the droplet. The matching PRIVATE key must be passphrase-less (Terraform's remote-exec cannot prompt)."
  type        = string
  default     = "~/.ssh/free-droid-mother.pub"
}

# A régió NEM szabadon választható: 2026-08-13-án mérve az Ada-kártyák csak `tor1`-ben
# vannak, és európai DO GPU-régió nincs. Ha egyszer lesz, ez az egysoros váltás.
# No defaults here either: the root module owns the decision (and its validation),
# and a second default would only drift from it (PR #104 review).
variable "do_region" {
  description = "DigitalOcean region. Passed from the root; see gpu_pick.py."
  type        = string
}

variable "do_gpu_size" {
  description = "GPU droplet size. Passed from the root; see gpu_pick.py."
  type        = string
}

variable "do_image" {
  description = "NVIDIA AI/ML Ready image (driver preinstalled). Plain Ubuntu would silently fall back to CPU."
  type        = string
  default     = "gpu-h100x1-base"
}
