import SerialMessageHandler
import Utils

# Command identifiers
HANDSHAKE_COMMAND = 0xFF
GPIO_COMMAND = 0x01
LED_COMMAND = 0x02
TURRET_COMMAND = 0x03

def send_handshake(payload: bytes, handler):
    """
    Send a handshake command with the given payload
    
    Args:
        payload: The payload for the handshake:
                - 0x00 for initial request
                - Device ID to echo it back
                - 0xAA for acknowledge
        handler: The SerialMessageHandler to send the command through
    """
    command_id = bytes([HANDSHAKE_COMMAND])
    handler.send_data(command_id, payload)
    
def send_gpio_command(pin: int, state: int, handler):
    """
    Send a command to control a GPIO pin
    
    Args:
        pin: The pin number to control
        state: The state to set (0=LOW, 1=HIGH)
        handler: The SerialMessageHandler to send the command through
    """
    command_id = bytes([GPIO_COMMAND])
    payload = bytes([pin, state])
    handler.send_data(command_id, payload)
    
def send_led_command(brightness: int, handler):
    """
    Send a command to control an LED's brightness
    
    Args:
        brightness: Brightness value (0-255)
        handler: The SerialMessageHandler to send the command through
    """
    command_id = bytes([LED_COMMAND])
    payload = bytes([brightness])
    handler.send_data(command_id, payload)
    
def send_turret_command(angle: int, power: int, handler):
    """
    Send a command to control a turret
    
    Args:
        angle: Angle value (0-180)
        power: Power value (0-100)
        handler: The SerialMessageHandler to send the command through
    """
    command_id = bytes([TURRET_COMMAND])
    payload = bytes([angle, power])
    handler.send_data(command_id, payload)