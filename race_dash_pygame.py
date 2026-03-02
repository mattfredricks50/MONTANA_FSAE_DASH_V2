"""
Race Dash - PyGame GUI
Clean, config-driven racing dashboard for Pi Zero 2W
Runs on any platform - PC for testing, Pi framebuffer for deployment
"""

import pygame
import pygame.gfxdraw
import sys
import os
import time
import math

# Import our modules
from race_dash_core import SignalBuffer, CANThread, SensorThread
from race_dash_config import (config, SETTINGS_PAGES, SETTING_CHOICES,
    convert_speed, convert_temp, convert_pressure,
    speed_label, temp_label, pressure_label)


# ============================================================
# FONT MANAGER
# ============================================================

class FontManager:
    """Manages fonts with fallback to system defaults"""
    
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


def calculate_gear(speed):
    gear_speeds = config.get('engine', 'gear_speeds')
    for i, threshold in enumerate(gear_speeds):
        if speed < threshold:
            return i + 1
    return len(gear_speeds)


# ============================================================
# WIDGET DRAWING FUNCTIONS
# ============================================================

def draw_shift_lights(surface, x, y, w, h, rpm, flash_state):
    e = config['engine']
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
    
    light_order = [4, 5, 3, 6, 2, 7, 1, 8, 0, 9]
    light_w = (w - (num_lights + 1) * 4) / num_lights
    light_h = h - 8
    ly = y + 4
    
    for i in range(num_lights):
        lx = x + 4 + i * (light_w + 4)
        pos = light_order.index(i)
        is_on = pos < lights_on
        
        if flash_all and flash_state:
            color = config.color('rpm_red')
        elif is_on:
            if pos < 4:
                color = config.color('rpm_green')
            elif pos < 7:
                color = config.color('rpm_yellow')
            else:
                color = config.color('rpm_red')
        else:
            color = config.color('shift_off')
        
        draw_rounded_rect(surface, (int(lx), int(ly), int(light_w), int(light_h)), color, radius=4)


def draw_rpm_bar(surface, x, y, w, h, rpm):
    e = config['engine']
    draw_rounded_rect(surface, (x, y, w, h), config.color('bar_bg'), radius=6)
    
    ratio = min(rpm / e['max_rpm'], 1.0)
    fill_w = int((w - 8) * ratio)
    
    if fill_w > 0:
        seg_w, seg_gap = 6, 2
        drawn = 0
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
    spacing = 16
    start_x = cx - (total - 1) * spacing // 2
    for i in range(total):
        x = start_x + i * spacing
        color = config.color('text') if i == active else config.color('shift_off')
        pygame.draw.circle(surface, color, (x, cy), 4)


# ============================================================
# SCREEN: LAP TIMER
# ============================================================

