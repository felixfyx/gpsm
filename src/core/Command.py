import SerialMessageHandler
import Utils

# Handshake requests
HANDSHAKE_COMMAND = 0XFF


def send_handshake_request(id: bytes, handler):
    startByte = bytes([0xAA])
    length = bytes([5])
    identifier = bytes([0xFF])
    value = id
    checksum_value = startByte[0] ^ length[0] ^ identifier[0] ^ value[0]
    checksum = bytes([checksum_value])
    command  = bytearray(startByte + length + identifier + value + checksum)
    handler.send_data(command)