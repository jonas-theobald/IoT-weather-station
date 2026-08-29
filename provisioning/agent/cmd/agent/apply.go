//go:build linux

package main

import (
	"bytes"
	"fmt"
	"log"
	"os"
	"os/exec"
	"strconv"
	"strings"

	pb "github.com/projectqai/proto/go"
)

// Applying config is the reason this agent runs as root: it writes
// system drop-ins, joins WiFi networks and restarts services. The PSK
// is handled write-only -- it goes to NetworkManager and nowhere else:
// never logged, never persisted, never reported back.

const dropinPath = "/etc/systemd/system/bme280.service.d/hydris.conf"

// Emission control (EMCON). Radio state cannot touch the provisioning
// link (USB is non-RF), so it is applied FIRST: enabling bluetooth
// before the station restart lets the service's ExecStartPost re-add
// the BLE advertisement -- externally registered adv instances die on
// radio churn.
func wifiAllowed(mode string) bool { return mode == "" || mode == "all" || mode == "wifi-only" }
func bleAllowed(mode string) bool  { return mode == "" || mode == "all" || mode == "ble-only" }

func validEmissionMode(mode string) bool {
	switch mode {
	case "", "all", "wifi-only", "ble-only", "silent":
		return true
	}
	return false
}

func applyEmissionControl(mode string) error {
	if mode == "" {
		return nil // absent: leave the radios untouched
	}
	wifi, ble := "off", "block"
	if wifiAllowed(mode) {
		wifi = "on"
	}
	if bleAllowed(mode) {
		ble = "unblock"
	}
	// Both persist across reboots (NetworkManager state / systemd-rfkill).
	if err := run("nmcli", "radio", "wifi", wifi); err != nil {
		return fmt.Errorf("wifi radio: %w", err)
	}
	if err := run("/usr/sbin/rfkill", ble, "bluetooth"); err != nil {
		return fmt.Errorf("bluetooth radio: %w", err)
	}
	return nil
}

func applyConfig(cfg *pb.ConfigurationComponent) error {
	values := cfg.GetValue().AsMap()

	mode, _ := values["emission_mode"].(string)
	if !validEmissionMode(mode) {
		return fmt.Errorf("unknown emission_mode %q", mode)
	}
	if err := applyEmissionControl(mode); err != nil {
		return err
	}

	// identify is an action riding the config channel, not a setting:
	// execute it, then treat it like the PSK -- never persisted.
	if on, _ := values["identify"].(bool); on {
		go blinkLED(15)
	}
	delete(values, "identify")

	if ssid, _ := values["wifi_ssid"].(string); ssid != "" && wifiAllowed(mode) {
		if cc, _ := values["wifi_country"].(string); cc != "" {
			if err := run("raspi-config", "nonint", "do_wifi_country", cc); err != nil {
				return fmt.Errorf("wifi country: %w", err)
			}
		}
		args := []string{"device", "wifi", "connect", ssid, "ifname", "wlan0"}
		if psk, _ := values["wifi_psk"].(string); psk != "" {
			args = append(args, "password", psk)
		}
		log.Printf("joining wifi %q (psk redacted)", ssid)
		if err := runUnlogged("nmcli", args...); err != nil {
			return fmt.Errorf("wifi connect: %w", err)
		}
	}

	if err := writeHydrisDropin(values); err != nil {
		return err
	}

	delete(values, "wifi_psk") // write-only: never persisted, never reported
	return saveState(appliedState{Version: cfg.GetVersion(), Values: values})
}

// The drop-in is rewritten whole from the pushed values -- config is
// whole-replace semantics end to end, no merging of stale lines.
func writeHydrisDropin(v map[string]any) error {
	var b strings.Builder
	b.WriteString("# Written by provision-agent -- edit via Hydris, not by hand.\n[Service]\n")
	add := func(key, val string) { fmt.Fprintf(&b, "Environment=\"%s=%s\"\n", key, val) }
	if s, _ := v["hydris_server"].(string); s != "" {
		add("HYDRIS_SERVER", s)
	}
	if s, _ := v["entity_id"].(string); s != "" {
		add("HYDRIS_ENTITY_ID", s)
	}
	if s, _ := v["label"].(string); s != "" {
		add("HYDRIS_LABEL", s)
	}
	// The app layer follows the radio: no BLE peripheral when emission
	// control has the bluetooth radio off.
	mode, _ := v["emission_mode"].(string)
	if on, _ := v["ble_enabled"].(bool); on && bleAllowed(mode) {
		add("HYDRIS_BLE", "1")
	}
	if s, _ := v["ble_name"].(string); s != "" {
		add("HYDRIS_BLE_NAME", s)
	}
	if n, ok := v["interval_seconds"].(float64); ok && n >= 5 {
		add("HYDRIS_INTERVAL", strconv.Itoa(int(n)))
	}
	if err := os.MkdirAll("/etc/systemd/system/bme280.service.d", 0o755); err != nil {
		return err
	}
	if err := os.WriteFile(dropinPath, []byte(b.String()), 0o644); err != nil {
		return err
	}
	if err := run("systemctl", "daemon-reload"); err != nil {
		return err
	}
	return run("systemctl", "restart", "bme280")
}

func run(name string, args ...string) error {
	log.Printf("run: %s %s", name, strings.Join(args, " "))
	out, err := exec.Command(name, args...).CombinedOutput()
	if err != nil {
		return fmt.Errorf("%s: %v: %s", name, err, bytes.TrimSpace(out))
	}
	return nil
}

// runUnlogged never puts its arguments in logs or error text -- for
// commands that carry secrets (nmcli with a PSK).
func runUnlogged(name string, args ...string) error {
	out, err := exec.Command(name, args...).CombinedOutput()
	if err != nil {
		return fmt.Errorf("%s failed: %v: %s", name, err, bytes.TrimSpace(out))
	}
	return nil
}
