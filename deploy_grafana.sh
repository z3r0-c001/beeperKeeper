#!/bin/bash
# BEEPER KEEPER 10000 - Grafana Stack Deployment Script
# Deploys complete monitoring stack to Raspberry Pi

set -e

# Configuration - Update these for your environment
PI_USER="${PI_USER:-pi}"
PI_HOST="${PI_HOST:-raspberrypi.local}"
PI_DIR="${PI_DIR:-/home/pi/beeperKeeper}"

echo "=== BEEPER KEEPER 10000 - Grafana Deployment ==="
echo

# Check if Docker is installed on Pi
echo "[1/6] Checking Docker installation on Pi..."
if ssh ${PI_USER}@${PI_HOST} "command -v docker &> /dev/null"; then
    echo "✓ Docker is installed"
else
    echo "✗ Docker not found. Installing..."
    ssh ${PI_USER}@${PI_HOST} "curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker ${PI_USER}"
    echo "✓ Docker installed. Please log out and back in, then run this script again."
    exit 0
fi

# Check if Docker Compose is installed
echo "[2/6] Checking Docker Compose installation..."
if ssh ${PI_USER}@${PI_HOST} "command -v docker-compose &> /dev/null"; then
    echo "✓ Docker Compose is installed"
else
    echo "✗ Docker Compose not found. Installing..."
    ssh ${PI_USER}@${PI_HOST} "sudo apt-get update && sudo apt-get install -y docker-compose"
    echo "✓ Docker Compose installed"
fi

# Create project directory on Pi
echo "[3/6] Creating project directory..."
ssh ${PI_USER}@${PI_HOST} "mkdir -p ${PI_DIR}"
echo "✓ Directory created: ${PI_DIR}"

# Copy all Grafana stack files
echo "[4/6] Copying Grafana stack files..."
scp -r docker-compose.yml mosquitto telegraf grafana ${PI_USER}@${PI_HOST}:${PI_DIR}/
echo "✓ Files copied"

# Copy MQTT publisher script
echo "[5/6] Copying MQTT publisher..."
scp production_files/mqtt_publisher.py config.example.py ${PI_USER}@${PI_HOST}:${PI_DIR}/
echo "✓ MQTT publisher copied"

# Start the Docker stack
echo "[6/6] Starting Grafana stack..."
ssh ${PI_USER}@${PI_HOST} "cd ${PI_DIR} && docker-compose up -d"
echo "✓ Grafana stack started"

echo
echo "=== Deployment Complete! ==="
echo
echo "Services running:"
echo "  - Mosquitto MQTT:  mqtt://${PI_HOST}:1883"
echo "  - InfluxDB:        http://${PI_HOST}:8086"
echo "  - Grafana:         http://${PI_HOST}:3000"
echo
echo "Grafana Login:"
echo "  Username: admin"
echo "  Password: beeperkeeper"
echo
echo "Next steps:"
echo "  1. Configure config.py on the Pi"
echo "  2. Start MQTT publisher: python3 ${PI_DIR}/mqtt_publisher.py"
echo "  3. Access Grafana at http://${PI_HOST}:3000"
echo
