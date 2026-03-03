"""
Race Dash - Configuration
Central config for all dash settings. Saves/loads from config.json.
Edit DEFAULT_CONFIG below or change settings from the in-dash Settings page.

DATA ASSUMPTIONS:
  - All data arrives over UART from the STM32 MCU
  - Raw data from MCU is ALWAYS in imperial: °F, mph, psi
  - Unit conversion happens at display time only
"""

import json
import os
import copy

# ============================================================
# DEFAULT CONFIGURATION
# All settings live here. Edit defaults below, or they can be
# changed at runtime from the Settings screen and saved to
# config.json which overrides these defaults.
# ============================================================

DEFAULT_CONFIG = {

    # ── Display ──────────────────────────────────────────────
    'screen': {
        'width': 800,
        'height': 480,
        'fps': 30,
        'fullscreen': False,      # True for Pi (requires restart)
        'title': 'Race Dash',
        'brightness': 100,        # 0-100, Pi backlight only
    },

    # ── Engine / RPM ─────────────────────────────────────────
    'engine': {
        'max_rpm': 13500,
        'shift_rpm': 10000,       # Shift lights start here
        'critical_rpm': 11250,    # All lights on / flash
        'redline_rpm': 12500,
        'idle_rpm': 1000,
        'num_gears': 6,
        # Gear ratio speed breakpoints (mph) - speed < value = that gear
        'gear_speeds': [15, 30, 50, 70, 90, 999],
    },

    # ── Warning Thresholds (always stored in imperial) ───────
    # These are compared against raw data which is in °F / psi
    'warnings': {
        'coolant_high': 220,      # °F - yellow warning
        'coolant_critical': 240,  # °F - red flash
        'oil_low': 25,            # psi - yellow warning
        'oil_critical': 15,       # psi - red flash
    },

    # ── Display Units (conversion applied at render time) ────
    # Raw data from MCU is ALWAYS imperial (°F, mph, psi).
    # These settings only affect what's shown on screen.
    'units': {
        'speed': 'mph',           # 'mph' or 'kph'
        'temp': 'F',              # 'F' or 'C'
        'pressure': 'psi',        # 'psi' or 'bar'
    },

    # ── Data Source (UART from STM32) ────────────────────────
    'data': {
        'simulate': True,         # True = fake data for testing
        'uart_port': '/dev/ttyAMA0',   # Pi GPIO UART
        'uart_baud': 115200,
    },

    # ── Driver / Event ───────────────────────────────────────
    # Shown on dash header and tagged in log files so you know
    # which driver was in the car and what event the data is from.
    'driver': {
        'name': 'Default',
        'event': 'Endurance',
    },

    # ── Enabled Screens ──────────────────────────────────────
    # List of screen IDs to show in swipe rotation.
    # Available: lap_timer, main_gauge, drag, strip, gps, diagnostics, warnings
    # Settings screen is always available (not listed here).
    'screens': {
        'enabled': ['lap_timer', 'main_gauge', 'diagnostics'],
    },

    # ── Colors (RGB tuples) ──────────────────────────────────
    'colors': {
        'bg':              [10,  10,  15],
        'panel':           [22,  22,  28],
        'panel_border':    [40,  40,  50],
        'text':            [220, 220, 220],
        'text_dim':        [100, 100, 110],
        'text_label':      [70,  75,  85],
        'rpm_green':       [0,   220, 60],
        'rpm_yellow':      [255, 210, 0],
        'rpm_orange':      [255, 140, 0],
        'rpm_red':         [255, 30,  30],
        'shift_off':       [30,  30,  35],
        'gear_yellow':     [255, 230, 0],
        'speed_white':     [255, 255, 255],
        'clt_blue':        [80,  180, 255],
        'throttle_green':  [0,   200, 80],
        'brake_red':       [220, 30,  30],
        'best_green':      [0,   220, 80],
        'bar_bg':          [35,  35,  42],
        'warning_red':     [255, 40,  40],
        'warning_bg':      [80,  0,   0],
        'accent':          [0,   160, 255],
    },
}


# ============================================================
# UNIT CONVERSION
# Raw data from MCU is always imperial. These convert for display.
# ============================================================

def convert_speed(mph):
    """Convert mph to display unit"""
    if config.get('units', 'speed') == 'kph':
        return round(mph * 1.60934)
    return mph

def convert_temp(f):
    """Convert °F to display unit"""
    if config.get('units', 'temp') == 'C':
        return round((f - 32) * 5.0 / 9.0)
    return f

def convert_pressure(psi):
    """Convert psi to display unit"""
    if config.get('units', 'pressure') == 'bar':
        return round(psi * 0.0689476, 1)
    return psi

def speed_label():
    return config.get('units', 'speed').upper()

def temp_label():
    u = config.get('units', 'temp')
    return f"deg{u}"

def pressure_label():
    return config.get('units', 'pressure')


# ============================================================
# BRIGHTNESS CONTROL (Pi backlight)
# ============================================================

PI_BACKLIGHT_PATH = '/sys/class/backlight/rpi_backlight/brightness'
PI_BACKLIGHT_MAX = 255

