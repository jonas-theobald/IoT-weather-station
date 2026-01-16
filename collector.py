"""
Data collector - reads BME280 sensor and saves to database.
Run this alongside the web server.
"""

import time
import board
from adafruit_bme280 import basic as adafruit_bme280
from database import save_reading

INTERVAL_SECONDS = 30  # How often to read the sensor


def create_sensor(address=0x76):
    """Initialize the BME280 sensor."""
    i2c = board.I2C()
    try:
        sensor = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=address)
    except ValueError:
        print(f"Address 0x{address:02x} not found, trying alternate...")
        alt_address = 0x77 if address == 0x76 else 0x76
        sensor = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=alt_address)
    return sensor


def main():
    print("Initializing BME280 sensor...")
    sensor = create_sensor(address=0x77)  # Your sensor is at 0x77
    print(f"Sensor initialized. Collecting data every {INTERVAL_SECONDS} seconds.")
    print("Press Ctrl+C to stop.\n")

    try:
        while True:
            temperature = sensor.temperature
            humidity = sensor.relative_humidity
            pressure = sensor.pressure

            save_reading(temperature, humidity, pressure)
            print(f"Saved: {temperature:.1f}°C, {humidity:.1f}%, {pressure:.1f}hPa")

            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
