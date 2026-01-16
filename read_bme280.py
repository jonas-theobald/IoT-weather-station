"""
BME280 Environmental Sensor Reader
Reads temperature, humidity, and pressure from a BME280 sensor via I2C.
"""

import time
import board
from adafruit_bme280 import basic as adafruit_bme280


def create_sensor(address=0x76):
    """Initialize the BME280 sensor."""
    i2c = board.I2C()
    sensor = adafruit_bme280.Adafruit_BME280_I2C(i2c, address=address)
    # Set sea level pressure for altitude calculation (adjust for your location)
    sensor.sea_level_pressure = 1013.25
    return sensor


def read_sensor(sensor):
    """Read all values from the sensor."""
    return {
        "temperature_c": sensor.temperature,
        "humidity_percent": sensor.relative_humidity,
        "pressure_hpa": sensor.pressure,
        "altitude_m": sensor.altitude,
    }


def print_readings(readings):
    """Display sensor readings in a formatted way."""
    print(f"Temperature: {readings['temperature_c']:.1f} °C")
    print(f"Humidity:    {readings['humidity_percent']:.1f} %")
    print(f"Pressure:    {readings['pressure_hpa']:.1f} hPa")
    print(f"Altitude:    {readings['altitude_m']:.2f} m")
    print("-" * 30)


def main():
    """Main loop - read and display sensor data."""
    print("Initializing BME280 sensor...")

    # Try address 0x76 first, fall back to 0x77
    try:
        sensor = create_sensor(address=0x76)
    except ValueError:
        print("Address 0x76 not found, trying 0x77...")
        sensor = create_sensor(address=0x77)

    print("Sensor initialized! Reading data...\n")

    try:
        while True:
            readings = read_sensor(sensor)
            print_readings(readings)
            time.sleep(2)  # Read every 2 seconds
    except KeyboardInterrupt:
        print("\nStopped by user.")


if __name__ == "__main__":
    main()
