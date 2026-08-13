terraform {
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.60"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
    }
  }
}

# Hetzner private network. Kept on a DISTINCT range from the WireGuard overlay
# (10.0.0.0/24, per spec) so the cloud host never has the same IP on two
# interfaces. The edge (RPi) reaches the cloud over WireGuard, not this network.
resource "hcloud_network" "vpn_network" {
  name     = "free-droid-vpn"
  ip_range = "10.1.0.0/16"
}

resource "hcloud_network_subnet" "vpn_subnet" {
  network_id   = hcloud_network.vpn_network.id
  type         = "cloud"
  network_zone = "eu-central"
  ip_range     = "10.1.0.0/24"
}

resource "hcloud_firewall" "free_droid_fw" {
  name = "free-droid-firewall"
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = ["0.0.0.0/0", "::/0"]
  }
  rule {
    direction  = "in"
    protocol   = "udp"
    port       = "51820"
    source_ips = ["0.0.0.0/0", "::/0"]
  }
}

resource "hcloud_ssh_key" "default" {
  name       = "free-droid-key"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

# The cloud backend is intentionally disposable: `terraform destroy` tears it
# (and its network/firewall) down to save cost while the droid is offline. The
# RPi 5 edge is NOT managed here (Ansible-only), so destroy never touches it.
# Note: recreating this server mints a new WireGuard key, so re-run the wireguard
# role on the Pi (or update its wg0.conf) to restore the tunnel.
resource "hcloud_server" "mother" {
  name         = "mother-001"
  server_type  = var.cloud_server_type # ARM64 Ampere (CAX31/41), CPU-only
  image        = "ubuntu-24.04"        # served as arm64 for CAX server types
  location     = var.cloud_location
  ssh_keys     = [hcloud_ssh_key.default.id]
  firewall_ids = [hcloud_firewall.free_droid_fw.id]
  public_net {
    ipv4_enabled = true
    ipv6_enabled = true
  }
}

resource "hcloud_server_network" "mother_network" {
  server_id  = hcloud_server.mother.id
  network_id = hcloud_network.vpn_network.id
  # .1 is reserved by Hetzner as the network gateway (ip_not_available) — use .2.
  # This private-network IP is vestigial anyway: the edge reaches the cloud over
  # WireGuard (10.0.0.1), and Ollama binds to the wg0 IP, not this address.
  ip         = "10.1.0.2"
  depends_on = [hcloud_network_subnet.vpn_subnet]
}
