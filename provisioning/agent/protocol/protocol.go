// Package protocol defines the RPC vocabulary spoken inside frames.
// Payloads are plain world.proto messages; the frame type says which.
package protocol

const (
	// Requests (hub -> pi). A response echoes the request type with
	// RespBit set and the same seq -- that's how answers are matched.
	TypeGetEntity = 0x01 // no payload        -> response: world.Entity
	TypePush      = 0x02 // EntityChangeRequest -> response: world.Entity
	TypeEvent     = 0x03 // pi -> hub, unsolicited progress: world.Entity

	RespBit = 0x80
)
