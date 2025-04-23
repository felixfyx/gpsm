import serial
import time
import threading
from enum import Enum
import Globals


class ConnectionStatus(Enum):
    NOT_CONNECTED = 0
    CONNECTED = 1
    IN_PROGRESS = 2


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
        
        # Connection management
        self.forced_disconnect = False
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 5
        self.reconnect_delay = 2  # seconds
        
        # Thread management - using simple lock-protected flag for thread control
        self._lock = threading.Lock()
        self._thread_running = True
        self.thread = threading.Thread(target=self.run)
        self.thread.daemon = False  # Non-daemon thread so we can join it properly
        self.thread.start()
        
    @property
    def thread_running(self):
        """Thread-safe getter for thread_running flag"""
        with self._lock:
            return self._thread_running
            
    @thread_running.setter
    def thread_running(self, value):
        """Thread-safe setter for thread_running flag"""
        with self._lock:
            self._thread_running = value

    def log(self, message):
        """Print debug messages if debug mode is enabled"""
        if self.debug:
            print(f"[{self.port}] {message}")

    def run(self):
        """Main thread loop"""
        try:
            self.open_connection()
            
            while self.thread_running:  # Using simple boolean flag
                if not self.thread_running:
                    break  # Double-check to ensure quick exit
                    
                if self.running:
                    try:
                        self.read_data()
                    except Exception as e:
                        self.log(f"Error in read loop: {e}")
                        self.handle_connection_error()
                else:
                    # If not running and not a forced disconnect, check if we should attempt reconnection
                    if not self.forced_disconnect and self.reconnect_attempts < self.max_reconnect_attempts and self.thread_running:
                        time.sleep(0.1)  # Shorter sleep to check thread_running more frequently
                        if not self.thread_running:
                            break  # Check again after sleep
                            
                        self.reconnect_attempts += 1
                        self.log(f"Attempting reconnection {self.reconnect_attempts}/{self.max_reconnect_attempts}")
                        self.open_connection()
                    else:
                        # Sleep to avoid CPU spinning, but in smaller chunks with exit checks
                        for _ in range(10):  # 10 × 0.01s = 0.1s total
                            if not self.thread_running:
                                break
                            time.sleep(0.01)
            
            self.log(f"Thread for {self.port} is exiting normally")
        except Exception as e:
            self.log(f"Thread for {self.port} exiting due to exception: {e}")
            
            # Update device connection status if exception occurred
            if self.device_name != "NULL" and self.device:
                if self.device.get("connection_status", None) != ConnectionStatus.NOT_CONNECTED:
                    self.log(f"Updating connection status for {self.device_name} to NOT_CONNECTED due to exception")
                    self.device["connection_status"] = ConnectionStatus.NOT_CONNECTED
        finally:
            # Ensure connection is closed when thread exits
            if self.serial_connection and self.serial_connection.is_open:
                try:
                    self.serial_connection.close()
                    self.log(f"Closed serial connection to {self.port} on thread exit")
                except:
                    pass
            self.log(f"Thread for {self.port} has exited")

    def open_connection(self):
        """Open the serial connection."""
        try:
            self.serial_connection = serial.Serial(self.port, self.baudrate, timeout=1)
            self.log(f"Connected to {self.port} at {self.baudrate} baud.")
            time.sleep(0.5)  # Short delay for connection to stabilize
            self.running = True
            self.forced_disconnect = False  # Reset forced disconnect flag on successful connection
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
        
        # Update device connection status if handler is associated with a device
        # and it's not already marked as disconnected
        if self.device_name != "NULL" and self.device and not self.forced_disconnect:
            if self.device.get("connection_status", None) != ConnectionStatus.NOT_CONNECTED:
                self.log(f"Connection error: updating status for {self.device_name} to NOT_CONNECTED")
                self.device["connection_status"] = ConnectionStatus.NOT_CONNECTED

    def close_connection(self):
        """Close the serial connection and terminate the thread."""
        self.log(f"Closing connection to {self.port}")
        
        # Update device connection status when closing connection
        if self.device_name != "NULL" and self.device:
            if self.device.get("connection_status", None) != ConnectionStatus.NOT_CONNECTED:
                self.log(f"Updating connection status for {self.device_name} to NOT_CONNECTED during close")
                self.device["connection_status"] = ConnectionStatus.NOT_CONNECTED
        
        # Use the dedicated thread stopping method
        success = self.stop_thread(timeout=3.0)
        
        if not success:
            self.log(f"Warning: Thread for {self.port} may still be running")

    def stop_thread(self, timeout=3.0):
        """
        Stop the background thread explicitly.
        
        Args:
            timeout: Maximum time to wait for the thread to terminate (seconds)
            
        Returns:
            bool: True if thread terminated successfully, False if it timed out
        """
        self.log(f"Stopping thread for {self.port}...")
        
        # Update device connection status if this handler is associated with a device
        if self.device_name != "NULL" and self.device:
            # Using self.device reference instead of direct io_devices access
            if self.device.get("connection_status", None) != ConnectionStatus.NOT_CONNECTED:
                self.log(f"Updating connection status for {self.device_name} to NOT_CONNECTED")
                self.device["connection_status"] = ConnectionStatus.NOT_CONNECTED
        
        # Signal the thread to stop
        self.thread_running = False
        self.forced_disconnect = True
        self.running = False
        
        # Give the thread a moment to notice the signal
        time.sleep(0.1)
        
        # Close the serial connection if open
        if self.serial_connection and self.serial_connection.is_open:
            try:
                self.serial_connection.close()
                self.log(f"Closed serial connection to {self.port}")
            except Exception as e:
                self.log(f"Error closing serial port: {e}")
        
        # Join the thread if it's still alive and we're not in the thread
        if self.thread and self.thread.is_alive() and threading.current_thread() != self.thread:
            self.log(f"Waiting for thread to terminate (timeout: {timeout}s)...")
            
            # Try joining the thread with the specified timeout
            start_time = time.time()
            while self.thread.is_alive() and (time.time() - start_time < timeout):
                self.thread.join(timeout=0.5)
                if self.thread.is_alive():
                    self.log(f"Still waiting for thread to terminate...")
            
            # Return success based on whether the thread terminated
            if self.thread.is_alive():
                self.log(f"Warning: Thread for {self.port} did not terminate within {timeout}s")
                return False
            else:
                self.log(f"Thread for {self.port} terminated successfully")
                return True
                
        return not self.thread.is_alive()

    def read_data(self):
        """Read data from the serial port."""
        if not self.thread_running:
            return  # Exit immediately if thread should stop
            
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
                # Update connection status on serial exception
                if self.device_name != "NULL" and self.device:
                    if self.device.get("connection_status", None) != ConnectionStatus.NOT_CONNECTED:
                        self.log(f"Updating connection status for {self.device_name} to NOT_CONNECTED due to serial exception")
                        self.device["connection_status"] = ConnectionStatus.NOT_CONNECTED
                self.handle_connection_error()
            except Exception as e:
                self.log(f"Error reading data: {e}")
                # Update connection status on any exception
                if self.device_name != "NULL" and self.device:
                    if self.device.get("connection_status", None) != ConnectionStatus.NOT_CONNECTED:
                        self.log(f"Updating connection status for {self.device_name} to NOT_CONNECTED due to error")
                        self.device["connection_status"] = ConnectionStatus.NOT_CONNECTED

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
            
            # Update connection status if connection is closed
            if self.device_name != "NULL" and self.device:
                if self.device.get("connection_status", None) != ConnectionStatus.NOT_CONNECTED:
                    self.log(f"Updating connection status for {self.device_name} to NOT_CONNECTED - connection closed")
                    self.device["connection_status"] = ConnectionStatus.NOT_CONNECTED
            
            return False
            
        try:
            message = self.format_message(command_id, payload)
            self.serial_connection.write(message)
            self.log(f"Sent message: {[hex(b) for b in message]}")
            return True
        except Exception as e:
            self.log(f"Error sending data: {e}")
            
            # Update connection status on send error
            if self.device_name != "NULL" and self.device:
                if self.device.get("connection_status", None) != ConnectionStatus.NOT_CONNECTED:
                    self.log(f"Updating connection status for {self.device_name} to NOT_CONNECTED due to send error")
                    self.device["connection_status"] = ConnectionStatus.NOT_CONNECTED
                    
            self.handle_connection_error()
            return False
    
    def send_raw_data(self, data):
        """Send raw data to the serial port without formatting."""
        if not self.serial_connection or not self.serial_connection.is_open:
            self.log("Cannot send raw data - serial connection not open")
            
            # Update connection status if connection is closed
            if self.device_name != "NULL" and self.device:
                if self.device.get("connection_status", None) != ConnectionStatus.NOT_CONNECTED:
                    self.log(f"Updating connection status for {self.device_name} to NOT_CONNECTED - connection closed")
                    self.device["connection_status"] = ConnectionStatus.NOT_CONNECTED
                    
            return False
            
        try:
            self.serial_connection.write(data)
            self.log(f"Sent raw data: {[hex(b) for b in data]}")
            return True
        except Exception as e:
            self.log(f"Error sending raw data: {e}")
            
            # Update connection status on send error
            if self.device_name != "NULL" and self.device:
                if self.device.get("connection_status", None) != ConnectionStatus.NOT_CONNECTED:
                    self.log(f"Updating connection status for {self.device_name} to NOT_CONNECTED due to send error")
                    self.device["connection_status"] = ConnectionStatus.NOT_CONNECTED
                    
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