"""
Race Dash - PyGame GUI
Clean, config-driven racing dashboard for Pi Zero 2W
Replaces Kivy version - runs on any platform including framebuffer
"""

import pygame
import pygame.gfxdraw
import sys
import os
import time
import math

# Import our data acquisition system
from race_dash_core import SignalBuffer, CANThread, SensorThread

# ============================================================
# CONFIGURATION - Edit these to customize your dash
# ============================================================

CONFIG = {
    'screen': {
        'width': 800,
        'height': 480,
        'fps': 30,
        'fullscreen': False,  # Set True for Pi deployment
        'title': 'Race Dash'
    },
    'engine': {
        'max_rpm': 13500,
        'shift_rpm': 10000,       # When shift lights start
        'critical_rpm': 11250,    # All lights on / flash
        'redline_rpm': 12500,
        'idle_rpm': 1000,
    },
    'warnings': {
        'coolant_high': 220,
        'coolant_critical': 240,
        'oil_low': 25,
        'oil_critical': 15,
    },
    'colors': {
        'bg':              (10,  10,  15),
        'panel':           (22,  22,  28),
        'panel_border':    (40,  40,  50),
        'text':            (220, 220, 220),
        'text_dim':        (100, 100, 110),
        'text_label':      (70,  75,  85),
        'rpm_green':       (0,   220, 60),
        'rpm_yellow':      (255, 210, 0),
        'rpm_orange':      (255, 140, 0),
        'rpm_red':         (255, 30,  30),
        'shift_off':       (30,  30,  35),
        'gear_yellow':     (255, 230, 0),
        'speed_white':     (255, 255, 255),
        'clt_blue':        (80,  180, 255),
        'throttle_green':  (0,   200, 80),
        'brake_red':       (220, 30,  30),
        'best_green':      (0,   220, 80),
        'bar_bg':          (35,  35,  42),
        'warning_red':     (255, 40,  40),
        'warning_bg':      (80,  0,   0),
    }
}


# ============================================================
# FONT MANAGER
# ============================================================

class FontManager:
    """Manages fonts with fallback to system defaults"""
    
    def __init__(self):
        pygame.font.init()
        self._cache = {}
        
        # Try to find a good monospace / racing-style font
        # On Pi, we'll use the system default which is clean enough
        self.mono_family = None
        self.sans_family = None
        
        # Check for custom fonts in a fonts/ directory
        font_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
        self.custom_font_path = None
        self.custom_bold_path = None
        
        if os.path.exists(font_dir):
            for f in os.listdir(font_dir):
                fl = f.lower()
                if 'bold' in fl and fl.endswith(('.ttf', '.otf')):
                    self.custom_bold_path = os.path.join(font_dir, f)
                elif fl.endswith(('.ttf', '.otf')):
                    self.custom_font_path = os.path.join(font_dir, f)
    
    def get(self, size, bold=False):
        key = (size, bold)
        if key not in self._cache:
            if bold and self.custom_bold_path:
                self._cache[key] = pygame.font.Font(self.custom_bold_path, size)
            elif self.custom_font_path:
                self._cache[key] = pygame.font.Font(self.custom_font_path, size)
            else:
                self._cache[key] = pygame.font.SysFont('consolas,dejavusansmono,liberationmono,mono', size, bold=bold)
        return self._cache[key]


# ============================================================
# DRAWING HELPERS
# ============================================================

