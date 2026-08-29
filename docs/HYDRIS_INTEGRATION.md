# Hydris Integration Architecture

How this Pi Zero + BME280 weather node publishes into a Hydris engine, and why. Sources: [github.com/projectqai/hydris](https://github.com/projectqai/hydris), [projectqai.github.io/docs](https://projectqai.github.io/docs), [github.com/projectqai/proto](https://github.com/projectqai/proto).

## Decision: external gRPC integration, not a native plugin

Hydris takes data in two ways: an external process pushing/watching entities over gRPC (`WorldService.Push`), or a TypeScript plugin running inside the engine with access to a small HAL (Bluetooth LE + serial only — no I2C/SPI).

The BME280 is on I2C, which isn't in the documented plugin HAL. A native plugin can't read it today without stepping outside supported APIs (`bun:ffi` into i2c-dev — unsupported, and breaks Hydris's cross-platform plugin story). So: keep `read_bme280.py` as-is, add a gRPC publisher next to the existing SQLite write in `collector.py`/`start_all.py`. The entity/component design is decoupled from transport, so this isn't a dead end — if Hydris ever adds I2C to the HAL, see "Future: native plugin" below.

## Entity design

Matches Hydris's own "Weather Station" pattern: `{ id, classification, sensor, metric, device, link, lifetime }` — the symbol is derived by the engine, not pushed.

| Component | Value |
|---|---|
| `id` | `pizero-01.weather` |
| `geo` | **Never pushed by the station.** The operator places it on the map in Hydris (openmeteo pattern) — components are whole-replaced, so a station that kept pushing geo would overwrite the manual placement every tick. |
| `device` | `class: "weather"`, `category: "Sensors"`, `parent: "weatherstation.service"`, `unique_hardware_id` = Pi SoC serial, `state: DeviceStateActive`. Identical shape from both transports, or the fields flap with whichever pushed last. |
| `classification` | Taxonomy `equipment → sensor → emplaced`; the engine derives the `SFGPESE---*****` symbol from it (friendly ground emplaced sensor). |
| `sensor` | `{}` (marks it as a sensor, no coverage geometry needed) |
| `metric` | Ids 1–3: one `Metric` per reading, see below. Ids 10+ are per-transport telemetry: 10 = "WiFi updates" (appended by the gRPC adapter), 11 = "BLE updates" (pushed by the hub plugin). Metrics sub-merge by id, so each transport owns its counter, and its `measured_at` reads as "last update over this path". |
| `lifetime` | `fresh` on every push (advances "last seen" in Hydris); never `until` — the entity is permanent. |
| `link` | BLE-only, owned by the hub plugin: `status`, `rssi_dbm`, `last_seen`, `rf_mode: "BLE"`, `via: "weatherstation.service"`. The WiFi path is a direct gRPC push, not a mediated link — its liveness shows via metric 10. |

| Reading | `kind` | `unit` | `range` |
|---|---|---|---|
| Temperature | `MetricKindTemperature` | `MetricUnitCelsius` | -40…85 |
| Humidity | `MetricKindHumidity` | `MetricUnitPercent` | 0…100 |
| Pressure | `MetricKindPressure` | `MetricUnitHectopascal` | 300…1100 |

All confirmed against the installed `platform-proto` package, not guessed from docs. No `MetricKindAltitude` exists — altitude is intentionally omitted; it's a derived value depending on a manually-set sea-level reference, and the station's real altitude belongs to its geo, which the operator sets when placing it.

## Deployment notes

- **Engine runs off the Pi**, on a real host (laptop/NAS/Docker) — same pattern Hydris's own builtins (ADS-B, AIS, Meshtastic) use. The engine is a full Go+web-UI service, plus an embedded Bun runtime for plugins; more than a Pi Zero wants to carry alongside its own Flask+SQLite. Running the engine on-Pi would only make sense for a fully disconnected field kit acting as both sensor and operator station, which isn't this project.
- **The Pi can't meaningfully sleep either way.** No ACPI/suspend-to-RAM on the Pi's SoC. Options are (a) stay booted and duty-cycle WiFi for modest (~20-40%) savings, or (b) hard power-cut via an external RTC timer (PiJuice, Witty Pi, TPL5110+MOSFET) between readings for real savings, at the cost of boot latency and no live dashboard between cycles. Either way, a node that can be power-cycled like that can only be a thin client — reinforces the engine-elsewhere decision above.
- **RF:** only WiFi/BLE on-board (2.4GHz, no LoRa). Both are implemented: WiFi pushes gRPC to the engine, and `HYDRIS_BLE=1` additionally flips the Pi into a GATT peripheral (see "BLE peripheral" below) for a Hydris-side plugin to consume. For a genuinely remote site with no WiFi, Hydris has first-class Meshtastic (LoRa) support with an efficient Hydris-to-Hydris wire format — worth it only if WiFi coverage is actually the constraint.
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

`model/entity_builder.py` is the only file that knows about the BME280; everything above it only ever handles a `world_pb2.Entity`. Both adapters take the identical Entity; WiFi forwards it verbatim over gRPC, BLE maps it onto GATT characteristics (below). The router runs in `BROADCAST` because BLE isn't a fallback route to the same hub — it's a different consumer.

## BLE peripheral

Enabled with `HYDRIS_BLE=1` (`HYDRIS_BLE_NAME` overrides the advertised name, default `hydris-weather`). Not chunked protobuf: a serialized Entity doesn't fit the 23-byte default MTU, and the hub-side plugin has no protobuf runtime on its BLE path. Instead, three GATT services:

| Service | Characteristics | Purpose |
|---|---|---|
| `eef67fbe-b177-4705-857f-6a475536a66f` (custom, advertised) | metadata `7b264d39-…` (read): JSON `{v, id, label, serial}` | Discovery anchor — the Hydris engine records advertised UUIDs on `ble.device.*` entities and the plugin filters on this one. Metadata carries the entity identity (id + hardware serial); deliberately no position — see the entity design table. |
| Environmental Sensing `0x181A` | temperature `0x2A6E` (sint16, 0.01 °C), humidity `0x2A6F` (uint16, 0.01 %), pressure `0x2A6D` (uint32, 0.1 Pa) — all read+notify, little-endian | The readings, in standard ESS encoding — single-MTU, verifiable with any BLE tool (nRF Connect shows real values). |
| Device Information `0x180A` | manufacturer `2A29`, model `2A24`, serial `2A25` (Pi SoC serial), firmware `2A26` | BLE-tool interop only. The hub never reads it: bluetoothd exposes its own built-in `0x180A`, so a central asking for DIS can land on the wrong instance. Identity (`unique_hardware_id`) comes from the metadata serial instead. |

Threading: `bluezero`'s `publish()` owns the GLib mainloop on a daemon thread; `send()` hands characteristic updates over via `GLib.idle_add` — never touch BlueZ from the collector thread directly.

### BLE gotchas (each one cost real debugging on a Pi Zero 2 W)

- **bluezero read callbacks must introspect as zero-argument callables.** bluezero inspects the callback signature; anything with one visible parameter — a `lambda u=uuid:` default-arg closure counts — gets called with the D-Bus *options dict* as that argument, throws, and the central sees ATT "Unlikely error" (0x0E) with nothing in the Pi journal. Use `functools.partial` with everything bound.
- **Kernel ext-adv MGMT bug (Pi OS Bookworm, 6.12 rpt kernel, Zero 2 W):** bluetoothd registers advertisements via `Add Extended Advertising Data (0x0055)` and the kernel answers `Invalid Parameters (0x0d)` even for a minimal 3-byte flags payload — every D-Bus advertisement (bluezero, even `bluetoothctl advertise on`) fails, while GATT registration works fine. The legacy MGMT op still works, so the advert is registered out-of-band: `btmgmt add-adv -u <station uuid> -c -g 1`, persisted as a systemd drop-in (`bme280.service.d/ble-adv-workaround.conf`, `ExecStartPost=-+/usr/bin/btmgmt add-adv …`, `ExecStopPost=-+/usr/bin/btmgmt rm-adv 1`). Diagnose with `btmon` — bluetoothd's own journal only says "Failed to add advertisement".
- **`bluetoothd`'s built-in DIS collides with an app-provided one** (two `0x180A` instances in the ATT database). Hence: hub identity via the metadata characteristic, never via reading our DIS copy.
- **Component merge flap (resolved):** both transports push a `device` component and the engine whole-replaces components — with different shapes, the hub plugin's `parent`/`category`/`unique_hardware_id` got clobbered by the next WiFi push. Fixed by making both paths push a byte-identical `device` component (`model/entity_builder.py` is the reference shape).
- **PyGObject/dbus for `bluezero` on the Pi:** don't build from pip (fails without gi dev headers) — `apt install python3-gi python3-dbus`, expose them to the venv (`system-gi.pth` with `/usr/lib/python3/dist-packages`), then `pip install --no-deps bluezero`.

## Gotchas found while building this

- `class` on `DeviceComponent` has no `class_` alias in the generated Python — it's a real reserved word collision, set via `DeviceComponent(**{"class": "weather"})`, not a kwarg.
- `DeviceState` values are plain int constants on `world_pb2` (`world_pb2.DeviceStateActive`), not strings.
- A `queue/` package name silently shadows Python's stdlib `queue` (which `grpcio` imports internally) once the repo root is on `sys.path` — that's why the reliability layer is `reliability/`, not `queue/`.
- `Entity | None` throws `TypeError` at class-definition time on Python 3.9 (Pi OS Bullseye's default) — needs `from __future__ import annotations`.
- `install.sh` had two latent bugs, both fixed: a dead `sed` pattern that never actually corrected the systemd `User=` line for non-`pi` usernames, and a file-copy step that only globbed root `*.py` files, missing the new package subdirectories.

## Status

Verified end-to-end on real hardware (Pi Zero 2 W, armv7l, Bookworm) against a real Hydris.app instance, not a stand-in: `grpcio` installs from a prebuilt armv7l wheel, a real sensor reading round-trips through the full layer stack into Hydris's world model (confirmed via `GetEntity`), and `bme280.service` runs continuously via the fixed `install.sh` with `HYDRIS_SERVER` set through a systemd drop-in — local dashboard unaffected throughout.

BLE: verified end-to-end against a live engine — discovery via the advertised UUID, connect, metadata identity, ESS notifications into metrics, RSSI on the link, stale-data drop to `Lost`, automatic reconnect. Encoding covered by `tests/test_ble_gatt.py`; the hub-side consumer is the separate `hydris-weather-ble-plugin` repo, which mirrors the ESS test vectors.

Not done: armv6l (original Pi Zero W — only tested on the newer Zero 2 W).

## Future: native plugin

If Hydris's HAL ever gains I2C/SPI support, `model/entity_builder.py`'s logic becomes a TypeScript `attach({ run: ... })` block inside a plugin, and L3–L5 (transport adapters, router, pending store) simply disappear — no transport choice needed once you're in-process with the engine. Until then, the gRPC integration isn't a compromise; it's the path Hydris's own docs point external hardware at.
