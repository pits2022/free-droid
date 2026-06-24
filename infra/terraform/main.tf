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
  description = "Path to the public SSH key used to access the cloud instance."
  type        = string
  default     = "~/.ssh/id_rsa.pub"
}

variable "cloud_server_type" {
  description = "Hetzner Cloud server type for the cloud backend (ARM64, CPU-only). CAX31 default; CAX41 for more headroom."
  type        = string
  default     = "cax31"
}

module "cloud" {
  source              = "./cloud"
  ssh_public_key_path = var.ssh_public_key_path
  cloud_server_type   = var.cloud_server_type
}
