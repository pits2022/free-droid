variable "ssh_public_key_path" {
  description = "Public key registered on the droplet. The matching PRIVATE key must be passphrase-less (Terraform's remote-exec cannot prompt)."
  type        = string
  default     = "~/.ssh/free-droid-mother.pub"
}

# A régió NEM szabadon választható: 2026-08-13-án mérve az Ada-kártyák csak `tor1`-ben
# vannak, és európai DO GPU-régió nincs. Ha egyszer lesz, ez az egysoros váltás.
variable "do_region" {
  description = "DigitalOcean region. Measured 2026-08-28: the H100 is in ams3 (EU, 44.9 ms RTT from the Pi). The 2026-08-13 'Ada is tor1-only, no EU GPU region' finding is superseded."
  type        = string
  default     = "ams3"
}

# A demó-doboz a H100 (mérve 2026-08-28: 233 tok/s a 8B-n, whisper 0,31 s), mert a
# „legkisebb Ada" terv MEGDŐLT: a gpu-4000adax1 régiólistája ÜRES (2026-08-13 óta,
# újra ellenőrizve 2026-09-03), tehát alapértelmezésként egy sima `apply` elbukott
# volna vele. Az ár 5,8× ($4,41/h), cserébe EU-régió. Az `-var do_gpu_size=...`
# felülírás megmaradt, ha egy olcsóbb kártya újra kapna régiót.
variable "do_gpu_size" {
  description = "GPU droplet size. gpu-h100x1-80gb ($4.41/h, ams3) is the measured demo box; gpu-4000adax1-20gb ($0.76/h) currently has no region at all."
  type        = string
  default     = "gpu-h100x1-80gb"
}

variable "do_image" {
  description = "NVIDIA AI/ML Ready image (driver preinstalled). Plain Ubuntu would silently fall back to CPU."
  type        = string
  default     = "gpu-h100x1-base"
}
