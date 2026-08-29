#!/bin/bash
# Builds the USB gadget identity at boot: one CDC ACM serial function.
# The strings below are what the laptop (and the Hydris plugin) will see
# when this device enumerates -- the serialnumber doubles as the same
# hardware identity the station uses everywhere else.
set -euo pipefail

G=/sys/kernel/config/usb_gadget/pizero

modprobe libcomposite

# Make re-runs safe: unbind and tear down any previous gadget first.
if [ -d "$G" ]; then
    echo "" > "$G/UDC" 2>/dev/null || true
    rm -f "$G/configs/c.1/acm.usb0"
    rmdir "$G/configs/c.1/strings/0x409" "$G/configs/c.1" \
          "$G/functions/acm.usb0" "$G/strings/0x409" "$G" 2>/dev/null || true
fi

mkdir -p "$G"
echo 0x1d6b > "$G/idVendor"     # Linux Foundation vendor id
echo 0x0104 > "$G/idProduct"    # "multifunction composite gadget"
echo 0x0100 > "$G/bcdDevice"    # our device revision: 1.0.0
echo 0x0200 > "$G/bcdUSB"       # speaks USB 2.0

SERIAL=$(awk -F': ' '/^Serial/ {print $2}' /proc/cpuinfo)
mkdir -p "$G/strings/0x409"     # 0x409 = US-English string table
echo "$SERIAL"                       > "$G/strings/0x409/serialnumber"
echo "jonas-theobald"                > "$G/strings/0x409/manufacturer"
echo "PiZero Weather Provisioning"   > "$G/strings/0x409/product"

mkdir -p "$G/configs/c.1/strings/0x409"
echo "ACM" > "$G/configs/c.1/strings/0x409/configuration"
echo 250   > "$G/configs/c.1/MaxPower"   # advertised max draw (mA)

mkdir -p "$G/functions/acm.usb0"         # creating the dir CREATES the function
ln -sf "$G/functions/acm.usb0" "$G/configs/c.1/"   # config c.1 includes it

# The "plug in" moment: binding to the UDC (USB Device Controller) starts
# enumeration on the host side. Must be last -- the identity is frozen here.
# Guard first: writing an empty string to UDC is a legal no-op (unbind), so
# a missing controller would otherwise "succeed" silently. Exit 0 must mean
# the gadget is actually live.
UDC=$(ls /sys/class/udc)
[ -n "$UDC" ] || { echo "usb-gadget: no UDC found -- is dwc2 in peripheral mode?" >&2; exit 1; }
echo "$UDC" > "$G/UDC"
