"""
The only module that knows both what a BME280 reading looks like and what
world.proto expects. Everything above this layer speaks only
platform_proto.world_pb2.Entity; swapping the sensor means touching only
this file.

Field/enum names below are verified against platform-proto 0.1.0
(git+https://github.com/projectqai/proto.git#subdirectory=python), not
guessed from the TypeScript docs:

- Metrics types live in platform_proto.metrics_pb2, a separate module
  from platform_proto.world_pb2.
- MetricKindPressure / MetricUnitHectopascal exist exactly as named.
- There is no MetricKindAltitude — altitude is intentionally left off the
  metric list (see docs/HYDRIS_INTEGRATION.md, Section 3); geo.altitude
  already carries the station's real, static altitude.
- DeviceComponent's `class` field keeps its literal proto name in the
  generated Python code (no `class_` alias) because `class` is a Python
  keyword. It has to be set via dict-unpacking, e.g.
  DeviceComponent(**{"class": "weather"}) — a bare `class=` kwarg is a
  syntax error.
- DeviceState values (e.g. DeviceStateActive) are plain int module-level
  constants on world_pb2, not strings.
"""

from dataclasses import dataclass

from google.protobuf.timestamp_pb2 import Timestamp
from platform_proto import metrics_pb2, world_pb2

# BME280 operating range (Bosch datasheet BST-BME280-DS001-24, tables 2-4).
# Not the "full accuracy" range -- the hard sensor limits, for MetricRange.
_TEMPERATURE_RANGE = metrics_pb2.MetricRange(min_double=-40.0, max_double=85.0)
_HUMIDITY_RANGE = metrics_pb2.MetricRange(min_double=0.0, max_double=100.0)
_PRESSURE_RANGE = metrics_pb2.MetricRange(min_double=300.0, max_double=1100.0)


@dataclass(frozen=True)
class StationConfig:
    entity_id: str
    label: str
    lat: float
    lon: float
    alt: float


def build_weather_entity(reading: dict, station: StationConfig, measured_at) -> world_pb2.Entity:
    """
    reading: {"temperature_c": float, "humidity_percent": float, "pressure_hpa": float}
              -- the same shape read_bme280.read_sensor() already returns.
    measured_at: a timezone-aware datetime.datetime of when the reading was taken.
    """
    ts = Timestamp()
    ts.FromDatetime(measured_at)

    device = world_pb2.DeviceComponent(**{"class": "weather"})
    device.state = world_pb2.DeviceStateActive

    return world_pb2.Entity(
        id=station.entity_id,
        label=station.label,
        geo=world_pb2.GeoSpatialComponent(
            latitude=station.lat,
            longitude=station.lon,
            altitude=station.alt,
        ),
        device=device,
        sensor=world_pb2.SensorComponent(),
        metric=metrics_pb2.MetricComponent(metrics=[
            metrics_pb2.Metric(
                id=1, label="Temperature",
                kind=metrics_pb2.MetricKindTemperature,
                unit=metrics_pb2.MetricUnitCelsius,
                double=reading["temperature_c"],
                measured_at=ts,
                range=_TEMPERATURE_RANGE,
            ),
            metrics_pb2.Metric(
                id=2, label="Humidity",
                kind=metrics_pb2.MetricKindHumidity,
                unit=metrics_pb2.MetricUnitPercent,
                double=reading["humidity_percent"],
                measured_at=ts,
                range=_HUMIDITY_RANGE,
            ),
            metrics_pb2.Metric(
                id=3, label="Pressure",
                kind=metrics_pb2.MetricKindPressure,
                unit=metrics_pb2.MetricUnitHectopascal,
                double=reading["pressure_hpa"],
                measured_at=ts,
                range=_PRESSURE_RANGE,
            ),
        ]),
    )
