"""gRPC already speaks world.proto directly -- no translation, just hands the Entity to WorldService.Push."""

import socket

import grpc
from platform_proto.world_pb2 import Entity, EntityChangeRequest
from platform_proto.world_pb2_grpc import WorldServiceStub

from .base import Transport, TransportKind, TransportResult


class GrpcWifiTransport:
    kind = TransportKind.WIFI

    def __init__(self, server: str, timeout_s: float = 5.0):
        self._server = server
        self._timeout = timeout_s
        self._stub = WorldServiceStub(grpc.insecure_channel(server))

    def is_available(self) -> bool:
        host, _, port = self._server.partition(":")
        try:
            with socket.create_connection((host, int(port)), timeout=1.0):
                return True
        except OSError:
            return False

    def send(self, entity: Entity) -> TransportResult:
        try:
            self._stub.Push(EntityChangeRequest(changes=[entity]), timeout=self._timeout)
            return TransportResult(self.kind, True)
        except grpc.RpcError as e:
            return TransportResult(self.kind, False, str(e.code()))
