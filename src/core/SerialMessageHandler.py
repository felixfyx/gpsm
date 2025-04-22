import serial
import serial.tools.list_ports
import time
import threading
import Globals
import Command
from enum import Enum

class ConnectionStatus(Enum):
    NOT_CONNECTED = 0
    CONNECTED = 1
    IN_PROGRESS = 2

# Dictionary to track different connected devices
io_devices = {
    "gpio": {
        "id": 0x01,
        "connection_status": ConnectionStatus.NOT_CONNECTED,
        "port_number": "NULL",
        "thread": None,
        "handler": None
    },
    "turret": {
        "id": 0x02,
        "connection_status": ConnectionStatus.NOT_CONNECTED,
        "port_number": "NULL",
        "thread": None,
        "handler": None
    },
    "led": {
        "id": 0x03,
        "connection_status": ConnectionStatus.NOT_CONNECTED,
        "port_number": "NULL",
        "thread": None,
        "handler": None
    },
}

class MessageState(Enum):
    WAITING_FOR_START = 0
    WAITING_FOR_LENGTH = 1
    COLLECTING_DATA = 2
    COMPLETE = 3
    ERROR = 4

class SerialMessageHandler:
    # Start byte that signifies the beginning of a message
    START_BYTE = 0xAA
    
    def __init__(self, port, baudrate=115200, debug=False):
        self.port = port
        self.baudrate = baudrate
        self.serial_connection = None
        self.running = False
        self.debug = debug
        
        # Message processing state
        self.buffer = bytearray(Globals.MAX_BUFFER_SIZE)
        self.bufferIndex = 0
        self.message_state = MessageState.WAITING_FOR_START
        self.expected_length = 0
        
        # Command handlers
        self.command_map = {}
        self.device = None
        self.device_name = "NULL"
        
        # Auto-reconnect parameters
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 2  # seconds
        
        # Thread management
        self.thread_exit = threading.Event()
        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = False  # Non-daemon thread so we can join it properly
        self.thread.start()

    def log(self, message):
        """Print debug messages if debug mode is enabled"""
        if self.debug:
            print(f"[{self.port}] {message}")

    def run(self):
        """Main thread loop"""
        self.open_connection()
        
        while not self.thread_exit.is_set():
            if self.running:
                try:
                    self.read_data()
                except Exception as e:
                    self.log(f"Error in read loop: {e}")
                    self.handle_connection_error()
            else:
                # If not running, check if we should attempt reconnection
                if self.reconnect_attempts < self.max_reconnect_attempts and not self.thread_exit.is_set():
                    time.sleep(self.reconnect_delay)
                    self.reconnect_attempts += 1
                    self.log(f"Attempting reconnection {self.reconnect_attempts}/{self.max_reconnect_attempts}")
                    self.open_connection()
                else:
                    # Sleep to avoid CPU spinning, but check exit flag frequently
                    self.thread_exit.wait(1)

    def open_connection(self):
        """Open the serial connection."""
        try:
            self.serial_connection = serial.Serial(self.port, self.baudrate, timeout=1)
            self.log(f"Connected to {self.port} at {self.baudrate} baud.")
            time.sleep(0.5)  # Short delay for connection to stabilize
            self.running = True
            self.reconnect_attempts = 0  # Reset reconnection counter on successful connection
        except serial.SerialException as e:
            self.log(f"Error opening serial port {self.port}: {e}")
            self.running = False

    def handle_connection_error(self):
        """Handle connection errors and initiate reconnection if needed"""
        if self.serial_connection and self.serial_connection.is_open:
            try:
                self.serial_connection.close()
            except Exception as e:
                self.log(f"Error closing connection: {e}")
        
        self.running = False
        # We'll attempt reconnection in the run loop

    def close_connection(self):
        """Close the serial connection."""
        self.running = False
        if self.serial_connection and self.serial_connection.is_open:
            try:
                self.serial_connection.close()
                self.log(f"Serial connection to {self.port} closed.")
            except Exception as e:
                self.log(f"Error closing serial port: {e}")

    def read_data(self):
        """Read data from the serial port."""
        if self.serial_connection and self.serial_connection.is_open:
            try:
                # Check if data is available
                if self.serial_connection.in_waiting > 0:
                    # Read available data
                    data = self.serial_connection.read(self.serial_connection.in_waiting)
                    self.process_data(data)
                else:
                    # Small sleep to avoid CPU spinning when no data is available
                    time.sleep(0.01)
            except serial.SerialException as e:
                self.log(f"Serial exception: {e}")
                self.handle_connection_error()
            except Exception as e:
                self.log(f"Error reading data: {e}")

    def process_data(self, data):
        """Process the received byte data using state machine approach"""
        for byte_val in data:
            # Process based on current state
            if self.message_state == MessageState.WAITING_FOR_START:
                if byte_val == self.START_BYTE:
                    self.reset_buffer()
                    self.add_to_buffer(byte_val)
                    self.message_state = MessageState.WAITING_FOR_LENGTH
                    self.log("Start byte received")
                # Otherwise keep looking for start byte
            
            elif self.message_state == MessageState.WAITING_FOR_LENGTH:
                if self.is_valid_length(byte_val):
                    self.add_to_buffer(byte_val)
                    self.expected_length = byte_val
                    self.message_state = MessageState.COLLECTING_DATA
                    self.log(f"Valid length received: {byte_val}")
                else:
                    self.log(f"Invalid length received: {byte_val}")
                    self.message_state = MessageState.WAITING_FOR_START
            
            elif self.message_state == MessageState.COLLECTING_DATA:
                self.add_to_buffer(byte_val)
                
                # Check if we've collected the complete message
                if self.bufferIndex >= self.expected_length:
                    self.log(f"Complete message received: {[hex(b) for b in self.buffer[:self.expected_length]]}")
                    self.validate_and_process_message()
                    self.message_state = MessageState.WAITING_FOR_START
            
            # Sanity check for buffer overflow
            if self.bufferIndex >= Globals.MAX_BUFFER_SIZE:
                self.log("Buffer overflow, resetting")
                self.message_state = MessageState.WAITING_FOR_START
                self.reset_buffer()

    def validate_and_process_message(self):
        """Validate checksum and process message if valid"""
        length = self.buffer[1]
        
        # Ensure we have at least the minimum message length
        # Minimum is: start(1) + length(1) + command(1) + checksum(1) = 4 bytes
        # Note: We now allow for an empty payload
        if length < 4:
            self.log("Message too short")
            return
            
        # Validate checksum
        received_checksum = self.buffer[length - 1]
        calculated_checksum = self.calculate_checksum(self.buffer[:length - 1])
        
        if received_checksum == calculated_checksum:
            command_id = bytes([self.buffer[2]])
            # Handle empty payload case
            payload = self.buffer[3:length - 1] if length > 4 else bytes()
            
            payload_desc = payload.hex() if payload else "(empty)"
            self.log(f"Valid message received - Command: {command_id.hex()}, Payload: {payload_desc}")
            self.call_command(command_id, payload)
        else:
            self.log(f"Checksum mismatch - Received: {hex(received_checksum)}, Calculated: {hex(calculated_checksum)}")

    def calculate_checksum(self, data):
        """Calculate XOR checksum of data bytes"""
        checksum = 0
        for byte in data:
            checksum ^= byte
        return checksum

    def is_valid_length(self, length):
        """Verify that length value is within valid range"""
        # Minimum valid length: start(1) + length(1) + command(1) + checksum(1) = 4
        # Maximum is the buffer size
        return 4 <= length <= Globals.MAX_BUFFER_SIZE

    def format_message(self, command_id, payload=None):
        """Format a message according to the protocol"""
        if not isinstance(command_id, bytes) or len(command_id) != 1:
            raise ValueError("Command ID must be a single byte")
            
        # Handle None payload as empty bytes
        if payload is None:
            payload = bytes()
            
        # Calculate message length (start + length + command + payload + checksum)
        length = 3 + len(payload) + 1
        
        # Build message
        message = bytearray([self.START_BYTE, length])
        message.extend(command_id)
        message.extend(payload)
        
        # Calculate and append checksum
        checksum = self.calculate_checksum(message)
        message.append(checksum)
        
        return message

    def send_data(self, command_id, payload=None):
        """Send formatted message to the serial port."""
        if not self.serial_connection or not self.serial_connection.is_open:
            self.log("Cannot send data - serial connection not open")
            return False
            
        try:
            message = self.format_message(command_id, payload)
            self.serial_connection.write(message)
            self.log(f"Sent message: {[hex(b) for b in message]}")
            return True
        except Exception as e:
            self.log(f"Error sending data: {e}")
            self.handle_connection_error()
            return False
    
    def send_raw_data(self, data):
        """Send raw data to the serial port without formatting."""
        if not self.serial_connection or not self.serial_connection.is_open:
            self.log("Cannot send raw data - serial connection not open")
            return False
            
        try:
            self.serial_connection.write(data)
            self.log(f"Sent raw data: {[hex(b) for b in data]}")
            return True
        except Exception as e:
            self.log(f"Error sending raw data: {e}")
            self.handle_connection_error()
            return False
    
    def register_command(self, command_id, handler_function):
        """Register a function to handle a specific command ID"""
        if not isinstance(command_id, bytes) or len(command_id) != 1:
            raise ValueError("Command ID must be a single byte")
        
        if not callable(handler_function):
            raise ValueError("Handler must be a callable function")
        
        self.command_map[command_id] = handler_function
        self.log(f"Registered handler for command: {command_id.hex()}")

    def call_command(self, command_id, payload):
        """Call the registered handler for a command"""
        handler = self.command_map.get(command_id)
        if handler:
            try:
                handler(self, payload)
            except Exception as e:
                self.log(f"Error in command handler: {e}")
        else:
            self.log(f"No handler registered for command: {command_id.hex()}")

    def add_to_buffer(self, byte_val):
        """Add a byte to the buffer at the current index"""
        self.buffer[self.bufferIndex] = byte_val
        self.bufferIndex += 1
    
    def reset_buffer(self):
        """Reset the buffer index to start"""
        self.bufferIndex = 0

    def set_device(self, device_name, device_info):
        """Set this handler's associated device"""
        self.device_name = device_name
        self.device = device_info
        self.log(f"Associated with device: {device_name}")