def draw_rounded_rect(surface, rect, color, radius=8):
    """Draw a rounded rectangle"""
    x, y, w, h = rect
    r = min(radius, h // 2, w // 2)
    
    pygame.draw.rect(surface, color, (x + r, y, w - 2*r, h))
    pygame.draw.rect(surface, color, (x, y + r, w, h - 2*r))
    pygame.draw.circle(surface, color, (x + r, y + r), r)
    pygame.draw.circle(surface, color, (x + w - r, y + r), r)
    pygame.draw.circle(surface, color, (x + r, y + h - r), r)
    pygame.draw.circle(surface, color, (x + w - r, y + h - r), r)


def draw_text(surface, fonts, text, x, y, size=24, color=None, bold=False, anchor='topleft'):
    """Draw text with anchor support (topleft, center, midright, etc.)"""
    if color is None:
        color = CONFIG['colors']['text']
    font = fonts.get(size, bold)
    rendered = font.render(str(text), True, color)
    rect = rendered.get_rect()
    setattr(rect, anchor, (x, y))
    surface.blit(rendered, rect)
    return rect


def rpm_color(rpm):
    """Get color based on RPM value"""
    c = CONFIG['colors']
    e = CONFIG['engine']
    if rpm < 9000:
        return c['rpm_green']
    elif rpm < 11000:
        t = (rpm - 9000) / 2000.0
        return lerp_color(c['rpm_green'], c['rpm_yellow'], t)
    elif rpm < e['redline_rpm']:
        t = (rpm - 11000) / 1500.0
        return lerp_color(c['rpm_yellow'], c['rpm_red'], t)
    else:
        return c['rpm_red']


def lerp_color(c1, c2, t):
    """Linearly interpolate between two colors"""
    t = max(0, min(1, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


# ============================================================
# WIDGET DRAWING FUNCTIONS
# ============================================================

def draw_shift_lights(surface, x, y, w, h, rpm, flash_state):
    """Draw shift light bar across top"""
    c = CONFIG['colors']
    e = CONFIG['engine']
    num_lights = 10
    
    if rpm < e['shift_rpm']:
        lights_on = 0
        flash_all = False
    elif rpm >= e['critical_rpm']:
        lights_on = num_lights
        flash_all = True
    else:
        ratio = (rpm - e['shift_rpm']) / (e['critical_rpm'] - e['shift_rpm'])
        lights_on = int(ratio * num_lights)
        flash_all = False
    
    # Light order: center out
    light_order = [4, 5, 3, 6, 2, 7, 1, 8, 0, 9]
    
    light_w = (w - (num_lights + 1) * 4) / num_lights
    light_h = h - 8
    ly = y + 4
    
    for i in range(num_lights):
        lx = x + 4 + i * (light_w + 4)
        pos = light_order.index(i)
        is_on = pos < lights_on
        
        if flash_all and flash_state:
            color = c['rpm_red']
        elif is_on:
            if pos < 4:
                color = c['rpm_green']
            elif pos < 7:
                color = c['rpm_yellow']
            else:
                color = c['rpm_red']
        else:
            color = c['shift_off']
        
        draw_rounded_rect(surface, (int(lx), int(ly), int(light_w), int(light_h)), color, radius=4)


def draw_rpm_bar(surface, x, y, w, h, rpm):
    """Draw horizontal RPM bar with segmented look"""
    c = CONFIG['colors']
    e = CONFIG['engine']
    
    # Background
    draw_rounded_rect(surface, (x, y, w, h), c['bar_bg'], radius=6)
    
    ratio = min(rpm / e['max_rpm'], 1.0)
    fill_w = int((w - 8) * ratio)
    
    if fill_w > 0:
        # Draw filled segments
        seg_w = 6
        seg_gap = 2
        sx = x + 4
        drawn = 0
        while drawn < fill_w:
            sw = min(seg_w, fill_w - drawn)
            seg_ratio = (drawn + sw/2) / (w - 8)
            seg_rpm = seg_ratio * e['max_rpm']
            color = rpm_color(seg_rpm)
            
            pygame.draw.rect(surface, color, (sx + drawn, y + 4, sw, h - 8))
            drawn += seg_w + seg_gap
    
    # RPM markers
    markers = [3000, 6000, 9000, 12000]
    for m in markers:
        mx = x + 4 + int((w - 8) * (m / e['max_rpm']))
        pygame.draw.line(surface, (60, 60, 70), (mx, y + 2), (mx, y + h - 2), 1)


def draw_vertical_bar(surface, x, y, w, h, value, max_val, color, label, fonts):
    """Draw a vertical bar gauge with label"""
    c = CONFIG['colors']
    
    # Background
    draw_rounded_rect(surface, (x, y, w, h), c['bar_bg'], radius=4)
    
    # Fill
    ratio = min(value / max_val, 1.0)
    fill_h = int((h - 4) * ratio)
    if fill_h > 0:
        pygame.draw.rect(surface, color, (x + 2, y + h - 2 - fill_h, w - 4, fill_h))
    
    # Label above
    draw_text(surface, fonts, label, x + w // 2, y - 16, size=12, 
              color=c['text_dim'], anchor='midtop')


def draw_gear_indicator(surface, fonts, x, y, gear):
    """Draw large gear number"""
    c = CONFIG['colors']
    draw_text(surface, fonts, str(gear), x, y, size=160, 
              color=c['gear_yellow'], bold=True, anchor='center')


def draw_warning_panel(surface, fonts, x, y, w, h, data):
    """Draw warning indicators if thresholds exceeded"""
    c = CONFIG['colors']
    warnings = CONFIG['warnings']
    
    active_warnings = []
    if data['coolant_temp'] >= warnings['coolant_critical']:
        active_warnings.append(('CLT CRITICAL', c['warning_red']))
    elif data['coolant_temp'] >= warnings['coolant_high']:
        active_warnings.append(('CLT HIGH', c['rpm_yellow']))
    
    if data['oil_pressure'] <= warnings['oil_critical']:
        active_warnings.append(('OIL CRITICAL', c['warning_red']))
    elif data['oil_pressure'] <= warnings['oil_low']:
        active_warnings.append(('OIL LOW', c['rpm_yellow']))
    
    for i, (text, color) in enumerate(active_warnings):
        wy = y + i * 28
        draw_rounded_rect(surface, (x, wy, w, 24), (color[0]//4, color[1]//4, color[2]//4), radius=4)
        draw_text(surface, fonts, text, x + w//2, wy + 12, size=14, color=color, bold=True, anchor='center')


# ============================================================
# SCREEN CLASSES
# ============================================================

class LapTimerScreen:
    """Primary endurance/lap timer screen"""
    
    def __init__(self):
        self.current_lap_start = time.time()
        self.best_lap = 65.432
        self.last_lap = 67.891
        self.flash_counter = 0
    
    def format_time(self, seconds):
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}:{secs:06.3f}"
    
    def calculate_gear(self, speed):
        if speed < 15: return 1
        elif speed < 30: return 2
        elif speed < 50: return 3
        elif speed < 70: return 4
        elif speed < 90: return 5
        else: return 6
    
    def draw(self, surface, data, fonts):
        c = CONFIG['colors']
        W, H = surface.get_size()
        
        self.flash_counter += 1
        flash_state = (self.flash_counter // 4) % 2 == 0
        
        rpm = data['rpm']
        speed = data['speed']
        throttle = data['throttle']
        brake = data['brake']
        temp = data['coolant_temp']
        gear = self.calculate_gear(speed)
        
        # Background
        surface.fill(c['bg'])
        
        # ── Shift Lights (top bar) ──
        draw_shift_lights(surface, 8, 6, W - 16, 36, rpm, flash_state)
        
        # ── RPM Bar ──
        bar_y = 50
        bar_h = 60
        draw_rpm_bar(surface, 12, bar_y, int(W * 0.72), bar_h, rpm)
        
        # RPM number below bar
        rpm_col = rpm_color(rpm)
        draw_text(surface, fonts, f"{rpm}", 20, bar_y + bar_h + 12, 
                  size=38, color=rpm_col, bold=True)
        draw_text(surface, fonts, "RPM", 20, bar_y + bar_h + 52, 
                  size=14, color=c['text_dim'])
        
        # ── CLT (bottom left) ──
        draw_text(surface, fonts, "CLT", 24, H - 80, size=14, color=c['text_label'])
        clt_color = c['clt_blue']
        if temp >= CONFIG['warnings']['coolant_high']:
            clt_color = c['warning_red'] if flash_state else c['rpm_yellow']
        draw_text(surface, fonts, f"{temp}°F", 24, H - 62, size=32, color=clt_color, bold=True)
        
        # ── Oil Pressure (next to CLT) ──
        draw_text(surface, fonts, "OIL", 160, H - 80, size=14, color=c['text_label'])
        oil_color = c['text']
        if data['oil_pressure'] <= CONFIG['warnings']['oil_low']:
            oil_color = c['warning_red'] if flash_state else c['rpm_yellow']
        draw_text(surface, fonts, f"{data['oil_pressure']} psi", 160, H - 62, 
                  size=32, color=oil_color, bold=True)
        
        # ── Center: Lap Times ──
        cx = int(W * 0.46)
        
        # Divider line
        pygame.draw.line(surface, c['panel_border'], (cx - 120, 180), (cx + 120, 180), 1)
        
        draw_text(surface, fonts, "CURRENT", cx, 190, size=14, 
                  color=c['text_label'], anchor='midtop')
        
        elapsed = time.time() - self.current_lap_start
        draw_text(surface, fonts, self.format_time(elapsed), cx, 220, 
                  size=48, color=c['text'], bold=True, anchor='midtop')
        
        # Simulate lap completion
        if elapsed > 70:
            self.last_lap = elapsed
            if elapsed < self.best_lap:
                self.best_lap = elapsed
            self.current_lap_start = time.time()
        
        # Delta line
        pygame.draw.line(surface, c['panel_border'], (cx - 120, 290), (cx + 120, 290), 1)
        
        # Best / Last
        draw_text(surface, fonts, "BEST", cx - 100, 310, size=13, color=c['text_label'])
        draw_text(surface, fonts, self.format_time(self.best_lap), cx - 100, 328, 
                  size=22, color=c['best_green'], bold=True)
        
        draw_text(surface, fonts, "LAST", cx + 20, 310, size=13, color=c['text_label'])
        draw_text(surface, fonts, self.format_time(self.last_lap), cx + 20, 328, 
                  size=22, color=c['text'])
        
        # ── Speed (bottom right area) ──
        sx = int(W * 0.76)
        draw_text(surface, fonts, f"{speed}", sx, H - 90, size=72, 
                  color=c['speed_white'], bold=True, anchor='midtop')
        draw_text(surface, fonts, "MPH", sx, H - 18, size=16, 
                  color=c['text_dim'], anchor='midtop')
        
        # ── Gear (right side, large) ──
        gx = int(W * 0.88)
        draw_gear_indicator(surface, fonts, gx, 180, gear)
        
        # ── Throttle / Brake bars (far right) ──
        bar_x_t = W - 50
        bar_x_b = W - 24
        bar_top = 60
        bar_bot = 280
        bar_h_tb = bar_bot - bar_top
        
        draw_vertical_bar(surface, bar_x_t, bar_top, 18, bar_h_tb, 
                         throttle, 100, c['throttle_green'], "T", fonts)
        draw_vertical_bar(surface, bar_x_b, bar_top, 18, bar_h_tb, 
                         brake, 100, c['brake_red'], "B", fonts)
        
        # ── Warning panel ──
        draw_warning_panel(surface, fonts, int(W * 0.30), H - 40, 200, 36, data)
        
        # ── Page indicator dots ──
        draw_page_dots(surface, W // 2, H - 10, 3, 0)


class MainDashScreen:
    """Traditional gauge-focused dashboard"""
    
    def __init__(self):
        self.flash_counter = 0
    
    def calculate_gear(self, speed):
        if speed < 15: return 1
        elif speed < 30: return 2
        elif speed < 50: return 3
        elif speed < 70: return 4
        elif speed < 90: return 5
        else: return 6
    
    def draw_arc_gauge(self, surface, cx, cy, radius, rpm, line_width=24):
        """Draw a circular arc RPM gauge"""
        e = CONFIG['engine']
        c = CONFIG['colors']
        
        # Background arc
        start_angle = math.radians(135)
        end_angle = math.radians(-135)
        
        # Draw background arc segments
        steps = 80
        for i in range(steps):
            t = i / steps
            angle = start_angle + t * (end_angle - start_angle)
            x1 = cx + int(math.cos(angle) * (radius - line_width))
            y1 = cy - int(math.sin(angle) * (radius - line_width))
            x2 = cx + int(math.cos(angle) * radius)
            y2 = cy - int(math.sin(angle) * radius)
            pygame.draw.line(surface, c['bar_bg'], (x1, y1), (x2, y2), 3)
        
        # Filled arc
        ratio = min(rpm / e['max_rpm'], 1.0)
        filled_steps = int(steps * ratio)
        
        for i in range(filled_steps):
            t = i / steps
            angle = start_angle + t * (end_angle - start_angle)
            seg_rpm = t * e['max_rpm']
            color = rpm_color(seg_rpm)
            
            x1 = cx + int(math.cos(angle) * (radius - line_width))
            y1 = cy - int(math.sin(angle) * (radius - line_width))
            x2 = cx + int(math.cos(angle) * radius)
            y2 = cy - int(math.sin(angle) * radius)
            pygame.draw.line(surface, color, (x1, y1), (x2, y2), 4)
    
    def draw(self, surface, data, fonts):
        c = CONFIG['colors']
        W, H = surface.get_size()
        
        self.flash_counter += 1
        flash_state = (self.flash_counter // 4) % 2 == 0
        
        rpm = data['rpm']
        speed = data['speed']
        throttle = data['throttle']
        brake = data['brake']
        temp = data['coolant_temp']
        gear = self.calculate_gear(speed)
        
        # Background
        surface.fill(c['bg'])
        
        # ── Shift Lights ──
        draw_shift_lights(surface, 8, 6, W - 16, 32, rpm, flash_state)
        
        # ── Circular RPM gauge (center) ──
        gauge_cx = W // 2
        gauge_cy = H // 2 + 10
        gauge_r = 180
        
        # Flash background on shift
        if rpm >= CONFIG['engine']['critical_rpm'] and flash_state:
            pygame.draw.circle(surface, (60, 0, 0), (gauge_cx, gauge_cy), gauge_r + 10)
        
        self.draw_arc_gauge(surface, gauge_cx, gauge_cy, gauge_r, rpm)
        
        # Gear in center of gauge
        draw_gear_indicator(surface, fonts, gauge_cx, gauge_cy - 10, gear)
        
        # RPM below gear
        draw_text(surface, fonts, f"{rpm}", gauge_cx, gauge_cy + 70, 
                  size=32, color=rpm_color(rpm), bold=True, anchor='center')
        draw_text(surface, fonts, "RPM", gauge_cx, gauge_cy + 100, 
                  size=14, color=c['text_dim'], anchor='center')
        
        # ── Speed (right) ──
        draw_text(surface, fonts, f"{speed}", W - 80, H // 2, 
                  size=56, color=c['speed_white'], bold=True, anchor='center')
        draw_text(surface, fonts, "MPH", W - 80, H // 2 + 36, 
                  size=16, color=c['text_dim'], anchor='center')
        
        # ── CLT (bottom left) ──
        draw_text(surface, fonts, "CLT", 30, H - 70, size=13, color=c['text_label'])
        clt_color = c['clt_blue']
        if temp >= CONFIG['warnings']['coolant_high']:
            clt_color = c['warning_red'] if flash_state else c['rpm_yellow']
        draw_text(surface, fonts, f"{temp}°F", 30, H - 54, 
                  size=28, color=clt_color, bold=True)
        
        # ── Oil (bottom left, next to CLT) ──
        draw_text(surface, fonts, "OIL", 140, H - 70, size=13, color=c['text_label'])
        draw_text(surface, fonts, f"{data['oil_pressure']} psi", 140, H - 54, 
                  size=28, color=c['text'], bold=True)
        
        # ── Throttle / Brake ──
        draw_vertical_bar(surface, 30, 80, 22, 260, throttle, 100, 
                         c['throttle_green'], "T", fonts)
        draw_vertical_bar(surface, 60, 80, 22, 260, brake, 100, 
                         c['brake_red'], "B", fonts)
        
        # ── Warnings ──
        draw_warning_panel(surface, fonts, W // 2 - 100, H - 35, 200, 30, data)
        
        # ── Page dots ──
        draw_page_dots(surface, W // 2, H - 10, 3, 1)


class DiagnosticScreen:
    """Debug / sensor readout screen"""
    
    def draw(self, surface, data, fonts):
        c = CONFIG['colors']
        W, H = surface.get_size()
        
        surface.fill(c['bg'])
        
        # Title
        draw_text(surface, fonts, "DIAGNOSTICS", W // 2, 20, 
                  size=20, color=c['text_dim'], bold=True, anchor='midtop')
        
        # Separator
        pygame.draw.line(surface, c['panel_border'], (40, 50), (W - 40, 50), 1)
        
        # Signal readouts in a clean grid
        signals = [
            ("RPM",          f"{data['rpm']}",            rpm_color(data['rpm'])),
            ("SPEED",        f"{data['speed']} mph",      c['speed_white']),
            ("THROTTLE",     f"{data['throttle']}%",      c['throttle_green']),
            ("BRAKE",        f"{data['brake']}%",         c['brake_red']),
            ("COOLANT",      f"{data['coolant_temp']}°F", c['clt_blue']),
            ("OIL PRESS",    f"{data['oil_pressure']} psi", c['text']),
        ]
        
        col_w = W // 3
        row_h = 65
        
        for i, (label, value, color) in enumerate(signals):
            col = i % 3
            row = i // 3
            
            x = 40 + col * col_w
            y = 70 + row * (row_h + 20)
            
            # Panel background
            draw_rounded_rect(surface, (x, y, col_w - 20, row_h), c['panel'], radius=6)
            pygame.draw.rect(surface, c['panel_border'], (x, y, col_w - 20, row_h), 1, border_radius=6)
            
            draw_text(surface, fonts, label, x + 12, y + 8, 
                      size=12, color=c['text_label'])
            draw_text(surface, fonts, value, x + 12, y + 28, 
                      size=28, color=color, bold=True)
        
        # System info
        y_info = 260
        pygame.draw.line(surface, c['panel_border'], (40, y_info), (W - 40, y_info), 1)
        
        draw_text(surface, fonts, "SYSTEM", 40, y_info + 10, 
                  size=12, color=c['text_label'])
        
        ts = data.get('timestamp', 0)
        if ts > 0:
            age_ms = int((time.time() - ts) * 1000)
            draw_text(surface, fonts, f"Data age: {age_ms}ms", 40, y_info + 30, 
                      size=16, color=c['text'])
        
        draw_text(surface, fonts, f"Target: {CONFIG['screen']['fps']} FPS", 40, y_info + 55, 
                  size=16, color=c['text'])
        
        # Page dots
        draw_page_dots(surface, W // 2, H - 10, 3, 2)


def draw_page_dots(surface, cx, cy, total, active):
    """Draw page indicator dots"""
    c = CONFIG['colors']
    dot_r = 4
    spacing = 16
    start_x = cx - (total - 1) * spacing // 2
    
    for i in range(total):
        x = start_x + i * spacing
        color = c['text'] if i == active else c['shift_off']
        pygame.draw.circle(surface, color, (x, cy), dot_r)


# ============================================================
# MAIN APPLICATION
# ============================================================

class RaceDashApp:
    def __init__(self):
        pygame.init()
        
        sc = CONFIG['screen']
        
        # Display setup - works on both PC and Pi framebuffer
        flags = 0
        if sc['fullscreen']:
            flags = pygame.FULLSCREEN
            # On Pi, try framebuffer
            if os.environ.get('DISPLAY') is None:
                os.environ['SDL_VIDEODRIVER'] = 'kmsdrm'
        
        self.screen = pygame.display.set_mode((sc['width'], sc['height']), flags)
        pygame.display.set_caption(sc['title'])
        pygame.mouse.set_visible(not sc['fullscreen'])
        
        self.clock = pygame.time.Clock()
        self.fonts = FontManager()
        self.running = True
        
        # Data acquisition
        self.buffer = SignalBuffer()
        self.can_thread = CANThread(self.buffer, simulate=True)
        self.sensor_thread = SensorThread(self.buffer, simulate=True)
        self.can_thread.start()
        self.sensor_thread.start()
        
        # Screens
        self.screens = [
            LapTimerScreen(),
            MainDashScreen(),
            DiagnosticScreen(),
        ]
        self.current_screen = 0
        
        # Touch / swipe tracking
        self.touch_start_x = None
        self.swipe_threshold = 80
    
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_RIGHT or event.key == pygame.K_SPACE:
                    self.current_screen = (self.current_screen + 1) % len(self.screens)
                elif event.key == pygame.K_LEFT:
                    self.current_screen = (self.current_screen - 1) % len(self.screens)
            
            elif event.type == pygame.MOUSEBUTTONDOWN:
                self.touch_start_x = event.pos[0]
            
            elif event.type == pygame.MOUSEBUTTONUP:
                if self.touch_start_x is not None:
                    dx = event.pos[0] - self.touch_start_x
                    if abs(dx) > self.swipe_threshold:
                        if dx < 0:
                            self.current_screen = (self.current_screen + 1) % len(self.screens)
                        else:
                            self.current_screen = (self.current_screen - 1) % len(self.screens)
                    self.touch_start_x = None
    
    def run(self):
        while self.running:
            self.handle_events()
            
            data = self.buffer.get_all()
            self.screens[self.current_screen].draw(self.screen, data, self.fonts)
            
            pygame.display.flip()
            self.clock.tick(CONFIG['screen']['fps'])
        
        self.shutdown()
    
    def shutdown(self):
        print("Shutting down...")
        self.can_thread.stop()
        self.sensor_thread.stop()
        self.can_thread.join(timeout=0.5)
        self.sensor_thread.join(timeout=0.5)
        pygame.quit()
        print("Shutdown complete")


if __name__ == '__main__':
    app = RaceDashApp()
    app.run()