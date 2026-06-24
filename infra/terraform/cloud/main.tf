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

resource "hcloud_network" "vpn_network" {
  name     = "free-droid-vpn"
  ip_range = "10.0.0.0/16"
}

resource "hcloud_network_subnet" "vpn_subnet" {
  network_id   = hcloud_network.vpn_network.id
  type         = "cloud"
  network_zone = "eu-central"
  ip_range     = "10.0.0.0/24"
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
  public_key = file(var.ssh_public_key_path)
}

resource "hcloud_server" "mother" {
  name         = "mother-001"
  server_type  = "gex44"
  image        = "ubuntu-24.04"
  location     = "nbg1"
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
  ip         = "10.0.0.1"
  depends_on = [hcloud_network_subnet.vpn_subnet]
}

resource "local_file" "ansible_inventory" {
  content  = <<-EOT
  [cloud]
  mother-001 ansible_host=${hcloud_server.mother.ipv4_address} ansible_user=root vpn_ip=10.0.0.1

  [edge]
  # Update 'ansible_host' with the actual LAN IP of the Pi if it's not reachable via its mDNS hostname
  child-001 ansible_host=child-001.local ansible_user=pi vpn_ip=10.0.0.2
  EOT
  filename = "${path.root}/../ansible/inventory.ini"
}

resource "null_resource" "trigger_ansible" {
  depends_on = [local_file.ansible_inventory, hcloud_server_network.mother_network]

  provisioner "remote-exec" {
    inline = ["echo 'SSH is ready on mother-001!'"]

    connection {
      type        = "ssh"
      user        = "root"
      private_key = file(replace(var.ssh_public_key_path, ".pub", ""))
      host        = hcloud_server.mother.ipv4_address
    }
  }

  provisioner "local-exec" {
    # This triggers the master playbook for the entire flow
    command = "cd ${path.root}/../ansible && ansible-playbook -i inventory.ini site.yml"
  }
}