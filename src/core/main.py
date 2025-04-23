import time
from DeviceManager import io_devices, discover_devices, connect_specific_device, disconnect_device

def main():
    print("Serial Message Handler")
    print("=====================")
    
    try:
        # Example of using the specific device connection functions
        print("1. Connect to all devices")
        print("2. Connect to a specific device")
        print("3. Disconnect a specific device")
        print("4. Exit")
        
        choice = input("Enter your choice (1-4): ")
        
        if choice == "1":
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
                    
        elif choice == "2":
            # Connect to a specific device
            device_name = input("Enter device name (gpio/led/turret): ")
            handler = connect_specific_device(device_name)
            
            if handler:
                print(f"Connected to {device_name}. Press Ctrl+C to exit...")
                while True:
                    time.sleep(1)
            
        elif choice == "3":
            # Disconnect a specific device
            device_name = input("Enter device name to disconnect: ")
            success = disconnect_device(device_name)
            if success:
                print(f"Device {device_name} disconnected successfully")
            else:
                print(f"Failed to disconnect {device_name}")
                
        elif choice == "4":
            print("Exiting...")
        
        else:
            print("Invalid choice")
                
    except KeyboardInterrupt:
        print("\nShutting down...")
        
    finally:
        print("Closing all connections...")
        # Close all device handlers
        for device_name, device_info in io_devices.items():
            if device_info["handler"]:
                try:
                    print(f"Closing connection to {device_name}...")
                    device_info["handler"].stop_thread(timeout=5.0)
                except Exception as e:
                    print(f"Error stopping thread for {device_name}: {e}")
        
        print("Done!")

if __name__ == "__main__":
    main()