#!/bin/bash
# Install script for BME280 service
# Run this on the Pi: chmod +x install_service.sh && ./install_service.sh

echo "Installing BME280 service..."

# Copy service file
sudo cp bme280.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service to start on boot
sudo systemctl enable bme280

# Start the service now
sudo systemctl start bme280

echo ""
echo "Done! Service installed and started."
echo ""
echo "Useful commands:"
echo "  Check status:  sudo systemctl status bme280"
echo "  View logs:     journalctl -u bme280 -f"
echo "  Stop:          sudo systemctl stop bme280"
echo "  Restart:       sudo systemctl restart bme280"
