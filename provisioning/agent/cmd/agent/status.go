//go:build linux

package main

import (
	"encoding/json"
	"net"
	"os"
	"os/exec"
	"strconv"
	"strings"

	pb "github.com/projectqai/proto/go"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/structpb"
	"google.golang.org/protobuf/types/known/timestamppb"
)

// The agent's answer to "what is currently true on this device": last
// applied config (never the PSK), live system metrics, addresses and
// service state. Everything the hub shows as "current data" comes
// through here.

const stateFile = "/var/lib/pi-provision/state.json"

// Provisioning status metric ids live at 20+ (1-3 are the station's
// readings, 10-11 transport telemetry -- one namespace, documented in
// docs/HYDRIS_INTEGRATION.md).
const (
	metricUptime         = 20
	metricCPUTemp        = 21
	metricWifiRSSI       = 22
	metricStationService = 23
	metricWifiRadio      = 27 // emission control: live radio truth
	metricBleRadio       = 28
)

type appliedState struct {
	Version uint64         `json:"version"`
	Values  map[string]any `json:"values"`
}

func loadState() appliedState {
	var s appliedState
	if data, err := os.ReadFile(stateFile); err == nil {
		_ = json.Unmarshal(data, &s)
	}
	return s
}

func saveState(s appliedState) error {
	if err := os.MkdirAll("/var/lib/pi-provision", 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(s, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(stateFile, data, 0o600)
}

func statusEntity(sn string) *pb.Entity {
	e := identityEntity(sn)

	if st := loadState(); st.Version > 0 {
		if val, err := structpb.NewStruct(st.Values); err == nil {
			e.Config = &pb.ConfigurationComponent{Value: val, Version: st.Version}
		}
	}

	var metrics []*pb.Metric
	metric := func(id uint32, label string, kind *pb.MetricKind, unit pb.MetricUnit, v float64) {
		metrics = append(metrics, &pb.Metric{
			Id: proto.Uint32(id), Label: proto.String(label),
			Kind: kind, Unit: unit,
			Val:        &pb.Metric_Double{Double: v},
			MeasuredAt: timestamppb.Now(),
		})
	}
	if v, ok := readFloatFile("/proc/uptime", 0); ok {
		metric(metricUptime, "Uptime", pb.MetricKind_MetricKindDuration.Enum(), pb.MetricUnit_MetricUnitSecond, v)
	}
	if v, ok := readFloatFile("/sys/class/thermal/thermal_zone0/temp", 0); ok {
		metric(metricCPUTemp, "CPU temperature", pb.MetricKind_MetricKindTemperature.Enum(), pb.MetricUnit_MetricUnitCelsius, v/1000)
	}
	if v, ok := wifiRSSI(); ok {
		metric(metricWifiRSSI, "WiFi signal", pb.MetricKind_MetricKindSignalStrength.Enum(), pb.MetricUnit_MetricUnitDecibelMilliwatt, v)
	}
	active := 0.0
	if out, err := exec.Command("systemctl", "is-active", "bme280").Output(); err == nil &&
		strings.TrimSpace(string(out)) == "active" {
		active = 1
	}
	metric(metricStationService, "Station service", nil, pb.MetricUnit_MetricUnitCount, active)

	// Emission control truth: what the radios ACTUALLY are, not what
	// config asked for.
	wifiRadio := 0.0
	if out, err := exec.Command("nmcli", "radio", "wifi").Output(); err == nil &&
		strings.TrimSpace(string(out)) == "enabled" {
		wifiRadio = 1
	}
	metric(metricWifiRadio, "WiFi radio", nil, pb.MetricUnit_MetricUnitCount, wifiRadio)
	bleRadio := 0.0
	if bluetoothUnblocked() {
		bleRadio = 1
	}
	metric(metricBleRadio, "Bluetooth radio", nil, pb.MetricUnit_MetricUnitCount, bleRadio)
	e.Metric = &pb.MetricComponent{Metrics: metrics}

	if ip := wlanIP(); ip != "" {
		e.Device.Ip = &pb.IpDevice{Host: proto.String(ip)}
	}
	return e
}

// readFloatFile parses the nth whitespace-separated field as a float.
func readFloatFile(path string, field int) (float64, bool) {
	data, err := os.ReadFile(path)
	if err != nil {
		return 0, false
	}
	parts := strings.Fields(string(data))
	if len(parts) <= field {
		return 0, false
	}
	v, err := strconv.ParseFloat(strings.TrimSuffix(parts[field], "."), 64)
	if err != nil {
		return 0, false
	}
	return v, true
}

// wifiRSSI reads the signal level for wlan0 from /proc/net/wireless --
// no exec, no dependencies. Format: iface | status | link | level | ...
func wifiRSSI() (float64, bool) {
	data, err := os.ReadFile("/proc/net/wireless")
	if err != nil {
		return 0, false
	}
	for _, line := range strings.Split(string(data), "\n") {
		fields := strings.Fields(line)
		if len(fields) >= 4 && strings.HasPrefix(fields[0], "wlan0") {
			v, err := strconv.ParseFloat(strings.TrimSuffix(fields[3], "."), 64)
			return v, err == nil
		}
	}
	return 0, false
}

// bluetoothUnblocked reads rfkill state from sysfs -- soft==0 on the
// bluetooth entry means the radio is allowed to emit.
func bluetoothUnblocked() bool {
	entries, err := os.ReadDir("/sys/class/rfkill")
	if err != nil {
		return false
	}
	for _, ent := range entries {
		base := "/sys/class/rfkill/" + ent.Name()
		if t, err := os.ReadFile(base + "/type"); err == nil &&
			strings.TrimSpace(string(t)) == "bluetooth" {
			soft, err := os.ReadFile(base + "/soft")
			return err == nil && strings.TrimSpace(string(soft)) == "0"
		}
	}
	return false
}

func wlanIP() string {
	iface, err := net.InterfaceByName("wlan0")
	if err != nil {
		return ""
	}
	addrs, err := iface.Addrs()
	if err != nil {
		return ""
	}
	for _, a := range addrs {
		if ipn, ok := a.(*net.IPNet); ok && ipn.IP.To4() != nil {
			return ipn.IP.String()
		}
	}
	return ""
}
