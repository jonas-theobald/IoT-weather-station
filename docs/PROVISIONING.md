# USB Provisioning

How a Pi gets configured over a USB cable, via Hydris. Counterpart of
the hub-side [hydris-pi-provisioner](https://github.com/jonas-theobald/hydris-pi-provisioner) plugin.

```
 Hydris UI (Configure form)          engine                          Pi Zero 2 W
┌─────────────────────────┐  entity ┌──────────────────────┐ CDC ACM ┌────────────────────────┐
│ provision.<serial>      │◀──────▶│ pi-provisioner plugin │◀═══════▶│ provision-agent (Go,   │
│ config + live status    │  world  │ Hydris.serial.open    │ framed  │ root, /dev/ttyGS0)     │
└─────────────────────────┘  model  └──────────────────────┘ protobuf└───────────┬────────────┘
                                                              writes: NetworkManager (WiFi),
                                                              bme280 drop-in, service restarts
```

**Trust model:** physical USB possession is the trust anchor — the
industry norm for provisioning. Credentials cross only the cable; the
WiFi PSK is write-only end to end (never logged, persisted, or
reported back by the agent).

## Components on the Pi

| Piece | Path | Job |
|---|---|---|
| gadget script | `provisioning/usb-gadget.sh` → `/usr/local/sbin/` | builds the USB identity at boot via configfs: CDC ACM function, product string "PiZero Weather Provisioning", **serialnumber = SoC serial** |
| gadget unit | `provisioning/usb-gadget.service` | oneshot at boot; fails loudly if the controller isn't in peripheral mode |
| agent | `provisioning/agent/` (Go) → `/usr/local/sbin/provision-agent` | answers RPCs on `/dev/ttyGS0`; static cross-compiled binary, zero runtime deps — the repair channel must not share a failure domain with what it repairs |
| agent unit | `provisioning/pi-provision.service` | root (writes system config), `Restart=always` |

Build: `cd provisioning/agent && GOOS=linux GOARCH=arm GOARM=7 CGO_ENABLED=0 go build -o provision-agent ./cmd/agent`

## Wire protocol

Serial is a byte stream, so frames (see `agent/framing/`, twin
implementation + shared test vectors in the plugin repo):

```
magic(2)=B2 80 | ver(1)=01 | type(1) | seq(1) | len(4 LE) | payload
```

| type | payload → response | meaning |
|---|---|---|
| `0x01` GetEntity | – → `world.Entity` | full status: applied config, metrics, IP, service state |
| `0x02` Push | `EntityChangeRequest` → `world.Entity` | apply config; response reports what is now true |
| `0x03` Event | `world.Entity` | reserved (unused — see polling note) |
| `0x04` Read | `Struct{keys:[…]}` → `Struct` | whitelisted named reads: `sensor` (live BME280 via the station's local API), `system` (hostname/os/kernel/model) |
| `0x05` Write | `Struct{key:arg}` → `Struct` | whitelisted actions: `identify` (blink ACT LED), `reboot` |

Responses echo the request type with the top bit set (`0x01→0x81`) and
the same seq. **Status is host-polled (10 s), never agent-pushed:**
gadget serial writes block forever when no host is reading, so the
agent only writes when a request proves a reader exists.

## Entity model

One `provision.<SoC serial>` entity per device, under
`provisioner.service` — deliberately **separate** from the station
entity: provisioning precedes identity (a virgin Pi has no station id
yet), the lifetimes differ (bench session vs permanent asset), and the
config namespaces must not collide. The binding is explicit instead:
both entities share `device.unique_hardware_id`, and after
provisioning `device.composition` points at the configured station id.

Metric id namespace (shared discipline across the system):

| ids | owner | meaning |
|---|---|---|
| 1–3 | station | temperature / humidity / pressure |
| 10–11 | transports | "WiFi updates" / "BLE updates" counters |
| 20–23 | agent | uptime, CPU temp, WiFi signal, station service state |
| 24–26 | plugin | sensor check — live readings pulled through the USB cable |
| 27–28 | agent | emission control truth: WiFi radio / Bluetooth radio actually on |

Config keys: `wifi_ssid`, `wifi_psk` (write-only), `wifi_country`,
`hydris_server`, `ble_enabled`, `ble_name`, `entity_id`, `label`,
`interval_seconds`, `emission_mode`, `identify` (action, not
persisted). Ack semantics: the plugin sets
`configurable.applied_version = config.version` after a successful
apply.

### Emission control (EMCON)

`emission_mode` ∈ `all` | `wifi-only` | `ble-only` | `silent` — which
radios may emit. Absent = radios untouched. Applied via
`nmcli radio wifi` and `rfkill block bluetooth` (both persist across
reboots), **first** in the apply sequence — radio state can't touch
the USB provisioning link. After the radios are set the agent kicks
`ble-advert.service`, the single owner of the BLE advertisement
(externally registered adv instances die silently on radio churn and
don't resume after a connection drops; its 60s reconcile timer is the
guarantee, the kick just makes it prompt). The app layer follows: no
BLE peripheral while the bluetooth radio is blocked.

**`ble-only` and `silent` cut WiFi — and SSH and the gRPC push with
it.** That is the feature, not a bug: a silenced station keeps
logging locally, and the USB provisioning channel remains the non-RF
way to reach it and lift the restriction. Don't set these modes
remotely-by-habit; set them with the cable in hand.

## Desk CLI

```
cd provisioning/agent && go build -o poke ./cmd/poke
./poke                      # GetEntity as prototext
./poke -read sensor,system  # whitelisted reads as JSON
```

Only one reader per port: use poke when the plugin isn't connected.

## Gotchas (each cost real debugging)

- **`config.txt` is sectioned.** `[cm4]`/`[cm5]` headers scope every
  line below them to that board. The dwc2 overlay must sit under
  `[all]`: `dtoverlay=dwc2,dr_mode=peripheral`. A line in the wrong
  section fails silently — no UDC in `/sys/class/udc`.
- **macOS gates new USB accessories.** First plug-in needs the "Allow
  accessory to connect?" approval or nothing enumerates.
- **Exactly one reader on each end of the port.** No
  `serial-getty@ttyGS0`; and `ssh host command` orphans its remote
  process when the client dies — a stale agent steals frames.
- **Engine: serial fds leak per plugin dev-cycle.** Every
  `hydris plugin run` re-upload leaks the previous instance's open
  port handle; zombie readers then race for response bytes (RPC
  timeouts). Fix: restart the engine, run the plugin once. Packaged
  plugins (mission pack) don't have this problem.
- **Engine: the hal serial scanner can stall** — `serial.device.*`
  entities vanish while config still says `serial: true`. Toggling the
  hal config off/on revives it; a fresh engine scans fine.
- **Engine: one dev slot.** `hydris plugin run` evicts the previous
  dev plugin.
