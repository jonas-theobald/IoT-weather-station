"""
Starts both the data collector and web server in one process.
Used by the systemd service for auto-start on boot.
"""

import threading
import time
import board
from adafruit_bme280 import basic as adafruit_bme280
from database import save_reading, init_db
from web_server import app

INTERVAL_SECONDS = 10


def create_sensor(address=0x77):
    """Initialize the BME280 sensor."""
    i2c = board.I2C()
    try:
        sensor = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=address)
    except ValueError:
        alt_address = 0x76 if address == 0x77 else 0x77
        sensor = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=alt_address)
    return sensor


def collector_loop():
    """Background thread that collects sensor data."""
    print("Starting sensor collector...")
    sensor = create_sensor()

    while True:
        try:
            temperature = sensor.temperature
            humidity = sensor.relative_humidity
            pressure = sensor.pressure
            save_reading(temperature, humidity, pressure)
            print(f"Saved: {temperature:.1f}°C, {humidity:.1f}%, {pressure:.1f}hPa")
        except Exception as e:
            print(f"Sensor read error: {e}")
        time.sleep(INTERVAL_SECONDS)


def main():
    init_db()

    # Start collector in background thread
    collector_thread = threading.Thread(target=collector_loop, daemon=True)
    collector_thread.start()

    # Start web server (blocks)
    print("Starting web server on port 5000...")
    app.run(host='0.0.0.0', port=5000)


if __name__ == "__main__":
    main()
