"""
Race Dash - PyGame GUI
Config-driven racing dashboard for Pi Zero 2W

SCREENS:
  Drivers can enable/disable screens from the Settings > Screens tab.
  To add a new screen: create a class with NAME and draw(), then add it
  to SCREEN_REGISTRY at the bottom of this section.
"""

import pygame
import pygame.gfxdraw
import sys
import os
import time
import math
from collections import deque

# Import our modules
from race_dash_core import SignalBuffer, CANThread
from race_dash_config import (config, SETTINGS_PAGES, SETTING_CHOICES,
    convert_speed, convert_temp, convert_pressure,
    speed_label, temp_label, pressure_label)
from race_dash_updater import Updater


# ============================================================
# FONT MANAGER
# ============================================================

class FontManager:
    def __init__(self):
        pygame.font.init()
        self._cache = {}
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
                self._cache[key] = pygame.font.SysFont(
                    'consolas,dejavusansmono,liberationmono,mono', size, bold=bold)
        return self._cache[key]


# ============================================================
# DRAWING HELPERS
# ============================================================

def draw_rounded_rect(surface, rect, color, radius=8):
    x, y, w, h = rect
    r = min(radius, h // 2, w // 2)
    pygame.draw.rect(surface, color, (x + r, y, w - 2*r, h))
    pygame.draw.rect(surface, color, (x, y + r, w, h - 2*r))
    pygame.draw.circle(surface, color, (x + r, y + r), r)
    pygame.draw.circle(surface, color, (x + w - r, y + r), r)
    pygame.draw.circle(surface, color, (x + r, y + h - r), r)
    pygame.draw.circle(surface, color, (x + w - r, y + h - r), r)


def draw_text(surface, fonts, text, x, y, size=24, color=None, bold=False, anchor='topleft'):
    if color is None:
        color = config.color('text')
    font = fonts.get(size, bold)
    rendered = font.render(str(text), True, color)
    rect = rendered.get_rect()
    setattr(rect, anchor, (x, y))
    surface.blit(rendered, rect)
    return rect


def rpm_color(rpm):
    c = config.data['colors']
    e = config['engine']
    if rpm < 9000:
        return tuple(c['rpm_green'])
    elif rpm < 11000:
        t = (rpm - 9000) / 2000.0
        return lerp_color(tuple(c['rpm_green']), tuple(c['rpm_yellow']), t)
    elif rpm < e['redline_rpm']:
        t = (rpm - 11000) / 1500.0
        return lerp_color(tuple(c['rpm_yellow']), tuple(c['rpm_red']), t)
    else:
        return tuple(c['rpm_red'])


def lerp_color(c1, c2, t):
    t = max(0, min(1, t))
    return (
        int(c1[0] + (c2[0] - c1[0]) * t),
        int(c1[1] + (c2[1] - c1[1]) * t),
        int(c1[2] + (c2[2] - c1[2]) * t),
    )


def get_gear(data):
    """Get gear from STM32 data. Returns int 0-6 (0 = neutral/unknown)."""
    return data.get('gear', 0)


def get_gear_display(data):
    """Get gear display string. 'N' if clutch in or gear=0, else '1'-'6'."""
    clutch = data.get('clutch', 0)
    gear = data.get('gear', 0)
    if clutch or gear == 0:
        return 'N'
    return str(gear)


# ============================================================
# SHARED WIDGETS
# ============================================================

def draw_shift_lights(surface, x, y, w, h, rpm, flash_state):
    e = config['engine']
    num_lights = 10
    if rpm < e['shift_rpm']:
        lights_on = 0; flash_all = False
    elif rpm >= e['critical_rpm']:
        lights_on = num_lights; flash_all = True
    else:
        ratio = (rpm - e['shift_rpm']) / (e['critical_rpm'] - e['shift_rpm'])
        lights_on = int(ratio * num_lights); flash_all = False

    light_order = [4, 5, 3, 6, 2, 7, 1, 8, 0, 9]
    gap = 3
    light_w = (w - (num_lights + 1) * gap) / num_lights
    light_h = h - 4; ly = y + 2
    for i in range(num_lights):
        lx = x + gap + i * (light_w + gap)
        pos = light_order.index(i)
        is_on = pos < lights_on
        if flash_all and flash_state:
            color = config.color('rpm_red')
        elif is_on:
            color = (config.color('rpm_green') if pos < 4 else
                     config.color('rpm_yellow') if pos < 7 else
                     config.color('rpm_red'))
        else:
            color = config.color('shift_off')
        draw_rounded_rect(surface, (int(lx), int(ly), int(light_w), int(light_h)), color, radius=6)


def draw_rpm_bar(surface, x, y, w, h, rpm):
    e = config['engine']
    draw_rounded_rect(surface, (x, y, w, h), config.color('bar_bg'), radius=6)
    ratio = min(rpm / e['max_rpm'], 1.0)
    fill_w = int((w - 8) * ratio)
    if fill_w > 0:
        seg_w, seg_gap = 6, 2; drawn = 0
        while drawn < fill_w:
            sw = min(seg_w, fill_w - drawn)
            seg_ratio = (drawn + sw/2) / (w - 8)
            color = rpm_color(seg_ratio * e['max_rpm'])
            pygame.draw.rect(surface, color, (x + 4 + drawn, y + 4, sw, h - 8))
            drawn += seg_w + seg_gap
    for m in [3000, 6000, 9000, 12000]:
        mx = x + 4 + int((w - 8) * (m / e['max_rpm']))
        pygame.draw.line(surface, (60, 60, 70), (mx, y + 2), (mx, y + h - 2), 1)


def draw_vertical_bar(surface, x, y, w, h, value, max_val, color, label, fonts):
    draw_rounded_rect(surface, (x, y, w, h), config.color('bar_bg'), radius=4)
    ratio = min(value / max_val, 1.0)
    fill_h = int((h - 4) * ratio)
    if fill_h > 0:
        pygame.draw.rect(surface, color, (x + 2, y + h - 2 - fill_h, w - 4, fill_h))
    draw_text(surface, fonts, label, x + w // 2, y - 16, size=12,
              color=config.color('text_dim'), anchor='midtop')


def draw_gear_indicator(surface, fonts, x, y, gear):
    draw_text(surface, fonts, str(gear), x, y, size=160,
              color=config.color('gear_yellow'), bold=True, anchor='center')


def draw_warning_panel(surface, fonts, x, y, w, h, data):
    warnings = config['warnings']
    active = []
    if data['coolant_temp'] >= warnings['coolant_critical']:
        active.append(('CLT CRITICAL', config.color('warning_red')))
    elif data['coolant_temp'] >= warnings['coolant_high']:
        active.append(('CLT HIGH', config.color('rpm_yellow')))
    if data['oil_pressure'] <= warnings['oil_critical']:
        active.append(('OIL CRITICAL', config.color('warning_red')))
    elif data['oil_pressure'] <= warnings['oil_low']:
        active.append(('OIL LOW', config.color('rpm_yellow')))
    for i, (text, color) in enumerate(active):
        wy = y + i * 28
        draw_rounded_rect(surface, (x, wy, w, 24),
                         (color[0]//4, color[1]//4, color[2]//4), radius=4)
        draw_text(surface, fonts, text, x + w//2, wy + 12,
                  size=14, color=color, bold=True, anchor='center')


def draw_page_dots(surface, cx, cy, total, active):
    if total <= 1:
        return
    spacing = min(16, (surface.get_width() - 40) // max(total, 1))
    start_x = cx - (total - 1) * spacing // 2
    for i in range(total):
        x = start_x + i * spacing
        color = config.color('text') if i == active else config.color('shift_off')
        pygame.draw.circle(surface, color, (x, cy), 4)


def draw_clt(surface, fonts, x, y, data, flash_state, size=32):
    """Reusable CLT display"""
    draw_text(surface, fonts, "CLT", x, y, size=14, color=config.color('text_label'))
    temp = data['coolant_temp']
    clt_color = config.color('clt_blue')
    if temp >= config['warnings']['coolant_high']:
        clt_color = config.color('warning_red') if flash_state else config.color('rpm_yellow')
    draw_text(surface, fonts, f"{convert_temp(temp)}{temp_label()}", x, y + 18,
              size=size, color=clt_color, bold=True)


def draw_oil(surface, fonts, x, y, data, flash_state, size=32):
    """Reusable oil pressure display"""
    draw_text(surface, fonts, "OIL", x, y, size=14, color=config.color('text_label'))
    oil_color = config.color('text')
    if data['oil_pressure'] <= config['warnings']['oil_low']:
        oil_color = config.color('warning_red') if flash_state else config.color('rpm_yellow')
    draw_text(surface, fonts, f"{convert_pressure(data['oil_pressure'])} {pressure_label()}",
              x, y + 18, size=size, color=oil_color, bold=True)


# ============================================================
# SCREEN 1: LAP TIMER (endurance primary)
# Layout: thick shift lights top, GIANT gear center,
#         lap times left, speed right, RPM/temps bottom
# ============================================================

class LapTimerScreen:
    NAME = "Lap Timer"
    DESC = "Giant gear + shift lights + lap times"

    def __init__(self):
        self.current_lap_start = time.time()
        self.best_lap = 65.432
        self.last_lap = 67.891
        self.flash_counter = 0

    def format_time(self, seconds):
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}:{secs:06.3f}"

    def draw(self, surface, data, fonts, page_idx=0, page_total=1):
        W, H = surface.get_size()
        self.flash_counter += 1
        flash_state = (self.flash_counter // 4) % 2 == 0
        rpm, speed = data['rpm'], data['speed']
        gear = get_gear_display(data)

        surface.fill(config.color('bg'))

        # ── SHIFT LIGHTS - big and bold across the top ──
        draw_shift_lights(surface, 6, 4, W - 12, 54, rpm, flash_state)

        # ── GIANT GEAR - dead center, dominates the screen ──
        gear_cx = W // 2
        gear_cy = H // 2 - 10
        draw_text(surface, fonts, str(gear), gear_cx, gear_cy,
                  size=240, color=config.color('gear_yellow'), bold=True, anchor='center')

        # ── RPM bar underneath gear ──
        bar_y = gear_cy + 120
        draw_rpm_bar(surface, 100, bar_y, W - 200, 30, rpm)
        draw_text(surface, fonts, f"{rpm}", W // 2, bar_y + 36,
                  size=20, color=rpm_color(rpm), bold=True, anchor='midtop')

        # ── Lap times - left side ──
        lx = 16
        draw_text(surface, fonts, "CURRENT", lx, 70, size=12,
                  color=config.color('text_label'))
        elapsed = time.time() - self.current_lap_start
        draw_text(surface, fonts, self.format_time(elapsed), lx, 82,
                  size=32, color=config.color('text'), bold=True)

        if elapsed > 70:
            self.last_lap = elapsed
            if elapsed < self.best_lap:
                self.best_lap = elapsed
            self.current_lap_start = time.time()

        draw_text(surface, fonts, "BEST", lx, 125, size=12,
                  color=config.color('text_label'))
        draw_text(surface, fonts, self.format_time(self.best_lap), lx, 140,
                  size=22, color=config.color('best_green'), bold=True)
        draw_text(surface, fonts, "LAST", lx, 172, size=12,
                  color=config.color('text_label'))
        draw_text(surface, fonts, self.format_time(self.last_lap), lx, 187,
                  size=22, color=config.color('text'))

        # ── Speed - right side ──
        sx = W - 20
        draw_text(surface, fonts, f"{convert_speed(speed)}", sx, 80,
                  size=64, color=config.color('speed_white'), bold=True, anchor='topright')
        draw_text(surface, fonts, speed_label(), sx, 145,
                  size=16, color=config.color('text_dim'), anchor='topright')

        # ── Throttle / Brake bars - far right edge ──
        draw_vertical_bar(surface, W - 42, 170, 16, 200,
                         data['throttle'], 100, config.color('throttle_green'), "T", fonts)
        draw_vertical_bar(surface, W - 20, 170, 16, 200,
                         data['brake'], 100, config.color('brake_red'), "B", fonts)

        # ── Bottom strip: CLT + Oil ──
        draw_clt(surface, fonts, 16, H - 60, data, flash_state, size=26)
        draw_oil(surface, fonts, 180, H - 60, data, flash_state, size=26)

        draw_warning_panel(surface, fonts, W // 2 - 100, H - 40, 200, 36, data)
        draw_page_dots(surface, W // 2, H - 10, page_total, page_idx)


# ============================================================
# SCREEN 2: MAIN DASH (circular gauge)
# Layout: thick shift lights, giant gear inside RPM arc,
#         speed + temps at edges
# ============================================================

class MainDashScreen:
    NAME = "Main Gauge"
    DESC = "Giant gear inside RPM arc gauge"

    def __init__(self):
        self.flash_counter = 0

    def draw_arc_gauge(self, surface, cx, cy, radius, rpm, line_width=28):
        e = config['engine']
        start_angle = math.radians(135)
        end_angle = math.radians(-135)
        steps = 80
        for i in range(steps):
            t = i / steps
            angle = start_angle + t * (end_angle - start_angle)
            x1 = cx + int(math.cos(angle) * (radius - line_width))
            y1 = cy - int(math.sin(angle) * (radius - line_width))
            x2 = cx + int(math.cos(angle) * radius)
            y2 = cy - int(math.sin(angle) * radius)
            pygame.draw.line(surface, config.color('bar_bg'), (x1, y1), (x2, y2), 3)
        ratio = min(rpm / e['max_rpm'], 1.0)
        for i in range(int(steps * ratio)):
            t = i / steps
            angle = start_angle + t * (end_angle - start_angle)
            color = rpm_color(t * e['max_rpm'])
            x1 = cx + int(math.cos(angle) * (radius - line_width))
            y1 = cy - int(math.sin(angle) * (radius - line_width))
            x2 = cx + int(math.cos(angle) * radius)
            y2 = cy - int(math.sin(angle) * radius)
            pygame.draw.line(surface, color, (x1, y1), (x2, y2), 5)

    def draw(self, surface, data, fonts, page_idx=0, page_total=1):
        W, H = surface.get_size()
        self.flash_counter += 1
        flash_state = (self.flash_counter // 4) % 2 == 0
        rpm, speed = data['rpm'], data['speed']
        gear = get_gear_display(data)

        surface.fill(config.color('bg'))

        # ── SHIFT LIGHTS - thick strip ──
        draw_shift_lights(surface, 6, 4, W - 12, 54, rpm, flash_state)

        # ── RPM arc gauge ──
        gcx, gcy, gr = W // 2, H // 2 + 15, 190
        if rpm >= config['engine']['critical_rpm'] and flash_state:
            pygame.draw.circle(surface, (60, 0, 0), (gcx, gcy), gr + 10)
        self.draw_arc_gauge(surface, gcx, gcy, gr, rpm, line_width=28)

        # ── GIANT GEAR inside the arc ──
        draw_text(surface, fonts, str(gear), gcx, gcy - 15,
                  size=220, color=config.color('gear_yellow'), bold=True, anchor='center')

        # ── RPM number below gear ──
        draw_text(surface, fonts, f"{rpm}", gcx, gcy + 85,
                  size=28, color=rpm_color(rpm), bold=True, anchor='center')

        # ── Speed - right side ──
        draw_text(surface, fonts, f"{convert_speed(speed)}", W - 30, H // 2 - 10,
                  size=52, color=config.color('speed_white'), bold=True, anchor='midright')
        draw_text(surface, fonts, speed_label(), W - 30, H // 2 + 30,
                  size=14, color=config.color('text_dim'), anchor='midright')

        # ── Throttle / Brake - left edge ──
        draw_vertical_bar(surface, 16, 90, 20, 250, data['throttle'], 100,
                         config.color('throttle_green'), "T", fonts)
        draw_vertical_bar(surface, 44, 90, 20, 250, data['brake'], 100,
                         config.color('brake_red'), "B", fonts)

        # ── Bottom: CLT + Oil ──
        draw_clt(surface, fonts, 16, H - 58, data, flash_state, size=24)
        draw_oil(surface, fonts, 170, H - 58, data, flash_state, size=24)

        draw_warning_panel(surface, fonts, W // 2 - 100, H - 35, 200, 30, data)
        draw_page_dots(surface, W // 2, H - 10, page_total, page_idx)


# ============================================================
# SCREEN 3: DRAG / ACCELERATION
# ============================================================

class DragScreen:
    NAME = "Drag"
    DESC = "Giant gear + speed, zero clutter"

    def __init__(self):
        self.flash_counter = 0

    def draw(self, surface, data, fonts, page_idx=0, page_total=1):
        W, H = surface.get_size()
        self.flash_counter += 1
        flash_state = (self.flash_counter // 4) % 2 == 0
        rpm, speed = data['rpm'], data['speed']
        gear = get_gear_display(data)

        surface.fill(config.color('bg'))

        # ── Thick shift lights ──
        draw_shift_lights(surface, 6, 4, W - 12, 52, rpm, flash_state)

        # ── MASSIVE gear - left of center ──
        draw_text(surface, fonts, str(gear), W // 3, H // 2,
                  size=240, color=config.color('gear_yellow'), bold=True, anchor='center')

        # ── Big speed - right side ──
        draw_text(surface, fonts, f"{convert_speed(speed)}", W * 3 // 4, H // 2 - 20,
                  size=100, color=config.color('speed_white'), bold=True, anchor='center')
        draw_text(surface, fonts, speed_label(), W * 3 // 4, H // 2 + 40,
                  size=20, color=config.color('text_dim'), anchor='center')

        # ── RPM bar at the bottom ──
        draw_rpm_bar(surface, 12, H - 60, W - 24, 32, rpm)
        draw_text(surface, fonts, f"{rpm}", W // 2, H - 22,
                  size=14, color=config.color('text_dim'), anchor='midtop')

        draw_page_dots(surface, W // 2, H - 10, page_total, page_idx)


# ============================================================
# SCREEN 4: DRIVER STRIP (everything at a glance, horizontal)
# ============================================================

class DriverStripScreen:
    NAME = "Strip"
    DESC = "All key info in horizontal strips"

    def __init__(self):
        self.flash_counter = 0

    def draw(self, surface, data, fonts, page_idx=0, page_total=1):
        W, H = surface.get_size()
        self.flash_counter += 1
        flash_state = (self.flash_counter // 4) % 2 == 0
        rpm, speed = data['rpm'], data['speed']
        gear = get_gear_display(data)

        surface.fill(config.color('bg'))
        draw_shift_lights(surface, 8, 4, W - 16, 32, rpm, flash_state)

        # Row 1: RPM bar full width
        draw_rpm_bar(surface, 12, 44, W - 24, 50, rpm)

        # Row 2: Gear | Speed | RPM number
        row2_y = 108
        # Gear
        draw_text(surface, fonts, str(gear), 60, row2_y + 40,
                  size=80, color=config.color('gear_yellow'), bold=True, anchor='center')
        # Speed
        draw_text(surface, fonts, f"{convert_speed(speed)}", W // 2, row2_y + 10,
                  size=64, color=config.color('speed_white'), bold=True, anchor='midtop')
        draw_text(surface, fonts, speed_label(), W // 2, row2_y + 75,
                  size=14, color=config.color('text_dim'), anchor='midtop')
        # RPM
        draw_text(surface, fonts, f"{rpm}", W - 100, row2_y + 20,
                  size=42, color=rpm_color(rpm), bold=True, anchor='midtop')
        draw_text(surface, fonts, "RPM", W - 100, row2_y + 65,
                  size=14, color=config.color('text_dim'), anchor='midtop')

        # Row 3: Throttle bar | Brake bar (horizontal)
        row3_y = 210
        # Throttle
        draw_text(surface, fonts, f"THR {data['throttle']}%", 20, row3_y,
                  size=14, color=config.color('text_label'))
        bar_x, bar_w = 120, W - 160
        draw_rounded_rect(surface, (bar_x, row3_y, bar_w, 22), config.color('bar_bg'), radius=4)
        tw = int(bar_w * data['throttle'] / 100)
        if tw > 0:
            draw_rounded_rect(surface, (bar_x, row3_y, tw, 22),
                             config.color('throttle_green'), radius=4)
        # Brake
        row3b_y = row3_y + 32
        draw_text(surface, fonts, f"BRK {data['brake']}%", 20, row3b_y,
                  size=14, color=config.color('text_label'))
        draw_rounded_rect(surface, (bar_x, row3b_y, bar_w, 22), config.color('bar_bg'), radius=4)
        bw = int(bar_w * data['brake'] / 100)
        if bw > 0:
            draw_rounded_rect(surface, (bar_x, row3b_y, bw, 22),
                             config.color('brake_red'), radius=4)

        # Row 4: Temps
        row4_y = 290
        pygame.draw.line(surface, config.color('panel_border'), (20, row4_y), (W - 20, row4_y), 1)
        draw_clt(surface, fonts, 30, row4_y + 8, data, flash_state, size=36)
        draw_oil(surface, fonts, 260, row4_y + 8, data, flash_state, size=36)

        # GPS sats
        sats = data.get('gps_satellites', 0)
        sat_color = config.color('best_green') if sats >= 6 else config.color('rpm_yellow') if sats >= 3 else config.color('warning_red')
        draw_text(surface, fonts, f"GPS: {sats} sats", W - 140, row4_y + 12,
                  size=16, color=sat_color)

        draw_warning_panel(surface, fonts, W // 2 - 100, H - 40, 200, 30, data)
        draw_page_dots(surface, W // 2, H - 10, page_total, page_idx)


# ============================================================
# SCREEN 5: GPS / MAP INFO
# ============================================================

class GPSScreen:
    NAME = "GPS"
    DESC = "GPS coordinates, satellites, track map"

    def __init__(self):
        self.trail = deque(maxlen=2000)   # GPS position history (~80s at 25Hz)
        self.start_pos = None             # First valid GPS position (never overwritten)
        self.flash_counter = 0
        self.last_lat = 0.0
        self.last_lon = 0.0

    def update(self, data):
        """Record GPS trail. Called every frame regardless of active screen."""
        lat = data.get('lat', 0.0)
        lon = data.get('lon', 0.0)
        if lat != 0.0 and lon != 0.0:
            if self.start_pos is None:
                self.start_pos = (lat, lon)
            if lat != self.last_lat or lon != self.last_lon:
                self.trail.append((lat, lon))
                self.last_lat = lat
                self.last_lon = lon

    def draw(self, surface, data, fonts, page_idx=0, page_total=1):
        W, H = surface.get_size()
        self.flash_counter += 1
        flash_state = (self.flash_counter // 4) % 2 == 0

        surface.fill(config.color('bg'))
        draw_shift_lights(surface, 8, 4, W - 16, 28, data['rpm'], flash_state)

        lat = data.get('lat', 0.0)
        lon = data.get('lon', 0.0)

        # ── Left column: text info ──
        info_w = 240
        y = 42
        draw_text(surface, fonts, "LAT", 20, y, size=11, color=config.color('text_label'))
        draw_text(surface, fonts, f"{lat:.6f}", 20, y + 14, size=22,
                  color=config.color('text'), bold=True)
        y += 48
        draw_text(surface, fonts, "LON", 20, y, size=11, color=config.color('text_label'))
        draw_text(surface, fonts, f"{lon:.6f}", 20, y + 14, size=22,
                  color=config.color('text'), bold=True)

        y += 52
        sats = data.get('gps_satellites', 0)
        fix = sats >= 3
        sat_color = config.color('best_green') if sats >= 6 else (
            config.color('rpm_yellow') if fix else config.color('warning_red'))
        draw_text(surface, fonts, "SATS", 20, y, size=11, color=config.color('text_label'))
        draw_text(surface, fonts, str(sats), 20, y + 14, size=36,
                  color=sat_color, bold=True)
        draw_text(surface, fonts, "FIX" if fix else "NO FIX", 80, y + 20,
                  size=14, color=sat_color, bold=True)

        y += 60
        gps_spd = data.get('gps_speed', 0)
        draw_text(surface, fonts, "GPS SPD", 20, y, size=11, color=config.color('text_label'))
        draw_text(surface, fonts, f"{convert_speed(int(gps_spd))} {speed_label()}", 20, y + 14,
                  size=22, color=config.color('accent'), bold=True)

        y += 44
        draw_text(surface, fonts, "WHEEL SPD", 20, y, size=11, color=config.color('text_label'))
        draw_text(surface, fonts, f"{convert_speed(data['speed'])} {speed_label()}", 20, y + 14,
                  size=22, color=config.color('speed_white'), bold=True)

        y += 44
        gear = get_gear_display(data)
        draw_text(surface, fonts, "GEAR", 20, y, size=11, color=config.color('text_label'))
        draw_text(surface, fonts, gear, 20, y + 14, size=36,
                  color=config.color('gear_yellow'), bold=True)

        y += 52
        trail_len = len(self.trail)
        draw_text(surface, fonts, f"TRAIL: {trail_len} pts", 20, y,
                  size=11, color=config.color('text_dim'))

        # ── Right side: Mini Map ──
        map_x = info_w + 10
        map_y = 38
        map_w = W - map_x - 12
        map_h = H - map_y - 20

        # Map background
        draw_rounded_rect(surface, (map_x, map_y, map_w, map_h),
                         config.color('panel'), radius=8)
        pygame.draw.rect(surface, config.color('panel_border'),
                        (map_x, map_y, map_w, map_h), 1, border_radius=8)

        # Padding inside the map box
        pad = 20
        draw_x = map_x + pad
        draw_y = map_y + pad
        draw_w = map_w - pad * 2
        draw_h = map_h - pad * 2

        if len(self.trail) >= 2:
            trail_list = list(self.trail)

            # Include start position in bounds so it's always visible
            all_points = trail_list[:]
            if self.start_pos is not None:
                all_points.append(self.start_pos)

            # Find bounds
            lats = [p[0] for p in all_points]
            lons = [p[1] for p in all_points]
            min_lat, max_lat = min(lats), max(lats)
            min_lon, max_lon = min(lons), max(lons)

            # Add margin so the dot isn't right on the edge
            lat_range = max_lat - min_lat
            lon_range = max_lon - min_lon

            # Minimum range so early samples don't produce a giant dot
            if lat_range < 0.0001:
                lat_range = 0.0001
                mid = (max_lat + min_lat) / 2
                min_lat = mid - lat_range / 2
                max_lat = mid + lat_range / 2
            if lon_range < 0.0001:
                lon_range = 0.0001
                mid = (max_lon + min_lon) / 2
                min_lon = mid - lon_range / 2
                max_lon = mid + lon_range / 2

            # Margin (10% each side)
            margin = 0.1
            min_lat -= lat_range * margin
            max_lat += lat_range * margin
            min_lon -= lon_range * margin
            max_lon += lon_range * margin
            lat_range = max_lat - min_lat
            lon_range = max_lon - min_lon

            # Aspect ratio correction (latitude degrees are taller than longitude)
            # cos(lat) corrects for map projection
            mid_lat_rad = math.radians((min_lat + max_lat) / 2)
            lon_scale = math.cos(mid_lat_rad)

            # Scale to fit draw area while maintaining aspect ratio
            geo_w = lon_range * lon_scale
            geo_h = lat_range
            scale_x = draw_w / geo_w if geo_w > 0 else 1
            scale_y = draw_h / geo_h if geo_h > 0 else 1
            scale = min(scale_x, scale_y)

            # Center the track in the draw area
            rendered_w = geo_w * scale
            rendered_h = geo_h * scale
            offset_x = draw_x + (draw_w - rendered_w) / 2
            offset_y = draw_y + (draw_h - rendered_h) / 2

            def geo_to_px(la, lo):
                px = offset_x + (lo - min_lon) * lon_scale * scale
                py = offset_y + rendered_h - (la - min_lat) * scale  # Y flipped
                return int(px), int(py)

            # Draw trail with fading color
            for i in range(1, len(trail_list)):
                # Fade from dim to bright
                t = i / len(trail_list)
                r = int(20 + 40 * t)
                g = int(40 + 120 * t)
                b = int(80 + 175 * t)
                p1 = geo_to_px(trail_list[i-1][0], trail_list[i-1][1])
                p2 = geo_to_px(trail_list[i][0], trail_list[i][1])
                # Only draw if points are within the map area
                if (map_x <= p1[0] <= map_x + map_w and map_x <= p2[0] <= map_x + map_w and
                    map_y <= p1[1] <= map_y + map_h and map_y <= p2[1] <= map_y + map_h):
                    thickness = 1 if t < 0.5 else 2
                    pygame.draw.line(surface, (r, g, b), p1, p2, thickness)

            # Current position dot (glow effect)
            cx, cy = geo_to_px(lat, lon)
            if map_x <= cx <= map_x + map_w and map_y <= cy <= map_y + map_h:
                pygame.draw.circle(surface, (0, 60, 130), (cx, cy), 10)
                pygame.draw.circle(surface, (0, 150, 255), (cx, cy), 6)
                pygame.draw.circle(surface, (200, 230, 255), (cx, cy), 3)

            # Start position marker (small green dot, pinned to first GPS fix)
            if self.start_pos is not None:
                sx, sy = geo_to_px(self.start_pos[0], self.start_pos[1])
                if map_x <= sx <= map_x + map_w and map_y <= sy <= map_y + map_h:
                    pygame.draw.circle(surface, config.color('best_green'), (sx, sy), 4)

            # Compass: N arrow in top-right corner of map
            nx, ny = map_x + map_w - 18, map_y + 18
            draw_text(surface, fonts, "N", nx, ny, size=11,
                      color=config.color('text_dim'), bold=True, anchor='center')
            pygame.draw.line(surface, config.color('text_dim'),
                           (nx, ny + 7), (nx, ny + 16), 1)

        else:
            # No trail yet
            msg = "WAITING FOR GPS..." if lat == 0.0 else "BUILDING TRAIL..."
            draw_text(surface, fonts, msg,
                     map_x + map_w // 2, map_y + map_h // 2,
                     size=16, color=config.color('text_dim'), anchor='center')

        draw_page_dots(surface, W // 2, H - 10, page_total, page_idx)


# ============================================================
# SCREEN 6: DIAGNOSTICS
# ============================================================

class DiagnosticScreen:
    NAME = "Diagnostics"
    DESC = "All sensor values in a grid"

    def draw(self, surface, data, fonts, page_idx=0, page_total=1):
        W, H = surface.get_size()
        surface.fill(config.color('bg'))

        draw_text(surface, fonts, "DIAGNOSTICS", W // 2, 20,
                  size=20, color=config.color('text_dim'), bold=True, anchor='midtop')
        pygame.draw.line(surface, config.color('panel_border'), (40, 50), (W - 40, 50), 1)

        signals = [
            ("RPM",       f"{data['rpm']}",               rpm_color(data['rpm'])),
            ("SPEED",     f"{convert_speed(data['speed'])} {speed_label()}", config.color('speed_white')),
            ("THROTTLE",  f"{data['throttle']}%",          config.color('throttle_green')),
            ("BRAKE",     f"{data['brake']}%",             config.color('brake_red')),
            ("COOLANT",   f"{convert_temp(data['coolant_temp'])}{temp_label()}", config.color('clt_blue')),
            ("OIL PRESS", f"{convert_pressure(data['oil_pressure'])} {pressure_label()}", config.color('text')),
            ("GPS SATS",  f"{data.get('gps_satellites', 0)}", config.color('accent')),
            ("LAT",       f"{data.get('lat', 0):.4f}",    config.color('text')),
            ("LON",       f"{data.get('lon', 0):.4f}",    config.color('text')),
        ]

        col_w = W // 3
        for i, (label, value, color) in enumerate(signals):
            col, row = i % 3, i // 3
            x, y = 40 + col * col_w, 70 + row * 85
            draw_rounded_rect(surface, (x, y, col_w - 20, 65), config.color('panel'), radius=6)
            pygame.draw.rect(surface, config.color('panel_border'),
                           (x, y, col_w - 20, 65), 1, border_radius=6)
            draw_text(surface, fonts, label, x + 12, y + 8, size=12, color=config.color('text_label'))
            draw_text(surface, fonts, value, x + 12, y + 28, size=28, color=color, bold=True)

        y_info = 340
        pygame.draw.line(surface, config.color('panel_border'), (40, y_info), (W - 40, y_info), 1)
        draw_text(surface, fonts, f"Driver: {config.get('driver','name')}  |  "
                  f"Event: {config.get('driver','event')}",
                  40, y_info + 10, size=16, color=config.color('text'))

        ts = data.get('timestamp', 0)
        if ts > 0:
            age_ms = int((time.time() - ts) * 1000)
            draw_text(surface, fonts, f"Data age: {age_ms}ms", 40, y_info + 32,
                      size=14, color=config.color('text_dim'))

        draw_page_dots(surface, W // 2, H - 10, page_total, page_idx)


# ============================================================
# SCREEN 7: WARNINGS ONLY (big text, high visibility)
# ============================================================

class WarningScreen:
    NAME = "Warnings"
    DESC = "Big full-screen warning display"

    def __init__(self):
        self.flash_counter = 0

    def draw(self, surface, data, fonts, page_idx=0, page_total=1):
        W, H = surface.get_size()
        self.flash_counter += 1
        flash_state = (self.flash_counter // 4) % 2 == 0

        surface.fill(config.color('bg'))
        draw_shift_lights(surface, 8, 4, W - 16, 28, data['rpm'], flash_state)

        warnings_cfg = config['warnings']
        alerts = []

        temp = data['coolant_temp']
        oil = data['oil_pressure']

        if temp >= warnings_cfg['coolant_critical']:
            alerts.append(('CLT CRITICAL', f"{convert_temp(temp)}{temp_label()}",
                          config.color('warning_red'), True))
        elif temp >= warnings_cfg['coolant_high']:
            alerts.append(('CLT HIGH', f"{convert_temp(temp)}{temp_label()}",
                          config.color('rpm_yellow'), False))

        if oil <= warnings_cfg['oil_critical']:
            alerts.append(('OIL CRITICAL', f"{convert_pressure(oil)} {pressure_label()}",
                          config.color('warning_red'), True))
        elif oil <= warnings_cfg['oil_low']:
            alerts.append(('OIL LOW', f"{convert_pressure(oil)} {pressure_label()}",
                          config.color('rpm_yellow'), False))

        if not alerts:
            # All good
            draw_text(surface, fonts, "ALL SYSTEMS OK", W // 2, H // 2 - 30,
                      size=48, color=config.color('best_green'), bold=True, anchor='center')
            draw_text(surface, fonts, f"CLT: {convert_temp(temp)}{temp_label()}   "
                      f"OIL: {convert_pressure(oil)} {pressure_label()}",
                      W // 2, H // 2 + 30, size=24, color=config.color('text'), anchor='center')
        else:
            # Show warnings big
            y_start = 60
            h_per = min(160, (H - 80) // len(alerts))
            for i, (title, value, color, critical) in enumerate(alerts):
                y = y_start + i * h_per
                bg_color = (color[0]//4, color[1]//4, color[2]//4)
                if critical and flash_state:
                    bg_color = (color[0]//2, color[1]//2, color[2]//2)
                draw_rounded_rect(surface, (20, y, W - 40, h_per - 10), bg_color, radius=10)
                draw_text(surface, fonts, title, W // 2, y + 20,
                          size=36, color=color, bold=True, anchor='midtop')
                draw_text(surface, fonts, value, W // 2, y + 65,
                          size=48, color=color, bold=True, anchor='midtop')

        draw_page_dots(surface, W // 2, H - 10, page_total, page_idx)


# ============================================================
# SCREEN 8: C4 CORVETTE DIGITAL DASH
# Inspired by the 1984-89 C4 Corvette LCD instrument cluster.
# Speedo: convex upward-sloping bar graph (left panel)
# Tach: parabolic curve opening right, cut off (right panel)
# Center: amber digital readouts for temps/info
# ============================================================

class C4CorvetteScreen:
    NAME = "C4 Corvette"
    DESC = "80s digital dash tribute"

    C4_GREEN     = (0, 200, 60)
    C4_GREEN_DIM = (0, 40, 12)
    C4_YELLOW    = (200, 200, 0)
    C4_YELLOW_DIM = (50, 50, 0)
    C4_RED       = (200, 0, 0)
    C4_RED_DIM   = (50, 0, 0)
    C4_AMBER     = (255, 140, 0)    # neon orange
    C4_AMBER_DIM = (70, 35, 0)
    C4_BG        = (0, 0, 0)
    C4_CENTER_BG = (48, 48, 48)   # lighter gray for center panel
    C4_CENTER_BD = (65, 65, 65)

    def __init__(self):
        self.flash_counter = 0

    def _speedo_curve(self, t, ox, oy, w, h):
        """Speedometer: convex upward-sloping sweep (no curve-back).
        Starts bottom-left, sweeps up-right with a leftward bulge."""
        y = oy + h * (1.0 - t)
        x = ox + w * (t ** 1.6)
        bulge = math.sin(t * math.pi) * w * 0.35
        x -= bulge
        return int(x), int(y)

    def _tach_curve(self, t, ox, oy, w, h):
        """Tachometer: MIRRORED — sweeps up from bottom-LEFT, up-right,
        then curves BACK DOWN to the right at the top.
        Like the speedo mirror: starts left, goes right, arcs back down."""
        # X moves rightward as t increases (mirror of speedo)
        x = ox + w * (t ** 1.6)
        bulge = math.sin(t * math.pi) * w * 0.30
        x += bulge  # bulge rightward (opposite of speedo)
        # Y: inverted parabola — goes up then comes back down
        peak = 0.55
        if t <= peak:
            frac = t / peak
            y_norm = frac
        else:
            frac = (t - peak) / (1.0 - peak)
            y_norm = 1.0 - frac * 0.6
        y = oy + h * (1.0 - y_norm)
        return int(x), int(y)

    def _draw_c4_bar_gauge(self, surface, fonts, curve_func,
                           ox, oy, w, h, value, max_val,
                           segments=55, bar_len=22, labels=None,
                           label_side='left'):
        """Draw C4-style segmented bar gauge along a curve path."""
        for i in range(segments):
            t = i / segments
            seg_frac = (i + 0.5) / segments
            cx, cy = curve_func(t, ox, oy, w, h)

            t2 = min(1.0, (i + 1) / segments)
            cx2, cy2 = curve_func(t2, ox, oy, w, h)
            dx, dy = cx2 - cx, cy2 - cy
            length = max(1, math.sqrt(dx*dx + dy*dy))
            nx, ny = -dy / length, dx / length

            if seg_frac < 0.70:
                lit = self.C4_GREEN; dim = self.C4_GREEN_DIM
            elif seg_frac < 0.88:
                lit = self.C4_YELLOW; dim = self.C4_YELLOW_DIM
            else:
                lit = self.C4_RED; dim = self.C4_RED_DIM

            is_lit = (value / max(max_val, 1)) >= t
            color = lit if is_lit else dim

            half = bar_len // 2
            x1 = int(cx - nx * half)
            y1 = int(cy - ny * half)
            x2 = int(cx + nx * half)
            y2 = int(cy + ny * half)
            pygame.draw.line(surface, color, (x1, y1), (x2, y2), 3)

        if labels:
            for val, text in labels:
                t = val / max(max_val, 1)
                if t > 1:
                    continue
                cx, cy = curve_func(t, ox, oy, w, h)
                t2 = min(1.0, t + 0.02)
                t0 = max(0.0, t - 0.02)
                cx2, cy2 = curve_func(t2, ox, oy, w, h)
                cx0, cy0 = curve_func(t0, ox, oy, w, h)
                ddx, ddy = cx2 - cx0, cy2 - cy0
                ln = max(1, math.sqrt(ddx*ddx + ddy*ddy))
                nnx, nny = -ddy / ln, ddx / ln
                offset = 20 if label_side == 'left' else -20
                lx = int(cx + nnx * offset)
                ly = int(cy + nny * offset)
                font = fonts.get(12)
                rendered = font.render(str(text), True, self.C4_AMBER)
                rect = rendered.get_rect(center=(lx, ly))
                surface.blit(rendered, rect)

    def _draw_turn_signal(self, surface, cx, cy, direction, lit=False):
        """Draw a C4-style turn signal arrow. direction: 'left' or 'right'."""
        color = self.C4_GREEN if lit else self.C4_GREEN_DIM
        if direction == 'left':
            pts = [(cx + 20, cy - 12), (cx - 12, cy), (cx + 20, cy + 12)]
        else:
            pts = [(cx - 20, cy - 12), (cx + 12, cy), (cx - 20, cy + 12)]
        pygame.draw.polygon(surface, color, pts)

    def draw(self, surface, data, fonts, page_idx=0, page_total=1):
        W, H = surface.get_size()
        self.flash_counter += 1
        flash_state = (self.flash_counter // 4) % 2 == 0
        rpm, speed = data['rpm'], data['speed']
        gear = get_gear_display(data)
        temp = data['coolant_temp']
        oil = data['oil_pressure']
        e = config['engine']

        surface.fill(self.C4_BG)

        # ── LEFT PANEL: SPEEDOMETER ──
        panel_w = 245
        pygame.draw.rect(surface, (10, 10, 10), (4, 4, panel_w, H - 8), border_radius=6)
        pygame.draw.rect(surface, (28, 28, 28), (4, 4, panel_w, H - 8), 1, border_radius=6)

        max_spd = 120
        spd_labels = [(v, str(v)) for v in range(0, max_spd + 1, 20)]
        self._draw_c4_bar_gauge(surface, fonts, self._speedo_curve,
                                14, 20, 155, H - 105,
                                min(speed, max_spd), max_spd,
                                segments=80, bar_len=24,
                                labels=spd_labels, label_side='left')

        # Digital speed at bottom
        disp_speed = convert_speed(speed)
        draw_text(surface, fonts, f"{disp_speed}", panel_w // 2 + 10, H - 58,
                  size=52, color=self.C4_AMBER, bold=True, anchor='center')
        draw_text(surface, fonts, speed_label(), panel_w // 2 + 10, H - 28,
                  size=14, color=self.C4_AMBER_DIM, anchor='center')

        # ── RIGHT PANEL: TACHOMETER (mirrored, curves back down at top) ──
        right_x = W - panel_w - 4
        pygame.draw.rect(surface, (10, 10, 10), (right_x, 4, panel_w, H - 8), border_radius=6)
        pygame.draw.rect(surface, (28, 28, 28), (right_x, 4, panel_w, H - 8), 1, border_radius=6)

        rpm_max_disp = e['max_rpm']
        rpm_labels = [(v, str(v // 100)) for v in range(0, rpm_max_disp + 1, 1000)]
        self._draw_c4_bar_gauge(surface, fonts, self._tach_curve,
                                right_x + 20, 20, 190, H - 105,
                                min(rpm, rpm_max_disp), rpm_max_disp,
                                segments=80, bar_len=26,
                                labels=rpm_labels, label_side='left')

        # Upshift arrow — upper LEFT corner of tach panel
        if rpm >= e['shift_rpm']:
            arrow_color = self.C4_RED if flash_state else self.C4_YELLOW
            ay = 22
            ac = right_x + 22
            pygame.draw.polygon(surface, arrow_color, [
                (ac, ay - 12), (ac - 9, ay + 2), (ac + 9, ay + 2)])
            pygame.draw.rect(surface, arrow_color, (ac - 3, ay + 2, 6, 8))

        # Digital RPM (hundreds like real C4)
        rpm_color = self.C4_RED if rpm >= e['redline_rpm'] else self.C4_AMBER
        draw_text(surface, fonts, f"{rpm // 100}", right_x + panel_w // 2, H - 58,
                  size=42, color=rpm_color, bold=True, anchor='center')
        draw_text(surface, fonts, "RPM/100", right_x + panel_w // 2, H - 28,
                  size=12, color=self.C4_AMBER_DIM, anchor='center')

        # ── CENTER PANEL (lighter gray like real C4) ──
        cx = W // 2
        center_l = panel_w + 10
        center_r = right_x - 6
        center_w = center_r - center_l
        # Lighter gray fill
        pygame.draw.rect(surface, self.C4_CENTER_BG,
                        (center_l, 4, center_w, H - 8), border_radius=4)
        pygame.draw.rect(surface, self.C4_CENTER_BD,
                        (center_l, 4, center_w, H - 8), 1, border_radius=4)

        # ── Info packed tighter at the top ──
        # Orange box around oil + coolant data
        row1_y = 18
        half_cw = center_w // 2
        oil_cx = center_l + half_cw // 2 + 4
        clt_cx = center_l + half_cw + half_cw // 2 - 4

        # Orange border box around the top readouts
        box_pad = 6
        box_top = row1_y - box_pad
        box_bot = row1_y + 56
        pygame.draw.rect(surface, self.C4_AMBER,
                        (center_l + 6, box_top, center_w - 12, box_bot - box_top), 1, border_radius=3)

        draw_text(surface, fonts, "OIL PRESS", oil_cx, row1_y, size=10,
                  color=self.C4_AMBER_DIM, anchor='center')
        oil_color = self.C4_RED if oil <= config['warnings']['oil_critical'] and flash_state else self.C4_AMBER
        draw_text(surface, fonts, f"{convert_pressure(oil)}", oil_cx, row1_y + 18,
                  size=28, color=oil_color, bold=True, anchor='center')
        draw_text(surface, fonts, pressure_label().upper(), oil_cx, row1_y + 44,
                  size=9, color=self.C4_AMBER_DIM, anchor='center')

        draw_text(surface, fonts, "COOLANT TEMP", clt_cx, row1_y, size=10,
                  color=self.C4_AMBER_DIM, anchor='center')
        clt_color = self.C4_RED if temp >= config['warnings']['coolant_high'] and flash_state else self.C4_AMBER
        draw_text(surface, fonts, f"{convert_temp(temp)}", clt_cx, row1_y + 18,
                  size=28, color=clt_color, bold=True, anchor='center')
        draw_text(surface, fonts, temp_label().upper(), clt_cx, row1_y + 44,
                  size=9, color=self.C4_AMBER_DIM, anchor='center')

        # Divider line
        div_y = row1_y + 60
        pygame.draw.line(surface, self.C4_CENTER_BD,
                        (center_l + 8, div_y), (center_r - 8, div_y), 1)

        # Row 2: Gear, Throttle, Brake packed in a row
        row2_y = div_y + 8
        draw_text(surface, fonts, "GEAR", cx, row2_y, size=9,
                  color=self.C4_AMBER_DIM, anchor='center')
        draw_text(surface, fonts, str(gear), cx, row2_y + 16,
                  size=40, color=self.C4_AMBER, bold=True, anchor='center')

        thr_x = center_l + 20
        brk_x = center_r - 20
        draw_text(surface, fonts, "THR", thr_x, row2_y + 6, size=9,
                  color=self.C4_AMBER_DIM, anchor='center')
        draw_text(surface, fonts, f"{data['throttle']}%", thr_x, row2_y + 22,
                  size=18, color=self.C4_GREEN, bold=True, anchor='center')
        draw_text(surface, fonts, "BRK", brk_x, row2_y + 6, size=9,
                  color=self.C4_AMBER_DIM, anchor='center')
        draw_text(surface, fonts, f"{data['brake']}%", brk_x, row2_y + 22,
                  size=18, color=self.C4_RED, bold=True, anchor='center')

        # Divider line
        div2_y = row2_y + 52
        pygame.draw.line(surface, self.C4_CENTER_BD,
                        (center_l + 8, div2_y), (center_r - 8, div2_y), 1)

        # Turn signals — pushed down near bottom, doubled in size
        turn_y = H - 130
        self._draw_turn_signal(surface, center_l + 32, turn_y, 'left')
        self._draw_turn_signal(surface, center_r - 32, turn_y, 'right')
        # High beam indicator (bigger)
        pygame.draw.rect(surface, (0, 40, 100), (cx - 12, turn_y - 8, 24, 16), border_radius=3)
        draw_text(surface, fonts, "HI", cx, turn_y, size=10,
                  color=(60, 120, 200), anchor='center')

        # Bottom area: GPS and fake trip/fuel display
        bot_y = H - 90
        pygame.draw.line(surface, self.C4_CENTER_BD,
                        (center_l + 8, bot_y), (center_r - 8, bot_y), 1)

        draw_text(surface, fonts, "RANGE", center_l + 18, bot_y + 8, size=8,
                  color=self.C4_AMBER_DIM)
        draw_text(surface, fonts, "TRIP", cx - 10, bot_y + 8, size=8,
                  color=self.C4_AMBER, bold=True)

        draw_text(surface, fonts, "MILES", center_l + 18, bot_y + 30, size=8,
                  color=self.C4_AMBER_DIM)
        draw_text(surface, fonts, "---", center_l + 50, bot_y + 30, size=12,
                  color=self.C4_AMBER, bold=True)

        # Fuel icon area
        draw_text(surface, fonts, "UNLEADED", cx, bot_y + 22, size=7,
                  color=self.C4_AMBER_DIM, anchor='center')
        draw_text(surface, fonts, "FUEL ONLY", cx, bot_y + 32, size=7,
                  color=self.C4_AMBER_DIM, anchor='center')
        # Small fuel pump icon (just a rectangle placeholder)
        pygame.draw.rect(surface, self.C4_AMBER_DIM, (cx - 4, bot_y + 42, 8, 10), 1)

        draw_text(surface, fonts, "AVERAGE", center_r - 22, bot_y + 8, size=8,
                  color=self.C4_AMBER_DIM, anchor='topright')
        draw_text(surface, fonts, "INSTANT", center_r - 22, bot_y + 18, size=8,
                  color=self.C4_AMBER, anchor='topright')
        draw_text(surface, fonts, "MPG", center_r - 22, bot_y + 38, size=8,
                  color=self.C4_AMBER_DIM, anchor='topright')

        # GPS sats
        sats = data.get('gps_satellites', 0)
        draw_text(surface, fonts, f"GPS:{sats}", cx, H - 22,
                  size=10, color=self.C4_AMBER_DIM, anchor='center')

        draw_page_dots(surface, W // 2, H - 8, page_total, page_idx)


# ============================================================
# SCREEN 9: CLASSIC ANALOG DASH
# Traditional round gauges with needles. No shift lights,
# no gear indicator — just pure analog gauges like a street car.
# Big tach + speedo, smaller CLT + oil gauges with needles.
# ============================================================

class ClassicAnalogScreen:
    NAME = "Classic"
    DESC = "Traditional round gauge needles"

    CL_FACE    = (18, 18, 22)
    CL_RING    = (50, 50, 55)
    CL_TICK    = (180, 180, 180)
    CL_NEEDLE  = (220, 30, 30)
    CL_HUB     = (80, 80, 80)
    CL_TEXT    = (200, 200, 200)
    CL_DIM     = (90, 90, 100)
    CL_RED_ZONE = (60, 10, 10)

    def __init__(self):
        self.flash_counter = 0
        self.needle_rpm = 0
        self.needle_speed = 0
        self.needle_clt = 180
        self.needle_oil = 40

    def _draw_round_gauge(self, surface, fonts, cx, cy, radius,
                          value, max_val, label, unit_label,
                          major_step=None, start_deg=225, end_deg=-45,
                          red_zone_start=None, show_digital=True,
                          digital_size=28, warn_high=None, warn_low=None,
                          flash_state=False):
        """Draw a classic round analog gauge with needle"""
        total_sweep = end_deg - start_deg

        # Gauge face
        pygame.draw.circle(surface, self.CL_FACE, (cx, cy), radius)
        pygame.draw.circle(surface, self.CL_RING, (cx, cy), radius, 2)

        # Red zone arc (for high-warning gauges like RPM, CLT)
        if red_zone_start is not None and red_zone_start < max_val:
            rz_t_start = red_zone_start / max_val
            for i in range(int(rz_t_start * 60), 60):
                t = i / 60
                angle = math.radians(start_deg + total_sweep * t)
                x1 = cx + int(math.cos(angle) * (radius - 14))
                y1 = cy - int(math.sin(angle) * (radius - 14))
                x2 = cx + int(math.cos(angle) * (radius - 2))
                y2 = cy - int(math.sin(angle) * (radius - 2))
                pygame.draw.line(surface, self.CL_RED_ZONE, (x1, y1), (x2, y2), 4)

        # Low-warning zone (for oil pressure — red at the low end)
        if warn_low is not None:
            rz_t_end = warn_low / max_val
            for i in range(0, int(rz_t_end * 60)):
                t = i / 60
                angle = math.radians(start_deg + total_sweep * t)
                x1 = cx + int(math.cos(angle) * (radius - 14))
                y1 = cy - int(math.sin(angle) * (radius - 14))
                x2 = cx + int(math.cos(angle) * (radius - 2))
                y2 = cy - int(math.sin(angle) * (radius - 2))
                pygame.draw.line(surface, self.CL_RED_ZONE, (x1, y1), (x2, y2), 4)

        # Tick marks
        if major_step:
            num_major = int(max_val / major_step) + 1
            for i in range(num_major):
                val = i * major_step
                t = val / max_val
                angle = math.radians(start_deg + total_sweep * t)

                x1 = cx + int(math.cos(angle) * (radius - 18))
                y1 = cy - int(math.sin(angle) * (radius - 18))
                x2 = cx + int(math.cos(angle) * (radius - 4))
                y2 = cy - int(math.sin(angle) * (radius - 4))
                pygame.draw.line(surface, self.CL_TICK, (x1, y1), (x2, y2), 2)

                lx = cx + int(math.cos(angle) * (radius - 28))
                ly = cy - int(math.sin(angle) * (radius - 28))
                lbl = str(int(val))
                if max_val > 1000:
                    lbl = str(int(val / 1000))
                font = fonts.get(max(9, min(12, radius // 12)))
                rendered = font.render(lbl, True, self.CL_DIM)
                rect = rendered.get_rect(center=(lx, ly))
                surface.blit(rendered, rect)

            # Minor ticks
            minor_step = major_step / 2
            num_minor = int(max_val / minor_step) + 1
            for i in range(num_minor):
                val = i * minor_step
                if val % major_step == 0:
                    continue
                t = val / max_val
                angle = math.radians(start_deg + total_sweep * t)
                x1 = cx + int(math.cos(angle) * (radius - 10))
                y1 = cy - int(math.sin(angle) * (radius - 10))
                x2 = cx + int(math.cos(angle) * (radius - 4))
                y2 = cy - int(math.sin(angle) * (radius - 4))
                pygame.draw.line(surface, (60, 60, 65), (x1, y1), (x2, y2), 1)

        # Needle
        clamped = max(0, min(value, max_val))
        t = clamped / max_val
        angle = math.radians(start_deg + total_sweep * t)
        needle_len = radius - 22
        nx = cx + int(math.cos(angle) * needle_len)
        ny = cy - int(math.sin(angle) * needle_len)
        tail_len = 15
        tx = cx - int(math.cos(angle) * tail_len)
        ty = cy + int(math.sin(angle) * tail_len)
        pygame.draw.line(surface, self.CL_NEEDLE, (tx, ty), (nx, ny), 3)
        pygame.draw.circle(surface, self.CL_HUB, (cx, cy), 8)
        pygame.draw.circle(surface, self.CL_NEEDLE, (cx, cy), 4)

        # Label
        draw_text(surface, fonts, label, cx, cy + radius * 0.35,
                  size=max(10, radius // 10), color=self.CL_DIM, anchor='center')

        # Digital readout
        if show_digital:
            # Determine color for warning state
            digit_color = self.CL_TEXT
            if warn_high is not None and clamped >= warn_high:
                digit_color = (255, 40, 40) if flash_state else (255, 200, 0)
            if warn_low is not None and clamped <= warn_low:
                digit_color = (255, 40, 40) if flash_state else (255, 200, 0)

            draw_text(surface, fonts, f"{int(clamped)}", cx, cy + radius * 0.55,
                      size=digital_size, color=digit_color, bold=True, anchor='center')
            draw_text(surface, fonts, unit_label, cx, cy + radius * 0.55 + digital_size * 0.8,
                      size=max(8, radius // 14), color=self.CL_DIM, anchor='center')

    def draw(self, surface, data, fonts, page_idx=0, page_total=1):
        W, H = surface.get_size()
        self.flash_counter += 1
        flash_state = (self.flash_counter // 4) % 2 == 0
        rpm, speed = data['rpm'], data['speed']
        temp = data['coolant_temp']
        oil = data['oil_pressure']
        e = config['engine']

        # Smooth needle movement
        self.needle_rpm += (rpm - self.needle_rpm) * 0.25
        self.needle_speed += (speed - self.needle_speed) * 0.25
        self.needle_clt += (temp - self.needle_clt) * 0.15
        self.needle_oil += (oil - self.needle_oil) * 0.15

        surface.fill((5, 5, 8))

        # No shift lights, no gear — pure analog instrument cluster

        # ── TACHOMETER (center-right, largest gauge) ──
        tach_r = 170
        tach_cx = W - 190
        tach_cy = 185
        self._draw_round_gauge(surface, fonts, tach_cx, tach_cy, tach_r,
                               self.needle_rpm, e['max_rpm'],
                               "RPM x1000", "RPM",
                               major_step=1000,
                               red_zone_start=e['redline_rpm'],
                               digital_size=24, flash_state=flash_state)

        # ── SPEEDOMETER (center-left, second largest) ──
        spd_r = 140
        spd_cx = 165
        spd_cy = 170
        max_spd_gauge = 160
        self._draw_round_gauge(surface, fonts, spd_cx, spd_cy, spd_r,
                               self.needle_speed, max_spd_gauge,
                               speed_label(), speed_label(),
                               major_step=20,
                               digital_size=30, flash_state=flash_state)

        # ── COOLANT TEMP gauge (bottom-left, proper analog needle) ──
        clt_r = 80
        clt_cx = 85
        clt_cy = H - 85
        disp_clt = convert_temp(int(self.needle_clt))
        if config.get('units', 'temp') == 'C':
            clt_max = 130; clt_step = 20
            clt_rz = convert_temp(config['warnings']['coolant_critical'])
        else:
            clt_max = 280; clt_step = 40
            clt_rz = config['warnings']['coolant_critical']
        clt_warn = convert_temp(config['warnings']['coolant_high']) if config.get('units', 'temp') == 'C' else config['warnings']['coolant_high']
        self._draw_round_gauge(surface, fonts, clt_cx, clt_cy, clt_r,
                               disp_clt, clt_max,
                               "COOLANT", temp_label(),
                               major_step=clt_step,
                               red_zone_start=clt_rz,
                               digital_size=20,
                               warn_high=clt_warn,
                               flash_state=flash_state)

        # ── OIL PRESSURE gauge (bottom-center-left, proper analog needle) ──
        oil_r = 80
        oil_cx = 265
        oil_cy = H - 85
        disp_oil = convert_pressure(int(self.needle_oil))
        if config.get('units', 'pressure') == 'bar':
            oil_max = 6; oil_step = 1
            oil_wl = convert_pressure(config['warnings']['oil_low'])
        else:
            oil_max = 100; oil_step = 20
            oil_wl = config['warnings']['oil_low']
        self._draw_round_gauge(surface, fonts, oil_cx, oil_cy, oil_r,
                               disp_oil, oil_max,
                               "OIL", pressure_label(),
                               major_step=oil_step,
                               warn_low=oil_wl,
                               digital_size=20,
                               flash_state=flash_state)

        # ── Throttle/Brake horizontal bars at very bottom ──
        bar_y = H - 14
        bar_w = W - 40
        bar_h = 8
        draw_rounded_rect(surface, (20, bar_y, bar_w // 2 - 5, bar_h),
                         (20, 20, 25), radius=3)
        tw = int((bar_w // 2 - 5) * data['throttle'] / 100)
        if tw > 0:
            draw_rounded_rect(surface, (20, bar_y, tw, bar_h),
                             config.color('throttle_green'), radius=3)
        draw_text(surface, fonts, f"THR {data['throttle']}%", 20, bar_y - 11,
                  size=9, color=self.CL_DIM)
        bx = 20 + bar_w // 2 + 5
        draw_rounded_rect(surface, (bx, bar_y, bar_w // 2 - 5, bar_h),
                         (20, 20, 25), radius=3)
        bw = int((bar_w // 2 - 5) * data['brake'] / 100)
        if bw > 0:
            draw_rounded_rect(surface, (bx, bar_y, bw, bar_h),
                             config.color('brake_red'), radius=3)
        draw_text(surface, fonts, f"BRK {data['brake']}%", bx, bar_y - 11,
                  size=9, color=self.CL_DIM)

        draw_warning_panel(surface, fonts, W // 2 - 100, 10, 200, 30, data)
        draw_page_dots(surface, W // 2, H - 4, page_total, page_idx)


# ============================================================
# SCREEN 10: G-FORCE
# Real-time g-force circle (lateral vs longitudinal) with
# trace history, plus digital readouts for all 3 axes.
# ============================================================

class GForceScreen:
    NAME = "G-Force"
    DESC = "Accelerometer g-force display"

    def __init__(self):
        self.trace = []       # History of (x, y) g-force points
        self.max_trace = 200  # ~8 seconds at 25Hz
        self.peak_lat = 0.0
        self.peak_lon_accel = 0.0
        self.peak_lon_brake = 0.0

    def draw(self, surface, data, fonts, page_idx=0, page_total=1):
        W, H = surface.get_size()
        surface.fill(config.color('bg'))

        ax = data.get('accel_x', 0.0)  # lateral
        ay = data.get('accel_y', 0.0)  # longitudinal
        az = data.get('accel_z', 0.0)  # vertical

        # Track peaks
        self.peak_lat = max(self.peak_lat, abs(ax))
        if ay > 0:
            self.peak_lon_accel = max(self.peak_lon_accel, ay)
        else:
            self.peak_lon_brake = max(self.peak_lon_brake, abs(ay))

        # Add to trace
        self.trace.append((ax, ay))
        if len(self.trace) > self.max_trace:
            self.trace.pop(0)

        # ── G-FORCE CIRCLE (full screen) ──
        circle_r = min(W, H) // 2 - 20
        circle_cx = W // 2
        circle_cy = H // 2
        g_scale = 2.0  # max g displayed (radius = this many g)

        WHITE = (255, 255, 255)
        RING_WIDTH = 2

        # Background rings — pure white, thick
        for ring_g in [0.5, 1.0, 1.5, 2.0]:
            ring_r = int(circle_r * ring_g / g_scale)
            if ring_r > 0 and ring_r <= circle_r:
                pygame.draw.circle(surface, WHITE, (circle_cx, circle_cy), ring_r, RING_WIDTH)

        # Crosshair — white, thick
        pygame.draw.line(surface, WHITE,
                        (circle_cx - circle_r, circle_cy),
                        (circle_cx + circle_r, circle_cy), RING_WIDTH)
        pygame.draw.line(surface, WHITE,
                        (circle_cx, circle_cy - circle_r),
                        (circle_cx, circle_cy + circle_r), RING_WIDTH)

        # Ring labels
        for ring_g in [0.5, 1.0, 1.5, 2.0]:
            ring_r = int(circle_r * ring_g / g_scale)
            if ring_r > 0 and ring_r <= circle_r:
                draw_text(surface, fonts, f"{ring_g:.1f}",
                         circle_cx + ring_r + 4, circle_cy - 10,
                         size=12, color=(150, 150, 150))

        # Axis labels
        draw_text(surface, fonts, "BRAKE", circle_cx, circle_cy + circle_r + 8,
                  size=14, color=(150, 150, 150), anchor='center')
        draw_text(surface, fonts, "ACCEL", circle_cx, circle_cy - circle_r - 4,
                  size=14, color=(150, 150, 150), anchor='midbottom')
        draw_text(surface, fonts, "L", circle_cx - circle_r - 14, circle_cy,
                  size=14, color=(150, 150, 150), anchor='center')
        draw_text(surface, fonts, "R", circle_cx + circle_r + 14, circle_cy,
                  size=14, color=(150, 150, 150), anchor='center')

        # Outer circle border — white, thick
        pygame.draw.circle(surface, WHITE, (circle_cx, circle_cy), circle_r, 3)

        # Draw trace (fading dots)
        for i, (tx, ty) in enumerate(self.trace):
            alpha = int(40 + 160 * i / max(len(self.trace), 1))
            px = circle_cx + int(tx / g_scale * circle_r)
            py = circle_cy - int(ty / g_scale * circle_r)
            dx, dy = px - circle_cx, py - circle_cy
            dist = math.sqrt(dx*dx + dy*dy)
            if dist > circle_r:
                px = circle_cx + int(dx / dist * circle_r)
                py = circle_cy + int(dy / dist * circle_r)
            color = (0, alpha // 2, alpha)
            pygame.draw.circle(surface, color, (px, py), 3)

        # Current position (big dot)
        cur_px = circle_cx + int(ax / g_scale * circle_r)
        cur_py = circle_cy - int(ay / g_scale * circle_r)
        dx, dy = cur_px - circle_cx, cur_py - circle_cy
        dist = math.sqrt(dx*dx + dy*dy)
        if dist > circle_r:
            cur_px = circle_cx + int(dx / dist * circle_r)
            cur_py = circle_cy + int(dy / dist * circle_r)

        # Glow effect
        pygame.draw.circle(surface, (0, 60, 120), (cur_px, cur_py), 12)
        pygame.draw.circle(surface, (0, 150, 255), (cur_px, cur_py), 8)
        pygame.draw.circle(surface, (200, 230, 255), (cur_px, cur_py), 4)

        # ── DIGITAL READOUTS (corners, overlaid) ──
        # Top-left: lateral
        draw_text(surface, fonts, "LAT", 12, 8, size=11,
                  color=config.color('text_dim'))
        lat_color = config.color('brake_red') if abs(ax) > 1.2 else WHITE
        draw_text(surface, fonts, f"{ax:+.2f}g", 12, 22,
                  size=28, color=lat_color, bold=True)

        # Top-right: longitudinal
        draw_text(surface, fonts, "LON", W - 12, 8, size=11,
                  color=config.color('text_dim'), anchor='topright')
        lon_color = config.color('throttle_green') if ay > 0.5 else (config.color('brake_red') if ay < -0.5 else WHITE)
        draw_text(surface, fonts, f"{ay:+.2f}g", W - 12, 22,
                  size=28, color=lon_color, bold=True, anchor='topright')

        # Bottom-left: combined
        combined = math.sqrt(ax*ax + ay*ay)
        comb_color = config.color('gear_yellow') if combined > 1.0 else WHITE
        draw_text(surface, fonts, f"{combined:.2f}g", 12, H - 30,
                  size=24, color=comb_color, bold=True)

        # Bottom-right: peaks
        draw_text(surface, fonts, f"Pk L:{self.peak_lat:.1f} A:{self.peak_lon_accel:.1f} B:{self.peak_lon_brake:.1f}",
                  W - 12, H - 28, size=12, color=config.color('text_dim'), anchor='topright')

        draw_page_dots(surface, W // 2, H - 10, page_total, page_idx)


# ============================================================
# SCREEN REGISTRY
# To add a new screen:
#   1. Create a class with NAME, DESC, and draw(surface, data, fonts, page_idx, page_total)
#   2. Add it to this list
#   3. That's it — it will appear in Settings > Screens
# ============================================================

SCREEN_REGISTRY = [
    ('lap_timer',    LapTimerScreen),
    ('main_gauge',   MainDashScreen),
    ('drag',         DragScreen),
    ('strip',        DriverStripScreen),
    ('gps',          GPSScreen),
    ('diagnostics',  DiagnosticScreen),
    ('warnings',     WarningScreen),
    ('c4_corvette',  C4CorvetteScreen),
    ('classic',      ClassicAnalogScreen),
    ('gforce',       GForceScreen),
]

# Screen IDs for config storage
ALL_SCREEN_IDS = [sid for sid, _ in SCREEN_REGISTRY]
DEFAULT_ENABLED = ['lap_timer', 'main_gauge', 'diagnostics']


def get_enabled_screen_ids():
    """Get list of enabled screen IDs from config"""
    enabled = config.get('screens', 'enabled')
    if enabled is None:
        return list(DEFAULT_ENABLED)
    # Filter to only valid IDs
    return [sid for sid in enabled if sid in ALL_SCREEN_IDS]


def set_enabled_screen_ids(ids):
    """Save enabled screen list to config"""
    config.set('screens', 'enabled', ids)


# ============================================================
# SCREEN: SETTINGS (always available, not toggleable)
# ============================================================

class SettingsScreen:
    NAME = "Settings"
    DESC = "Configuration"

    def __init__(self, app=None):
        self.app = app  # Reference to app for rebuild_screens
        self.page_names = list(SETTINGS_PAGES.keys()) + ['Screens', 'Update']
        self.current_page = 0
        self.selected_row = 0
        self.scroll_offset = 0  # Scroll for pages with many rows
        self.dirty = False
        self.touch_regions = []
        self.updater = Updater()

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            mx, my = event.pos
            for region in self.touch_regions:
                if region['rect'].collidepoint(mx, my):
                    self._handle_action(region['action'], region.get('data'))
                    return True
            # Scroll by touch on the row area (drag up/down)
        
        if event.type == pygame.MOUSEWHEEL:
            # Mouse wheel scrolling
            max_rows = self._get_row_count()
            self.scroll_offset = max(0, self.scroll_offset - event.y)
            return True

        if event.type == pygame.KEYDOWN:
            mods = pygame.key.get_mods()
            max_rows = self._get_row_count()

            # ── Page navigation: LEFT/RIGHT arrows switch tabs ──
            if event.key == pygame.K_LEFT and (mods & pygame.KMOD_SHIFT):
                self.current_page = (self.current_page - 1) % len(self.page_names)
                self.selected_row = 0
                self.scroll_offset = 0
                return True
            elif event.key == pygame.K_RIGHT and (mods & pygame.KMOD_SHIFT):
                self.current_page = (self.current_page + 1) % len(self.page_names)
                self.selected_row = 0
                self.scroll_offset = 0
                return True
            elif event.key == pygame.K_TAB:
                direction = -1 if (mods & pygame.KMOD_SHIFT) else 1
                self.current_page = (self.current_page + direction) % len(self.page_names)
                self.selected_row = 0
                self.scroll_offset = 0
                return True

            # ── Row navigation: UP/DOWN ──
            elif event.key == pygame.K_UP:
                self.selected_row = (self.selected_row - 1) % max_rows
                self._ensure_visible()
                return True
            elif event.key == pygame.K_DOWN:
                self.selected_row = (self.selected_row + 1) % max_rows
                self._ensure_visible()
                return True

            # ── Value adjust: LEFT/RIGHT or RETURN/BACKSPACE ──
            elif event.key == pygame.K_RIGHT:
                self._adjust_current(1)
                return True
            elif event.key == pygame.K_LEFT:
                self._adjust_current(-1)
                return True
            elif event.key == pygame.K_RETURN:
                self._activate_current()
                return True
            elif event.key == pygame.K_BACKSPACE:
                self._adjust_current(-1)
                return True

            # ── Quick actions ──
            elif event.key == pygame.K_s and (mods & pygame.KMOD_CTRL):
                config.save()
                self.dirty = False
                return True

            # ── Exit settings: Q goes back to dash ──
            elif event.key == pygame.K_q:
                if self.app:
                    self.app.current_screen = 0
                return True

        return False

    def _ensure_visible(self):
        """Auto-scroll so the selected row is visible"""
        # visible_rows is roughly how many fit (480 - tab bar - title - dots)
        visible_rows = 7
        if self.selected_row < self.scroll_offset:
            self.scroll_offset = self.selected_row
        elif self.selected_row >= self.scroll_offset + visible_rows:
            self.scroll_offset = self.selected_row - visible_rows + 1

    def _get_row_count(self):
        if self.page_names[self.current_page] == 'Screens':
            return len(SCREEN_REGISTRY)
        if self.page_names[self.current_page] == 'Update':
            return 4  # Flash, Reset STM32, Git Pull, Restart
        return len(SETTINGS_PAGES.get(self.page_names[self.current_page], []))

    def _handle_action(self, action, data=None):
        if action == 'tab':
            self.current_page = data
            self.selected_row = 0
            self.scroll_offset = 0
        elif action == 'toggle_screen':
            self._toggle_screen(data)
        elif action == 'inc':
            self._adjust_value(data, 1)
        elif action == 'dec':
            self._adjust_value(data, -1)
        elif action == 'save':
            config.save()
            self.dirty = False
        elif action == 'reset':
            config.reset()
            self.dirty = True
            if self.app:
                self.app.rebuild_screens()
        elif action == 'flash_stm32':
            uart_thread = self.app.can_thread if self.app else None
            self.updater.flash_stm32(uart_thread=uart_thread)
        elif action == 'reset_stm32':
            self.updater.reset_stm32_action()
        elif action == 'git_pull':
            self.updater.update_pi_software()
        elif action == 'restart_app':
            if self.app:
                self.app.shutdown()
            self.updater.restart_app()

    def _toggle_screen(self, screen_id):
        enabled = get_enabled_screen_ids()
        if screen_id in enabled:
            if len(enabled) > 1:  # Don't disable the last screen
                enabled.remove(screen_id)
        else:
            enabled.append(screen_id)
        set_enabled_screen_ids(enabled)
        self.dirty = True
        if self.app:
            self.app.rebuild_screens()

    def _activate_current(self):
        """ENTER key — toggle/activate the selected row."""
        page = self.page_names[self.current_page]
        if page == 'Screens':
            if self.selected_row < len(SCREEN_REGISTRY):
                self._toggle_screen(SCREEN_REGISTRY[self.selected_row][0])
        elif page == 'Update':
            actions = ['flash_stm32', 'reset_stm32', 'git_pull', 'restart_app']
            if self.selected_row < len(actions):
                self._handle_action(actions[self.selected_row])
        else:
            self._adjust_current(1)

    def _adjust_current(self, direction):
        page = self.page_names[self.current_page]
        if page == 'Screens':
            if self.selected_row < len(SCREEN_REGISTRY):
                self._toggle_screen(SCREEN_REGISTRY[self.selected_row][0])
        elif page == 'Update':
            pass  # Update buttons don't have inc/dec, use ENTER
        else:
            items = SETTINGS_PAGES.get(page, [])
            if self.selected_row < len(items):
                self._adjust_value(self.selected_row, direction)

    def _adjust_value(self, row_idx, direction):
        page_name = self.page_names[self.current_page]
        if page_name == 'Screens':
            return
        items = SETTINGS_PAGES.get(page_name, [])
        if row_idx >= len(items):
            return
        section, key, name, typ, vmin, vmax, step = items[row_idx]
        current = config.get(section, key)

        if typ == 'int':
            new_val = max(vmin, min(vmax, current + step * direction))
            config.set(section, key, new_val)
            self.dirty = True
        elif typ == 'float':
            new_val = max(vmin, min(vmax, round(current + step * direction, 2)))
            config.set(section, key, new_val)
            self.dirty = True
        elif typ == 'bool':
            config.set(section, key, not current)
            self.dirty = True
        elif typ == 'choice':
            choices = SETTING_CHOICES.get((section, key), [])
            if choices:
                try:
                    idx = choices.index(current)
                except ValueError:
                    idx = 0
                config.set(section, key, choices[(idx + direction) % len(choices)])
                self.dirty = True

    def draw(self, surface, data, fonts, page_idx=0, page_total=1):
        W, H = surface.get_size()
        surface.fill(config.color('bg'))
        self.touch_regions = []

        # Title bar
        draw_rounded_rect(surface, (0, 0, W, 44), config.color('panel'), radius=0)
        draw_text(surface, fonts, "SETTINGS", 16, 12, size=18,
                  color=config.color('text'), bold=True)

        if self.dirty:
            draw_text(surface, fonts, "* UNSAVED", W // 2, 13, size=13,
                      color=config.color('warning_red'), anchor='midtop')

        # Save / Reset
        save_x = W - 140
        save_color = config.color('accent') if self.dirty else config.color('text_dim')
        draw_rounded_rect(surface, (save_x, 6, 60, 30), config.color('bar_bg'), radius=6)
        draw_text(surface, fonts, "SAVE", save_x + 30, 21, size=14,
                  color=save_color, bold=True, anchor='center')
        self.touch_regions.append({'rect': pygame.Rect(save_x, 6, 60, 30), 'action': 'save'})

        reset_x = W - 70
        draw_rounded_rect(surface, (reset_x, 6, 60, 30), config.color('bar_bg'), radius=6)
        draw_text(surface, fonts, "RESET", reset_x + 30, 21, size=14,
                  color=config.color('text_dim'), anchor='center')
        self.touch_regions.append({'rect': pygame.Rect(reset_x, 6, 60, 30), 'action': 'reset'})

        # Tab bar
        tab_y, tab_h = 48, 32
        tab_w = W // len(self.page_names)
        for i, name in enumerate(self.page_names):
            tx = i * tab_w
            is_active = (i == self.current_page)
            if is_active:
                draw_rounded_rect(surface, (tx + 2, tab_y, tab_w - 4, tab_h),
                                 config.color('panel_border'), radius=4)
            color = config.color('text') if is_active else config.color('text_dim')
            draw_text(surface, fonts, name, tx + tab_w // 2, tab_y + tab_h // 2,
                      size=12, color=color, bold=is_active, anchor='center')
            self.touch_regions.append({
                'rect': pygame.Rect(tx, tab_y, tab_w, tab_h), 'action': 'tab', 'data': i
            })

        row_start = tab_y + tab_h + 12
        row_h, row_gap = 48, 4

        if self.page_names[self.current_page] == 'Screens':
            self._draw_screens_page(surface, fonts, W, H, row_start, row_h, row_gap)
        elif self.page_names[self.current_page] == 'Update':
            self._draw_update_page(surface, fonts, W, H, row_start, row_h, row_gap)
        else:
            self._draw_settings_page(surface, fonts, W, H, row_start, row_h, row_gap)

        draw_page_dots(surface, W // 2, H - 10, page_total, page_idx)

    def _draw_screens_page(self, surface, fonts, W, H, row_start, row_h, row_gap):
        """Draw screen toggle list with scrolling"""
        enabled = get_enabled_screen_ids()
        total = len(SCREEN_REGISTRY)

        # Use compact rows to fit more
        row_h = 40
        row_gap = 3
        max_visible_y = H - 30

        # Clamp scroll offset
        self.scroll_offset = max(0, min(self.scroll_offset, total - 1))

        # Scroll indicator if items above
        if self.scroll_offset > 0:
            draw_text(surface, fonts, "^ more ^", W // 2, row_start - 2,
                      size=10, color=config.color('text_dim'), anchor='midbottom')

        drawn_any_below = False
        for i, (screen_id, screen_cls) in enumerate(SCREEN_REGISTRY):
            display_i = i - self.scroll_offset
            ry = row_start + display_i * (row_h + row_gap)

            # Skip rows above viewport
            if ry + row_h < row_start:
                continue
            # Stop drawing below viewport, but note there are more
            if ry > max_visible_y:
                drawn_any_below = True
                continue

            is_sel = (i == self.selected_row)
            is_on = screen_id in enabled

            bg = config.color('panel_border') if is_sel else config.color('panel')
            draw_rounded_rect(surface, (12, ry, W - 24, row_h), bg, radius=6)

            # Toggle switch
            tog_x, tog_y = 22, ry + row_h // 2
            tog_w, tog_h = 36, 20
            if is_on:
                draw_rounded_rect(surface, (tog_x, tog_y - tog_h//2, tog_w, tog_h),
                                 config.color('best_green'), radius=10)
                pygame.draw.circle(surface, (255, 255, 255),
                                 (tog_x + tog_w - tog_h//2, tog_y), tog_h//2 - 2)
            else:
                draw_rounded_rect(surface, (tog_x, tog_y - tog_h//2, tog_w, tog_h),
                                 config.color('bar_bg'), radius=10)
                pygame.draw.circle(surface, config.color('text_dim'),
                                 (tog_x + tog_h//2, tog_y), tog_h//2 - 2)

            # Name and description on one line
            name_color = config.color('text') if is_on else config.color('text_dim')
            draw_text(surface, fonts, screen_cls.NAME, 68, ry + row_h // 2 - 8,
                      size=15, color=name_color, bold=is_on)
            draw_text(surface, fonts, screen_cls.DESC, 68, ry + row_h // 2 + 10,
                      size=10, color=config.color('text_dim'))

            self.touch_regions.append({
                'rect': pygame.Rect(12, ry, W - 24, row_h),
                'action': 'toggle_screen', 'data': screen_id
            })

        # Scroll indicator if items below
        if drawn_any_below:
            draw_text(surface, fonts, "v more v", W // 2, max_visible_y + 4,
                      size=10, color=config.color('text_dim'), anchor='midtop')

    def _draw_update_page(self, surface, fonts, W, H, row_start, row_h, row_gap):
        """Draw firmware/software update buttons"""
        buttons = [
            ('flash_stm32',  'FLASH STM32',       'Write firmware.bin to STM32 over UART'),
            ('reset_stm32',  'RESET STM32',        'Reset the STM32 microcontroller'),
            ('git_pull',     'UPDATE PI SOFTWARE',  'Git pull latest code from GitHub'),
            ('restart_app',  'RESTART DASH APP',    'Restart to apply updates'),
        ]

        busy = self.updater.busy

        for i, (action, label, desc) in enumerate(buttons):
            ry = row_start + i * (row_h + row_gap + 8)
            is_sel = (i == self.selected_row)
            bg = config.color('panel_border') if is_sel else config.color('panel')
            draw_rounded_rect(surface, (12, ry, W - 24, row_h + 4), bg, radius=8)

            # Button label
            label_color = config.color('text_dim') if busy else config.color('text')
            draw_text(surface, fonts, label, 24, ry + 10,
                      size=16, color=label_color, bold=True)
            # Description
            draw_text(surface, fonts, desc, 24, ry + 32,
                      size=11, color=config.color('text_dim'))

            # Action button on right side
            btn_w, btn_h = 80, row_h - 4
            btn_x = W - 24 - btn_w
            if busy:
                btn_color = config.color('bar_bg')
                text_color = config.color('text_dim')
                btn_label = "..."
            elif action == 'flash_stm32':
                btn_color = (180, 60, 20)
                text_color = (255, 255, 255)
                btn_label = "FLASH"
            elif action == 'restart_app':
                btn_color = (20, 100, 180)
                text_color = (255, 255, 255)
                btn_label = "RESTART"
            else:
                btn_color = config.color('bar_bg')
                text_color = config.color('accent')
                btn_label = "RUN"

            draw_rounded_rect(surface, (btn_x, ry + 4, btn_w, btn_h), btn_color, radius=6)
            draw_text(surface, fonts, btn_label, btn_x + btn_w // 2, ry + row_h // 2,
                      size=14, color=text_color, bold=True, anchor='center')

            if not busy:
                self.touch_regions.append({
                    'rect': pygame.Rect(btn_x, ry + 4, btn_w, btn_h),
                    'action': action
                })

        # Status bar at bottom
        status_y = row_start + len(buttons) * (row_h + row_gap + 8) + 16
        draw_rounded_rect(surface, (12, status_y, W - 24, 44), config.color('panel'), radius=8)
        status_color = config.color('warning_red') if 'ERROR' in self.updater.status else \
                       config.color('best_green') if 'OK' in self.updater.status or \
                       'complete' in self.updater.status or 'Updated' in self.updater.status or \
                       'running' in self.updater.status else config.color('text')
        draw_text(surface, fonts, self.updater.status, W // 2, status_y + 22,
                  size=15, color=status_color, bold=True, anchor='center')

        # Spinning indicator when busy
        if busy:
            spinner = ['|', '/', '-', '\\']
            spin_char = spinner[int(time.time() * 4) % 4]
            draw_text(surface, fonts, spin_char, W - 40, status_y + 22,
                      size=18, color=config.color('accent'), bold=True, anchor='center')

    def _draw_settings_page(self, surface, fonts, W, H, row_start, row_h, row_gap):
        """Draw normal settings rows"""
        page_name = self.page_names[self.current_page]
        items = SETTINGS_PAGES.get(page_name, [])

        for i, (section, key, name, typ, vmin, vmax, step) in enumerate(items):
            ry = row_start + i * (row_h + row_gap)
            if ry + row_h > H - 30:
                break

            is_sel = (i == self.selected_row)
            bg = config.color('panel_border') if is_sel else config.color('panel')
            draw_rounded_rect(surface, (12, ry, W - 24, row_h), bg, radius=6)

            draw_text(surface, fonts, name, 24, ry + row_h // 2,
                      size=16, color=config.color('text'), anchor='midleft')

            current = config.get(section, key)
            if typ == 'bool':
                val_text = "ON" if current else "OFF"
                val_color = config.color('best_green') if current else config.color('text_dim')
            elif typ == 'choice':
                val_text = str(current)
                val_color = config.color('accent')
            else:
                val_text = str(current)
                val_color = config.color('text')

            draw_text(surface, fonts, val_text, W // 2 + 20, ry + row_h // 2,
                      size=18, color=val_color, bold=True, anchor='midleft')

            btn_w, btn_h = 44, row_h - 8
            dec_x = W - 24 - btn_w * 2 - 8
            draw_rounded_rect(surface, (dec_x, ry + 4, btn_w, btn_h),
                             config.color('bar_bg'), radius=6)
            draw_text(surface, fonts, "<", dec_x + btn_w // 2, ry + row_h // 2,
                      size=20, color=config.color('text'), bold=True, anchor='center')
            self.touch_regions.append({
                'rect': pygame.Rect(dec_x, ry + 4, btn_w, btn_h), 'action': 'dec', 'data': i
            })

            inc_x = W - 24 - btn_w
            draw_rounded_rect(surface, (inc_x, ry + 4, btn_w, btn_h),
                             config.color('bar_bg'), radius=6)
            draw_text(surface, fonts, ">", inc_x + btn_w // 2, ry + row_h // 2,
                      size=20, color=config.color('text'), bold=True, anchor='center')
            self.touch_regions.append({
                'rect': pygame.Rect(inc_x, ry + 4, btn_w, btn_h), 'action': 'inc', 'data': i
            })


# ============================================================
# MAIN APPLICATION
# ============================================================

class RaceDashApp:
    def __init__(self):
        sc = config['screen']
        flags = 0

        if sc['fullscreen'] and os.environ.get('DISPLAY') is None:
            # No X server — try video drivers in order of preference
            # kmsdrm is fastest but needs EGL; fbcon is the fallback
            flags = pygame.FULLSCREEN
            for driver in ['kmsdrm', 'fbcon', 'directfb', 'svgalib']:
                os.environ['SDL_VIDEODRIVER'] = driver
                try:
                    pygame.display.init()
                    print(f"# Video driver: {driver}")
                    break
                except pygame.error:
                    pygame.display.quit()
                    continue
            else:
                # All failed, let SDL pick
                os.environ.pop('SDL_VIDEODRIVER', None)
                pygame.display.init()
                print("# Video driver: SDL default")
            # Init remaining pygame subsystems (audio, events, etc.)
            pygame.init()
        else:
            if sc['fullscreen']:
                flags = pygame.FULLSCREEN
            pygame.init()

        self.screen = pygame.display.set_mode((sc['width'], sc['height']), flags)
        pygame.display.set_caption(sc['title'])
        pygame.mouse.set_visible(not sc['fullscreen'])

        self.clock = pygame.time.Clock()
        self.fonts = FontManager()
        self.running = True

        # Data acquisition
        self.buffer = SignalBuffer()
        self.can_thread = CANThread(self.buffer, simulate=config.get('data', 'simulate'))
        self.can_thread.start()

        # Ensure screens config section exists
        if 'screens' not in config.data:
            config.data['screens'] = {'enabled': list(DEFAULT_ENABLED)}

        # Screen instances (created once, reused)
        self.screen_instances = {}
        for sid, cls in SCREEN_REGISTRY:
            self.screen_instances[sid] = cls()

        # Settings screen (always available)
        self.settings_screen = SettingsScreen(app=self)

        # Build active screen list from config
        self.active_screens = []
        self.current_screen = 0
        self.rebuild_screens()

        self.touch_start_x = None
        self.touch_start_y = None
        self.swipe_threshold = 80

        # ── Physical button on GPIO (cycle screens with gloves on) ──
        # GPIO16 (pin 36) — momentary push button to GND, internal pull-up
        # Falls back gracefully on PC (no RPi.GPIO available)
        self.btn_pin = 16
        self.btn_available = False
        self.btn_last_state = True   # True = released (pulled high)
        self.btn_last_press = 0      # millis of last press (debounce)
        self.btn_debounce_ms = 150   # reject presses faster than this
        try:
            import RPi.GPIO as GPIO
            self.GPIO = GPIO
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(self.btn_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
            self.btn_available = True
            print(f"# Button on GPIO{self.btn_pin} ready")
        except (ImportError, RuntimeError):
            self.GPIO = None
            print("# No GPIO available (PC mode) — button disabled")

    def rebuild_screens(self):
        """Rebuild the active screen list from config.
        Called when screens are toggled in settings."""
        enabled = get_enabled_screen_ids()
        self.active_screens = []
        for sid in enabled:
            if sid in self.screen_instances:
                self.active_screens.append(self.screen_instances[sid])
        # Settings is always last
        self.active_screens.append(self.settings_screen)
        
        # Always stay on settings when toggling (user is in settings)
        self.current_screen = len(self.active_screens) - 1

    def handle_events(self):
        # ── Poll physical button (GPIO) ──
        if self.btn_available:
            state = self.GPIO.input(self.btn_pin)  # LOW = pressed
            now_ms = int(time.time() * 1000)
            if state == False and self.btn_last_state == True:
                # Falling edge — button just pressed
                if now_ms - self.btn_last_press > self.btn_debounce_ms:
                    self.btn_last_press = now_ms
                    self.current_screen = (self.current_screen + 1) % len(self.active_screens)
            self.btn_last_state = state

        touch_on = config.get('screen', 'touch_enabled')

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                continue

            # Skip all mouse/touch events when touchscreen is disabled
            # (keyboard and GPIO button still work)
            if not touch_on and event.type in (
                    pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP,
                    pygame.MOUSEMOTION, pygame.MOUSEWHEEL):
                continue

            # Settings screen consumes its own events
            if isinstance(self.active_screens[self.current_screen], SettingsScreen):
                if self.settings_screen.handle_event(event):
                    continue

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key in (pygame.K_RIGHT, pygame.K_SPACE):
                    self.current_screen = (self.current_screen + 1) % len(self.active_screens)
                elif event.key == pygame.K_LEFT:
                    self.current_screen = (self.current_screen - 1) % len(self.active_screens)
                elif event.key == pygame.K_s:
                    self.current_screen = len(self.active_screens) - 1

            elif event.type == pygame.MOUSEBUTTONDOWN:
                self.touch_start_x = event.pos[0]
                self.touch_start_y = event.pos[1]

            elif event.type == pygame.MOUSEBUTTONUP:
                if self.touch_start_x is not None:
                    dx = event.pos[0] - self.touch_start_x
                    dy = abs(event.pos[1] - self.touch_start_y)
                    if abs(dx) > self.swipe_threshold and dy < 100:
                        if dx < 0:
                            self.current_screen = (self.current_screen + 1) % len(self.active_screens)
                        else:
                            self.current_screen = (self.current_screen - 1) % len(self.active_screens)
                    self.touch_start_x = None
                    self.touch_start_y = None

    def run(self):
        while self.running:
            self.handle_events()
            data = self.buffer.get_all()

            # Update all screens that need continuous data (not just the visible one)
            for screen in self.screen_instances.values():
                if hasattr(screen, 'update'):
                    screen.update(data)

            total = len(self.active_screens)
            self.active_screens[self.current_screen].draw(
                self.screen, data, self.fonts,
                page_idx=self.current_screen, page_total=total)

            pygame.display.flip()
            self.clock.tick(config.get('screen', 'fps'))
        self.shutdown()

    def shutdown(self):
        print("Shutting down...")
        self.can_thread.stop()
        self.can_thread.join(timeout=0.5)
        self.settings_screen.updater.cleanup()
        if self.btn_available:
            self.GPIO.cleanup()
        pygame.quit()
        print("Shutdown complete")


if __name__ == '__main__':
    app = RaceDashApp()
    app.run()