# Handshake command handler
def send_handshake_response(handler, payload):
    """
    Process handshake responses from devices according to the protocol:
    1. PC sends 0xFF with payload 0x00
    2. Arduino responds with 0xFF and its device ID
    3. PC responds with 0xFF and echoes back the device ID it received
    4. Arduino responds with 0xFF and payload 0xAA for success or 0xFF for failure
    """
    handler.log(f"Processing handshake response with payload: {[hex(b) for b in payload]}")
    
    if len(payload) < 1:
        handler.log("Invalid handshake payload length")
        return
        
    received_value = payload[0]
    handler.log(f"Received value: {hex(received_value)}")
    
    # Phase 2: Arduino responded with its device ID
    if received_value in [device_info["id"] for device_name, device_info in io_devices.items()]:
        # Find which device this ID belongs to
        for device_name, device_info in io_devices.items():
            if received_value == device_info["id"]:
                handler.log(f"Identified device: {device_name} with ID: {hex(received_value)}")
                
                # Update device status to in-progress
                device_info["connection_status"] = ConnectionStatus.IN_PROGRESS
                device_info["port_number"] = handler.port
                device_info["thread"] = handler.thread
                device_info["handler"] = handler
                
                # Associate this handler with the device
                handler.set_device(device_name, device_info)
                
                # Phase 3: Echo back the device ID using Command.py
                handler.log(f"Sending back device ID: {hex(received_value)}")
                Command.send_handshake(bytes([received_value]), handler)
                return
    
    # Phase 4: Arduino responded with success/failure
    elif received_value == 0xAA:
        # Success confirmation
        handler.log("Received successful handshake confirmation (0xAA)")
        if handler.device_name != "NULL":
            device_info = io_devices[handler.device_name]
            if device_info["connection_status"] == ConnectionStatus.IN_PROGRESS:
                device_info["connection_status"] = ConnectionStatus.CONNECTED
                handler.log(f"Handshake complete for {handler.device_name}!")
                return
            else:
                handler.log(f"Device {handler.device_name} not in progress state (state: {device_info['connection_status']})")
        else:
            handler.log("Received handshake confirmation but no device is associated with this handler")
    
    elif received_value == 0xFF:
        # Error confirmation
        handler.log("Received error handshake response (0xFF)")
        if handler.device_name != "NULL":
            device_info = io_devices[handler.device_name]
            if device_info["connection_status"] == ConnectionStatus.IN_PROGRESS:
                device_info["connection_status"] = ConnectionStatus.NOT_CONNECTED
                handler.log(f"Handshake failed for {handler.device_name}!")
                return
    
    handler.log(f"Unhandled handshake response: {hex(received_value)}")
    handler.log(f"Current handler device: {handler.device_name}")
    for device_name, device_info in io_devices.items():
        handler.log(f"Device {device_name}: ID={hex(device_info['id'])}, Status={device_info['connection_status']}, Port={device_info['port_number']}")


