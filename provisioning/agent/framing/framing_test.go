package framing

import (
	"bytes"
	"reflect"
	"testing"
)

func TestKnownBytes(t *testing.T) {
	// Pins the wire format itself: if this breaks, both ends break.
	got := Encode(0x01, 0x07, nil)
	want := []byte{0xB2, 0x80, 0x01, 0x01, 0x07, 0x00, 0x00, 0x00, 0x00}
	if !bytes.Equal(got, want) {
		t.Fatalf("got % x, want % x", got, want)
	}
}

func TestRoundtrip(t *testing.T) {
	var d Decoder
	got := d.Feed(Encode(0x02, 9, []byte("hello")))
	want := []Frame{{Type: 0x02, Seq: 9, Payload: []byte("hello")}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %+v, want %+v", got, want)
	}
}

func TestTornReadsByteByByte(t *testing.T) {
	var d Decoder
	var got []Frame
	for _, b := range Encode(0x02, 1, []byte("payload")) {
		got = append(got, d.Feed([]byte{b})...)
	}
	if len(got) != 1 || string(got[0].Payload) != "payload" {
		t.Fatalf("got %+v", got)
	}
}

func TestTwoFramesInOneRead(t *testing.T) {
	var d Decoder
	data := append(Encode(1, 1, []byte("a")), Encode(2, 2, []byte("bb"))...)
	got := d.Feed(data)
	if len(got) != 2 || got[0].Type != 1 || got[1].Type != 2 {
		t.Fatalf("got %+v", got)
	}
}

func TestGarbageBeforeFrame(t *testing.T) {
	var d Decoder
	data := append([]byte("login: \x00\xffnoise"), Encode(3, 3, []byte("x"))...)
	got := d.Feed(data)
	if len(got) != 1 || got[0].Type != 3 {
		t.Fatalf("got %+v", got)
	}
}

func TestMagicSplitAcrossReads(t *testing.T) {
	var d Decoder
	frame := Encode(4, 4, []byte("y"))
	if got := d.Feed(append([]byte("junk"), frame[:1]...)); len(got) != 0 {
		t.Fatalf("early frame: %+v", got)
	}
	if got := d.Feed(frame[1:]); len(got) != 1 || got[0].Type != 4 {
		t.Fatalf("got %+v", got)
	}
}

func TestCorruptLengthResyncs(t *testing.T) {
	// A header claiming a 2GB payload must not stall the decoder.
	bad := Encode(1, 1, nil)
	bad[5], bad[6], bad[7], bad[8] = 0xFF, 0xFF, 0xFF, 0x7F
	var d Decoder
	got := d.Feed(append(bad, Encode(5, 5, []byte("ok"))...))
	if len(got) != 1 || got[0].Type != 5 {
		t.Fatalf("got %+v", got)
	}
}
