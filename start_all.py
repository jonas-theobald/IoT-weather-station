"""
Starts both the data collector and web server in one process.
Used by the systemd service for auto-start on boot.
"""

import datetime
import os
import threading
import time
import board
from adafruit_bme280 import basic as adafruit_bme280
from database import save_reading, init_db
from web_server import app

from model.entity_builder import StationConfig, build_weather_entity
from reliability.pending_store import PendingEntityStore
from routing.transport_router import RouterMode, TransportRouter
from transport.grpc_wifi import GrpcWifiTransport

INTERVAL_SECONDS = 10

# Hydris publishing is entirely independent of local logging above -- see
# docs/HYDRIS_INTEGRATION.md Section 2. If HYDRIS_SERVER is unset, this
# reduces to a router with no transports, and send() below is a no-op.
HYDRIS_SERVER = os.environ.get("HYDRIS_SERVER")
HYDRIS_ENTITY_ID = os.environ.get("HYDRIS_ENTITY_ID", "pizero-01.weather")
HYDRIS_LABEL = os.environ.get("HYDRIS_LABEL", "Pi Zero Weather Station")
HYDRIS_LAT = float(os.environ.get("HYDRIS_LAT", "0"))
HYDRIS_LON = float(os.environ.get("HYDRIS_LON", "0"))
HYDRIS_ALT = float(os.environ.get("HYDRIS_ALT", "0"))


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

    station = StationConfig(
        entity_id=HYDRIS_ENTITY_ID, label=HYDRIS_LABEL,
        lat=HYDRIS_LAT, lon=HYDRIS_LON, alt=HYDRIS_ALT,
    )
    transports = [GrpcWifiTransport(HYDRIS_SERVER)] if HYDRIS_SERVER else []
    router = TransportRouter(transports, mode=RouterMode.FAILOVER)
    pending = PendingEntityStore()

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
            continue

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
                # Must never take down local logging above -- see
                # docs/HYDRIS_INTEGRATION.md Section 2.
                print(f"Hydris publish error (continuing): {e}")

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
