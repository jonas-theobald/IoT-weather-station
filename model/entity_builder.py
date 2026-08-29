"""Converts a BME280 reading into a world.proto Entity. The only module
that knows about the sensor -- everything above this speaks Entity only."""

import functools
from dataclasses import dataclass

from google.protobuf.timestamp_pb2 import Timestamp
from platform_proto import metrics_pb2, taxonomy_pb2, world_pb2

# Device tree parent -- the entity the hydris-weather-ble-plugin creates.
# Both transports must push an IDENTICAL device component: the engine
# whole-replaces components, so if the shapes differ the fields flap with
# whichever path pushed last.
WEATHER_SERVICE_PARENT = "weatherstation.service"

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


@functools.lru_cache(maxsize=1)
def device_serial() -> str:
    """Pi SoC serial -- entity identity (unique_hardware_id) keys on this,
    so it must survive reboots and BLE address changes."""
    try:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("Serial"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    import uuid

    return f"{uuid.getnode():012x}"  # non-Pi fallback: MAC as hex


def _emplaced_sensor_classification() -> world_pb2.ClassificationComponent:
    """Taxonomy, not a hardcoded SIDC: with a device component present the
    engine derives SFGPESE---***** (friendly ground emplaced sensor) --
    same pattern as Hydris's own weather examples."""
    return world_pb2.ClassificationComponent(taxonomy=[
        taxonomy_pb2.ClassificationTaxonomy(
            equipment=taxonomy_pb2.EquipmentTaxonomy(
                sensor=taxonomy_pb2.EquipmentTaxonomySensor(
                    emplaced=taxonomy_pb2.EquipmentTaxonomySensorEmplaced(),
                ),
            ),
        ),
    ])


def build_weather_entity(reading: dict, station: StationConfig, measured_at) -> world_pb2.Entity:
    """reading: same shape as read_bme280.read_sensor(). measured_at: aware datetime."""
    ts = Timestamp()
    ts.FromDatetime(measured_at)

    device = world_pb2.DeviceComponent(**{"class": "weather"})  # `class` is a reserved word, no kwarg
    device.state = world_pb2.DeviceStateActive
    device.category = "Sensors"
    device.parent = WEATHER_SERVICE_PARENT
    device.unique_hardware_id = device_serial()

    return world_pb2.Entity(
        id=station.entity_id,
        label=station.label,
        geo=world_pb2.GeoSpatialComponent(
            latitude=station.lat,
            longitude=station.lon,
            altitude=station.alt,
        ),
        device=device,
        classification=_emplaced_sensor_classification(),
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
