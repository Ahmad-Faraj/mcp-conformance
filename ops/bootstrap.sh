#!/usr/bin/env bash
# Prepare a fresh Ubuntu or Amazon Linux host to run the census.
#
#   bash ops/bootstrap.sh
#
# Installs Docker and Python, pulls the base images, and prints the digests that
# every result row will carry.
set -euo pipefail

if command -v apt-get >/dev/null; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker.io python3 python3-pip git
else
  sudo dnf install -y -q docker python3 python3-pip git
fi

sudo systemctl enable --now docker
sudo usermod -aG docker "$USER" || true

NODE_IMAGE=node:22-slim
UV_IMAGE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim

sudo docker pull "$NODE_IMAGE"
sudo docker pull "$UV_IMAGE"

echo "image digests, recorded with every row:"
for image in "$NODE_IMAGE" "$UV_IMAGE"; do
  sudo docker image inspect "$image" --format '{{index .RepoDigests 0}}'
done

echo
echo "docker group membership needs a new login. Run 'newgrp docker' or log out and back in."
echo "Then: bash ops/run_census.sh smoke"
