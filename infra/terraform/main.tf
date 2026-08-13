terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.60"
    }
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Mindkét token OPCIONÁLIS, mert egyszerre csak az egyik felhő él. A `cloud_provider`
# választja ki, melyik modul jön létre (`count`), és csak annak a tokenje kell. Ha a
# hcloud_token kötelező maradna, a DO-s apply is a .tfvars-ra várna.
variable "hcloud_token" {
  description = "Hetzner Cloud API token (cloud-fallback). Only needed when cloud_provider=hetzner."
  type        = string
  sensitive   = true
  default     = ""
}

variable "do_token" {
  description = "DigitalOcean API token (cloud-main). Only needed when cloud_provider=digitalocean."
  type        = string
  sensitive   = true
  default     = ""
}

provider "hcloud" {
  token = var.hcloud_token
}

provider "digitalocean" {
  # `null`, ha a változó üres: így a provider a saját env-fallbackjára esik
  # (`DIGITALOCEAN_TOKEN`), és nem egy ÜRES sztringgel próbál hitelesíteni. Üres
  # sztringnél a hiba "401 Unauthorized" lenne, ami tokenhiányra nem utal —
  # órákat lehet vele elmenni.
  token = var.do_token != "" ? var.do_token : null
}

provider "aws" {
  region  = "eu-central-1"
  profile = "terraform-s3-access"
}

terraform {
  backend "s3" {
    bucket       = "terraform-tfstate-files-871544274798-eu-central-1-an"
    key          = "free-droid/terraform.tfstate"
    region       = "eu-central-1"
    encrypt      = true
    use_lockfile = true
  }
}

variable "ssh_public_key_path" {
  description = "Path to the public SSH key used to access the cloud instance. The matching private key (same path minus .pub) must be PASSPHRASE-LESS — the Ansible provisioner reads it via file()."
  type        = string
  default     = "~/.ssh/free-droid-mother.pub"
}

variable "cloud_server_type" {
  description = "Hetzner Cloud server type for the cloud backend (ARM64, CPU-only). CAX31 default; CAX41 for more headroom."
  type        = string
  default     = "cax31"
}

variable "cloud_location" {
  description = "Hetzner location for the cloud server (eu-central zone: nbg1/fsn1/hel1). Switch if a location is out of CAX (ARM Ampere) capacity."
  type        = string
  default     = "nbg1"
}

# See the cloud module's variable of the same name: the Pi's Ansible host differs
# per network (home DNS / hotspot / WireGuard).
variable "edge_ansible_host" {
  description = "Ansible host for the Pi: home DNS name, hotspot IP, or the WireGuard 10.0.0.2"
  type        = string
  default     = "free-droid-001.home"
}

# See the cloud module's variables of the same name. The user is the Pi image's
# (`creator`), the key is operator-specific.
variable "edge_ansible_user" {
  description = "SSH user on the Pi (`creator`, not the Raspberry Pi OS default `pi`)"
  type        = string
  default     = "creator"
}

variable "edge_ssh_key" {
  description = "Private key path for the Pi (dedicated key)"
  type        = string
  default     = "~/.ssh/free-droid"
}

# ── A felhő-választás EGYETLEN pontja ────────────────────────────────────────────
# cloud-main     = DigitalOcean GPU (tor1, RTX 4000 Ada) — a demó felhője
# cloud-fallback = Hetzner CAX31/41 (nbg1, CPU-only)     — tartósabb, demó utáni út
#
# A Teremtő döntése (2026-08-13): a DO a fő út, mert a Hetzneren folyamatos a
# VPS-hiány (egy demó napján nem lehet rá hagyatkozni), és mert a GPU-s 8B 144 tok/s
# a CPU-s 3,6-5 tok/s-mal szemben — a hang-pipeline ~6,8 tok/s-ot kíván, amit a CPU-s
# út NEM ér el. A GPU-t óradíjban, pár órára vesszük ki; a Hetzner marad a tartós
# üzemre. Részletek és mérés: H200-tests.md.
variable "cloud_provider" {
  description = "Which cloud to create: digitalocean (cloud-main, GPU) or hetzner (cloud-fallback, CPU)"
  type        = string
  default     = "digitalocean"

  validation {
    condition     = contains(["digitalocean", "hetzner"], var.cloud_provider)
    error_message = "cloud_provider must be \"digitalocean\" (main) or \"hetzner\" (fallback)."
  }
}

# A `count` teszi kizárólagossá: egyszerre PONTOSAN egy felhő létezik. Ez nem csak
# tisztaság — két egyidejű felhő két WireGuard-peert jelentene ugyanarra a 10.0.0.1
# címre, és az inventory sem tudná, melyikre mutasson.
module "cloud" {
  count               = var.cloud_provider == "hetzner" ? 1 : 0
  source              = "./cloud"
  ssh_public_key_path = var.ssh_public_key_path
  cloud_server_type   = var.cloud_server_type
  cloud_location      = var.cloud_location
}

