"""
Race Dash - Core Data Acquisition System
Step 1: Thread-safe signal buffer and acquisition threads
"""

import threading
import time
import random
from collections import deque


class SignalBuffer:
    """Thread-safe buffer for storing latest sensor values"""
    
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {
            'rpm': 0,
            'speed': 0,
            'throttle': 0,
            'brake': 0,
            'coolant_temp': 0,
            'oil_pressure': 0,
            'lat': 0.0,
            'lon': 0.0,
            'gps_speed': 0.0,
            'gps_satellites': 0,
            'timestamp': 0
        }
        # Optional: store history for each signal
        self.history = {key: deque(maxlen=100) for key in self.data.keys()}
    
    def update(self, key, value):
        """Update a single signal value"""
        with self.lock:
            self.data[key] = value
            self.data['timestamp'] = time.time()
            self.history[key].append((time.time(), value))
    
    def update_multiple(self, updates):
        """Update multiple signals at once (more efficient)"""
        with self.lock:
            for key, value in updates.items():
                self.data[key] = value
            self.data['timestamp'] = time.time()
            for key, value in updates.items():
                if key in self.history:
                    self.history[key].append((time.time(), value))
    
    def get(self, key):
        """Get a single signal value"""
        with self.lock:
            return self.data.get(key, 0)
    
    def get_all(self):
        """Get a snapshot of all current values"""
        with self.lock:
            return self.data.copy()
    
    def get_history(self, key, count=None):
        """Get historical values for a signal"""
        with self.lock:
            if count:
                return list(self.history[key])[-count:]
            return list(self.history[key])


class UARTThread(threading.Thread):
    """Thread for reading CSV data from STM32 over UART
    
    The STM32 handles all sensor reading (CAN, analog, GPS) and sends
    a simplified CSV line to the Pi at ~25Hz for display.
    
    CSV format from STM32:
      RPM,SPEED_MPH,THROTTLE_PCT,BRAKE_PCT,CLT_F,OIL_PSI,LAT,LON,GPS_SPD,GPS_SATS
    
    Lines starting with '#' are comments/status messages from STM32.
    All values arrive in imperial (°F, mph, psi).
    """
    
    # CSV field order (must match STM32 send_to_pi())
    CSV_FIELDS = [
        'rpm', 'speed', 'throttle', 'brake',
        'coolant_temp', 'oil_pressure',
        'lat', 'lon', 'gps_speed', 'gps_satellites'
    ]
    # Which fields are integers (rest are float)
    INT_FIELDS = {'rpm', 'speed', 'throttle', 'brake',
                  'coolant_temp', 'oil_pressure', 'gps_satellites'}
    
    def __init__(self, signal_buffer, simulate=True,
                 port='/dev/ttyAMA0', baud=115200):
        super().__init__(daemon=True)
        self.buffer = signal_buffer
        self.simulate = simulate
        self.port = port
        self.baud = baud
        self.stop_event = threading.Event()
        self.parse_errors = 0
        self.lines_parsed = 0
        
    def run(self):
        if self.simulate:
            print("UART thread started (SIMULATION)")
            self._simulate_data()
        else:
            print(f"UART thread started ({self.port} @ {self.baud})")
            self._read_uart()
    
    def _parse_csv_line(self, line):
        """Parse one CSV line from STM32 into signal buffer updates.
        Returns True on success, False on parse error."""
        line = line.strip()
        
        # Skip comments and empty lines
        if not line or line.startswith('#'):
            return True
        
        parts = line.split(',')
        if len(parts) < 6:
            # Need at least RPM through oil_pressure
            self.parse_errors += 1
            return False
        
        try:
            update = {}
            for i, field in enumerate(self.CSV_FIELDS):
                if i >= len(parts):
                    break
                val = parts[i].strip()
                if not val:
                    continue
                if field in self.INT_FIELDS:
                    update[field] = int(float(val))
                else:
                    update[field] = float(val)
            
            self.buffer.update_multiple(update)
            self.lines_parsed += 1
            return True
        
        except (ValueError, IndexError):
            self.parse_errors += 1
            return False
    
    def _read_uart(self):
        """Read CSV lines from STM32 over UART using pyserial"""
        try:
            import serial
        except ImportError:
            print("ERROR: pyserial not installed. Run: pip install pyserial")
            print("Falling back to simulation mode")
            self._simulate_data()
            return
        
        while not self.stop_event.is_set():
            try:
                ser = serial.Serial(
                    port=self.port,
                    baudrate=self.baud,
                    timeout=1.0,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE
                )
                print(f"UART connected: {self.port}")
                
                while not self.stop_event.is_set():
                    line = ser.readline().decode('ascii', errors='ignore')
                    if line:
                        self._parse_csv_line(line)
                
                ser.close()
            
            except serial.SerialException as e:
                print(f"UART error: {e}, retrying in 2s...")
                self.stop_event.wait(2.0)
            except Exception as e:
                print(f"UART unexpected error: {e}")
                self.stop_event.wait(2.0)
    
    def _simulate_data(self):
        """Simulate STM32 CSV data for PC testing"""
        rpm = 1000
        rpm_direction = 40
        
        while not self.stop_event.is_set():
            rpm += rpm_direction
            if rpm >= 13500:
                rpm = 13500
                rpm_direction = -40
            elif rpm <= 1000:
                rpm = 1000
                rpm_direction = 40
            
            speed = int(rpm / 100)
            
            if rpm_direction > 0:
                throttle = min(100, int((rpm - 1000) / 125))
                brake = 0
            else:
                throttle = 0
                brake = min(100, int((13500 - rpm) / 125))
            
            # Build a CSV line exactly like the STM32 would send
            csv_line = (f"{rpm},{speed},{throttle},{brake},"
                       f"{random.randint(180, 210)},{random.randint(40, 65)},"
                       f"40.712800,-74.006000,{speed * 0.95:.1f},8")
            
            self._parse_csv_line(csv_line)
            self.stop_event.wait(0.04)  # 25Hz like real STM32
    
    def stop(self):
        self.stop_event.set()


