# Hydris Integration Architecture

How to expose this Pi Zero + BME280 weather node as a Hydris weather node, and why.

Sources: [github.com/projectqai/hydris](https://github.com/projectqai/hydris), [projectqai.github.io/docs](https://projectqai.github.io/docs) (Operator, Integration, and Developer guides). Where a detail below couldn't be confirmed from the published docs, it's marked **[verify]** — check it against the annotated `.proto` files at `github.com/projectqai/proto` before relying on it, as the docs themselves recommend.

## 1. What Hydris is

Hydris positions itself as "Home Assistant for the outdoors" — an open-source coordination layer for sensors, unmanned assets, and decision-support apps. Core properties relevant to us:

- **Entity Component System (ECS), not a type hierarchy.** An entity is just an ID plus a bag of components (`geo`, `metric`, `device`, `sensor`, `symbol`, …). There's no `Sensor` class to subclass or register — "what something is" emerges from which components are attached to it.
- **API-first.** The wire format is Protocol Buffers over gRPC (`WorldService.Push`), with an HTTP/JSON bridge for convenience. Official client libraries exist for TypeScript, Python, Go, and Rust.
- **Two ways to get data in:**
  1. **Integration** — an external process, in any language, pushes/watches entities over gRPC. No Hydris-specific runtime required.
  2. **Plugin** — a TypeScript module that runs *inside* the Hydris engine process (via Bun), gets a local gRPC client for free, and can additionally reach a small Hardware Abstraction Layer (HAL) for **Bluetooth LE and serial ports**.
- The engine itself is a single Go binary (also shipped as a Docker image and a Kubernetes manifest) that listens on `localhost:50051` for both gRPC and its web UI.

## 2. The two integration shapes, and which one fits a BME280 on I2C

### Option A — External integration over gRPC (recommended)

Treat the Pi exactly like ADS-B or AIS feeders in Hydris's own Integration Guide: a standalone process reads the sensor and calls `WorldService.Push(EntityChangeRequest)` periodically. This is officially sanctioned — the Integration Guide's own words: *"If you're looking to connect an existing external system to Hydris (in any language), see the Integration Guide instead"* of the plugin guide. That is precisely our situation: a working Python collector already reading real hardware.

### Option B — Native TypeScript plugin running on the node

This is Hydris's "native" extension mechanism, and it's the one you asked about explicitly. It's the right tool when a plugin needs the engine's local HAL — and that HAL is documented as covering exactly two peripheral classes: **Bluetooth LE** (`Hydris.bluetooth`) and **serial ports** (`Hydris.serial`, incl. BLE-wrapped-as-serial). The BME280 on this board is wired over **I2C** (`/docs/WIRING.md`: SDA/SCL to GPIO2/GPIO3). I2C/SPI GPIO access is not part of the published Node Peripherals API.

That means a "pure" native plugin can't read this sensor through any documented, supported API today. The only way to get I2C bytes into a Bun-hosted plugin would be to reach outside the documented HAL — e.g. Bun's `bun:ffi` calling into `libi2c`/`i2c-dev` ioctls directly. I'd avoid that:
- It's unsupported surface — nothing in the docs says plugins can do raw FFI, and Hydris explicitly advertises "write once, run on Android/macOS/Windows/Linux" plugin portability; a Linux-only i2c-dev binding breaks that promise and simply cannot exist on Android.
- It duplicates a sensor driver (`adafruit-circuitpython-bme280`) that's already correct and already running.
- It only pays off if the plugin needs the rest of the in-engine plugin surface (entity `watch`/enrichment of *other* entities, CEL policies, etc.), which this project doesn't need.

### Decision

**Use Option A.** Keep `read_bme280.py` exactly as it is — it's the correct I2C driver for this hardware — and add a second, independent sink next to the existing SQLite write in `collector.py`/`start_all.py`: a small gRPC publisher that pushes the same reading into Hydris as an entity. Nothing about the existing dashboard, database, or systemd service changes or is put at risk (Section 9 has the implemented version of this).

If Hydris ever adds an I2C/SPI HAL, the "Future path" section at the bottom describes migrating to a real native plugin — the entity/component design below carries over unchanged either way, since the entity shape is decoupled from how the process talks to the engine.

## 3. Entity design for this node

Hydris's own component reference lists **"Weather Station"** as one of its named common patterns:

```
{ id, geo, symbol, sensor, metric, device, link, power }
```

That's the model to target. Concretely, for this node:

| Component | Purpose | Values |
|---|---|---|
| `id` | Stable entity ID | `pizero-01.weather` (dotted, hierarchical convention used throughout Hydris's own examples) |
| `geo` | Fixed WGS84 location of the station | `latitude`, `longitude`, `altitude` — hardcode for a stationary node |
| `symbol` | Map icon | MIL-STD-2525C symbol code, or omit if you don't care about the tactical map icon |
| `device` | Hardware identity/health | `class: "weather"` (this literal string is used in Hydris's own cookbook example for a wind sensor), `state: DeviceStateActive`, optionally `unique_hardware_id` from the Pi's CPU serial |
| `sensor` | Marks this entity as a sensor | `{}` — an empty `SensorComponent` is sufficient (no coverage-area geometry needed for a point weather station) |
| `metric` | The actual readings | One `Metric` per measurement — see table below |
| `power` | Optional | Only meaningful if you add battery monitoring (e.g. an INA219) later; the README already documents a battery-powered runtime scenario |

`metric.metrics[]` entries, one per BME280 reading:

| Reading | `kind` | `unit` | Confirmed? |
|---|---|---|---|
| Temperature | `MetricKindTemperature` | `MetricUnitCelsius` | Yes — used verbatim in both the HAL example and the component reference |
| Humidity | `MetricKindHumidity` | `MetricUnitPercent` | Yes — used verbatim in the HAL "pushing metrics" example |
| Pressure | `MetricKindPressure` | `MetricUnitHectopascal` | Yes — confirmed directly against the installed `platform-proto` package (Section 9.1), not just the docs |
| Altitude | — omitted | — | Confirmed: **no `MetricKindAltitude` exists** in the installed proto package. Correctly left out — it's a derived value depending on a manually-set sea-level reference (`sensor.sea_level_pressure` in `read_bme280.py`), and `geo.altitude` already carries the station's real, static altitude |

Each `Metric` also gets `id` (stable per-measurement number, e.g. 1/2/3), `label` (human string, e.g. `"Temperature"`), and `measured_at` (timestamp of the actual reading — use the sensor read time, not the push time).

## 4. Where does the Hydris engine run?

Given the constraints of this specific hardware, run the engine **off the Pi Zero**, not on it:

- The engine is a full Go service plus a web UI plus (for plugins) an embedded Bun runtime — comfortable on a desktop/NUC/Docker host, but more than a Pi Zero W/2 W wants to carry alongside its existing Flask + SQLite footprint (~150 mA total is a stated design goal in the README).
- Nothing about Option A requires the engine and the sensor to be co-located — that's the entire point of the gRPC integration model, and it's exactly the pattern Hydris's own builtins (ADS-B, AIS, Meshtastic) use.
- Practically: install Hydris on whatever machine already acts as your "hub" (a home server, NAS, or laptop on the same LAN), start it (`docker run -p 50051:50051 ... ghcr.io/projectqai/hydris:latest`, per the install docs), and point the Pi's publisher at `<hub-host>:50051`.

One thing to check before exposing that port beyond `localhost`: the default bind is `localhost:50051`. For reaching a node that isn't directly routable — across the internet, behind CGNAT, etc. — Hydris ships its own answer rather than requiring you to build one: `hydris --server ssh://user@remote-host` or `hydris --server host:port --wireguard wg.conf` opens an SSH or WireGuard tunnel and runs a local proxy that serves the UI locally while forwarding gRPC to the remote node (Developer Guide → *Remote Access*). Authorization of what a given connection is allowed to do is governed by CEL policy chains (Developer Guide → *CEL Policies*, not fetched in depth here). Read both before opening 50051 beyond your LAN — the gRPC quickstart as documented uses a plaintext `insecure_channel`.

## 5. Should the Hydris *engine* run on the Pi itself?

Section 4 already concluded "run it elsewhere" for the sensor-integration design, but this is worth answering directly, since it's a different question from "how does the Pi talk to Hydris."

**Architecture/binary support is unverified for this specific board.** Hydris publishes Linux binaries, a Docker image, and a Kubernetes manifest; the docs don't spell out which ARM variant. Pi Zero 2 W (quad-core Cortex-A53, `armv7`/`aarch64`-capable) is a plausible target for a `linux/arm64` build. The original Pi Zero W (single-core ARM11, `armv6l`) is a much harder target — Go *can* cross-compile for `GOARM=6`, but plenty of projects' published release matrices and multi-arch Docker images stop at `armv7`/`arm64` and silently exclude `armv6l`. **[verify]** against the GitHub releases page and the Dockerfile's target platforms before assuming either board can run the engine at all.

**RAM is tight even if the binary runs.** Both Zero variants have 512 MB total. The engine is a Go service with an embedded web UI, a CRDT world-state store, and (if plugins are ever enabled) a Bun runtime for TypeScript plugins — layered on top of the Pi already running Raspberry Pi OS, the existing Flask dashboard, and SQLite. There's real risk of swap pressure on an SD card, which is also bad for the card's lifespan.

**The bigger issue is a purpose mismatch, not just resource cost.** The engine's job is to be a continuously-reachable coordination point that other systems push to, watch, and view a UI on. This node's actual job is "read one sensor, occasionally report a value." In Hydris's own vocabulary, this project is a *feed*, not a *node* — nothing else exists locally for a coordination engine to fuse. Every builtin Hydris ships (ADS-B, AIS, Meshtastic, camera integrations) assumes it's plugged into a capable node — a laptop, server, or cluster — not into the sensor itself.

Running the engine locally would only earn its keep in a genuinely different deployment: a fully disconnected field kit where the Pi doubles as *both* sensor and operator station with no network back to a hub at all. That's not this project's situation (a home-network dashboard), so the recommendation stands: **engine on a real host, thin gRPC-publishing client on the Pi.** This also directly enables better power management — see the next section.

## 6. Can the Pi sleep to cut power?

Short answer: not the way a laptop or a microcontroller sleeps. The Broadcom SoC on a Pi has no ACPI and no supported suspend-to-RAM state in mainline Raspberry Pi OS — there's no "sleep 10 seconds, resume instantly, draw a few mA" mode to reach for. The two real levers are different in kind:

**A. Stay booted, trim what's running (software-only, modest savings).** Disable the HDMI output block, disable the activity LED, disable Bluetooth if you're not using it (`dtoverlay=disable-bt`), and — the one that actually matters — **duty-cycle the WiFi radio** (bring the interface down between reads with `ip link set wlan0 down` / `rfkill`, or hold the association only long enough to push a reading). Maintaining a WiFi association is one of the largest single draws after the SoC itself. Realistic outcome: on the order of 20-40% off the README's stated ~100-150 mA baseline, not an order of magnitude — an idle Linux SoC still draws tens of mA no matter what you turn off. This is a drop-in change to the existing `bme280.service`/systemd model, nothing structural moves.

**B. Fully power off between readings, wake on a timer (hardware, large savings, real cost).** To get meaningfully below ~100 mA you have to remove power from the whole board between readings, the same pattern battery dataloggers use: an external RTC/timer-triggered power switch between the battery and the Pi's 5V input — a **PiJuice HAT**, **Witty Pi**, **Sleepy Pi 2**, or a bare **TPL5110/TPL5111 timer + MOSFET** — cuts power entirely, then reapplies it on a schedule. The Pi cold-boots (~15-25s), the existing service takes a reading and pushes it, then either the timer cuts power again or the Pi self-issues `shutdown -h now`. Idle draw between cycles drops to the timer chip's µA range. The cost: boot latency every cycle, and the Flask dashboard (or any live query of the entity in Hydris) is only reachable during the brief awake window — between cycles, the node simply isn't there.

**This is exactly why Section 5's conclusion matters for power, not just resource fit.** A Hydris *engine* fundamentally cannot be hard-power-cycled like this — it needs to be reachable at arbitrary times for other systems watching it or for the operator UI. A node that powers off between readings can only ever be a *client*: wake, read the sensor, push one gRPC call, sleep — which is precisely Option A's shape from Section 2, and precisely what a hard-power-cut duty cycle requires. It also matches how Hydris's merge model treats intermittent sources: metrics carry a lifetime and naturally read as "stale" between wake cycles rather than requiring the entity to stay continuously live (Developer Guide → *Entity Merge & Synchronization*).

Practically: start with (A) — it's software-only and doesn't touch the current service architecture — and only reach for (B) if you need multi-week or fully off-grid runtime, accepting that both the local dashboard and the Hydris entity will show "last seen" data between cycles rather than continuous live readings.

## 7. RF options for forwarding data — and for federating a local Hydris node

**What's actually on the board:** both Pi Zero W and Pi Zero 2 W carry the same class of combo chip — 2.4 GHz 802.11 b/g/n WiFi and Bluetooth (4.1 on the original Zero W, 4.2 LE on the Zero 2 W). No 5 GHz WiFi, no LoRa or other sub-GHz radio, no Zigbee/Thread/Matter — anything beyond WiFi/BLE requires an add-on.

**WiFi — the transport already in use.** This is the gRPC/HTTP push over the LAN to the hub described below (Section 9). It's the simplest working answer to "get data to a gateway," requires no new hardware, and is the one to keep as the default.

**Bluetooth/BLE — present, but the wrong direction for this design.** Hydris's own BLE HAL (Node Peripherals) is built for an always-on Hydris node to *scan and poll* nearby peripherals — exactly the pattern in the documented `airthings` example plugin (connects to Airthings BLE sensors from inside the engine). You could in principle invert the architecture: make the Pi a BLE GATT *peripheral* advertising temperature/humidity/pressure characteristics — no WiFi/IP stack needed, lower radio draw than a sustained WiFi association — and have the hub's Hydris engine run an `airthings`-style plugin that polls it. This is real but not casual: Linux BlueZ's peripheral/GATT-server mode on a Pi is notably less turnkey than its central/scanning mode, and BLE range is much shorter than WiFi. Only worth prototyping if dropping WiFi entirely is the deciding factor for power.

**LoRa / genuine long-range federation — not onboard, but Hydris has a specific, first-class answer for it: Meshtastic.** This is the closest match to what "federated to a server/gateway" usually means in Hydris's own vocabulary, and it's documented, not something to bolt on yourself:

- Plug a Meshtastic-flashed LoRa radio (USB, or a bare LoRa module over UART/SPI — the Pi's UART pins, GPIO14/15, are free since I2C already claims GPIO2/3) into a machine running Hydris. It's auto-discovered over serial; no code required.
- Hydris can both *receive* mesh traffic and *send* its own picture back to the mesh. The send format that matters here is **"Hydris"** — per the Integration Guide: *"Efficient binary protocol for Hydris-to-Hydris communication. Much higher information density at much lower bandwidth. Use this when all peers run Hydris."* That means two Hydris nodes, each with a Meshtastic radio, can exchange entities purely over LoRa — no WiFi, no internet, genuinely low-power, long-range federation between e.g. a field node and a base-station hub.
- This only moves entities that opt in: any entity that should leave its originating node — including this weather entity — needs a `routing: { channels: [{}] }` component (Developer Guide → *Routing & Federation*). Without it, entities are node-local by default and never cross a Meshtastic link, TAK connection, or any other federation transport, regardless of what radio carries it.

**Where this leaves the actual project:** WiFi + the gRPC publisher already solves "get data to a hub" and is the simpler, cheaper answer as long as the deployment site has LAN/WiFi coverage — which a home weather station does. Meshtastic earns its extra hardware specifically for a genuinely remote site with no WiFi at all, which is the scenario Hydris's RF-federation feature is built for. In that case, note that a Meshtastic radio talks over **serial** — which, unlike I2C, *is* in Hydris's documented Node Peripherals HAL surface. So a Meshtastic-equipped Pi reopens the native-plugin question from Section 2 in a way the BME280 alone doesn't: the radio, not the sensor, would be the thing a native TypeScript plugin on the Pi could legitimately talk to. The sensor reading would still ride into that plugin the same way it does today (I2C via the existing Python driver, bridged in), but the *transport* to the hub could become a real in-engine plugin instead of a gRPC client, if you ever run a lightweight Hydris node on the Pi for that specific purpose.

## 8. Layered client architecture

The design so far (Section 5.1 in the earlier draft) bundled sensor reading, entity construction, and gRPC transport into one `publish_reading()` function. That collapses two things that should stay separate: **what the data means** (a `world.proto` `Entity`, Hydris's canonical, transport-independent wire type) and **how it gets to the hub** (WiFi today, possibly BLE, possibly both). Separating them is what makes "WiFi and/or BLE" a runtime *choice* rather than a rewrite.

This is a ports-and-adapters (hexagonal) shape: `world_pb2.Entity` is the port, the BME280 driver is the inbound adapter, and each radio is an outbound adapter. Six layers, bottom to top:

```
┌───────────────────────────────────────────────────────────────┐
│ L6  Orchestration        collector.py                          │
│                           read → build → route → (retry)       │
├───────────────────────────────────────────────────────────────┤
│ L5  Reliability           PendingEntityStore                    │
│                           holds the latest un-acked Entity      │
├───────────────────────────────────────────────────────────────┤
│ L4  Transport Routing     TransportRouter                       │
│                           policy: order, failover/broadcast     │
├───────────────────────────────────────────────────────────────┤
│ L3  Transport Adapters    GrpcWifiTransport │ BleGattTransport   │
│                           both move the SAME serialized bytes   │
├───────────────────────────────────────────────────────────────┤
│ L2  Domain Model           entity_builder.py                     │
│      (world.proto)         raw reading → world_pb2.Entity        │
├───────────────────────────────────────────────────────────────┤
│ L1  Sensor Driver          read_bme280.py  (I2C, unchanged)      │
└───────────────────────────────────────────────────────────────┘
        │
        └── sibling, not a layer: save_reading() → SQLite → Flask
            dashboard. Fed directly from L1/L6, never routed
            through L2–L5 — its failure domain stays independent
            of whether any radio or hub is reachable (Section 2).
```

The load-bearing property: **L2 is the only place that knows about the BME280.** Everything from L3 up only ever handles `world_pb2.Entity` — the exact protobuf type Hydris itself uses on the wire. WiFi and BLE aren't "two data formats to keep in sync," they're two ways of moving the identical serialized bytes:

- The WiFi adapter hands the `Entity` object straight to `WorldServiceStub.Push()` — gRPC *is* protobuf-over-HTTP/2, so no re-encoding happens at all.
- The BLE adapter calls `entity.SerializeToString()` and chunks the resulting bytes across a GATT characteristic (BLE's MTU is much smaller than a network packet). Whatever's listening on the other end deserializes with `Entity.FromString(...)` and calls the same `Push()` RPC. Same struct, same fields, different wire.

That symmetry is what makes routing between them a policy decision (L4) instead of two divergent code paths.

### 8.1 Module layout

```
read_bme280.py               # L1 — unchanged
model/entity_builder.py      # L2 — world.proto adapter
transport/base.py            # L3 — Transport protocol + result type
transport/grpc_wifi.py       # L3 — WiFi/gRPC adapter
transport/ble_gatt.py        # L3 — BLE GATT peripheral adapter (structural sketch, see 9.4)
routing/transport_router.py  # L4 — transport selection policy
reliability/pending_store.py # L5 — last-unsent-entity buffer
collector.py, start_all.py   # L6 — both existing entry points, extended
```

`reliability/`, not `queue/`: a top-level `queue/` package shadows Python's stdlib `queue` module for the whole process once the repo root is on `sys.path` — confirmed while building this (`grpcio` imports `queue` internally, and it silently becomes unreachable the moment a local `queue/` directory sits earlier on the path). Caught before it shipped; worth remembering if this layout is ever extended.

## 9. Reference implementation

This section matches what's actually in the repo, not a sketch — every field/enum name below was checked against the installed `platform-proto` package (`git+https://github.com/projectqai/proto.git#subdirectory=python`, version `0.1.0`) rather than inferred from the TypeScript docs. Three corrections came out of that check (all previously marked `[verify]`):

- `platform_proto.metrics_pb2` is a real, separate module from `world_pb2`, exactly as guessed.
- `MetricKindPressure` / `MetricUnitHectopascal` exist with those exact names. There is **no** `MetricKindAltitude`.
- `DeviceComponent`'s `class` field keeps its literal proto name in the generated Python — there is no `class_` alias, because the generated `.pyi` stub simply omits typed accessors for reserved-keyword fields. It has to be set via dict-unpacking: `DeviceComponent(**{"class": "weather"})`; a bare `class=` kwarg is a Python syntax error. `DeviceState` values (e.g. `DeviceStateActive`) are plain int module-level constants on `world_pb2`, not strings — assign directly, no quotes.

### 9.1 L2 — Domain model (`model/entity_builder.py`)

Also sets `Metric.range` from the BME280's datasheet-published operating range (Bosch `BST-BME280-DS001-24`, tables 2-4: -40…85°C, 0…100% RH, 300…1100 hPa) — a direct use of the `range` field the earlier datasheet analysis flagged as the natural home for exactly this.

```python
from dataclasses import dataclass

from google.protobuf.timestamp_pb2 import Timestamp
from platform_proto import metrics_pb2, world_pb2

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
    ts = Timestamp()
    ts.FromDatetime(measured_at)

    device = world_pb2.DeviceComponent(**{"class": "weather"})  # `class` can't be a kwarg name
    device.state = world_pb2.DeviceStateActive

    return world_pb2.Entity(
        id=station.entity_id,
        label=station.label,
        geo=world_pb2.GeoSpatialComponent(latitude=station.lat, longitude=station.lon, altitude=station.alt),
        device=device,
        sensor=world_pb2.SensorComponent(),
        metric=metrics_pb2.MetricComponent(metrics=[
            metrics_pb2.Metric(id=1, label="Temperature", kind=metrics_pb2.MetricKindTemperature,
                                unit=metrics_pb2.MetricUnitCelsius, double=reading["temperature_c"],
                                measured_at=ts, range=_TEMPERATURE_RANGE),
            metrics_pb2.Metric(id=2, label="Humidity", kind=metrics_pb2.MetricKindHumidity,
                                unit=metrics_pb2.MetricUnitPercent, double=reading["humidity_percent"],
                                measured_at=ts, range=_HUMIDITY_RANGE),
            metrics_pb2.Metric(id=3, label="Pressure", kind=metrics_pb2.MetricKindPressure,
                                unit=metrics_pb2.MetricUnitHectopascal, double=reading["pressure_hpa"],
                                measured_at=ts, range=_PRESSURE_RANGE),
        ]),
    )
```

### 9.2 L3 — Transport abstraction (`transport/base.py`)

```python
from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

from platform_proto.world_pb2 import Entity


class TransportKind(Enum):
    WIFI = auto()
    BLE = auto()


@dataclass
class TransportResult:
    kind: TransportKind
    ok: bool
    detail: str = ""


class Transport(Protocol):
    kind: TransportKind

    def is_available(self) -> bool:
        """Cheap, local check — no guarantee send() succeeds, just a hint for routing."""
        ...

    def send(self, entity: Entity) -> TransportResult: ...
```

### 9.3 L3 — WiFi/gRPC adapter (`transport/grpc_wifi.py`)

Verified end-to-end against a real (unreachable) target: `send()` against a dead server on `localhost` returns `TransportResult(ok=False, detail='StatusCode.UNAVAILABLE')` rather than raising — the `except grpc.RpcError` path actually works, not just compiles. No live Hydris engine was available in this environment to confirm a *successful* push, only that failure is handled cleanly; that half still needs a real engine to exercise.

```python
"""
Native transport: gRPC already speaks world.proto directly, so this
adapter does no translation — it hands the Entity straight to the RPC.
"""

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
```

### 9.4 L3 — BLE GATT adapter (`transport/ble_gatt.py`)

Created as scoped — structurally complete (implements the `Transport` protocol, imports fine), but deliberately not deeply verified in this pass: `bluezero` isn't installed and there's still no hub-side receiver to test against (open items #5-7 below still stand). Lower priority than getting WiFi solid, per the build task's own scope note.

```python
"""
Non-native transport: BLE GATT has no concept of protobuf, so this
adapter serializes the same Entity to bytes and chunks it across a
custom characteristic. The Pi is the BLE *peripheral* here — the
mirror image of Hydris's own `airthings` example plugin, which is
written to be the *central* that connects out to a sensor. Something
on the hub side (a Hydris plugin using Hydris.bluetooth as central, or
a standalone BLE-central bridge daemon) has to connect in, reassemble
the chunks, and call the same WorldService.Push — that piece is not
part of this repo and is a hard prerequisite for this transport to do
anything (see open item #5 below).

Framing: GATT writes/notifies are capped by the negotiated MTU (as low
as 20 bytes on BLE 4.x, more on 4.2+/5). A serialized weather Entity is
well under 1KB, so a 1-byte "is this the last chunk" flag plus payload
is enough -- no need for anything fancier.
"""

from platform_proto.world_pb2 import Entity

from .base import Transport, TransportKind, TransportResult

SERVICE_UUID = "REPLACE-WITH-PRIVATE-128BIT-UUID"
ENTITY_CHAR_UUID = "REPLACE-WITH-PRIVATE-128BIT-UUID"
CHUNK_SIZE = 180  # conservative default; negotiate up via MTU exchange if the central supports it


class BleGattTransport:
    kind = TransportKind.BLE

    def __init__(self, adapter_address: str, device_name: str):
        # [verify] BlueZ peripheral/GATT-server library choice — `bluezero` is one
        # option; raw BlueZ D-Bus (GattService1/GattCharacteristic1) is the fallback
        # if it proves too limited. Peripheral mode on Linux is materially less
        # turnkey than central/scanning mode (Section 7).
        from bluezero import peripheral

        self._peripheral = peripheral.Peripheral(adapter_address, local_name=device_name)
        self._peripheral.add_service(srv_id=1, uuid=SERVICE_UUID, primary=True)
        self._peripheral.add_characteristic(
            srv_id=1, chr_id=1, uuid=ENTITY_CHAR_UUID,
            value=[], notifying=False, flags=["read", "notify"],
        )
        self._published = False

    def is_available(self) -> bool:
        # Unlike WiFi, BLE peripheral mode has no clean local "link up" signal —
        # success really means "a central is connected and subscribed," which
        # this adapter can't verify before attempting a send. Treat this as
        # optimistic availability, not a real health check (open item #6).
        return True

    def send(self, entity: Entity) -> TransportResult:
        payload = entity.SerializeToString()
        chunks = [payload[i:i + CHUNK_SIZE] for i in range(0, len(payload), CHUNK_SIZE)] or [b""]
        try:
            for i, chunk in enumerate(chunks):
                framed = bytes([1 if i == len(chunks) - 1 else 0]) + chunk
                self._peripheral.characteristics[0].set_value(list(framed))
                if not self._published:
                    self._peripheral.publish()
                    self._published = True
            return TransportResult(self.kind, True)
        except Exception as e:  # BlueZ D-Bus errors aren't a narrow, well-known type
            return TransportResult(self.kind, False, str(e))
```

### 9.5 L4 — Transport router (`routing/transport_router.py`)

```python
"""
The only place that decides WiFi vs. BLE vs. both. Everything below
this is transport-agnostic; everything above it only calls router.send().
"""

from enum import Enum, auto

from platform_proto.world_pb2 import Entity

from transport.base import Transport, TransportResult


class RouterMode(Enum):
    FAILOVER = auto()   # try transports in order, stop at first success
    BROADCAST = auto()  # send on every available transport


class TransportRouter:
    def __init__(self, transports: list[Transport], mode: RouterMode = RouterMode.FAILOVER):
        self._transports = transports  # order = preference
        self._mode = mode

    def send(self, entity: Entity) -> list[TransportResult]:
        results = []
        for t in self._transports:
            if not t.is_available():
                continue
            result = t.send(entity)
            results.append(result)
            if self._mode is RouterMode.FAILOVER and result.ok:
                break
        return results
```

`TransportRouter([GrpcWifiTransport(...), BleGattTransport(...)])` prefers WiFi and only falls back to BLE if WiFi is unavailable or the push fails — a reasonable default, since WiFi is higher-bandwidth and native to gRPC. `RouterMode.BROADCAST` sends on both, useful during a migration or if you want BLE as a redundant path rather than a fallback. A further extension worth naming but not building yet: a **power-aware policy** that prefers BLE over WiFi specifically while the node is duty-cycling on battery (Section 6, Option A) — WiFi association is the more expensive radio state of the two — and reverts to WiFi-preferred when on mains. That's a policy swapped into the same `TransportRouter` shape, not a new layer.

### 9.6 L5 — Reliability (`reliability/pending_store.py`)

Renamed from the original `queue/pending_store.py` sketch — see Section 8.1 for why `queue/` was a landmine. One more fix needed here: `Entity | None` (PEP 604 union syntax) throws `TypeError` at class-definition time on Python 3.9, which is what Raspberry Pi OS Bullseye ships — caught by actually running this on 3.9, not just reading it. Fixed with `from __future__ import annotations`, which defers annotation evaluation and works from Python 3.7 up.

```python
from __future__ import annotations  # `Entity | None` needs this on Python < 3.10

from platform_proto.world_pb2 import Entity


class PendingEntityStore:
    def __init__(self):
        self._pending: Entity | None = None

    def stash(self, entity: Entity) -> None:
        self._pending = entity

    def clear(self) -> None:
        self._pending = None

    def pending(self) -> Entity | None:
        return self._pending
```

### 9.7 L6 — Orchestration (`collector.py` and `start_all.py`, both extended)

`start_all.py` is the one that actually matters: it's what `bme280.service` runs (`ExecStart=... start_all.py`), not `collector.py`, which the README documents as a standalone/manual-test script. Both got the same wiring so they don't silently diverge.

Only WiFi is wired into the router for now — `BleGattTransport` is left out of the transport list until Section 9.4's open items close, rather than constructing it unconditionally and having it fail confusingly. Hydris publishing is fully optional: if `HYDRIS_SERVER` isn't set, `transports` is empty, the router has nothing to try, and the loop behaves exactly as it did before this build (SQLite write only) — no new failure mode for anyone who doesn't set the env var.

```python
from model.entity_builder import StationConfig, build_weather_entity
from reliability.pending_store import PendingEntityStore
from routing.transport_router import RouterMode, TransportRouter
from transport.grpc_wifi import GrpcWifiTransport

HYDRIS_SERVER = os.environ.get("HYDRIS_SERVER")
# ... HYDRIS_ENTITY_ID / HYDRIS_LABEL / HYDRIS_LAT / HYDRIS_LON / HYDRIS_ALT, same pattern

station = StationConfig(entity_id=HYDRIS_ENTITY_ID, label=HYDRIS_LABEL,
                         lat=HYDRIS_LAT, lon=HYDRIS_LON, alt=HYDRIS_ALT)
transports = [GrpcWifiTransport(HYDRIS_SERVER)] if HYDRIS_SERVER else []
router = TransportRouter(transports, mode=RouterMode.FAILOVER)
pending = PendingEntityStore()

while True:
    # ... existing sensor read + save_reading(...) unconditionally, unchanged ...

    if transports:
        try:
            reading = {"temperature_c": temperature, "humidity_percent": humidity, "pressure_hpa": pressure}
            entity = pending.pending() or build_weather_entity(reading, station, measured_at=now_utc())
            results = router.send(entity)
            pending.clear() if any(r.ok for r in results) else pending.stash(entity)
        except Exception as e:
            print(f"Hydris publish error (continuing): {e}")  # never take down local logging above

    time.sleep(INTERVAL_SECONDS)
```

The local SQLite write happens unconditionally, before the `if transports:` block, and the Hydris side is wrapped in its own `try/except` on top of that — two independent layers of isolation, not one, matching Section 2's decision.

### 9.8 Dependencies

Added to `requirements.txt` (grpcio/protobuf/platform-proto only — `bluezero` stays commented out until BLE has something to talk to):

```
grpcio>=1.60.0
protobuf>=5.0.0
platform-proto @ git+https://github.com/projectqai/proto.git#subdirectory=python
# bluezero>=0.8.0  # uncomment once there is a hub-side BLE receiver
```

The ARMv6-vs-ARMv7 caveat is real but untested here (this was built and verified in a macOS venv, not on Pi hardware): `grpcio` ships prebuilt wheels for `armv7l`/`aarch64` (Pi Zero 2 W and up) via piwheels, but the original Pi Zero W (`armv6l`) may fall back to a from-source build — slow and memory-hungry on 512 MB of RAM. Smoke-test on the actual target board before relying on this.

## 10. Open items

### Resolved

Checked directly against the installed `platform-proto` 0.1.0 package rather than left as guesses:

1. `MetricKindPressure` / `MetricUnitHectopascal` — confirmed to exist with exactly those names. No `MetricKindAltitude` exists at all (Section 3 already recommended omitting altitude; this confirms there wasn't even an enum member for it).
2. `platform_proto.metrics_pb2` is a real, separate module from `platform_proto.world_pb2` — the Python equivalent of the TypeScript `@projectqai/proto/metrics` import.
3. `DeviceComponent`'s `class` field has no `class_` alias — the generated `.pyi` stub omits a typed accessor for it entirely because `class` is a Python keyword, but the field is still real and settable via `DeviceComponent(**{"class": "weather"})` or `setattr(msg, "class", ...)`.
4. `DeviceState` values (`DeviceStateActive`, etc.) are plain int constants directly on `world_pb2` (`world_pb2.DeviceStateActive`), not strings — confirmed by inspecting `world_pb2.DeviceState.items()`.

Also caught two things nobody had asked to verify, both real bugs found by actually running the code rather than reading it:

- A `queue/` package name collides with Python's stdlib `queue` module (which `grpcio` imports internally) the moment the repo root is on `sys.path` — renamed to `reliability/` (Section 8.1).
- `Entity | None` (PEP 604 syntax) throws `TypeError` at class-definition time on Python 3.9 (Raspberry Pi OS Bullseye's default) — fixed with `from __future__ import annotations` in `reliability/pending_store.py`.

### Still open

Specific to the BLE path (`transport/ble_gatt.py`, Section 9.4) — untouched by this build pass because there's nothing to test it against yet:

5. **The hub-side BLE receiver doesn't exist and isn't optional.** A Pi advertising entity bytes over GATT does nothing on its own — something has to run as the BLE central, connect in, reassemble chunks, and call `WorldService.Push`: either a Hydris plugin using `Hydris.bluetooth.requestDevice()`/`openBLEStream()` from inside the engine, or a standalone bridge daemon. This has to exist before BLE is anything more than a structural placeholder.
6. `BleGattTransport.is_available()` is honestly still a stub returning `True` unconditionally — BLE peripheral mode has no local equivalent of WiFi's "am I associated." A meaningful check needs to track whether a central is connected and subscribed (BlueZ exposes this via D-Bus properties), not implemented here.
7. `bluezero`'s peripheral/GATT-server API surface was not installed or exercised in this pass (deliberately, per the build task's scope) — the import and constructor calls in `transport/ble_gatt.py` are unverified against a real BlueZ stack.
### Verified on real hardware

Everything above was originally built and checked in a macOS venv; the following was then re-verified directly on the actual target device over SSH (a Pi Zero 2 W, hostname `raspberrypi`, `armv7l`, Debian Bookworm, Python 3.11.2):

- `pip install -r requirements.txt` — **`grpcio` installed from a prebuilt wheel** (`grpcio-1.83.1-cp311-cp311-linux_armv7l.whl`), no from-source build, full install in ~1 minute. Resolves the `armv7l` half of the wheel-availability concern in Section 9.8.
- I2C had to be enabled first (`dtparam=i2c_arm=on` was commented out — a fresh SD card image doesn't turn this on by itself, matching the README's own "Enable I2C" step). Once enabled and rebooted, `i2cdetect -y 1` found the BME280 at `0x77`.
- A real sensor reading (25.6°C, 35.0% RH, 981.4 hPa) was run through `build_weather_entity()` → `TransportRouter` → a minimal throwaway gRPC server implementing just `WorldService.Push` — confirming a **successful** push end-to-end (not just the clean-failure path tested earlier): the fake server received `kind=1/unit=1` (Temperature/Celsius), `kind=3/unit=20` (Humidity/Percent), `kind=2/unit=10` (Pressure/Hectopascal) — exactly the enum values expected, and `pending.clear()` fired correctly on success.
- `start_all.py` (the actual systemd entry point) was run as-is: with `HYDRIS_SERVER` unset it behaves identically to before this change (SQLite write + working `/api/readings` dashboard, no Hydris code path touched); with `HYDRIS_SERVER` pointed at a dead port, local logging and the dashboard kept working, `save_reading()` never affected.

**Still genuinely unverified**: the original Pi Zero W's `armv6l` wheel availability — this test hardware is the newer Pi Zero 2 W, a different architecture. And this was checked against a hand-written stand-in for exactly one RPC (`Push`); it hasn't been checked against the real Hydris engine binary, which may reject or handle the request differently in ways a minimal fake server can't surface.

## 11. Future path: a real native plugin

If Hydris's Node Peripherals HAL ever grows I2C/SPI support (worth watching the repo for, or filing as a feature request — the HAL already spans BLE and serial across four platforms, so the abstraction is clearly extensible), the migration is small and mostly a wash:

- Same entity/component shape from Section 3, same L2 domain-model boundary from Section 8 — neither changes based on transport.
- L2's `build_weather_entity()` becomes a TypeScript equivalent inside an `attach({ run: ... })` block; L3–L5 (transport adapters, router, pending store) simply disappear, since the plugin already has a local gRPC client for free — no transport choice needed once you're in-process with the engine.
- You'd gain: one less moving process (no separate publisher, no cross-network hop for local-node data), automatic heartbeat/health reporting via the plugin's `health()` callback, and OCI-image distribution if you ever want to share this as a reusable "BME280 weather node" plugin for other Hydris users.
- You'd still keep the existing Python I2C driver logic conceptually (BME280 register math doesn't change) — only the transport/wrapper layer moves from a standalone Python process to a Bun-hosted TypeScript one, or you'd shell out to the Python reader from the plugin, which is its own can of worms Hydris doesn't document either way.

Until then, Option A is not a compromise — it's the integration path Hydris's own docs point external hardware at.
