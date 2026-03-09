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
            'accel_x': 0.0,
            'accel_y': 0.0,
            'accel_z': 0.0,
            'gear': 0,
            'clutch': 0,
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
      RPM,SPEED,THROTTLE,BRAKE,CLT,OIL,LAT,LON,GPS_SPD,GPS_SATS,AX,AY,AZ,GEAR,CLUTCH
    
    Lines starting with '#' are comments/status messages from STM32.
    All values arrive in imperial (°F, mph, psi).
    """
    
    # CSV field order (must match STM32 send_to_pi())
    CSV_FIELDS = [
        'rpm', 'speed', 'throttle', 'brake',
        'coolant_temp', 'oil_pressure',
        'lat', 'lon', 'gps_speed', 'gps_satellites',
        'accel_x', 'accel_y', 'accel_z',
        'gear', 'clutch'
    ]
    # Which fields are integers (rest are float)
    INT_FIELDS = {'rpm', 'speed', 'throttle', 'brake',
                  'coolant_temp', 'oil_pressure', 'gps_satellites',
                  'gear', 'clutch'}
    
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
        """Simulate STM32 CSV data for PC testing.
        
        Simulates actually riding through the gears on a CBR 600RR:
        Rev up in each gear, clutch in, shift up, RPM drops, repeat.
        After 6th gear, engine brake back down through the gears.
        Speed is derived from RPM + gear ratio (like real life).
        """
        import math as _m
        
        # CBR 600RR drivetrain — derive from VSS calibration value
        GEARS = [2.666, 1.937, 1.661, 1.409, 1.260, 1.166]
        PRI = 2.111
        VSS_TEETH = 28
        SHIFT_RPM = 12500
        IDLE_RPM = 2000

        # Try to read VSS cal from config, fall back to stock
        try:
            from race_dash_config import config as _cfg
            vss_ppm = _cfg.get('engine', 'vss_pulses_per_mph') or 16.65
        except Exception:
            vss_ppm = 16.65

        # Precompute RPM-per-MPH for each gear (same math as STM32)
        cs_rps_per_mph = vss_ppm / VSS_TEETH
        RPM_PER_MPH = [cs_rps_per_mph * PRI * g * 60.0 for g in GEARS]
        
        cur_gear = 0        # 0-indexed (0=1st, 5=6th)
        rpm = 3000.0
        accel = True        # True = accelerating up through gears
        clutch_timer = 0    # countdown ticks for clutch engagement
        
        while not self.stop_event.is_set():
            t = time.time()
            
            # ── Shift logic ──
            if clutch_timer > 0:
                # Mid-shift: clutch is in, RPM drops
                clutch_timer -= 1
                rpm = max(rpm - 200, IDLE_RPM)
                clutch = 1
                gear_display = 0
            elif accel:
                # Accelerating: rev up
                rpm += random.uniform(50, 90)
                clutch = 0
                gear_display = cur_gear + 1
                
                if rpm >= SHIFT_RPM:
                    if cur_gear < 5:
                        # Shift up
                        clutch_timer = 4  # ~160ms clutch pull
                        cur_gear += 1
                    else:
                        # Top gear, switch to decel
                        accel = False
            else:
                # Decelerating / engine braking back down
                rpm -= random.uniform(40, 70)
                clutch = 0
                gear_display = cur_gear + 1
                
                if rpm <= 4000:
                    if cur_gear > 0:
                        # Downshift
                        clutch_timer = 3
                        cur_gear -= 1
                        rpm = 8000  # RPM jumps up on downshift (engine braking)
                    else:
                        # Back in 1st, start over
                        accel = True
                        rpm = 3000
            
            # Clamp RPM
            rpm = max(IDLE_RPM, min(14000, rpm))
            
            # Calculate speed from RPM and current gear
            # speed = rpm / rpm_per_mph[gear]
            speed = max(0, int(rpm / RPM_PER_MPH[cur_gear])) if RPM_PER_MPH[cur_gear] > 0 else 0
            
            # Throttle/brake
            if clutch:
                throttle = 0
                brake = 0
            elif accel:
                throttle = min(100, int(60 + (rpm - 3000) / 200))
                brake = 0
            else:
                throttle = 0
                brake = min(100, int(30 + (8000 - rpm) / 150))
            
            # IMU
            spd_frac = speed / 150.0
            ax = _m.sin(t / 2.0) * spd_frac * 1.5
            ay = 0.5 if accel and not clutch else (-0.6 if not accel and not clutch else 0.0)
            az = 1.0 + _m.sin(t * 12) * 0.03

            # Fake GPS: drive a figure-8 track pattern
            # ~0.002 degrees ≈ 200m which is a reasonable FSAE track size
            track_t = t * 0.15  # slow loop (~40s per lap)
            sim_lat = 40.7128 + 0.001 * _m.sin(track_t)
            sim_lon = -74.0060 + 0.0015 * _m.sin(track_t * 2)

            csv_line = (f"{int(rpm)},{speed},{throttle},{brake},"
                       f"{random.randint(180, 210)},{random.randint(40, 65)},"
                       f"{sim_lat:.6f},{sim_lon:.6f},{speed * 0.95:.1f},8,"
                       f"{ax:.2f},{ay:.2f},{az:.2f},"
                       f"{gear_display},{clutch}")
            
            self._parse_csv_line(csv_line)
            self.stop_event.wait(0.04)  # 25Hz
    
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
    
    # Test valid line (with accel data)
    assert t._parse_csv_line("8500,85,75,0,195,52,40.712800,-74.006000,80.5,8,0.45,-0.30,1.02")
    data = buf.get_all()
    assert data['rpm'] == 8500
    assert data['speed'] == 85
    assert data['coolant_temp'] == 195
    assert abs(data['accel_x'] - 0.45) < 0.01
    print(f"  Valid CSV:    OK  (RPM={data['rpm']}, Speed={data['speed']}, CLT={data['coolant_temp']}F, Ax={data['accel_x']:.2f}g)")
    
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