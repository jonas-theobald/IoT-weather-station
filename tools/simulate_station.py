"""Dev harness: pushes synthetic readings through the real L2-L4 stack
(entity builder -> router -> gRPC transport) so the Hydris path can be
exercised from any machine, without a Pi or a sensor on the bus.

    python tools/simulate_station.py --server localhost:50051
"""

import argparse
import datetime
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from model.entity_builder import StationConfig, build_weather_entity
from routing.transport_router import RouterMode, TransportRouter
from transport.grpc_wifi import GrpcWifiTransport


def synthetic_reading(t: float) -> dict:
    """Slow sine drift around plausible indoor values."""
    return {
        "temperature_c": 22.0 + 2.0 * math.sin(t / 60),
        "humidity_percent": 45.0 + 5.0 * math.sin(t / 90),
        "pressure_hpa": 1013.0 + 1.5 * math.sin(t / 120),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default="localhost:50051")
    parser.add_argument("--entity-id", default="pizero-01.weather",
                        help="collides with the real station on purpose -- it simulates it")
    parser.add_argument("--label", default="Pi Zero Weather Station")
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--count", type=int, default=0, help="0 = run until interrupted")
    args = parser.parse_args()

    # No position: like the real station, placement happens in Hydris.
    station = StationConfig(entity_id=args.entity_id, label=args.label)
    router = TransportRouter([GrpcWifiTransport(args.server)], mode=RouterMode.BROADCAST)

    sent = 0
    start = time.monotonic()
    try:
        while args.count == 0 or sent < args.count:
            reading = synthetic_reading(time.monotonic() - start)
            entity = build_weather_entity(
                reading, station, datetime.datetime.now(datetime.timezone.utc)
            )
            results = router.send(entity)
            status = "ok" if any(r.ok for r in results) else f"failed: {results}"
            print(f"[{sent + 1}] {reading['temperature_c']:.2f}degC "
                  f"{reading['humidity_percent']:.1f}% {reading['pressure_hpa']:.1f}hPa -> {status}")
            sent += 1
            if args.count == 0 or sent < args.count:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
