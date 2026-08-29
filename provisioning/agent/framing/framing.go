// Package framing turns the USB serial byte stream into discrete frames.
//
// A serial port has no message boundaries: a read may return half a
// frame or three and a half. Layout, 9-byte header:
//
//	magic(2)=B2 80 | ver(1)=01 | type(1) | seq(1) | len(4 LE) | payload
package framing

import (
	"bytes"
	"encoding/binary"
)

const (
	Version    = 1
	headerSize = 9
	// MaxPayload bounds a corrupted length field: no legal frame is
	// close, and without the bound a bad length stalls the decoder
	// forever waiting for a payload that never comes.
	MaxPayload = 64 * 1024
)

var magic = []byte{0xB2, 0x80}

type Frame struct {
	Type    byte
	Seq     byte
	Payload []byte
}

// Encode builds the wire form of one frame.
func Encode(frameType, seq byte, payload []byte) []byte {
	out := make([]byte, headerSize+len(payload))
	copy(out, magic)
	out[2] = Version
	out[3] = frameType
	out[4] = seq
	binary.LittleEndian.PutUint32(out[5:9], uint32(len(payload)))
	copy(out[headerSize:], payload)
	return out
}

// Decoder accumulates bytes across torn reads and resyncs past garbage.
// It never errors: on a long-lived link, recover-and-continue beats
// crash-on-glitch.
type Decoder struct {
	buf []byte
}

// Feed appends raw bytes and returns every frame they completed.
func (d *Decoder) Feed(data []byte) []Frame {
	d.buf = append(d.buf, data...)
	var frames []Frame
	for {
		start := bytes.Index(d.buf, magic)
		if start < 0 {
			// Keep only the last byte: it may be the first half of a
			// magic split across two reads.
			if len(d.buf) > 1 {
				d.buf = d.buf[len(d.buf)-1:]
			}
			return frames
		}
		if start > 0 {
			d.buf = d.buf[start:] // drop garbage before the magic
		}
		if len(d.buf) < headerSize {
			return frames // header incomplete; wait for more bytes
		}
		length := binary.LittleEndian.Uint32(d.buf[5:9])
		if d.buf[2] != Version || length > MaxPayload {
			// Looked like a frame but isn't trustworthy: skip one byte
			// and rescan -- a real frame may start further in.
			d.buf = d.buf[1:]
			continue
		}
		total := headerSize + int(length)
		if len(d.buf) < total {
			return frames // payload incomplete; wait for more bytes
		}
		frameType, seq := d.buf[3], d.buf[4]
		// Copy the payload out: d.buf's backing array gets reused by
		// future appends, and a Frame must not change under its owner.
		payload := make([]byte, length)
		copy(payload, d.buf[headerSize:total])
		d.buf = d.buf[total:]
		frames = append(frames, Frame{Type: frameType, Seq: seq, Payload: payload})
	}
}
