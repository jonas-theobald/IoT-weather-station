"""ESS wire-format tests: these bytes are what the Hydris plugin decodes,
so every value here is mirrored in the hub-side plugin's tests."""

import datetime
import json
import unittest

from model.entity_builder import StationConfig, build_weather_entity
from transport.ble_gatt import (
    HUMIDITY_CHAR_UUID,
    PRESSURE_CHAR_UUID,
    TEMPERATURE_CHAR_UUID,
    encode_from_entity,
    encode_humidity,
    encode_pressure,
    encode_temperature,
    station_metadata,
)

STATION = StationConfig(entity_id="pizero-01.weather", label="Pi Zero Weather Station")


class EssEncodingTest(unittest.TestCase):
    def test_temperature_scaled_sint16_le(self):
        self.assertEqual(encode_temperature(23.5), (2350).to_bytes(2, "little"))
        self.assertEqual(encode_temperature(-40.0), (-4000).to_bytes(2, "little", signed=True))
        self.assertEqual(encode_temperature(0.004), b"\x00\x00")  # rounds, not truncates

    def test_humidity_scaled_uint16_le(self):
        self.assertEqual(encode_humidity(45.2), (4520).to_bytes(2, "little"))
        self.assertEqual(encode_humidity(100.0), (10000).to_bytes(2, "little"))

    def test_pressure_scaled_uint32_le(self):
        # ESS unit is 0.1 Pa: 1013.25 hPa = 101325.0 Pa = 1013250 units
        self.assertEqual(encode_pressure(1013.25), (1013250).to_bytes(4, "little"))

    def test_entity_maps_all_three_metrics(self):
        reading = {"temperature_c": 23.5, "humidity_percent": 45.2, "pressure_hpa": 1013.25}
        entity = build_weather_entity(
            reading, STATION, datetime.datetime.now(datetime.timezone.utc)
        )
        encoded = encode_from_entity(entity)
        self.assertEqual(
            encoded,
            {
                TEMPERATURE_CHAR_UUID: encode_temperature(23.5),
                HUMIDITY_CHAR_UUID: encode_humidity(45.2),
                PRESSURE_CHAR_UUID: encode_pressure(1013.25),
            },
        )

    def test_entity_device_and_taxonomy(self):
        reading = {"temperature_c": 23.5, "humidity_percent": 45.2, "pressure_hpa": 1013.25}
        entity = build_weather_entity(
            reading, STATION, datetime.datetime.now(datetime.timezone.utc)
        )
        # Both transports must push this exact device shape (whole-replace
        # merge), and the taxonomy is what makes the engine derive the
        # SFGPESE---***** symbol.
        self.assertEqual(entity.device.category, "Sensors")
        self.assertEqual(entity.device.parent, "weatherstation.service")
        self.assertEqual(getattr(entity.device, "class"), "weather")
        self.assertTrue(entity.device.unique_hardware_id)
        self.assertTrue(
            entity.classification.taxonomy[0].equipment.sensor.HasField("emplaced")
        )
        # Position is operator-placed in Hydris -- the station must never
        # push geo, or it would overwrite the manual placement every tick.
        self.assertFalse(entity.HasField("geo"))
        # fresh advances "last seen"; no until keeps the entity permanent.
        self.assertTrue(entity.lifetime.HasField("fresh"))
        self.assertFalse(entity.lifetime.HasField("until"))

    def test_metadata_shape(self):
        meta = json.loads(station_metadata(STATION, "0000000012345678"))
        self.assertEqual(
            meta,
            {"v": 1, "id": "pizero-01.weather", "label": "Pi Zero Weather Station",
             "serial": "0000000012345678"},
        )

    def test_wifi_telemetry_metric(self):
        from transport.grpc_wifi import WIFI_UPDATES_METRIC_ID, with_wifi_telemetry

        reading = {"temperature_c": 23.5, "humidity_percent": 45.2, "pressure_hpa": 1013.25}
        entity = build_weather_entity(
            reading, STATION, datetime.datetime.now(datetime.timezone.utc)
        )
        wired = with_wifi_telemetry(entity, 7)
        self.assertEqual(len(entity.metric.metrics), 3)  # original untouched
        counter = {m.id: m for m in wired.metric.metrics}[WIFI_UPDATES_METRIC_ID]
        self.assertEqual(counter.uint64, 7)
        self.assertTrue(counter.HasField("measured_at"))


if __name__ == "__main__":
    unittest.main()
