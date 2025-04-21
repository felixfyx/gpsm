def calculate_checksum(data):
    """Calculate XOR checksum of bytes"""
    checksum = 0
    for byte in data:
        checksum ^= byte
    return checksum