def discover_devices(timeout=30):
    """
    Scan all available COM ports to discover connected devices
    Returns a dictionary of discovered devices
    """
    print("Starting device discovery...")
    
    # Keep track of all created handlers for clean exit
    handlers = []
    
    # Reset device statuses
    for device in io_devices:
        io_devices[device]["connection_status"] = ConnectionStatus.NOT_CONNECTED
        io_devices[device]["port_number"] = "NULL"
        io_devices[device]["handler"] = None
        io_devices[device]["thread"] = None
    
    # Get list of available COM ports
    ports = serial.tools.list_ports.comports()
    if not ports:
        print("No COM ports found")
        return {}
        
    print(f"Found {len(ports)} COM ports")
    
    # Create handlers for each port
    for port in ports:
        print(f"Checking {port.device}...")
        handler = SerialMessageHandler(port.device, 115200, debug=True)
        handler.register_command(bytes([0xFF]), send_handshake_response)
        handlers.append(handler)
    
    try:
        # Send handshake requests to all ports
        start_time = time.time()
        handshake_command_id = bytes([0xFF])
        
        while time.time() - start_time < timeout:
            # Check if all devices are connected
            all_connected = True
            for device_name, device_info in io_devices.items():
                if device_info["connection_status"] != ConnectionStatus.CONNECTED:
                    all_connected = False
                    break
                    
            if all_connected:
                print("All devices connected!")
                break
                
            # Send handshake requests to all handlers
            for handler in handlers:
                # Skip handlers that are already associated with a connected device
                if handler.device_name != "NULL" and io_devices[handler.device_name]["connection_status"] == ConnectionStatus.CONNECTED:
                    continue
                    
                # Send initial handshake request with 0x00 payload
                handler.send_data(handshake_command_id, bytes([0x00]))
            
            # Wait before next attempt
            time.sleep(1)
            
        # Print discovery results
        print("\nDevice Discovery Results:")
        for device_name, device_info in io_devices.items():
            status = device_info["connection_status"].name
            port = device_info["port_number"] if status != "NOT_CONNECTED" else "N/A"
            print(f"{device_name}: {status} on {port}")
        
        # Close handlers for devices that weren't connected
        for handler in handlers:
            if handler.device_name == "NULL":
                handler.close_connection()
                handlers.remove(handler)
        
        return {name: info for name, info in io_devices.items() 
                if info["connection_status"] == ConnectionStatus.CONNECTED}
                
    except Exception as e:
        print(f"Error during device discovery: {e}")
        # Clean up on error
        for handler in handlers:
            try:
                handler.close_connection()
            except:
                pass
        return {}
            
        # Print discovery results
        print("\nDevice Discovery Results:")
        for device_name, device_info in io_devices.items():
            status = device_info["connection_status"].name
            port = device_info["port_number"] if status != "NOT_CONNECTED" else "N/A"
            print(f"{device_name}: {status} on {port}")
        
        # Close handlers for devices that weren't connected
        for handler in handlers:
            if handler.device_name == "NULL":
                handler.close_connection()
                handlers.remove(handler)
        
        return {name: info for name, info in io_devices.items() 
                if info["connection_status"] == ConnectionStatus.CONNECTED}
                
    except Exception as e:
        print(f"Error during device discovery: {e}")
        # Clean up on error
        for handler in handlers:
            try:
                handler.close_connection()
            except:
                pass
        return {}
    
    # Print discovery results
    print("\nDevice Discovery Results:")
    for device_name, device_info in io_devices.items():
        status = device_info["connection_status"].name
        port = device_info["port_number"] if status != "NOT_CONNECTED" else "N/A"
        print(f"{device_name}: {status} on {port}")
    
    # Close handlers for devices that weren't connected
    for handler in handlers:
        if handler.device_name == "NULL":
            handler.close_connection()
    
    return {name: info for name, info in io_devices.items() 
            if info["connection_status"] == ConnectionStatus.CONNECTED}


