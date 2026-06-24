# free-droid project

## Context

Build a fully automated "Zero-Touch" infrastructure for a sovereign AI robot (free-droid/SZABI).

Goal: Deploy a Hetzner GPU server and configure a Raspberry Pi 5 without any manual SSH intervention after the initial rpi-imager setup.

## Technical Requirements for the Code Generation

Network: internal VPN range: 10.9.0.0/24. `Hetzner instance` IP: 10.9.0.1, `Pi 5` IP: 10.9.0.2.

Provider: hcloud/hcloud.

### Terraform (Hetzner Provisioning)

* Use hcloud provider to create a gex44 instance in nbg1.
* Create a private network and a firewall allowing 22/tcp and 51820/udp.
* Use a local-exec provisioner to trigger the Ansible playbook as soon as the server is reachable.
* Output the IP address into an Ansible-compatible inventory.ini.

### Ansible - WireGuard (The "Zero-Touch" Key Exchange)

Role: wireguard_setup

* Generate WireGuard private/public keys on the fly on both hosts using the community.general.wireguard module or wg genkey.
* Crucial: Use Ansible "facts" to exchange public keys between the [cloud] and [edge] groups dynamically during the run (use set_fact and hostvars).
* Ensure wg0 interface starts automatically on boot via systemd-networkd or wg-quick@wg0.

### Ansible - AI Stack (Ollama Deployment)

Role: ai_stack

On [cloud]: Install Docker, NVIDIA Container Toolkit, and start an Ollama container. Automatically run ollama pull llama3.1:70b.

On [edge]: Install Ollama natively for Linux (arm64). Automatically run ollama pull llama3.1:8b.

Configure Ollama to listen on all interfaces (OLLAMA_HOST=0.0.0.0) but only within the VPN subnet (10.9.0.0/24).

### Ansible - Robotics (ROS 2 & Python)

Role: ros2_setup

Install ros-humble-ros-base or ros-jazzy-ros-base depending on Ubuntu version.

Setup a Python virtual environment for the robot's logic.

Install dependencies: pip install ollama rclpy opencv-python-headless.

## Orchestration

Create a master site.yml that handles the entire flow.

Ensure all sensitive data (like VPN keys) are handled via variables, assuming they could be stored in ansible-vault.

## Coding standard

Use modern, best-practice and secure coding solutions (systemd units for VPN, Ansible hybrid inventory).
Keep the code clean and commented, especially with regard to WireGuard key management (use placeholders for secrets).
