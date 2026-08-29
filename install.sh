#!/bin/bash
#
# Pi Zero BME280 Environment Monitor - Installation Script
# https://github.com/jonas-theobald/IoT-weather-station
#

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}"
echo "╔═══════════════════════════════════════════════════════════╗"
echo "║       Pi Zero BME280 Environment Monitor Installer        ║"
echo "╚═══════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check if running on Raspberry Pi
if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo -e "${YELLOW}Warning: This doesn't appear to be a Raspberry Pi.${NC}"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check for I2C
echo -e "${YELLOW}[1/6]${NC} Checking I2C configuration..."
if ! ls /dev/i2c-* 1>/dev/null 2>&1; then
    echo -e "${RED}Error: I2C is not enabled.${NC}"
    echo "Please run: sudo raspi-config"
    echo "Navigate to: Interface Options → I2C → Enable"
    echo "Then reboot and run this script again."
    exit 1
fi
echo -e "${GREEN}✓${NC} I2C is enabled"

# Check for sensor
echo -e "${YELLOW}[2/6]${NC} Checking for BME280 sensor..."
if command -v i2cdetect &>/dev/null; then
    I2C_OUTPUT=$(sudo i2cdetect -y 1 2>/dev/null || true)
    if echo "$I2C_OUTPUT" | grep -qE "76|77"; then
        echo -e "${GREEN}✓${NC} BME280 sensor detected"
    else
        echo -e "${RED}Warning: BME280 sensor not detected.${NC}"
        echo "Please check your wiring:"
        echo "  VIN → Pin 1 (3.3V)"
        echo "  GND → Pin 6 (GND)"
        echo "  SCL → Pin 5 (GPIO 3)"
        echo "  SDA → Pin 3 (GPIO 2)"
        read -p "Continue anyway? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            exit 1
        fi
    fi
fi

# Install system dependencies
echo -e "${YELLOW}[3/6]${NC} Installing system dependencies..."
sudo apt-get update -qq
# python3-gi/python3-dbus: bluezero (BLE transport) needs the distro's
# PyGObject/dbus bindings -- building them inside a venv fails without
# the gi development headers.
sudo apt-get install -y -qq python3-pip python3-venv i2c-tools python3-gi python3-dbus

# Create virtual environment
echo -e "${YELLOW}[4/6]${NC} Setting up Python virtual environment..."
INSTALL_DIR="$HOME/bme280"
VENV_DIR="$HOME/bme280-env"

# Copy files to install directory
mkdir -p "$INSTALL_DIR"
cp -r ./*.py "$INSTALL_DIR/" 2>/dev/null || true
cp -r ./requirements.txt "$INSTALL_DIR/" 2>/dev/null || true
cp -r ./bme280.service "$INSTALL_DIR/" 2>/dev/null || true
# Python package subdirectories (e.g. model/, transport/, routing/,
# reliability/ for the Hydris client) -- a flat *.py glob misses these.
for pkg_dir in ./*/; do
    pkg_dir="${pkg_dir%/}"
    if [ -f "$pkg_dir/__init__.py" ]; then
        cp -r "$pkg_dir" "$INSTALL_DIR/"
    fi
done

# Create venv if it doesn't exist
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# Install Python dependencies
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r "$INSTALL_DIR/requirements.txt"
# Expose the system gi/dbus bindings to the venv, then add bluezero on
# top without its deps (they'd otherwise try to build PyGObject).
SITE_PACKAGES=$(python -c "import site; print(site.getsitepackages()[0])")
echo /usr/lib/python3/dist-packages > "$SITE_PACKAGES/system-gi.pth"
pip install --quiet --no-deps bluezero
deactivate

# Update service file with correct paths
echo -e "${YELLOW}[5/6]${NC} Configuring systemd service..."
SERVICE_FILE="$INSTALL_DIR/bme280.service"
sed -i "s|^User=.*|User=$USER|g" "$SERVICE_FILE"
sed -i "s|WorkingDirectory=.*|WorkingDirectory=$INSTALL_DIR|g" "$SERVICE_FILE"
sed -i "s|ExecStart=.*|ExecStart=$VENV_DIR/bin/python $INSTALL_DIR/start_all.py|g" "$SERVICE_FILE"

# Install service
sudo cp "$SERVICE_FILE" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bme280

# Start service
echo -e "${YELLOW}[6/6]${NC} Starting service..."
sudo systemctl start bme280

# Wait for service to start
sleep 3

# Check status
if sudo systemctl is-active --quiet bme280; then
    echo -e "${GREEN}"
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║              Installation Complete!                       ║"
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
    echo ""
    echo "Dashboard URL:"
    echo -e "  ${GREEN}http://$(hostname).local:5000${NC}"
    IP_ADDR=$(hostname -I | awk '{print $1}')
    echo -e "  ${GREEN}http://$IP_ADDR:5000${NC}"
    echo ""
    echo "Useful commands:"
    echo "  sudo systemctl status bme280    # Check status"
    echo "  journalctl -u bme280 -f         # View logs"
    echo "  sudo systemctl restart bme280   # Restart service"
    echo ""
else
    echo -e "${RED}Error: Service failed to start.${NC}"
    echo "Check logs with: journalctl -u bme280 -e"
    exit 1
fi
