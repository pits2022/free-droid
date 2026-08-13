variable "ssh_public_key_path" {
  description = "Public key registered on the droplet. The matching PRIVATE key must be passphrase-less (Terraform's remote-exec cannot prompt)."
  type        = string
  default     = "~/.ssh/free-droid-mother.pub"
}

# A régió NEM szabadon választható: 2026-08-13-án mérve az Ada-kártyák csak `tor1`-ben
# vannak, és európai DO GPU-régió nincs. Ha egyszer lesz, ez az egysoros váltás.
variable "do_region" {
  description = "DigitalOcean region. GPU reality (2026-08-13): the Ada cards are tor1-only; no EU GPU region exists."
  type        = string
  default     = "tor1"
}

# A demó-cél a legkisebb Ada: 20 GB VRAM egy 8B Q4-hez (~5 GB) bőven elég, és fele
# annyi, mint a 6000 Ada. A H200-mérés a 6000 Ada-n futott (144 tok/s) — a 4000 Ada
# ugyanaz a generáció, tehát a szám jól extrapolálható.
variable "do_gpu_size" {
  description = "GPU droplet size. gpu-4000adax1-20gb ($0.76/h) is the demo target; gpu-6000adax1-48gb ($1.57/h) is the measured one."
  type        = string
  default     = "gpu-4000adax1-20gb"
}

variable "do_image" {
  description = "NVIDIA AI/ML Ready image (driver preinstalled). Plain Ubuntu would silently fall back to CPU."
  type        = string
  default     = "gpu-h100x1-base"
}
