import serial
import serial.tools.list_ports
import time
import Command
from SerialMessageHandler import SerialMessageHandler, ConnectionStatus


class DeviceManager:
    """
    Manages communication with multiple devices over serial connections.
    This class handles device discovery, connection, and disconnection.
    """
    
    def __init__(self, devices_dict=None):
        """
        Initialize the device manager with a device dictionary.
        
        Args:
            devices_dict: Dictionary of devices to manage. If None, no devices will be managed.
                          Format: {"device_name": {"id": byte_id, "connection_status": ConnectionStatus,
                                                 "port_number": str, "thread": Thread, "handler": SerialMessageHandler}}
        """
        self.devices = devices_dict if devices_dict is not None else {}
        self.handlers = []  # List of all active SerialMessageHandlers
        
    def register_device(self, name, device_id):
        """
        Register a new device with the manager.
        
        Args:
            name: Device name (string)
            device_id: Device identifier (byte or int)
            
        Returns:
            True if device was registered, False if a device with that name already exists
        """
        if name in self.devices:
            print(f"Device {name} already registered")
            return False
            
        self.devices[name] = {
            "id": device_id,
            "connection_status": ConnectionStatus.NOT_CONNECTED,
            "port_number": "NULL",
            "thread": None,
            "handler": None
        }
        return True
        
    def get_device_handler(self, name):
        """Get the handler for a specific device"""
        if name not in self.devices:
            return None
        return self.devices[name].get("handler")
        
    def is_device_connected(self, name):
        """Check if a device is connected"""
        if name not in self.devices:
            return False
        return self.devices[name].get("connection_status") == ConnectionStatus.CONNECTED
    
    def get_connected_devices(self):
        """Get dictionary of connected devices"""
        return {name: info for name, info in self.devices.items() 
                if info.get("connection_status") == ConnectionStatus.CONNECTED}
    
    def send_handshake_response(self, handler, payload):
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
        device_ids = [device_info["id"] for device_name, device_info in self.devices.items()]
        if received_value in device_ids:
            # Find which device this ID belongs to
            for device_name, device_info in self.devices.items():
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
                device_info = self.devices[handler.device_name]
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
                device_info = self.devices[handler.device_name]
                if device_info["connection_status"] == ConnectionStatus.IN_PROGRESS:
                    device_info["connection_status"] = ConnectionStatus.NOT_CONNECTED
                    handler.log(f"Handshake failed for {handler.device_name}!")
                    return
        
        handler.log(f"Unhandled handshake response: {hex(received_value)}")
        handler.log(f"Current handler device: {handler.device_name}")
        for device_name, device_info in self.devices.items():
            handler.log(f"Device {device_name}: ID={hex(device_info['id'])}, Status={device_info['connection_status']}, Port={device_info['port_number']}")

    def discover_devices(self, timeout=30):
        """
        Scan all available COM ports to discover connected devices
        
        Args:
            timeout: Maximum time to spend attempting to connect (seconds)
            
        Returns:
            Dictionary of discovered devices
        """
        print("Starting device discovery...")
        
        # Reset device statuses
        for device in self.devices:
            self.devices[device]["connection_status"] = ConnectionStatus.NOT_CONNECTED
            self.devices[device]["port_number"] = "NULL"
            self.devices[device]["handler"] = None
            self.devices[device]["thread"] = None
        
        # Clear existing handlers
        self._cleanup_handlers()
        
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
            # Use a lambda to bind 'self' to the handshake_response method
            handler.register_command(bytes([0xFF]), lambda h, p: self.send_handshake_response(h, p))
            self.handlers.append(handler)
        
        try:
            # Send handshake requests to all ports
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                # Check if all devices are connected
                all_connected = True
                for device_name, device_info in self.devices.items():
                    if device_info["connection_status"] != ConnectionStatus.CONNECTED:
                        all_connected = False
                        break
                        
                if all_connected:
                    print("All devices connected!")
                    break
                    
                # Send handshake requests to all handlers
                for handler in self.handlers[:]:  # Use a copy to handle potential removals
                    # Skip handlers that are already associated with a connected device
                    if (handler.device_name != "NULL" and 
                        handler.device_name in self.devices and 
                        self.devices[handler.device_name]["connection_status"] == ConnectionStatus.CONNECTED):
                        continue
                        
                    # Send initial handshake request with 0x00 payload using Command.py
                    Command.send_handshake(bytes([0x00]), handler)
                
                # Wait before next attempt
                time.sleep(1)
                
            # Print discovery results
            print("\nDevice Discovery Results:")
            for device_name, device_info in self.devices.items():
                status = device_info["connection_status"].name
                port = device_info["port_number"] if status != "NOT_CONNECTED" else "N/A"
                print(f"{device_name}: {status} on {port}")
            
            # Close handlers for devices that weren't connected
            self._cleanup_unused_handlers()
            
            return self.get_connected_devices()
                    
        except Exception as e:
            print(f"Error during device discovery: {e}")
            # Clean up on error
            self._cleanup_handlers()
            return {}

    def connect_specific_device(self, device_name, timeout=15):
        """
        Attempt to connect to a specific device by name.
        
        Args:
            device_name: The name of the device to connect (must exist in devices)
            timeout: Maximum time to spend attempting to connect (seconds)
            
        Returns:
            The handler for the connected device, or None if connection failed
        """
        print(f"Attempting to connect to {device_name}...")
        
        # Check if device exists in the dictionary
        if device_name not in self.devices:
            print(f"Error: Device '{device_name}' not found in available devices")
            return None
        
        # Check if device is already connected
        device_info = self.devices[device_name]
        if device_info["connection_status"] == ConnectionStatus.CONNECTED and device_info["handler"]:
            print(f"Device {device_name} is already connected")
            return device_info["handler"]
        
        # Reset device status
        device_info["connection_status"] = ConnectionStatus.NOT_CONNECTED
        device_info["port_number"] = "NULL"
        device_info["handler"] = None
        device_info["thread"] = None
        
        # Get list of available COM ports
        ports = serial.tools.list_ports.comports()
        if not ports:
            print("No COM ports found")
            return None
            
        print(f"Found {len(ports)} COM ports, searching for {device_name}...")
        
        # Clear existing handlers that aren't associated with other connected devices
        self._cleanup_unused_handlers()
        
        try:
            # Create handlers for each port
            for port in ports:
                print(f"Checking {port.device}...")
                handler = SerialMessageHandler(port.device, 115200, debug=True)
                # Use a lambda to bind 'self' to the handshake_response method
                handler.register_command(bytes([0xFF]), lambda h, p: self.send_handshake_response(h, p))
                self.handlers.append(handler)
            
            # Start time for timeout
            start_time = time.time()
            
            # Send handshake requests to all ports until we find our device
            while time.time() - start_time < timeout:
                # Check if our device is connected
                if device_info["connection_status"] == ConnectionStatus.CONNECTED:
                    print(f"Successfully connected to {device_name} on {device_info['port_number']}")
                    break
                    
                # Send handshake requests to all handlers
                for handler in self.handlers[:]:  # Use a copy to handle potential removals
                    # Skip handlers that are already associated with a connected device
                    if handler.device_name != "NULL" and handler.device_name != device_name:
                        continue
                        
                    # Send initial handshake request with 0x00 payload
                    Command.send_handshake(bytes([0x00]), handler)
                
                # Wait before next attempt
                time.sleep(1)
            
            # Clean up handlers that are not for our device
            # but keep handlers for already connected devices
            self._cleanup_unused_handlers()
            
            # Check if connection was successful
            if device_info["connection_status"] == ConnectionStatus.CONNECTED:
                return device_info["handler"]
            else:
                print(f"Failed to connect to {device_name} within timeout period")
                return None
                
        except Exception as e:
            print(f"Error during device connection: {e}")
            self._cleanup_handlers()
            return None

    def disconnect_device(self, device_name):
        """
        Disconnect a specific device by name.
        
        Args:
            device_name: The name of the device to disconnect
            
        Returns:
            bool: True if successfully disconnected, False otherwise
        """
        print(f"Disconnecting {device_name}...")
        
        # Check if device exists in the dictionary
        if device_name not in self.devices:
            print(f"Error: Device '{device_name}' not found in available devices")
            return False
        
        device_info = self.devices[device_name]
        
        # Check if device is connected
        if device_info["connection_status"] != ConnectionStatus.CONNECTED:
            print(f"Device {device_name} is not connected")
            return False
        
        # Stop the device handler
        if device_info["handler"]:
            try:
                print(f"Stopping connection to {device_name}...")
                success = device_info["handler"].stop_thread(timeout=5.0)
                
                # Update device status
                device_info["connection_status"] = ConnectionStatus.NOT_CONNECTED
                device_info["port_number"] = "NULL"
                device_info["handler"] = None
                device_info["thread"] = None
                
                if success:
                    print(f"Successfully disconnected {device_name}")
                else:
                    print(f"Warning: Thread for {device_name} may still be running")
                    
                return success
            except Exception as e:
                print(f"Error disconnecting {device_name}: {e}")
                return False
        else:
            print(f"Device {device_name} has no active handler")
            # Update status anyway
            device_info["connection_status"] = ConnectionStatus.NOT_CONNECTED
            device_info["port_number"] = "NULL"
            device_info["thread"] = None
            return True
    
    def disconnect_all_devices(self):
        """
        Disconnect all connected devices
        
        Returns:
            bool: True if all devices were successfully disconnected
        """
        success = True
        for device_name in self.devices:
            if self.devices[device_name]["connection_status"] == ConnectionStatus.CONNECTED:
                if not self.disconnect_device(device_name):
                    success = False
        
        # Clean up any remaining handlers
        self._cleanup_handlers()
        return success
        
    def _cleanup_handlers(self):
        """Close and remove all handlers"""
        for handler in self.handlers[:]:  # Use a copy of the list since we'll be modifying it
            try:
                handler.close_connection()
            except Exception as e:
                print(f"Error closing handler: {e}")
            
            # Remove from our list
            if handler in self.handlers:
                self.handlers.remove(handler)
    
    def _cleanup_unused_handlers(self):
        """Close and remove handlers that aren't associated with connected devices"""
        for handler in self.handlers[:]:  # Use a copy of the list since we'll be modifying it
            # If handler isn't associated with a device or device isn't connected, close it
            if (handler.device_name == "NULL" or 
                handler.device_name not in self.devices or 
                self.devices[handler.device_name]["connection_status"] != ConnectionStatus.CONNECTED):
                try:
                    handler.close_connection()
                except Exception as e:
                    print(f"Error closing handler: {e}")
                
                # Remove from our list
                if handler in self.handlers:
                    self.handlers.remove(handler)


# Example device dictionary - can be replaced with any device configuration
default_devices = {
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