def set_brightness(percent):
    """Set Pi display brightness (0-100%). No-op on PC."""
    percent = max(0, min(100, percent))
    try:
        val = int(PI_BACKLIGHT_MAX * percent / 100)
        with open(PI_BACKLIGHT_PATH, 'w') as f:
            f.write(str(val))
    except (FileNotFoundError, PermissionError):
        pass  # Not on a Pi or no permission — silently ignore


# ============================================================
# CONFIG MANAGER
# ============================================================

class ConfigManager:
    """Loads, saves, and provides access to configuration."""
    
    def __init__(self, config_path=None):
        if config_path is None:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(script_dir, 'config.json')
        
        self.config_path = config_path
        self.data = copy.deepcopy(DEFAULT_CONFIG)
        self.load()
    
    def load(self):
        """Load config from JSON, merging with defaults"""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    saved = json.load(f)
                self._merge(self.data, saved)
                print(f"Config loaded from {self.config_path}")
            except Exception as e:
                print(f"Config load error: {e}, using defaults")
        else:
            print("No config.json found, using defaults")
        # Apply brightness on load
        set_brightness(self.data['screen']['brightness'])
    
    def save(self):
        """Save current config to JSON"""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(self.data, f, indent=2)
            print(f"Config saved to {self.config_path}")
            return True
        except Exception as e:
            print(f"Config save error: {e}")
            return False
    
    def reset(self):
        """Reset to defaults"""
        self.data = copy.deepcopy(DEFAULT_CONFIG)
    
    def _merge(self, base, override):
        """Recursively merge override into base"""
        for key, val in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(val, dict):
                self._merge(base[key], val)
            else:
                base[key] = val
    
    # ── Convenience accessors ──
    
    def __getitem__(self, key):
        return self.data[key]
    
    def get(self, section, key=None):
        if key is None:
            return self.data.get(section, {})
        return self.data.get(section, {}).get(key)
    
    def set(self, section, key, value):
        if section not in self.data:
            self.data[section] = {}
        self.data[section][key] = value
        # Live-apply brightness changes
        if section == 'screen' and key == 'brightness':
            set_brightness(value)
    
    def color(self, name):
        """Get a color as a tuple (JSON stores as lists)"""
        c = self.data['colors'].get(name, [255, 0, 255])
        return tuple(c)


# ============================================================
# SETTINGS DEFINITIONS
# Defines what appears on the Settings screen.
# Each entry: (section, key, display_name, type, min, max, step)
#   type: 'int', 'bool', 'choice'
# ============================================================

SETTINGS_PAGES = {
    'Engine': [
        ('engine',   'max_rpm',      'Max RPM',         'int',  8000, 16000, 500),
        ('engine',   'shift_rpm',    'Shift Light On',  'int',  6000, 15000, 250),
        ('engine',   'critical_rpm', 'Shift Flash RPM', 'int',  6000, 15000, 250),
        ('engine',   'redline_rpm',  'Redline RPM',     'int',  6000, 16000, 500),
        ('engine',   'idle_rpm',     'Idle RPM',        'int',  500,  3000,  100),
    ],
    'Warnings': [
        # Thresholds stored in imperial (°F, psi) — always compared
        # against raw MCU data which is also imperial
        ('warnings', 'coolant_high',     'CLT Warn (F)',     'int', 160, 260, 5),
        ('warnings', 'coolant_critical', 'CLT Critical (F)', 'int', 180, 280, 5),
        ('warnings', 'oil_low',          'Oil Warn (psi)',   'int', 10,  50,  5),
        ('warnings', 'oil_critical',     'Oil Crit (psi)',   'int', 5,   40,  5),
    ],
    'Display': [
        ('screen',   'brightness',  'Brightness %',    'int',  10, 100, 10),
        ('units',    'speed',       'Speed Unit',       'choice', 0, 0, 0),
        ('units',    'temp',        'Temp Unit',        'choice', 0, 0, 0),
        ('units',    'pressure',    'Pressure Unit',    'choice', 0, 0, 0),
    ],
    'Data': [
        ('data',     'simulate',    'Simulate Data',   'bool', 0, 0, 0),
        ('data',     'uart_baud',   'UART Baud Rate',  'choice', 0, 0, 0),
    ],
    'Driver': [
        # Shown on dash and tagged in log files
        ('driver',   'name',        'Driver Name',     'choice', 0, 0, 0),
        ('driver',   'event',       'Event',           'choice', 0, 0, 0),
    ],
}

# Choice options for 'choice' type settings
SETTING_CHOICES = {
    ('units', 'speed'):       ['mph', 'kph'],
    ('units', 'temp'):        ['F', 'C'],
    ('units', 'pressure'):    ['psi', 'bar'],
    ('data', 'uart_baud'):    [9600, 57600, 115200, 230400, 460800],
    ('driver', 'name'):       ['Default', 'Driver 1', 'Driver 2', 'Driver 3'],
    ('driver', 'event'):      ['Endurance', 'Autocross', 'Skidpad', 'Acceleration', 'Practice'],
}


# ============================================================
# Global config instance - import this in other modules
# ============================================================

config = ConfigManager()