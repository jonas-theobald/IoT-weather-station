# Pi Zero BME280 Environment Monitor

A lightweight IoT environmental monitoring system for Raspberry Pi Zero. Collects temperature, humidity, and barometric pressure data from a BME280 sensor and displays it on a real-time web dashboard.

![Dashboard Preview](docs/dashboard-preview.png)

## Features

- **Real-time monitoring** - Temperature, humidity, and pressure readings every 10 seconds
- **Interactive charts** - Drag-to-zoom, scroll zoom, and pan functionality
- **Time range selection** - View data from 1 hour to 30 days
- **Persistent storage** - SQLite database survives reboots
- **Auto-start service** - Runs automatically on boot via systemd
- **Mobile-friendly** - Responsive design works on phones and tablets
- **Low power** - Runs on Pi Zero 2 W with ~150mA draw

## Hardware Requirements

| Component | Notes |
|-----------|-------|
| Raspberry Pi Zero W/WH/2W/2WH | Any WiFi-enabled Pi Zero |
| BME280 sensor module | I2C version (4-pin) |
| MicroSD card | 8GB+ recommended |
| Female-to-female jumper wires | 4 wires needed |
| 5V power supply | 2A recommended |

## Wiring Diagram

```
BME280          Raspberry Pi Zero
┌──────┐        ┌─────────────────┐
│ VIN  │────────│ Pin 1  (3.3V)   │
│ GND  │────────│ Pin 6  (GND)    │
│ SCL  │────────│ Pin 5  (GPIO 3) │
│ SDA  │────────│ Pin 3  (GPIO 2) │
└──────┘        └─────────────────┘
```

## Quick Start

### 1. Prepare the SD Card

1. Download [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
2. Flash **Raspberry Pi OS Lite (32-bit)**
3. Configure WiFi, SSH, and hostname in the settings
4. Insert SD card into Pi and boot

### 2. Enable I2C

```bash
sudo raspi-config
# Interface Options → I2C → Enable
sudo reboot
```

### 3. Install the Project

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/piZero_BME280.git
cd piZero_BME280

# Run the install script
chmod +x install.sh
./install.sh
```

### 4. Access the Dashboard

Open in your browser:
```
http://pizero.local:5000
```

Or use the Pi's IP address: `http://<PI_IP>:5000`

## Manual Installation

If you prefer to install manually:

```bash
# Create virtual environment
python3 -m venv ~/bme280-env
source ~/bme280-env/bin/activate

# Install dependencies
pip install -r requirements.txt

# Verify sensor connection
sudo i2cdetect -y 1
# Should show 76 or 77

# Test the sensor
python read_bme280.py

# Install and start the service
sudo cp bme280.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bme280
sudo systemctl start bme280
```

## Project Structure

```
piZero_BME280/
├── start_all.py        # Main entry point (collector + web server)
├── web_server.py       # Flask web server with dashboard
├── database.py         # SQLite database operations
├── collector.py        # Standalone data collector
├── read_bme280.py      # Simple sensor test script
├── bme280.service      # Systemd service definition
├── install.sh          # Automated installation script
├── requirements.txt    # Python dependencies
└── README.md           # This file
```

## Configuration

### Change Sensor Reading Interval

Edit `start_all.py`:
```python
INTERVAL_SECONDS = 10  # Change to desired interval
```

### Change Web Dashboard Refresh Rate

Edit `web_server.py`, find this line:
```javascript
setInterval(updateData, 10000);  // milliseconds
```

### Change Sensor I2C Address

Most BME280 modules use `0x76` or `0x77`. The code auto-detects, but you can force an address in `start_all.py`:
```python
sensor = create_sensor(address=0x77)
```

## Service Management

```bash
# Check status
sudo systemctl status bme280

# View logs
journalctl -u bme280 -f

# Restart service
sudo systemctl restart bme280

# Stop service
sudo systemctl stop bme280

# Disable auto-start
sudo systemctl disable bme280
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Web dashboard |
| `GET /api/readings?hours=24` | JSON data for the last N hours |

### Example API Response

```json
{
  "latest": {
    "timestamp": "2025-01-16T18:30:00",
    "temperature": 23.5,
    "humidity": 45.2,
    "pressure": 1013.25
  },
  "history": [
    {"timestamp": "...", "temperature": 23.4, "humidity": 45.0, "pressure": 1013.20},
    ...
  ]
}
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `i2cdetect` shows nothing | Check wiring, ensure I2C is enabled |
| Address is `0x77` not `0x76` | Code auto-detects; no action needed |
| Permission denied | Run: `sudo usermod -aG i2c $USER` then reboot |
| Service won't start | Check logs: `journalctl -u bme280 -e` |
| Dashboard not loading | Verify service is running: `systemctl status bme280` |
| Can't access from network | Check firewall: `sudo ufw allow 5000` |

## Storage Requirements

- Each reading: ~50 bytes
- Per day (10s interval): ~432 KB
- Per year: ~158 MB
- 16GB SD card: **~100 years** of data

## Power Consumption

| Component | Current |
|-----------|---------|
| Pi Zero 2 W (idle + WiFi) | ~100-150 mA |
| BME280 sensor | ~1 mA |
| **Total** | ~150 mA |

With a 20,000 mAh battery pack: **~4-5 days** runtime

## License

MIT License - see [LICENSE](LICENSE) file

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## Acknowledgments

- [Adafruit CircuitPython BME280](https://github.com/adafruit/Adafruit_CircuitPython_BME280) - Sensor library
- [Chart.js](https://www.chartjs.org/) - Charting library
- [chartjs-plugin-zoom](https://www.chartjs.org/chartjs-plugin-zoom/) - Zoom functionality
