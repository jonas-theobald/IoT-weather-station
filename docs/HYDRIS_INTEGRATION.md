# Hydris Integration Architecture

How this Pi Zero + BME280 weather node publishes into a Hydris engine, and why. Sources: [github.com/projectqai/hydris](https://github.com/projectqai/hydris), [projectqai.github.io/docs](https://projectqai.github.io/docs), [github.com/projectqai/proto](https://github.com/projectqai/proto).

## Decision: external gRPC integration, not a native plugin

Hydris takes data in two ways: an external process pushing/watching entities over gRPC (`WorldService.Push`), or a TypeScript plugin running inside the engine with access to a small HAL (Bluetooth LE + serial only — no I2C/SPI).

The BME280 is on I2C, which isn't in the documented plugin HAL. A native plugin can't read it today without stepping outside supported APIs (`bun:ffi` into i2c-dev — unsupported, and breaks Hydris's cross-platform plugin story). So: keep `read_bme280.py` as-is, add a gRPC publisher next to the existing SQLite write in `collector.py`/`start_all.py`. The entity/component design is decoupled from transport, so this isn't a dead end — if Hydris ever adds I2C to the HAL, see "Future: native plugin" below.

## Entity design

Matches Hydris's own "Weather Station" pattern: `{ id, geo, symbol, sensor, metric, device, link, power }`.

| Component | Value |
|---|---|
| `id` | `pizero-01.weather` |
| `geo` | Fixed lat/lon/altitude (stationary node) |
| `device` | `class: "weather"`, `state: DeviceStateActive` |
| `sensor` | `{}` (marks it as a sensor, no coverage geometry needed) |
| `metric` | One `Metric` per reading, see below |

| Reading | `kind` | `unit` | `range` |
|---|---|---|---|
| Temperature | `MetricKindTemperature` | `MetricUnitCelsius` | -40…85 |
| Humidity | `MetricKindHumidity` | `MetricUnitPercent` | 0…100 |
| Pressure | `MetricKindPressure` | `MetricUnitHectopascal` | 300…1100 |

All confirmed against the installed `platform-proto` package, not guessed from docs. No `MetricKindAltitude` exists — altitude is intentionally omitted; it's a derived value depending on a manually-set sea-level reference, and `geo.altitude` already covers the station's real altitude.

## Deployment notes

- **Engine runs off the Pi**, on a real host (laptop/NAS/Docker) — same pattern Hydris's own builtins (ADS-B, AIS, Meshtastic) use. The engine is a full Go+web-UI service, plus an embedded Bun runtime for plugins; more than a Pi Zero wants to carry alongside its own Flask+SQLite. Running the engine on-Pi would only make sense for a fully disconnected field kit acting as both sensor and operator station, which isn't this project.
- **The Pi can't meaningfully sleep either way.** No ACPI/suspend-to-RAM on the Pi's SoC. Options are (a) stay booted and duty-cycle WiFi for modest (~20-40%) savings, or (b) hard power-cut via an external RTC timer (PiJuice, Witty Pi, TPL5110+MOSFET) between readings for real savings, at the cost of boot latency and no live dashboard between cycles. Either way, a node that can be power-cycled like that can only be a thin client — reinforces the engine-elsewhere decision above.
- **RF:** only WiFi/BLE on-board (2.4GHz, no LoRa). WiFi is what's implemented. BLE would mean flipping the Pi into a GATT peripheral for a Hydris-side plugin to poll — real but nontrivial (BlueZ peripheral mode is less turnkey than scanning mode). For a genuinely remote site with no WiFi, Hydris has first-class Meshtastic (LoRa) support with an efficient Hydris-to-Hydris wire format — worth it only if WiFi coverage is actually the constraint.
- **Reaching the engine off-LAN:** `hydris --server ssh://...` or `--wireguard` tunnels gRPC through SSH/WireGuard rather than exposing 50051 directly. Default gRPC is plaintext.
- **Federation between two Hydris nodes** requires a `routing: { channels: [{}] }` component on the entity — without it, entities stay node-local by default.

## Architecture

```
┌───────────────────────────────────────────────────────────────┐
│ L6  Orchestration        collector.py, start_all.py            │
├───────────────────────────────────────────────────────────────┤
│ L5  Reliability           reliability/pending_store.py          │
├───────────────────────────────────────────────────────────────┤
│ L4  Transport Routing     routing/transport_router.py           │
├───────────────────────────────────────────────────────────────┤
│ L3  Transport Adapters    transport/{grpc_wifi,ble_gatt}.py     │
├───────────────────────────────────────────────────────────────┤
│ L2  Domain Model           model/entity_builder.py               │
│      (world.proto)                                               │
├───────────────────────────────────────────────────────────────┤
│ L1  Sensor Driver          read_bme280.py (unchanged)            │
└───────────────────────────────────────────────────────────────┘
        │
        └── sibling, not a layer: save_reading() → SQLite → Flask
            dashboard. Never routed through L2–L5 — its failure
            domain stays independent of any radio/hub being up.
```

`model/entity_builder.py` is the only file that knows about the BME280; everything above it only ever handles a `world_pb2.Entity`. WiFi and BLE adapters move the identical serialized bytes (`entity.SerializeToString()`), so routing between them is a policy choice (`RouterMode.FAILOVER`/`BROADCAST` in `TransportRouter`), not two divergent code paths.

BLE (`transport/ble_gatt.py`) is a structural sketch, not wired into either entry point's transport list yet — no `bluezero` installed, and no hub-side BLE receiver exists to test against.

## Gotchas found while building this

- `class` on `DeviceComponent` has no `class_` alias in the generated Python — it's a real reserved word collision, set via `DeviceComponent(**{"class": "weather"})`, not a kwarg.
- `DeviceState` values are plain int constants on `world_pb2` (`world_pb2.DeviceStateActive`), not strings.
- A `queue/` package name silently shadows Python's stdlib `queue` (which `grpcio` imports internally) once the repo root is on `sys.path` — that's why the reliability layer is `reliability/`, not `queue/`.
- `Entity | None` throws `TypeError` at class-definition time on Python 3.9 (Pi OS Bullseye's default) — needs `from __future__ import annotations`.
- `install.sh` had two latent bugs, both fixed: a dead `sed` pattern that never actually corrected the systemd `User=` line for non-`pi` usernames, and a file-copy step that only globbed root `*.py` files, missing the new package subdirectories.

## Status

Verified end-to-end on real hardware (Pi Zero 2 W, armv7l, Bookworm) against a real Hydris.app instance, not a stand-in: `grpcio` installs from a prebuilt armv7l wheel, a real sensor reading round-trips through the full layer stack into Hydris's world model (confirmed via `GetEntity`), and `bme280.service` runs continuously via the fixed `install.sh` with `HYDRIS_SERVER` set through a systemd drop-in — local dashboard unaffected throughout.

Not done: BLE transport (no receiver, not installed, not wired in), armv6l (original Pi Zero W — only tested on the newer Zero 2 W).

## Future: native plugin

If Hydris's HAL ever gains I2C/SPI support, `model/entity_builder.py`'s logic becomes a TypeScript `attach({ run: ... })` block inside a plugin, and L3–L5 (transport adapters, router, pending store) simply disappear — no transport choice needed once you're in-process with the engine. Until then, the gRPC integration isn't a compromise; it's the path Hydris's own docs point external hardware at.
