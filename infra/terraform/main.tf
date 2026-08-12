terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.60"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "hcloud_token" {
  sensitive = true
}

provider "hcloud" {
  token = var.hcloud_token
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

module "cloud" {
  source              = "./cloud"
  ssh_public_key_path = var.ssh_public_key_path
  cloud_server_type   = var.cloud_server_type
  cloud_location      = var.cloud_location
  edge_ansible_host   = var.edge_ansible_host
  edge_ansible_user   = var.edge_ansible_user
  edge_ssh_key        = var.edge_ssh_key
}
