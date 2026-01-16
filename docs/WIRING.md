# Wiring Guide

## BME280 to Raspberry Pi Zero Connection

### Pin Reference

```
Raspberry Pi Zero GPIO Header (looking at the board with USB ports facing down)

                    3V3  (1)  (2)  5V
          SDA/GPIO2 (3)  (4)  5V
          SCL/GPIO3 (5)  (6)  GND
              GPIO4 (7)  (8)  GPIO14/TX
                GND (9)  (10) GPIO15/RX
             GPIO17 (11) (12) GPIO18
             GPIO27 (13) (14) GND
             GPIO22 (15) (16) GPIO23
                3V3 (17) (18) GPIO24
    SPI_MOSI/GPIO10 (19) (20) GND
     SPI_MISO/GPIO9 (21) (22) GPIO25
    SPI_SCLK/GPIO11 (23) (24) GPIO8/CE0
                GND (25) (26) GPIO7/CE1
              GPIO0 (27) (28) GPIO1
              GPIO5 (29) (30) GND
              GPIO6 (31) (32) GPIO12
             GPIO13 (33) (34) GND
             GPIO19 (35) (36) GPIO16
             GPIO26 (37) (38) GPIO20
                GND (39) (40) GPIO21
```

### Connection Table

| BME280 Pin | Wire Color (suggested) | Pi Zero Pin | Pi Zero GPIO |
|------------|------------------------|-------------|--------------|
| VIN / VCC  | Red                    | Pin 1       | 3.3V         |
| GND        | Black                  | Pin 6       | Ground       |
| SCL        | Yellow                 | Pin 5       | GPIO 3 (SCL) |
| SDA        | Blue                   | Pin 3       | GPIO 2 (SDA) |

### Wiring Diagram

```
BME280 Module          Jumper Wires         Raspberry Pi Zero
┌─────────────┐                            ┌──────────────────┐
│             │                            │                  │
│    VIN ─────┼──── Red ───────────────────┼── Pin 1 (3.3V)   │
│             │                            │                  │
│    GND ─────┼──── Black ─────────────────┼── Pin 6 (GND)    │
│             │                            │                  │
│    SCL ─────┼──── Yellow ────────────────┼── Pin 5 (GPIO3)  │
│             │                            │                  │
│    SDA ─────┼──── Blue ──────────────────┼── Pin 3 (GPIO2)  │
│             │                            │                  │
└─────────────┘                            └──────────────────┘
```

### Important Notes

1. **Voltage**: Use 3.3V (Pin 1), NOT 5V. The BME280 is a 3.3V device.

2. **I2C Address**: Most BME280 modules use address `0x76` or `0x77`. The software auto-detects this.

3. **Module Variations**: Some BME280 modules have 6 pins (VIN, GND, SCL, SDA, CSB, SDO). Only the first 4 are needed for I2C mode.

4. **Pull-up Resistors**: Most BME280 breakout boards include pull-up resistors. If using a bare sensor, you may need 4.7kΩ pull-ups on SDA and SCL.

### Verifying the Connection

After wiring, run:

```bash
sudo i2cdetect -y 1
```

Expected output (sensor at address 0x77):
```
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
70: -- -- -- -- -- -- -- 77
```

If you see `76` or `77`, the sensor is connected correctly.

### Troubleshooting

| Issue | Solution |
|-------|----------|
| No device detected | Check all wire connections |
| i2cdetect command not found | Run: `sudo apt install i2c-tools` |
| Permission denied | Run with `sudo` |
| Multiple devices shown | Normal if you have other I2C devices |
