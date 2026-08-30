//go:build linux

package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"time"

	"google.golang.org/protobuf/types/known/structpb"
)

// Generic read/write with a hard whitelist: the wire can name a key,
// never a command. Readable: sensor (live BME280 via the station's own
// local API -- the bench test reuses the real pipeline), system.
// Writable: identify (blink the ACT LED), reboot.

func handleRead(req *structpb.Struct) *structpb.Struct {
	out := map[string]any{}
	for _, k := range req.GetFields()["keys"].GetListValue().GetValues() {
		switch k.GetStringValue() {
		case "sensor":
			out["sensor"] = readSensor()
		case "system":
			out["system"] = readSystem()
		case "sync_pending":
			// Store-and-forward over the cable: readings the hub hasn't
			// acked, from the station's own API (the DB stays owned by
			// one codebase). Ack comes back as a sync_ack write.
			out["sync_pending"] = readSyncPending()
		default:
			out[k.GetStringValue()] = map[string]any{"error": "unknown key"}
		}
	}
	s, err := structpb.NewStruct(out)
	if err != nil {
		s, _ = structpb.NewStruct(map[string]any{"error": err.Error()})
	}
	return s
}

func handleWrite(req *structpb.Struct) *structpb.Struct {
	out := map[string]any{}
	for key, val := range req.GetFields() {
		switch key {
		case "identify":
			secs := int(val.GetNumberValue())
			if secs <= 0 || secs > 120 {
				secs = 15
			}
			go blinkLED(secs)
			out["identify"] = "blinking"
		case "reboot":
			if val.GetBoolValue() {
				log.Printf("reboot requested over provisioning link")
				go func() {
					time.Sleep(2 * time.Second) // let the response leave first
					_ = exec.Command("systemctl", "reboot").Run()
				}()
				out["reboot"] = "in 2s"
			}
		case "sync_ack":
			id := int(val.GetNumberValue())
			if id < 0 {
				out["sync_ack"] = "bad id"
				break
			}
			out["sync_ack"] = writeSyncAck(id)
		default:
			out[key] = "unknown key"
		}
	}
	s, _ := structpb.NewStruct(out)
	return s
}

func readSyncPending() map[string]any {
	client := http.Client{Timeout: 5 * time.Second}
	resp, err := client.Get("http://127.0.0.1:5000/api/sync/pending?name=usb&limit=200")
	if err != nil {
		return map[string]any{"error": fmt.Sprintf("station api: %v", err)}
	}
	defer resp.Body.Close()
	var body map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil {
		return map[string]any{"error": fmt.Sprintf("station api: %v", err)}
	}
	return body
}

func writeSyncAck(lastID int) string {
	client := http.Client{Timeout: 5 * time.Second}
	payload := strings.NewReader(fmt.Sprintf(`{"name":"usb","last_id":%d}`, lastID))
	resp, err := client.Post("http://127.0.0.1:5000/api/sync/ack", "application/json", payload)
	if err != nil {
		return fmt.Sprintf("station api: %v", err)
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Sprintf("station api: HTTP %d", resp.StatusCode)
	}
	return "ok"
}

// readSensor asks the station's local dashboard API for the latest
// reading -- if this answers, the sensor, the collector and the web
// server all work. One probe validates the whole station stack.
func readSensor() map[string]any {
	client := http.Client{Timeout: 2 * time.Second}
	resp, err := client.Get("http://127.0.0.1:5000/api/readings?hours=1")
	if err != nil {
		return map[string]any{"error": fmt.Sprintf("station api: %v", err)}
	}
	defer resp.Body.Close()
	var body struct {
		Latest map[string]any `json:"latest"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&body); err != nil || body.Latest == nil {
		return map[string]any{"error": "station api: no reading"}
	}
	return body.Latest
}

func readSystem() map[string]any {
	out := map[string]any{}
	if h, err := os.Hostname(); err == nil {
		out["hostname"] = h
	}
	if data, err := os.ReadFile("/etc/os-release"); err == nil {
		for _, line := range strings.Split(string(data), "\n") {
			if v, ok := strings.CutPrefix(line, "PRETTY_NAME="); ok {
				out["os"] = strings.Trim(v, `"`)
			}
		}
	}
	if data, err := os.ReadFile("/proc/sys/kernel/osrelease"); err == nil {
		out["kernel"] = strings.TrimSpace(string(data))
	}
	if data, err := os.ReadFile("/proc/device-tree/model"); err == nil {
		out["model"] = strings.Trim(string(data), "\x00")
	}
	return out
}

// blinkLED toggles the activity LED so a human can find THIS Pi on a
// bench full of identical ones. Trigger is saved and restored.
func blinkLED(seconds int) {
	base := "/sys/class/leds/ACT"
	if _, err := os.Stat(base); err != nil {
		base = "/sys/class/leds/led0" // older Pi OS naming
		if _, err := os.Stat(base); err != nil {
			log.Printf("identify: no activity LED found")
			return
		}
	}
	oldTrigger := "mmc0"
	if data, err := os.ReadFile(base + "/trigger"); err == nil {
		// current trigger is the [bracketed] entry
		if i := strings.Index(string(data), "["); i >= 0 {
			if j := strings.Index(string(data)[i:], "]"); j > 0 {
				oldTrigger = string(data)[i+1 : i+j]
			}
		}
	}
	_ = os.WriteFile(base+"/trigger", []byte("none"), 0o644)
	log.Printf("identify: blinking for %ds", seconds)
	for i := 0; i < seconds*2; i++ {
		v := "0"
		if i%2 == 0 {
			v = "1"
		}
		_ = os.WriteFile(base+"/brightness", []byte(v), 0o644)
		time.Sleep(250 * time.Millisecond)
	}
	_ = os.WriteFile(base+"/trigger", []byte(oldTrigger), 0o644)
}