class SensorThread(threading.Thread):
    """Placeholder - all sensors handled by STM32 now.
    
    Kept for backward compatibility. Does nothing in real mode.
    Could be repurposed for Pi-side sensors if ever needed
    (e.g. a USB accelerometer or Pi camera).
    """
    
    def __init__(self, signal_buffer, simulate=True):
        super().__init__(daemon=True)
        self.buffer = signal_buffer
        self.simulate = simulate
        self.stop_event = threading.Event()
    
    def run(self):
        # Nothing to do — STM32 sends everything over UART
        while not self.stop_event.is_set():
            self.stop_event.wait(1.0)
    
    def stop(self):
        self.stop_event.set()


# Backward compatibility alias
CANThread = UARTThread


# Test the system
if __name__ == "__main__":
    print("Starting Race Dash Data Acquisition Test\n")
    
    # Test CSV parsing directly
    print("=== CSV Parser Test ===")
    buf = SignalBuffer()
    t = UARTThread(buf, simulate=True)
    
    # Test valid line
    assert t._parse_csv_line("8500,85,75,0,195,52,40.712800,-74.006000,80.5,8")
    data = buf.get_all()
    assert data['rpm'] == 8500
    assert data['speed'] == 85
    assert data['coolant_temp'] == 195
    print(f"  Valid CSV:    OK  (RPM={data['rpm']}, Speed={data['speed']}, CLT={data['coolant_temp']}F)")
    
    # Test minimal line (just 6 fields)
    assert t._parse_csv_line("9000,90,80,0,200,55")
    data = buf.get_all()
    assert data['rpm'] == 9000
    print(f"  Minimal CSV:  OK  (RPM={data['rpm']})")
    
    # Test comment line
    assert t._parse_csv_line("# Race Dash STM32 starting...")
    print(f"  Comment skip: OK")
    
    # Test bad line
    assert not t._parse_csv_line("garbage")
    print(f"  Bad line:     OK  (rejected, errors={t.parse_errors})")
    
    print("\n=== Live Simulation Test (5s) ===")
    buffer = SignalBuffer()
    uart_thread = UARTThread(buffer, simulate=True)
    uart_thread.start()
    
    try:
        for i in range(50):
            data = buffer.get_all()
            print(f"\rRPM: {data['rpm']:5d} | Speed: {data['speed']:3d} mph | "
                  f"Throttle: {data['throttle']:3d}% | Brake: {data['brake']:3d}% | "
                  f"CLT: {data['coolant_temp']:3d}F | Oil: {data['oil_pressure']:2d} psi | "
                  f"Lines: {uart_thread.lines_parsed}",
                  end='', flush=True)
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\nStopping...")
    
    uart_thread.stop()
    print(f"\n\nTest complete! Lines parsed: {uart_thread.lines_parsed}, "
          f"Parse errors: {uart_thread.parse_errors}")
    print(f"Final: {buffer.get_all()}")