#!/bin/bash

set -e

echo "🔧 Updating package list..."
sudo apt update

echo "🐍 Installing Python 3 and pip..."
sudo apt install -y python3 python3-pip python3-venv

echo "🧰 Installing essential utilities..."
sudo apt install -y ca-certificates curl gnupg lsb-release software-properties-common

# Check if Docker is already installed
if ! command -v docker &> /dev/null; then
  echo "🐳 Docker not found. Installing Docker..."

  echo "🔐 Adding Docker’s official GPG key..."
  sudo mkdir -p /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

  echo "📦 Setting up Docker repository..."
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

  echo "🔄 Updating package index again..."
  sudo apt update

  echo "🚀 Installing Docker components..."
  sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

  echo "🔓 Adding current user to docker group..."
  sudo usermod -aG docker "$USER"

  echo "⚠️ You must log out and log back in for the group change to take effect."
else
  echo "✅ Docker is already installed."
fi

echo "🧪 Verifying installations..."
python3 --version
pip3 --version
docker --version
docker compose version || docker-compose --version

echo "🎉 Environment setup complete!"
