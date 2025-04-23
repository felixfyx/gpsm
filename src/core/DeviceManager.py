import serial
import serial.tools.list_ports
import time
import Command
from SerialMessageHandler import SerialMessageHandler, ConnectionStatus

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
                    
                # Send initial handshake request with 0x00 payload using Command.py
                Command.send_handshake(bytes([0x00]), handler)
            
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


def connect_specific_device(device_name, timeout=15):
    """
    Attempt to connect to a specific device by name.
    
    Args:
        device_name: The name of the device to connect (must exist in io_devices)
        timeout: Maximum time to spend attempting to connect (seconds)
        
    Returns:
        The handler for the connected device, or None if connection failed
    """
    print(f"Attempting to connect to {device_name}...")
    
    # Check if device exists in the dictionary
    if device_name not in io_devices:
        print(f"Error: Device '{device_name}' not found in available devices")
        return None
    
    # Check if device is already connected
    device_info = io_devices[device_name]
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
    
    handlers = []
    
    try:
        # Create handlers for each port
        for port in ports:
            print(f"Checking {port.device}...")
            handler = SerialMessageHandler(port.device, 115200, debug=True)
            handler.register_command(bytes([0xFF]), send_handshake_response)
            handlers.append(handler)
        
        # Start time for timeout
        start_time = time.time()
        
        # Send handshake requests to all ports until we find our device
        while time.time() - start_time < timeout:
            # Check if our device is connected
            if device_info["connection_status"] == ConnectionStatus.CONNECTED:
                print(f"Successfully connected to {device_name} on {device_info['port_number']}")
                break
                
            # Send handshake requests to all handlers
            for handler in handlers:
                # Skip handlers that are already associated with a connected device
                if handler.device_name != "NULL" and handler.device_name != device_name:
                    continue
                    
                # Send initial handshake request with 0x00 payload using Command.py
                Command.send_handshake(bytes([0x00]), handler)
            
            # Wait before next attempt
            time.sleep(1)
        
        # Clean up handlers that are not for our device
        for handler in handlers[:]:  # Create a copy of list for iteration
            if handler.device_name != device_name:
                handler.stop_thread()
                handlers.remove(handler)
        
        # Check if connection was successful
        if device_info["connection_status"] == ConnectionStatus.CONNECTED:
            return device_info["handler"]
        else:
            print(f"Failed to connect to {device_name} within timeout period")
            # Clean up any remaining handlers
            for handler in handlers:
                handler.stop_thread()
            return None
            
    except Exception as e:
        print(f"Error during device connection: {e}")
        # Clean up all handlers on error
        for handler in handlers:
            try:
                handler.stop_thread()
            except:
                pass
        return None


def disconnect_device(device_name):
    """
    Disconnect a specific device by name.
    
    Args:
        device_name: The name of the device to disconnect
        
    Returns:
        bool: True if successfully disconnected, False otherwise
    """
    print(f"Disconnecting {device_name}...")
    
    # Check if device exists in the dictionary
    if device_name not in io_devices:
        print(f"Error: Device '{device_name}' not found in available devices")
        return False
    
    device_info = io_devices[device_name]
    
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