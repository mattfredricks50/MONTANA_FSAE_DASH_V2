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


class CANThread(threading.Thread):
    """Thread for reading CAN bus data"""
    
    def __init__(self, signal_buffer, simulate=True):
        super().__init__(daemon=True)
        self.buffer = signal_buffer
        self.simulate = simulate
        self.stop_event = threading.Event()
        
    def run(self):
        print("CAN thread started")
        
        if self.simulate:
            self._simulate_can()
        else:
            self._read_can()
    
    def _simulate_can(self):
        """Simulate CAN data for testing"""
        rpm = 1000
        speed = 0
        rpm_direction = 40  # Even slower RPM change
        
        while not self.stop_event.is_set():
            # Simulate realistic RPM and speed (up to 13500 RPM)
            rpm += rpm_direction
            if rpm >= 13500:
                rpm = 13500
                rpm_direction = -40
            elif rpm <= 1000:
                rpm = 1000
                rpm_direction = 40
            
            speed = int(rpm / 100)  # Simple speed correlation
            
            # Calculate throttle and brake based on RPM direction
            if rpm_direction > 0:
                # Accelerating - high throttle, no brake
                throttle = min(100, int((rpm - 1000) / 125))  # 0-100% as RPM increases
                brake = 0
            else:
                # Decelerating - no throttle, high brake
                throttle = 0
                brake = min(100, int((13500 - rpm) / 125))  # 0-100% as RPM decreases
            
            # Update buffer with CAN data
            self.buffer.update_multiple({
                'rpm': rpm,
                'speed': speed,
                'coolant_temp': random.randint(180, 210),
                'oil_pressure': random.randint(40, 65),
                'throttle': throttle,
                'brake': brake
            })
            
            # Use wait instead of sleep - allows quick interruption
            self.stop_event.wait(0.01)
    
    def _read_can(self):
        """Real CAN bus reading (to be implemented)"""
        # TODO: Implement with python-can library
        pass
    
    def stop(self):
        self.stop_event.set()


class SensorThread(threading.Thread):
    """Thread for reading analog sensors (throttle, brake, etc.)"""
    
    def __init__(self, signal_buffer, simulate=True):
        super().__init__(daemon=True)
        self.buffer = signal_buffer
        self.simulate = simulate
        self.stop_event = threading.Event()
    
    def run(self):
        print("Sensor thread started")
        
        if self.simulate:
            self._simulate_sensors()
        else:
            self._read_sensors()
    
    def _simulate_sensors(self):
        """Simulate sensor data for testing"""
        # Throttle and brake now simulated in CAN thread
        # This can be used for other analog sensors if needed
        while not self.stop_event.is_set():
            self.stop_event.wait(0.02)  # 50Hz sensor update rate
    
    def _read_sensors(self):
        """Real sensor reading (to be implemented)"""
        # TODO: Implement with ADS1115 or serial from Arduino
        pass
    
    def stop(self):
        self.stop_event.set()


# Test the system
if __name__ == "__main__":
    print("Starting Race Dash Data Acquisition Test\n")
    
    # Create shared signal buffer
    buffer = SignalBuffer()
    
    # Start acquisition threads
    can_thread = CANThread(buffer, simulate=True)
    sensor_thread = SensorThread(buffer, simulate=True)
    
    can_thread.start()
    sensor_thread.start()
    
    # Monitor data for 10 seconds
    try:
        for i in range(50):  # 5 seconds at 10Hz display rate
            data = buffer.get_all()
            print(f"\rRPM: {data['rpm']:5d} | Speed: {data['speed']:3d} mph | "
                  f"Throttle: {data['throttle']:3d}% | Brake: {data['brake']:3d}% | "
                  f"Temp: {data['coolant_temp']:3d}°F | Oil: {data['oil_pressure']:2d} psi",
                  end='', flush=True)
            time.sleep(0.1)
    
    except KeyboardInterrupt:
        print("\n\nStopping...")
    
    # Stop threads
    can_thread.stop()
    sensor_thread.stop()
    
    print("\n\nTest complete!")
    print(f"Final values: {buffer.get_all()}")