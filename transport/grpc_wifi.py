"""gRPC already speaks world.proto directly -- no translation, just hands the Entity to WorldService.Push."""

import socket

import grpc
from google.protobuf.timestamp_pb2 import Timestamp
from platform_proto import metrics_pb2
from platform_proto.world_pb2 import Entity, EntityChangeRequest
from platform_proto.world_pb2_grpc import WorldServiceStub

from .base import Transport, TransportKind, TransportResult

# Metric id namespace: 1-3 are the sensor readings (entity_builder), 10+ is
# per-transport telemetry. Metrics sub-merge by id, so each transport can
# own its counter without clobbering the other -- its measured_at is the
# "last update over this path" the operator sees in Hydris.
WIFI_UPDATES_METRIC_ID = 10


def with_wifi_telemetry(entity: Entity, count: int) -> Entity:
    """Copy of the entity with this transport's liveness counter appended."""
    now = Timestamp()
    now.GetCurrentTime()
    out = Entity()
    out.CopyFrom(entity)
    out.metric.metrics.append(metrics_pb2.Metric(
        id=WIFI_UPDATES_METRIC_ID, label="WiFi updates",
        kind=metrics_pb2.MetricKindCount,
        unit=metrics_pb2.MetricUnitCount,
        uint64=count,
        measured_at=now,
    ))
    return out


class GrpcWifiTransport:
    kind = TransportKind.WIFI

    def __init__(self, server: str, timeout_s: float = 5.0):
        self._server = server
        self._timeout = timeout_s
        self._stub = WorldServiceStub(grpc.insecure_channel(server))
        self._sent = 0

    def is_available(self) -> bool:
        host, _, port = self._server.partition(":")
        try:
            with socket.create_connection((host, int(port)), timeout=1.0):
                return True
        except OSError:
            return False

    def send(self, entity: Entity) -> TransportResult:
        try:
            wired = with_wifi_telemetry(entity, self._sent + 1)
            self._stub.Push(EntityChangeRequest(changes=[wired]), timeout=self._timeout)
            self._sent += 1
            return TransportResult(self.kind, True)
        except grpc.RpcError as e:
            return TransportResult(self.kind, False, str(e.code()))