class LapTimerScreen:
    NAME = "Lap Timer"
    
    def __init__(self):
        self.current_lap_start = time.time()
        self.best_lap = 65.432
        self.last_lap = 67.891
        self.flash_counter = 0
    
    def format_time(self, seconds):
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}:{secs:06.3f}"
    
    def draw(self, surface, data, fonts):
        W, H = surface.get_size()
        self.flash_counter += 1
        flash_state = (self.flash_counter // 4) % 2 == 0
        
        rpm, speed = data['rpm'], data['speed']
        throttle, brake = data['throttle'], data['brake']
        temp = data['coolant_temp']
        gear = calculate_gear(speed)
        
        surface.fill(config.color('bg'))
        
        draw_shift_lights(surface, 8, 6, W - 16, 36, rpm, flash_state)
        
        bar_y, bar_h = 50, 60
        draw_rpm_bar(surface, 12, bar_y, int(W * 0.72), bar_h, rpm)
        
        draw_text(surface, fonts, f"{rpm}", 20, bar_y + bar_h + 12,
                  size=38, color=rpm_color(rpm), bold=True)
        draw_text(surface, fonts, "RPM", 20, bar_y + bar_h + 52,
                  size=14, color=config.color('text_dim'))
        
        # CLT
        draw_text(surface, fonts, "CLT", 24, H - 80, size=14, color=config.color('text_label'))
        clt_color = config.color('clt_blue')
        if temp >= config['warnings']['coolant_high']:
            clt_color = config.color('warning_red') if flash_state else config.color('rpm_yellow')
        draw_text(surface, fonts, f"{convert_temp(temp)}{temp_label()}", 24, H - 62, size=32, color=clt_color, bold=True)
        
        # Oil
        draw_text(surface, fonts, "OIL", 170, H - 80, size=14, color=config.color('text_label'))
        oil_color = config.color('text')
        if data['oil_pressure'] <= config['warnings']['oil_low']:
            oil_color = config.color('warning_red') if flash_state else config.color('rpm_yellow')
        draw_text(surface, fonts, f"{convert_pressure(data['oil_pressure'])} {pressure_label()}", 170, H - 62,
                  size=32, color=oil_color, bold=True)
        
        # Lap Times
        cx = int(W * 0.46)
        pygame.draw.line(surface, config.color('panel_border'), (cx - 120, 180), (cx + 120, 180), 1)
        draw_text(surface, fonts, "CURRENT", cx, 190, size=14,
                  color=config.color('text_label'), anchor='midtop')
        
        elapsed = time.time() - self.current_lap_start
        draw_text(surface, fonts, self.format_time(elapsed), cx, 220,
                  size=48, color=config.color('text'), bold=True, anchor='midtop')
        
        if elapsed > 70:
            self.last_lap = elapsed
            if elapsed < self.best_lap:
                self.best_lap = elapsed
            self.current_lap_start = time.time()
        
        pygame.draw.line(surface, config.color('panel_border'), (cx - 120, 290), (cx + 120, 290), 1)
        draw_text(surface, fonts, "BEST", cx - 100, 310, size=13, color=config.color('text_label'))
        draw_text(surface, fonts, self.format_time(self.best_lap), cx - 100, 328,
                  size=22, color=config.color('best_green'), bold=True)
        draw_text(surface, fonts, "LAST", cx + 20, 310, size=13, color=config.color('text_label'))
        draw_text(surface, fonts, self.format_time(self.last_lap), cx + 20, 328,
                  size=22, color=config.color('text'))
        
        # Speed
        sx = int(W * 0.76)
        draw_text(surface, fonts, f"{convert_speed(speed)}", sx, H - 90, size=72,
                  color=config.color('speed_white'), bold=True, anchor='midtop')
        draw_text(surface, fonts, speed_label(), sx, H - 18, size=16,
                  color=config.color('text_dim'), anchor='midtop')
        
        # Gear
        draw_gear_indicator(surface, fonts, int(W * 0.88), 180, gear)
        
        # Bars
        bx_t, bx_b, bt, bb = W - 50, W - 24, 60, 280
        draw_vertical_bar(surface, bx_t, bt, 18, bb - bt,
                         throttle, 100, config.color('throttle_green'), "T", fonts)
        draw_vertical_bar(surface, bx_b, bt, 18, bb - bt,
                         brake, 100, config.color('brake_red'), "B", fonts)
        
        draw_warning_panel(surface, fonts, int(W * 0.30), H - 40, 200, 36, data)
        draw_page_dots(surface, W // 2, H - 10, 4, 0)


# ============================================================
# SCREEN: MAIN DASH
# ============================================================

class MainDashScreen:
    NAME = "Main Dash"
    
    def __init__(self):
        self.flash_counter = 0
    
    def draw_arc_gauge(self, surface, cx, cy, radius, rpm, line_width=24):
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
            pygame.draw.line(surface, color, (x1, y1), (x2, y2), 4)
    
    def draw(self, surface, data, fonts):
        W, H = surface.get_size()
        self.flash_counter += 1
        flash_state = (self.flash_counter // 4) % 2 == 0
        
        rpm, speed = data['rpm'], data['speed']
        gear = calculate_gear(speed)
        
        surface.fill(config.color('bg'))
        draw_shift_lights(surface, 8, 6, W - 16, 32, rpm, flash_state)
        
        gcx, gcy, gr = W // 2, H // 2 + 10, 180
        if rpm >= config['engine']['critical_rpm'] and flash_state:
            pygame.draw.circle(surface, (60, 0, 0), (gcx, gcy), gr + 10)
        
        self.draw_arc_gauge(surface, gcx, gcy, gr, rpm)
        draw_gear_indicator(surface, fonts, gcx, gcy - 10, gear)
        
        draw_text(surface, fonts, f"{rpm}", gcx, gcy + 70,
                  size=32, color=rpm_color(rpm), bold=True, anchor='center')
        draw_text(surface, fonts, "RPM", gcx, gcy + 100,
                  size=14, color=config.color('text_dim'), anchor='center')
        
        draw_text(surface, fonts, f"{convert_speed(speed)}", W - 80, H // 2,
                  size=56, color=config.color('speed_white'), bold=True, anchor='center')
        draw_text(surface, fonts, speed_label(), W - 80, H // 2 + 36,
                  size=16, color=config.color('text_dim'), anchor='center')
        
        temp = data['coolant_temp']
        draw_text(surface, fonts, "CLT", 30, H - 70, size=13, color=config.color('text_label'))
        clt_color = config.color('clt_blue')
        if temp >= config['warnings']['coolant_high']:
            clt_color = config.color('warning_red') if flash_state else config.color('rpm_yellow')
        draw_text(surface, fonts, f"{convert_temp(temp)}{temp_label()}", 30, H - 54, size=28, color=clt_color, bold=True)
        
        draw_text(surface, fonts, "OIL", 150, H - 70, size=13, color=config.color('text_label'))
        draw_text(surface, fonts, f"{convert_pressure(data['oil_pressure'])} {pressure_label()}", 150, H - 54,
                  size=28, color=config.color('text'), bold=True)
        
        draw_vertical_bar(surface, 30, 80, 22, 260, data['throttle'], 100,
                         config.color('throttle_green'), "T", fonts)
        draw_vertical_bar(surface, 60, 80, 22, 260, data['brake'], 100,
                         config.color('brake_red'), "B", fonts)
        
        draw_warning_panel(surface, fonts, W // 2 - 100, H - 35, 200, 30, data)
        draw_page_dots(surface, W // 2, H - 10, 4, 1)


# ============================================================
# SCREEN: DIAGNOSTICS
# ============================================================

class DiagnosticScreen:
    NAME = "Diagnostics"
    
    def draw(self, surface, data, fonts):
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
        
        y_info = 260
        pygame.draw.line(surface, config.color('panel_border'), (40, y_info), (W - 40, y_info), 1)
        draw_text(surface, fonts, "SYSTEM", 40, y_info + 10, size=12, color=config.color('text_label'))
        
        ts = data.get('timestamp', 0)
        if ts > 0:
            age_ms = int((time.time() - ts) * 1000)
            draw_text(surface, fonts, f"Data age: {age_ms}ms", 40, y_info + 30,
                      size=16, color=config.color('text'))
        
        draw_text(surface, fonts, f"FPS: {config.get('screen','fps')}  |  "
                  f"Driver: {config.get('driver','name')}  |  "
                  f"Event: {config.get('driver','event')}",
                  40, y_info + 55, size=16, color=config.color('text'))
        
        draw_page_dots(surface, W // 2, H - 10, 4, 2)


# ============================================================
# SCREEN: SETTINGS
# ============================================================

class SettingsScreen:
    NAME = "Settings"
    
    def __init__(self):
        self.page_names = list(SETTINGS_PAGES.keys())
        self.current_page = 0
        self.selected_row = 0
        self.dirty = False
        self.touch_regions = []
    
    def handle_event(self, event):
        """Handle touch/click events. Returns True if consumed."""
        if event.type == pygame.MOUSEBUTTONDOWN:
            mx, my = event.pos
            for region in self.touch_regions:
                if region['rect'].collidepoint(mx, my):
                    self._handle_action(region['action'], region.get('data'))
                    return True
        
        if event.type == pygame.KEYDOWN:
            items = SETTINGS_PAGES[self.page_names[self.current_page]]
            if event.key == pygame.K_UP:
                self.selected_row = (self.selected_row - 1) % len(items)
                return True
            elif event.key == pygame.K_DOWN:
                self.selected_row = (self.selected_row + 1) % len(items)
                return True
            elif event.key == pygame.K_RETURN:
                self._adjust_current(1)
                return True
            elif event.key == pygame.K_BACKSPACE:
                self._adjust_current(-1)
                return True
            elif event.key == pygame.K_TAB:
                self.current_page = (self.current_page + 1) % len(self.page_names)
                self.selected_row = 0
                return True
        
        return False
    
    def _handle_action(self, action, data=None):
        if action == 'tab':
            self.current_page = data
            self.selected_row = 0
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
    
    def _adjust_current(self, direction):
        items = SETTINGS_PAGES[self.page_names[self.current_page]]
        if self.selected_row < len(items):
            self._adjust_value(self.selected_row, direction)
    
    def _adjust_value(self, row_idx, direction):
        items = SETTINGS_PAGES[self.page_names[self.current_page]]
        if row_idx >= len(items):
            return
        section, key, name, typ, vmin, vmax, step = items[row_idx]
        current = config.get(section, key)
        
        if typ == 'int':
            new_val = max(vmin, min(vmax, current + step * direction))
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
    
    def draw(self, surface, data, fonts):
        W, H = surface.get_size()
        surface.fill(config.color('bg'))
        self.touch_regions = []
        
        # ── Title bar ──
        draw_rounded_rect(surface, (0, 0, W, 44), config.color('panel'), radius=0)
        draw_text(surface, fonts, "SETTINGS", 16, 12, size=18,
                  color=config.color('text'), bold=True)
        
        # Unsaved indicator
        if self.dirty:
            draw_text(surface, fonts, "* UNSAVED", W // 2, 13, size=13,
                      color=config.color('warning_red'), anchor='midtop')
        
        # Save button
        save_x = W - 140
        save_color = config.color('accent') if self.dirty else config.color('text_dim')
        draw_rounded_rect(surface, (save_x, 6, 60, 30), config.color('bar_bg'), radius=6)
        draw_text(surface, fonts, "SAVE", save_x + 30, 21, size=14,
                  color=save_color, bold=True, anchor='center')
        self.touch_regions.append({'rect': pygame.Rect(save_x, 6, 60, 30), 'action': 'save'})
        
        # Reset button
        reset_x = W - 70
        draw_rounded_rect(surface, (reset_x, 6, 60, 30), config.color('bar_bg'), radius=6)
        draw_text(surface, fonts, "RESET", reset_x + 30, 21, size=14,
                  color=config.color('text_dim'), anchor='center')
        self.touch_regions.append({'rect': pygame.Rect(reset_x, 6, 60, 30), 'action': 'reset'})
        
        # ── Tab bar ──
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
                      size=13, color=color, bold=is_active, anchor='center')
            self.touch_regions.append({
                'rect': pygame.Rect(tx, tab_y, tab_w, tab_h), 'action': 'tab', 'data': i
            })
        
        # ── Rows ──
        items = SETTINGS_PAGES[self.page_names[self.current_page]]
        row_start = tab_y + tab_h + 12
        row_h, row_gap = 52, 4
        
        for i, (section, key, name, typ, vmin, vmax, step) in enumerate(items):
            ry = row_start + i * (row_h + row_gap)
            if ry + row_h > H - 30:
                break
            
            is_sel = (i == self.selected_row)
            bg = config.color('panel_border') if is_sel else config.color('panel')
            draw_rounded_rect(surface, (12, ry, W - 24, row_h), bg, radius=6)
            
            # Label
            draw_text(surface, fonts, name, 24, ry + row_h // 2,
                      size=16, color=config.color('text'), anchor='midleft')
            
            # Value
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
            
            # < > buttons
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
        
        draw_page_dots(surface, W // 2, H - 10, 4, 3)


# ============================================================
# MAIN APPLICATION
# ============================================================

class RaceDashApp:
    def __init__(self):
        pygame.init()
        
        sc = config['screen']
        flags = 0
        if sc['fullscreen']:
            flags = pygame.FULLSCREEN
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
        self.can_thread = CANThread(self.buffer, simulate=config.get('data', 'simulate'))
        self.sensor_thread = SensorThread(self.buffer, simulate=config.get('data', 'simulate'))
        self.can_thread.start()
        self.sensor_thread.start()
        
        # Screens
        self.settings_screen = SettingsScreen()
        self.screens = [
            LapTimerScreen(),
            MainDashScreen(),
            DiagnosticScreen(),
            self.settings_screen,
        ]
        self.current_screen = 0
        
        self.touch_start_x = None
        self.touch_start_y = None
        self.swipe_threshold = 80
    
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
                continue
            
            # Settings screen consumes its own events
            if isinstance(self.screens[self.current_screen], SettingsScreen):
                if self.settings_screen.handle_event(event):
                    continue
            
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key in (pygame.K_RIGHT, pygame.K_SPACE):
                    self.current_screen = (self.current_screen + 1) % len(self.screens)
                elif event.key == pygame.K_LEFT:
                    self.current_screen = (self.current_screen - 1) % len(self.screens)
                elif event.key == pygame.K_s:
                    self.current_screen = len(self.screens) - 1  # Jump to settings
            
            elif event.type == pygame.MOUSEBUTTONDOWN:
                self.touch_start_x = event.pos[0]
                self.touch_start_y = event.pos[1]
            
            elif event.type == pygame.MOUSEBUTTONUP:
                if self.touch_start_x is not None:
                    dx = event.pos[0] - self.touch_start_x
                    dy = abs(event.pos[1] - self.touch_start_y)
                    if abs(dx) > self.swipe_threshold and dy < 100:
                        if dx < 0:
                            self.current_screen = (self.current_screen + 1) % len(self.screens)
                        else:
                            self.current_screen = (self.current_screen - 1) % len(self.screens)
                    self.touch_start_x = None
                    self.touch_start_y = None
    
    def run(self):
        while self.running:
            self.handle_events()
            data = self.buffer.get_all()
            self.screens[self.current_screen].draw(self.screen, data, self.fonts)
            pygame.display.flip()
            self.clock.tick(config.get('screen', 'fps'))
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