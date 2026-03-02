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


class UARTThread(threading.Thread):
    """Thread for reading data from STM32 over UART
    
    The STM32 sends all sensor data (from its own CAN/analog/GPS)
    over UART using the RealDash 66 protocol. All values arrive
    in imperial units (°F, mph, psi).
    """
    
    def __init__(self, signal_buffer, simulate=True):
        super().__init__(daemon=True)
        self.buffer = signal_buffer
        self.simulate = simulate
        self.stop_event = threading.Event()
        
    def run(self):
        print("UART thread started")
        
        if self.simulate:
            self._simulate_data()
        else:
            self._read_uart()
    
    def _simulate_data(self):
        """Simulate UART data for testing"""
        rpm = 1000
        speed = 0
        rpm_direction = 40
        
        while not self.stop_event.is_set():
            rpm += rpm_direction
            if rpm >= 13500:
                rpm = 13500
                rpm_direction = -40
            elif rpm <= 1000:
                rpm = 1000
                rpm_direction = 40
            
            speed = int(rpm / 100)  # Simple speed correlation (mph)
            
            if rpm_direction > 0:
                throttle = min(100, int((rpm - 1000) / 125))
                brake = 0
            else:
                throttle = 0
                brake = min(100, int((13500 - rpm) / 125))
            
            # All values in imperial (°F, mph, psi)
            self.buffer.update_multiple({
                'rpm': rpm,
                'speed': speed,
                'coolant_temp': random.randint(180, 210),
                'oil_pressure': random.randint(40, 65),
                'throttle': throttle,
                'brake': brake
            })
            
            self.stop_event.wait(0.01)
    
    def _read_uart(self):
        """Real UART reading from STM32 (RealDash 66 protocol)
        
        TODO: Implement with pyserial
          - Open config['data']['uart_port'] at config['data']['uart_baud']
          - Parse RealDash 66 frames
          - Update signal buffer with decoded values
        """
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


# Backward compatibility alias
CANThread = UARTThread


# Test the system
if __name__ == "__main__":
    print("Starting Race Dash Data Acquisition Test\n")
    
    # Create shared signal buffer
    buffer = SignalBuffer()
    
    # Start acquisition threads
    uart_thread = UARTThread(buffer, simulate=True)
    sensor_thread = SensorThread(buffer, simulate=True)
    
    uart_thread.start()
    sensor_thread.start()
    
    # Monitor data for 5 seconds
    try:
        for i in range(50):
            data = buffer.get_all()
            print(f"\rRPM: {data['rpm']:5d} | Speed: {data['speed']:3d} mph | "
                  f"Throttle: {data['throttle']:3d}% | Brake: {data['brake']:3d}% | "
                  f"Temp: {data['coolant_temp']:3d}F | Oil: {data['oil_pressure']:2d} psi",
                  end='', flush=True)
            time.sleep(0.1)
    
    except KeyboardInterrupt:
        print("\n\nStopping...")
    
    # Stop threads
    uart_thread.stop()
    sensor_thread.stop()
    
    print("\n\nTest complete!")
    print(f"Final values: {buffer.get_all()}")