module "cloud_do" {
  count               = var.cloud_provider == "digitalocean" ? 1 : 0
  source              = "./cloud-do"
  ssh_public_key_path = var.ssh_public_key_path
  do_region           = var.do_region
  do_gpu_size         = var.do_gpu_size
}

variable "do_region" {
  description = "DO region (GPU reality 2026-08-13: Ada cards are tor1-only, no EU GPU region)"
  type        = string
  default     = "tor1"
}

variable "do_gpu_size" {
  description = "DO GPU size. gpu-4000adax1-20gb ($0.76/h) demo target; gpu-6000adax1-48gb ($1.57/h) is the measured one"
  type        = string
  default     = "gpu-4000adax1-20gb"
}

# Az aktív felhő adatai. A `one()` a count-os modul egyelemű listáját bontja ki, és
# `null`-t ad, ha az a modul nem él — így az inventory mindig a LÉTEZŐ felhőre mutat.
locals {
  cloud_ip = coalesce(one(module.cloud[*].cloud_ip), one(module.cloud_do[*].cloud_ip))
  cloud_id = coalesce(one(module.cloud[*].cloud_id), one(module.cloud_do[*].cloud_id))
}

# ── Inventory: a gyökérben, NEM a felhő-modulban ─────────────────────────────────
# Korábban a Hetzner-modul írta. Két felhő-modullal az UGYANARRA a fájlra írás
# ütközne, ezért került ide: egy inventory, bármelyik szolgáltatóval. A `mother-001`
# név szolgáltató-független, tehát az Ansible és a WireGuard-konfig változatlan.
resource "local_file" "ansible_inventory" {
  content  = <<-EOT
  [cloud]
  mother-001 ansible_host=${local.cloud_ip} ansible_user=root vpn_ip=10.0.0.1

  [edge]
  # Host/user/key come from vars. The user is `creator` (the Pi image's), NOT the Raspberry
  # Pi OS default `pi` — the old hardcoded `pi` would have failed auth on every real run.
  #
  # When the robot is on mobile data the correct host is its WireGuard address (10.0.0.2)
  # and SSH goes through the cloud as a jump host — the Pi sits behind carrier NAT, but it
  # is the WireGuard initiator and wg0.conf sets PersistentKeepalive on the edge side, so
  # the cloud can reach it at any time. FIGYELEM: az `ansible_ssh_common_args` egyetlen
  # kulcs, tehát a ProxyJump-ot BELE kell fűzni, nem másodikként hozzáadni — két azonos
  # kulcs esetén az INI az utolsót veszi, és az `IdentitiesOnly` némán elveszik:
  #   ansible_ssh_common_args='-o IdentitiesOnly=yes -o ProxyJump=root@${local.cloud_ip}'
  free-droid-001 ansible_host=${var.edge_ansible_host} ansible_user=${var.edge_ansible_user} ansible_ssh_private_key_file=${var.edge_ssh_key} ansible_ssh_common_args='-o IdentitiesOnly=yes' vpn_ip=10.0.0.2
  EOT
  filename = "${path.root}/../ansible/inventory.ini"
}

resource "null_resource" "trigger_ansible" {
  depends_on = [local_file.ansible_inventory]

  # Re-run provisioning when the server or the rendered inventory changes,
  # instead of only once at create time.
  triggers = {
    server_id = local.cloud_id
    inventory = local_file.ansible_inventory.content
  }

  provisioner "remote-exec" {
    inline = ["echo 'SSH is ready on mother-001!'"]

    # Read the dedicated, PASSPHRASE-LESS mother key (default: ~/.ssh/free-droid-mother,
    # derived from the .pub path). A passphrase-protected key (e.g. a personal id_rsa)
    # fails here with "this private key is passphrase protected" — hence the dedicated key.
    connection {
      type        = "ssh"
      user        = "root"
      private_key = file(pathexpand(trimsuffix(var.ssh_public_key_path, ".pub")))
      host        = local.cloud_ip
    }
  }

  provisioner "local-exec" {
    # Provision the cloud node. The edge (free-droid-001) is provisioned separately so
    # `terraform apply` doesn't block on the Pi being online.
    command = "cd ${path.root}/../ansible && ansible-playbook -i inventory.ini --private-key '${pathexpand(trimsuffix(var.ssh_public_key_path, ".pub"))}' --limit cloud site.yml"
  }
}

output "cloud_ip" {
  description = "The active cloud's public IPv4 (mother-001)"
  value       = local.cloud_ip
}
