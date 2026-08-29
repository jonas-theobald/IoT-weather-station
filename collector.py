"""
Data collector - reads BME280 sensor and saves to database.
Run this alongside the web server.

Note: start_all.py is the script actually run by the systemd service
(bme280.service); this standalone script mirrors the same Hydris
publishing so it stays usable on its own for manual testing.
"""

import datetime
import os
import time
import board
from adafruit_bme280 import basic as adafruit_bme280
from database import save_reading

from model.entity_builder import StationConfig, build_weather_entity
from reliability.pending_store import PendingEntityStore
from routing.transport_router import RouterMode, TransportRouter
from transport.ble_gatt import BleGattTransport
from transport.grpc_wifi import GrpcWifiTransport

INTERVAL_SECONDS = int(os.environ.get("HYDRIS_INTERVAL", "30"))  # How often to read the sensor

HYDRIS_SERVER = os.environ.get("HYDRIS_SERVER")
HYDRIS_BLE = os.environ.get("HYDRIS_BLE") == "1"
HYDRIS_BLE_NAME = os.environ.get("HYDRIS_BLE_NAME", "hydris-weather")
HYDRIS_ENTITY_ID = os.environ.get("HYDRIS_ENTITY_ID", "pizero-01.weather")
HYDRIS_LABEL = os.environ.get("HYDRIS_LABEL", "Pi Zero Weather Station")
# No HYDRIS_LAT/LON/ALT: position is set by the operator in Hydris.


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

    station = StationConfig(entity_id=HYDRIS_ENTITY_ID, label=HYDRIS_LABEL)
    transports = []
    if HYDRIS_SERVER:
        transports.append(GrpcWifiTransport(HYDRIS_SERVER))
    if HYDRIS_BLE:
        transports.append(BleGattTransport(station, device_name=HYDRIS_BLE_NAME))
    # BROADCAST: BLE isn't an alternative route to the same hub, it's a
    # different consumer (a nearby Hydris BLE central) -- feed both.
    router = TransportRouter(transports, mode=RouterMode.BROADCAST)
    pending = PendingEntityStore()

    try:
        while True:
            temperature = sensor.temperature
            humidity = sensor.relative_humidity
            pressure = sensor.pressure

            save_reading(temperature, humidity, pressure)
            print(f"Saved: {temperature:.1f}°C, {humidity:.1f}%, {pressure:.1f}hPa")

            if transports:
                try:
                    reading = {
                        "temperature_c": temperature,
                        "humidity_percent": humidity,
                        "pressure_hpa": pressure,
                    }
                    measured_at = datetime.datetime.now(datetime.timezone.utc)
                    entity = pending.pending() or build_weather_entity(reading, station, measured_at)
                    results = router.send(entity)
                    if any(r.ok for r in results):
                        pending.clear()
                    else:
                        pending.stash(entity)
                        print(f"Hydris push failed (continuing): {results}")
                except Exception as e:
                    print(f"Hydris publish error (continuing): {e}")

            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
