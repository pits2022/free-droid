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
# The name Ansible reaches the Pi by. The previously hardcoded `child-001.local`
# mDNS name resolved NOWHERE — not on the dev machine, not on the 4G router — so the
# first production run would have stalled on it. Home DNS serves `free-droid-001.home`.
#
# No single name is universal, which is why this is a VARIABLE and not a constant:
# `.home` comes from the home router's DNS, may not resolve on the Wifi196 hotspot,
# and on mobile data the correct value is the WireGuard address. Override per network:
#   terraform apply -var edge_ansible_host=10.0.0.2
variable "edge_ansible_host" {
  description = "Ansible host for the Pi: home DNS name, hotspot IP, or the WireGuard 10.0.0.2"
  type        = string
  default     = "free-droid-001.home"
}

# A Pi-n futó user és a hozzá tartozó kulcs. MÉRVE 2026-08-12-én a működő gépen: a user
# `creator`, nem `pi` — a korábbi `ansible_user=pi` MINDEN éles Ansible-futást elbuktatott
# volna hitelesítésnél, és ez a fajta hiba csak a helyszínen derül ki.
#
# Az `IdentitiesOnly=yes` nem kozmetika: nélküle az SSH minden betöltött kulcsot felajánl,
# és egy tele agent mellett a szerver "too many authentication failures"-szel eldobja a
# kapcsolatot, még akkor is, ha a helyes kulcs is a listán van.
#
# A user a Pi-IMAGE tulajdonsága, ezért ritkán változik; a kulcs útvonala viszont
# OPERÁTOR-specifikus, ezért mindkettő variable — ugyanaz az érv, mint az
# `edge_ansible_host`-nál: nincs univerzális érték.
variable "edge_ansible_user" {
  description = "SSH user on the Pi (the image's user, `creator` — not the Raspberry Pi OS default `pi`)"
  type        = string
  default     = "creator"
}

variable "edge_ssh_key" {
  description = "Private key path for the Pi (dedicated key — nothing else must be reachable with it)"
  type        = string
  default     = "~/.ssh/free-droid"
}