if __name__ == "__main__":
    print("Serial Message Handler")
    print("=====================")
    
    # Keep track of all handlers for clean exit
    all_handlers = []
    
    try:
        # Discover all devices
        connected_devices = discover_devices(timeout=15)
        
        if not connected_devices:
            print("No devices discovered")
        else:
            print(f"Discovered {len(connected_devices)} devices")
            
            # Keep the program running until interrupted
            print("Press Ctrl+C to exit...")
            while True:
                time.sleep(1)
                
    except KeyboardInterrupt:
        print("\nShutting down...")
        
    finally:
        print("Closing all connections...")
        # Close all device handlers
        for device_name, device_info in io_devices.items():
            if device_info["handler"]:
                try:
                    print(f"Closing connection to {device_name}...")
                    device_info["handler"].close_connection()
                except Exception as e:
                    print(f"Error closing {device_name} connection: {e}")
        
        # Join any remaining threads to ensure clean exit
        for device_name, device_info in io_devices.items():
            if device_info["thread"] and device_info["thread"].is_alive():
                try:
                    print(f"Waiting for {device_name} thread to terminate...")
                    device_info["thread"].join(timeout=2.0)
                    if device_info["thread"].is_alive():
                        print(f"Warning: Thread for {device_name} did not terminate gracefully")
                except Exception as e:
                    print(f"Error joining thread for {device_name}: {e}")
        
        print(f"Final status: {io_devices}")
        print("Done!")