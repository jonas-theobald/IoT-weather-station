//go:build linux

// The provisioning agent: answers world.proto RPCs on the USB gadget
// serial port. Deliberately dependency-free at runtime -- one static
// binary that must keep working while it reconfigures the system
// around itself.
package main

import (
	"log"
	"os"
	"strings"

	pb "github.com/projectqai/proto/go" // generated package is "_go"; always alias
	"golang.org/x/sys/unix"
	"google.golang.org/protobuf/proto"

	"github.com/jonas-theobald/IoT-weather-station/provisioning/agent/framing"
	"github.com/jonas-theobald/IoT-weather-station/provisioning/agent/protocol"
)

const port = "/dev/ttyGS0"

func main() {
	f, err := os.OpenFile(port, os.O_RDWR, 0)
	if err != nil {
		log.Fatalf("open %s: %v", port, err)
	}
	if err := rawMode(int(f.Fd())); err != nil {
		log.Fatalf("raw mode: %v", err)
	}
	sn := serialNumber()
	log.Printf("agent up on %s, serial %s", port, sn)

	dec := &framing.Decoder{}
	buf := make([]byte, 4096)
	for {
		n, err := f.Read(buf)
		if err != nil {
			log.Fatalf("read: %v", err) // systemd restarts us, later milestone
		}
		for _, fr := range dec.Feed(buf[:n]) {
			if err := handle(f, sn, fr); err != nil {
				log.Printf("handle type 0x%02x: %v", fr.Type, err)
			}
		}
	}
}

func handle(w *os.File, sn string, fr framing.Frame) error {
	switch fr.Type {
	case protocol.TypeGetEntity:
		return respond(w, sn, fr, statusEntity(sn))

	case protocol.TypePush:
		var req pb.EntityChangeRequest
		if err := proto.Unmarshal(fr.Payload, &req); err != nil {
			return err
		}
		if len(req.Changes) != 1 || req.Changes[0].Config == nil {
			log.Printf("push without a config change -- ignoring")
			return respond(w, sn, fr, statusEntity(sn))
		}
		cfg := req.Changes[0].Config
		log.Printf("applying config v%d", cfg.GetVersion())
		entity := func() *pb.Entity {
			if err := applyConfig(cfg); err != nil {
				log.Printf("apply v%d failed: %v", cfg.GetVersion(), err)
				e := statusEntity(sn)
				e.Device.State = pb.DeviceState_DeviceStateFailed
				e.Device.Error = proto.String(err.Error())
				return e
			}
			log.Printf("applied config v%d", cfg.GetVersion())
			return statusEntity(sn) // re-read: report what is now true
		}()
		return respond(w, sn, fr, entity)

	default:
		log.Printf("ignoring unknown frame type 0x%02x", fr.Type)
		return nil
	}
}

func respond(w *os.File, sn string, fr framing.Frame, e *pb.Entity) error {
	payload, err := proto.Marshal(e)
	if err != nil {
		return err
	}
	_, err = w.Write(framing.Encode(fr.Type|protocol.RespBit, fr.Seq, payload))
	return err
}

// identityEntity is the agent's self-description: everything the hub
// can know before any configuration has happened.
func identityEntity(sn string) *pb.Entity {
	return &pb.Entity{
		Id:    "provision." + sn,
		Label: proto.String("Pi Provisioning " + sn),
		Device: &pb.DeviceComponent{
			UniqueHardwareId: proto.String(sn),
			Class:            proto.String("provisioning"),
			State:            pb.DeviceState_DeviceStateActive,
		},
	}
}

func serialNumber() string {
	data, err := os.ReadFile("/proc/cpuinfo")
	if err == nil {
		for _, line := range strings.Split(string(data), "\n") {
			if strings.HasPrefix(line, "Serial") {
				if _, after, ok := strings.Cut(line, ":"); ok {
					return strings.TrimSpace(after)
				}
			}
		}
	}
	host, _ := os.Hostname()
	return "unknown-" + host
}

// rawMode disables the tty line discipline: no echo (or the port talks
// to itself), no line buffering, no CR/NL translation, no Ctrl-C
// signals. Bytes pass untouched; read returns at >=1 byte.
func rawMode(fd int) error {
	t, err := unix.IoctlGetTermios(fd, unix.TCGETS)
	if err != nil {
		return err
	}
	t.Iflag &^= unix.IGNBRK | unix.BRKINT | unix.PARMRK | unix.ISTRIP |
		unix.INLCR | unix.IGNCR | unix.ICRNL | unix.IXON
	t.Oflag &^= unix.OPOST
	t.Lflag &^= unix.ECHO | unix.ECHONL | unix.ICANON | unix.ISIG | unix.IEXTEN
	t.Cflag &^= unix.CSIZE | unix.PARENB
	t.Cflag |= unix.CS8
	t.Cc[unix.VMIN] = 1
	t.Cc[unix.VTIME] = 0
	return unix.IoctlSetTermios(fd, unix.TCSETS, t)
}
