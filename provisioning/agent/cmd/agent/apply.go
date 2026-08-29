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

func applyConfig(cfg *pb.ConfigurationComponent) error {
	values := cfg.GetValue().AsMap()

	if ssid, _ := values["wifi_ssid"].(string); ssid != "" {
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
	if on, _ := v["ble_enabled"].(bool); on {
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
