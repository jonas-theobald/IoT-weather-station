//go:build darwin

// poke is the desk probe: one GetEntity round trip over the gadget
// serial port, decoded with the same framing and proto types the real
// hub will use. If this prints an entity, the whole Pi-side stack works.
package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"os"
	"time"

	pb "github.com/projectqai/proto/go"
	"golang.org/x/sys/unix"
	"google.golang.org/protobuf/encoding/prototext"
	"google.golang.org/protobuf/proto"

	"github.com/jonas-theobald/IoT-weather-station/provisioning/agent/framing"
	"github.com/jonas-theobald/IoT-weather-station/provisioning/agent/protocol"
)

func main() {
	port := flag.String("port", "/dev/cu.usbmodem3101", "gadget serial port")
	flag.Parse()

	f, err := os.OpenFile(*port, os.O_RDWR, 0)
	if err != nil {
		log.Fatalf("open %s: %v", *port, err)
	}
	if err := rawMode(int(f.Fd())); err != nil {
		log.Fatalf("raw mode: %v", err)
	}

	const seq = 42
	if _, err := f.Write(framing.Encode(protocol.TypeGetEntity, seq, nil)); err != nil {
		log.Fatalf("write: %v", err)
	}

	dec := &framing.Decoder{}
	buf := make([]byte, 4096)
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		n, err := f.Read(buf)
		if errors.Is(err, io.EOF) {
			continue // VTIME expired with no bytes: silence, keep waiting
		}
		if err != nil {
			log.Fatalf("read: %v", err)
		}
		for _, fr := range dec.Feed(buf[:n]) {
			if fr.Type != protocol.TypeGetEntity|protocol.RespBit || fr.Seq != seq {
				log.Printf("skipping frame type 0x%02x seq %d", fr.Type, fr.Seq)
				continue
			}
			var e pb.Entity
			if err := proto.Unmarshal(fr.Payload, &e); err != nil {
				log.Fatalf("bad entity payload: %v", err)
			}
			fmt.Print(prototext.Format(&e))
			return
		}
	}
	log.Fatal("timeout: no response -- is the agent running on the Pi?")
}

// rawMode, macOS flavor: same intent as the agent's Linux version, but
// Darwin spells the ioctls TIOCGETA/TIOCSETA. VMIN=0/VTIME=10 makes
// reads return after ~1s of silence so the probe can time out politely.
func rawMode(fd int) error {
	t, err := unix.IoctlGetTermios(fd, unix.TIOCGETA)
	if err != nil {
		return err
	}
	t.Iflag &^= unix.IGNBRK | unix.BRKINT | unix.PARMRK | unix.ISTRIP |
		unix.INLCR | unix.IGNCR | unix.ICRNL | unix.IXON
	t.Oflag &^= unix.OPOST
	t.Lflag &^= unix.ECHO | unix.ECHONL | unix.ICANON | unix.ISIG | unix.IEXTEN
	t.Cflag &^= unix.CSIZE | unix.PARENB
	t.Cflag |= unix.CS8
	t.Cc[unix.VMIN] = 0
	t.Cc[unix.VTIME] = 10
	return unix.IoctlSetTermios(fd, unix.TIOCSETA, t)
}
