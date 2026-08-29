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

STATION = StationConfig(
    entity_id="pizero-01.weather", label="Pi Zero Weather Station",
    lat=49.44, lon=7.77, alt=251.0,
)


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

    def test_metadata_shape(self):
        meta = json.loads(station_metadata(STATION))
        self.assertEqual(
            meta,
            {"v": 1, "id": "pizero-01.weather", "label": "Pi Zero Weather Station",
             "lat": 49.44, "lon": 7.77, "alt": 251.0},
        )


if __name__ == "__main__":
    unittest.main()
