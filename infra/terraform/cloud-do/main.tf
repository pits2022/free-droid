# cloud-main: DigitalOcean GPU droplet — a demó elsődleges felhője.
#
# MIÉRT EZ A FŐ ÚT (a Teremtő döntése, 2026-08-13):
#   1. A Hetzneren folyamatos a VPS-hiány — egy demó napján nem lehet arra hagyatkozni,
#      hogy épp van szabad CAX31.
#   2. A 2026-07-29-i mérés (H200-tests.md) szerint a GPU-s felhő 8B-je 144 tok/s, a
#      CPU-s CAX31 3,6-5 tok/s-jával szemben. A hang-pipeline ~6,8 tok/s-ot igényel:
#      a CPU-s út ALATTA van, a GPU 21x ráhagyással fölötte.
#   3. A GPU-t óradíjban, a demó néhány órájára vesszük ki; a tartósabb, demó UTÁNI
#      működésre a Hetzner-ág marad (`-var cloud_provider=hetzner`).
#
# RÉGIÓ-KÉNYSZER, mérve 2026-08-13-án: az Ada-kártyák KIZÁRÓLAG `tor1`-ben vannak
# (a `gpu-4000adax1-20gb` és a `gpu-6000adax1-48gb` is), és EGYETLEN európai DO
# GPU-régió sem létezik — a legközelebbi bármi `nyc2`/`atl1` (H100/H200, 6x drágább).
# Ez ~139 ms RTT Magyarországról, szemben az AMS3 44,7 ms-ával. A H200-mérés szerint
# a tunnel 90 ms-os RTT-nél ~0,2 s-ot ad a válaszhoz, tehát tor1-ből ~0,3 s. Egy 16
# szavas válasz kimondása ~6,4 s, tehát ez elnyelődik — de tudni kell róla.

terraform {
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
}

# A kulcs ADAT-FORRÁS, nem erőforrás — két okból, és a második a fontosabb:
#
# 1. MÉRVE 2026-08-13-án: a `digitalocean_ssh_key` create 422-t ad
#    ("SSH Key is already in use on your account"), mert a kulcs a 2026-07-29-i
#    H200-mérés óta regisztrálva van a fiókon (ID 58084361).
# 2. A KULCS FIÓK-SZINTŰ erőforrás, ami TÚLÉLI az eldobható felhőt. Ha Terraform
#    kezelné, akkor minden `terraform destroy` TÖRÖLNÉ a fiókról — pont az a művelet,
#    amit a teszt végén szándékosan lefuttatunk. A felhő eldobhatósága a projekt
#    lopás-válasza (CLAUDE.md), tehát a destroy legyen bátran hívható: ne vigyen el
#    semmit, ami nem a felhő.
#
# EGYSZERI ELŐFELTÉTEL friss fiókon (a hibaüzenet is ezt mondja majd):
#   doctl compute ssh-key import free-droid-mother --public-key-file ~/.ssh/free-droid-mother.pub
data "digitalocean_ssh_key" "default" {
  name = "free-droid-mother"

  lifecycle {
    postcondition {
      condition     = self.fingerprint != ""
      error_message = "A 'free-droid-mother' kulcs nincs a DO-fiókon. Egyszeri regisztráció: doctl compute ssh-key import free-droid-mother --public-key-file ~/.ssh/free-droid-mother.pub"
    }
  }
}

# A droplet neve SZÁNDÉKOSAN ugyanaz, mint a Hetzner-ágon (`mother-001`): az Ansible
# inventory, a WireGuard-konfig és a role-ok erre a névre hivatkoznak, tehát a
# szolgáltató-váltás ne szivárogjon át a konfigba.
resource "digitalocean_droplet" "mother" {
  name   = "mother-001"
  region = var.do_region
  size   = var.do_gpu_size

  # NVIDIA AI/ML Ready Image. A slug H100-at mond, de ez a GENERIKUS egy-GPU-s
  # NVIDIA image (a DO minden single-GPU dropletjéhez ezt adja) — a lényeg, hogy az
  # NVIDIA-DRIVER előre telepítve van. Sima `ubuntu-24-04-x64`-en a driver hiányozna,
  # és az `ai_stack` natív Ollamája CPU-ra esne vissza NÉMÁN: a kártya megvan, a
  # sebesség nincs. Pont ez volt a 2026-07-29-i mérés fő tanulsága.
  image = var.do_image

  ssh_keys   = [data.digitalocean_ssh_key.default.fingerprint]
  monitoring = true

  # A WireGuard-kulcs a szerver ELSŐ indulásakor keletkezik (wireguard_setup role),
  # tehát a droplet újrateremtése ÚJ kulcsot jelent -> a Pi-n újra kell futtatni a
  # role-t. Ez tudatos: a felhő eldobható, és ez a tulajdonság a lopás-válasz is.
  tags = ["free-droid", "cloud-main"]
}

# Ugyanaz a két port, mint a Hetzner-ágon: SSH + WireGuard. Az Ollama 11434-e
# SZÁNDÉKOSAN nincs nyitva — a felhő inferencia-végpont csak a VPN-en érhető el, és
# ezt az `ai_stack` role egy külön őrrel is ellenőrzi (wildcard-kötés tilos).
resource "digitalocean_firewall" "free_droid_fw" {
  name        = "free-droid-fw"
  droplet_ids = [digitalocean_droplet.mother.id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  inbound_rule {
    protocol         = "udp"
    port_range       = "51820"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  # A kimenő forgalom nyitva: az `ai_stack` a telepítőt és a modellt tölti le.
  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
