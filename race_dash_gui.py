"""
Race Dash - Kivy GUI
Step 2: Multi-page touchscreen interface with Lap Timer screen
"""

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager, Screen, SlideTransition
from kivy.uix.label import Label
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.graphics import Color, Rectangle, Ellipse, Line
from kivy.clock import Clock
from kivy.core.window import Window
import time

# Import our data acquisition system
from race_dash_core import SignalBuffer, CANThread, SensorThread


class GaugeWidget(FloatLayout):
    """Custom circular gauge for RPM"""
    
    def __init__(self, min_val=0, max_val=13500, **kwargs):
        super().__init__(**kwargs)
        self.min_val = min_val
        self.max_val = max_val
        self.value = 0
        self.flash_background = False
        self.size_hint = (None, None)
        self.size = (525, 525)  # Maximum gauge size
        
    def update_value(self, value, flash=False):
        self.value = value
        self.flash_background = flash
        self.canvas.clear()
        self._draw_gauge()
    
    def _draw_gauge(self):
        with self.canvas:
            # Background circle - flash red when shift time
            if self.flash_background:
                Color(0.6, 0, 0, 1)  # Dark red background
            else:
                Color(0.2, 0.2, 0.2, 1)  # Normal grey background
            Ellipse(pos=self.pos, size=self.size)
            
            # Gauge arc (RPM indicator) - smooth color gradient
            if self.value < 9000:
                r, g, b = 0, 1, 0
            elif self.value < 11000:
                ratio = (self.value - 9000) / 2000.0
                r, g, b = ratio, 1, 0
            elif self.value < 12500:
                ratio = (self.value - 11000) / 1500.0
                r, g, b = 1, 1 - (ratio * 0.5), 0
            else:
                r, g, b = 1, 0, 0
            
            Color(r, g, b, 1)
            
            ratio = min((self.value - self.min_val) / (self.max_val - self.min_val), 1.0)
            angle = -135 + (ratio * 270)
            Line(circle=(self.center_x, self.center_y, 252, -135, angle), width=32)


class RPMArcWidget(FloatLayout):
    """Simple horizontal RPM bar that fills left to right"""
    
    def __init__(self, min_val=0, max_val=13500, **kwargs):
        super().__init__(**kwargs)
        self.min_val = min_val
        self.max_val = max_val
        self.value = 0
        
    def update_value(self, value):
        self.value = value
        self.canvas.clear()
        self._draw_bar()
    
    def _draw_bar(self):
        """Draw a thick horizontal bar that fills based on RPM"""
        with self.canvas:
            # Bar dimensions
            bar_x = self.x + 10
            bar_y = self.y + 5
            bar_width = self.width - 20
            bar_height = self.height - 10
            
            # Draw background bar (dark grey)
            Color(0.25, 0.25, 0.25, 1)
            Rectangle(pos=(bar_x, bar_y), size=(bar_width, bar_height))
            
            # Calculate fill ratio
            ratio = min((self.value - self.min_val) / (self.max_val - self.min_val), 1.0)
            
            # Color based on RPM
            if self.value < 9000:
                r, g, b = 0, 1, 0  # Green
            elif self.value < 11000:
                fade = (self.value - 9000) / 2000.0
                r, g, b = fade, 1, 0  # Green to yellow
            elif self.value < 12500:
                fade = (self.value - 11000) / 1500.0
                r, g, b = 1, 1 - (fade * 0.5), 0  # Yellow to orange
            else:
                r, g, b = 1, 0, 0  # Red
            
            Color(r, g, b, 1)
            
            # Draw filled portion
            fill_width = bar_width * ratio
            Rectangle(pos=(bar_x, bar_y), size=(fill_width, bar_height))


class ShiftLightBar(FloatLayout):
    """Shift light LEDs across top of screen (rectangular)"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (1, 0.08)
        self.pos_hint = {'x': 0, 'top': 1}
        self.num_lights = 10
        
    def update_lights(self, rpm, flash_state):
        """Update shift lights based on RPM"""
        self.canvas.clear()
        
        if rpm < 10000:
            lights_on = 0
            flash_red = False
        elif rpm >= 11250:
            lights_on = self.num_lights
            flash_red = True
        else:
            ratio = (rpm - 10000) / 1250.0
            lights_on = int(ratio * self.num_lights)
            flash_red = False
        
        light_width = self.width / self.num_lights
        light_height = self.height * 0.7
        y_pos = self.y + (self.height - light_height) / 2
        
        light_order = [4, 5, 3, 6, 2, 7, 1, 8, 0, 9]
        
        with self.canvas:
            for i in range(self.num_lights):
                x_pos = self.x + (i * light_width) + (light_width * 0.1)
                width = light_width * 0.8
                
                light_position = light_order.index(i)
                is_on = light_position < lights_on
                
                if flash_red and flash_state:
                    Color(1, 0, 0, 1)
                elif is_on:
                    if light_position < 6:
                        Color(0, 1, 0, 1)
                    elif light_position < 8:
                        Color(1, 1, 0, 1)
                    else:
                        Color(1, 0, 0, 1)
                else:
                    Color(0.3, 0.3, 0.3, 1)
                
                Rectangle(pos=(x_pos, y_pos), size=(width, light_height))


class ShiftLightBarCircular(FloatLayout):
    """Circular shift light LEDs for lap timer layout"""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint = (1, 0.16)
        self.pos_hint = {'x': 0, 'top': 1}
        self.num_lights = 10
        
    def update_lights(self, rpm, flash_state):
        """Update shift lights based on RPM"""
        self.canvas.clear()
        
        if rpm < 10000:
            lights_on = 0
            flash_red = False
        elif rpm >= 11250:
            lights_on = self.num_lights
            flash_red = True
        else:
            ratio = (rpm - 10000) / 1250.0
            lights_on = int(ratio * self.num_lights)
            flash_red = False
        
        light_size = min(self.width / self.num_lights * 0.75, self.height * 0.85)
        spacing = self.width / self.num_lights
        y_pos = self.y + (self.height - light_size) / 2
        
        light_order = [4, 5, 3, 6, 2, 7, 1, 8, 0, 9]
        
        with self.canvas:
            for i in range(self.num_lights):
                x_pos = self.x + (i * spacing) + (spacing - light_size) / 2
                
                light_position = light_order.index(i)
                is_on = light_position < lights_on
                
                if flash_red and flash_state:
                    Color(1, 0, 0, 1)
                elif is_on:
                    if light_position < 6:
                        Color(0, 1, 0, 1)
                    elif light_position < 8:
                        Color(1, 1, 0, 1)
                    else:
                        Color(1, 0, 0, 1)
                else:
                    Color(0.15, 0.15, 0.15, 1)
                
                Ellipse(pos=(x_pos, y_pos), size=(light_size, light_size))


class VerticalBar(FloatLayout):
    """Vertical bar gauge for throttle/brake"""
    
    def __init__(self, color=(0, 1, 0, 1), **kwargs):
        super().__init__(**kwargs)
        self.bar_color = color
        self.value = 0
        
    def update_value(self, value):
        self.value = value
        self.canvas.clear()
        self._draw_bar()
    
    def _draw_bar(self):
        with self.canvas:
            # Background
            Color(0.2, 0.2, 0.2, 1)
            Rectangle(pos=self.pos, size=self.size)
            
            # Fill based on value
            Color(*self.bar_color)
            height = self.height * (self.value / 100.0)
            Rectangle(pos=self.pos, size=(self.width, height))


class LapTimerScreen(Screen):
    """Lap Timer dashboard - matches the sketch layout"""
    
    def __init__(self, signal_buffer, **kwargs):
        super().__init__(**kwargs)
        self.buffer = signal_buffer
        self.flash_counter = 0
        
        # Lap timing data (simulated for now)
        self.current_lap_start = time.time()
        self.best_lap = 65.432  # 1:05.432
        self.last_lap = 67.891  # 1:07.891
        
        layout = FloatLayout()
        
        # ===== TOP: Circular Shift Lights =====
        self.shift_lights = ShiftLightBarCircular()
        layout.add_widget(self.shift_lights)
        
        # ===== LEFT SIDE: RPM Arc + RPM Number + CLT =====
        
        # RPM bar - thick horizontal bar across the top
        self.rpm_arc = RPMArcWidget()
        self.rpm_arc.size_hint = (0.85, 0.176)
        self.rpm_arc.pos_hint = {'x': 0.01, 'top': 0.86}
        layout.add_widget(self.rpm_arc)
        
        # RPM number below arc
        self.rpm_label = Label(
            text='0',
            font_size='48sp',
            bold=True,
            color=(1, 1, 1, 1),
            pos_hint={'x': 0.02, 'center_y': 0.28},
            size_hint=(0.2, 0.1),
            halign='left'
        )
        self.rpm_label.bind(size=self.rpm_label.setter('text_size'))
        layout.add_widget(self.rpm_label)
        
        # CLT (Coolant Temp) bottom left
        self.clt_label = Label(
            text='CLT\n185°F',
            font_size='18sp',
            color=(0.4, 0.8, 1, 1),  # Light blue like sketch
            pos_hint={'x': 0.02, 'y': 0.02},
            size_hint=(0.12, 0.15),
            halign='center'
        )
        layout.add_widget(self.clt_label)
        
        # ===== CENTER: Lap Times + Speed =====
        
        # "Current" label above time
        current_label = Label(
            text='CURRENT',
            font_size='14sp',
            color=(0.6, 0.6, 0.6, 1),
            pos_hint={'center_x': 0.45, 'center_y': 0.58}
        )
        layout.add_widget(current_label)
        
        # Current lap time
        self.current_time_label = Label(
            text='0:00.000',
            font_size='32sp',
            bold=True,
            color=(1, 1, 1, 1),
            pos_hint={'center_x': 0.45, 'center_y': 0.48},
            halign='center'
        )
        layout.add_widget(self.current_time_label)
        
        # Best lap time
        self.best_lap_label = Label(
            text='BEST  1:05.432',
            font_size='20sp',
            color=(0, 1, 0, 1),  # Green for best
            pos_hint={'center_x': 0.45, 'center_y': 0.36},
            halign='center'
        )
        layout.add_widget(self.best_lap_label)
        
        # Last lap time
        self.last_lap_label = Label(
            text='LAST  1:07.891',
            font_size='20sp',
            color=(1, 1, 1, 1),
            pos_hint={'center_x': 0.45, 'center_y': 0.26},
            halign='center'
        )
        layout.add_widget(self.last_lap_label)
        
        # Big MPH display
        self.speed_label = Label(
            text='0',
            font_size='72sp',
            bold=True,
            color=(1, 0.2, 0.2, 1),  # Red like sketch
            pos_hint={'center_x': 0.45, 'center_y': 0.15}
        )
        layout.add_widget(self.speed_label)
        
        # MPH label
        mph_label = Label(
            text='MPH',
            font_size='20sp',
            color=(1, 0.2, 0.2, 1),
            pos_hint={'center_x': 0.45, 'center_y': 0.04}
        )
        layout.add_widget(mph_label)
        
        # ===== RIGHT SIDE: Gear + Throttle/Brake Bars =====
        
        # Big gear indicator (yellow) - larger and positioned upper right
        self.gear_label = Label(
            text='3',
            font_size='220sp',
            bold=True,
            color=(1, 1, 0, 1),  # Yellow like sketch
            pos_hint={'center_x': 0.88, 'center_y': 0.68}
        )
        layout.add_widget(self.gear_label)
        
        # Throttle bar (T) - smaller
        self.throttle_bar = VerticalBar(color=(0, 1, 0, 1))
        self.throttle_bar.size_hint = (0.018, 0.28)
        self.throttle_bar.pos_hint = {'x': 0.92, 'y': 0.25}
        layout.add_widget(self.throttle_bar)
        
        # T label
        t_label = Label(
            text='T',
            font_size='12sp',
            color=(1, 1, 1, 1),
            pos_hint={'x': 0.92, 'y': 0.54},
            size_hint=(0.018, 0.04)
        )
        layout.add_widget(t_label)
        
        # Brake bar (B) - smaller
        self.brake_bar = VerticalBar(color=(1, 0, 0, 1))
        self.brake_bar.size_hint = (0.018, 0.28)
        self.brake_bar.pos_hint = {'x': 0.95, 'y': 0.25}
        layout.add_widget(self.brake_bar)
        
        # B label
        b_label = Label(
            text='B',
            font_size='12sp',
            color=(1, 1, 1, 1),
            pos_hint={'x': 0.95, 'y': 0.54},
            size_hint=(0.018, 0.04)
        )
        layout.add_widget(b_label)
        
        # Swipe hint - moved to bottom right corner
        swipe_hint = Label(
            text='← Swipe →',
            font_size='10sp',
            color=(0.3, 0.3, 0.3, 1),
            pos_hint={'x': 0.88, 'y': 0.01},
            size_hint=(0.12, 0.05)
        )
        layout.add_widget(swipe_hint)
        
        self.add_widget(layout)
        
        # Schedule updates at 30 FPS
        Clock.schedule_interval(self.update_display, 1/30.0)
    
    def format_lap_time(self, seconds):
        """Format seconds into M:SS.mmm"""
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}:{secs:06.3f}"
    
    def update_display(self, dt):
        """Update all display elements with current data"""
        data = self.buffer.get_all()
        
        # Flash counter for shift lights
        self.flash_counter += 1
        flash_state = (self.flash_counter // 5) % 2 == 0
        
        rpm = data['rpm']
        speed = data['speed']
        throttle = data['throttle']
        brake = data['brake']
        temp = data['coolant_temp']
        
        # Update shift lights
        self.shift_lights.update_lights(rpm, flash_state)
        
        # Update RPM arc and label
        self.rpm_arc.update_value(rpm)
        self.rpm_label.text = str(rpm)
        
        # Update CLT
        self.clt_label.text = f"CLT\n{temp}°F"
        
        # Update current lap time (running timer)
        elapsed = time.time() - self.current_lap_start
        self.current_time_label.text = self.format_lap_time(elapsed)
        
        # Simulate lap completion every ~70 seconds for demo
        if elapsed > 70:
            self.last_lap = elapsed
            if elapsed < self.best_lap:
                self.best_lap = elapsed
            self.current_lap_start = time.time()
        
        self.best_lap_label.text = f"BEST  {self.format_lap_time(self.best_lap)}"
        self.last_lap_label.text = f"LAST  {self.format_lap_time(self.last_lap)}"
        
        # Update speed
        self.speed_label.text = str(speed)
        
        # Update gear (simulated based on speed)
        if speed < 15:
            gear = 1
        elif speed < 30:
            gear = 2
        elif speed < 50:
            gear = 3
        elif speed < 70:
            gear = 4
        elif speed < 90:
            gear = 5
        else:
            gear = 6
        self.gear_label.text = str(gear)
        
        # Update throttle/brake bars
        self.throttle_bar.update_value(throttle)
        self.brake_bar.update_value(brake)


class MainDashScreen(Screen):
    """Main dashboard page (original circular gauge layout)"""
    
    def __init__(self, signal_buffer, **kwargs):
        super().__init__(**kwargs)
        self.buffer = signal_buffer
        self.flash_counter = 0
        
        layout = FloatLayout()
        
        # Shift lights at top
        self.shift_lights = ShiftLightBar()
        layout.add_widget(self.shift_lights)
        
        # RPM Gauge (center)
        self.rpm_gauge = GaugeWidget()
        self.rpm_gauge.pos_hint = {'center_x': 0.5, 'center_y': 0.50}
        layout.add_widget(self.rpm_gauge)
        
        # Gear indicator
        self.gear_label = Label(
            text='3',
            font_size='200sp',
            bold=True,
            color=(1, 1, 1, 1),
            outline_color=(0, 0, 0, 1),
            outline_width=8,
            pos_hint={'center_x': 0.5, 'center_y': 0.50}
        )
        layout.add_widget(self.gear_label)
        
        # RPM Value Label
        self.rpm_label = Label(
            text='0 RPM',
            font_size='40sp',
            bold=True,
            pos_hint={'center_x': 0.5, 'center_y': 0.22}
        )
        layout.add_widget(self.rpm_label)
        
        # Speed Display
        self.speed_label = Label(
            text='0\nmph',
            font_size='32sp',
            bold=True,
            halign='center',
            pos_hint={'center_x': 0.85, 'center_y': 0.50}
        )
        layout.add_widget(self.speed_label)
        
        # Coolant Temp Display
        self.temp_label = Label(
            text='CLT\n0°F',
            font_size='16sp',
            halign='center',
            pos_hint={'center_x': 0.85, 'center_y': 0.70}
        )
        layout.add_widget(self.temp_label)
        
        # Throttle Bar
        self.throttle_layout = BoxLayout(
            orientation='vertical',
            size_hint=(0.03, 0.55),
            pos_hint={'x': 0.05, 'center_y': 0.43}
        )
        self.throttle_label = Label(text='THR\n0%', font_size='16sp')
        self.throttle_bar = FloatLayout()
        self.throttle_layout.add_widget(Label(text='T', font_size='14sp', size_hint_y=0.08))
        self.throttle_layout.add_widget(self.throttle_bar)
        self.throttle_layout.add_widget(self.throttle_label)
        layout.add_widget(self.throttle_layout)
        
        # Brake Bar
        self.brake_layout = BoxLayout(
            orientation='vertical',
            size_hint=(0.03, 0.55),
            pos_hint={'x': 0.09, 'center_y': 0.43}
        )
        self.brake_label = Label(text='BRK\n0%', font_size='16sp')
        self.brake_bar = FloatLayout()
        self.brake_layout.add_widget(Label(text='B', font_size='14sp', size_hint_y=0.08))
        self.brake_layout.add_widget(self.brake_bar)
        self.brake_layout.add_widget(self.brake_label)
        layout.add_widget(self.brake_layout)
        
        # Swipe instruction
        swipe_hint = Label(
            text='← Swipe to change pages →',
            font_size='12sp',
            color=(0.4, 0.4, 0.4, 1),
            pos_hint={'center_x': 0.5, 'y': 0.01},
            size_hint=(1, 0.04)
        )
        layout.add_widget(swipe_hint)
        
        self.add_widget(layout)
        Clock.schedule_interval(self.update_display, 1/30.0)
    
    def update_display(self, dt):
        data = self.buffer.get_all()
        
        self.flash_counter += 1
        flash_state = (self.flash_counter // 5) % 2 == 0
        
        rpm = data['rpm']
        self.rpm_label.text = f"{rpm} RPM"
        
        should_flash = rpm >= 11250 and flash_state
        self.rpm_gauge.update_value(rpm, flash=should_flash)
        self.shift_lights.update_lights(rpm, flash_state)
        
        speed = data['speed']
        self.speed_label.text = f"{speed}\nmph"
        
        temp = data['coolant_temp']
        self.temp_label.text = f"CLT\n{temp}°F"
        
        if speed < 15:
            gear = 1
        elif speed < 30:
            gear = 2
        elif speed < 50:
            gear = 3
        elif speed < 70:
            gear = 4
        elif speed < 90:
            gear = 5
        else:
            gear = 6
        self.gear_label.text = str(gear)
        
        throttle = data['throttle']
        self.throttle_label.text = f"THR\n{throttle}%"
        self._draw_bar(self.throttle_bar, throttle, color=(0, 1, 0, 1))
        
        brake = data['brake']
        self.brake_label.text = f"BRK\n{brake}%"
        self._draw_bar(self.brake_bar, brake, color=(1, 0, 0, 1))
    
    def _draw_bar(self, widget, value, color):
        widget.canvas.clear()
        with widget.canvas:
            Color(0.3, 0.3, 0.3, 1)
            Rectangle(pos=widget.pos, size=widget.size)
            Color(*color)
            height = widget.height * (value / 100.0)
            Rectangle(pos=widget.pos, size=(widget.width, height))


class SensorTestScreen(Screen):
    """Sensor test/debug page"""
    
    def __init__(self, signal_buffer, **kwargs):
        super().__init__(**kwargs)
        self.buffer = signal_buffer
        
        layout = BoxLayout(orientation='vertical', padding=20, spacing=10)
        
        layout.add_widget(Label(text='Sensor Test Page', font_size='30sp', size_hint_y=0.1))
        
        self.rpm_label = Label(text='RPM: 0', font_size='24sp')
        self.speed_label = Label(text='Speed: 0 mph', font_size='24sp')
        self.throttle_label = Label(text='Throttle: 0%', font_size='24sp')
        self.brake_label = Label(text='Brake: 0%', font_size='24sp')
        self.temp_label = Label(text='Coolant: 0°F', font_size='24sp')
        self.oil_label = Label(text='Oil Pressure: 0 psi', font_size='24sp')
        
        layout.add_widget(self.rpm_label)
        layout.add_widget(self.speed_label)
        layout.add_widget(self.throttle_label)
        layout.add_widget(self.brake_label)
        layout.add_widget(self.temp_label)
        layout.add_widget(self.oil_label)
        
        layout.add_widget(Label(text='← Swipe to change pages →', 
                               font_size='14sp', 
                               color=(0.5, 0.5, 0.5, 1),
                               size_hint_y=0.1))
        
        self.add_widget(layout)
        Clock.schedule_interval(self.update_display, 1/10.0)
    
    def update_display(self, dt):
        data = self.buffer.get_all()
        self.rpm_label.text = f"RPM: {data['rpm']}"
        self.speed_label.text = f"Speed: {data['speed']} mph"
        self.throttle_label.text = f"Throttle: {data['throttle']}%"
        self.brake_label.text = f"Brake: {data['brake']}%"
        self.temp_label.text = f"Coolant: {data['coolant_temp']}°F"
        self.oil_label.text = f"Oil Pressure: {data['oil_pressure']} psi"


class SettingsScreen(Screen):
    """Settings page for configuring data source"""
    
    def __init__(self, app_ref, **kwargs):
        super().__init__(**kwargs)
        self.app_ref = app_ref
        
        layout = BoxLayout(orientation='vertical', padding=30, spacing=20)
        
        # Title
        layout.add_widget(Label(
            text='SETTINGS', 
            font_size='36sp', 
            bold=True,
            size_hint_y=0.15
        ))
        
        # Data Source Section
        source_layout = BoxLayout(orientation='horizontal', size_hint_y=0.15)
        source_layout.add_widget(Label(
            text='Data Source:', 
            font_size='24sp',
            size_hint_x=0.4
        ))
        
        # Button container
        btn_layout = BoxLayout(orientation='horizontal', spacing=10, size_hint_x=0.6)
        
        self.sim_btn = self._create_button('SIMULATOR', True)
        self.serial_btn = self._create_button('ARDUINO/SERIAL', False)
        
        btn_layout.add_widget(self.sim_btn)
        btn_layout.add_widget(self.serial_btn)
        source_layout.add_widget(btn_layout)
        layout.add_widget(source_layout)
        
        # Serial Port Setting
        port_layout = BoxLayout(orientation='horizontal', size_hint_y=0.12)
        port_layout.add_widget(Label(
            text='Serial Port:', 
            font_size='20sp',
            size_hint_x=0.4
        ))
        self.port_label = Label(
            text='/dev/ttyUSB0',
            font_size='20sp',
            color=(0.5, 1, 0.5, 1),
            size_hint_x=0.6
        )
        port_layout.add_widget(self.port_label)
        layout.add_widget(port_layout)
        
        # Port selection buttons
        port_btn_layout = BoxLayout(orientation='horizontal', spacing=10, size_hint_y=0.12)
        for port in ['/dev/ttyUSB0', '/dev/ttyUSB1', '/dev/ttyACM0', '/dev/ttyACM1']:
            btn = self._create_port_button(port)
            port_btn_layout.add_widget(btn)
        layout.add_widget(port_btn_layout)
        
        # Baud Rate
        baud_layout = BoxLayout(orientation='horizontal', size_hint_y=0.12)
        baud_layout.add_widget(Label(
            text='Baud Rate:', 
            font_size='20sp',
            size_hint_x=0.4
        ))
        self.baud_label = Label(
            text='115200',
            font_size='20sp',
            color=(0.5, 1, 0.5, 1),
            size_hint_x=0.6
        )
        baud_layout.add_widget(self.baud_label)
        layout.add_widget(baud_layout)
        
        # Status
        self.status_label = Label(
            text='Status: Running in SIMULATOR mode',
            font_size='18sp',
            color=(0, 1, 0, 1),
            size_hint_y=0.12
        )
        layout.add_widget(self.status_label)
        
        # Apply button
        apply_btn = self._create_apply_button()
        layout.add_widget(apply_btn)
        
        # Swipe hint
        layout.add_widget(Label(
            text='← Swipe to change pages →', 
            font_size='14sp', 
            color=(0.5, 0.5, 0.5, 1),
            size_hint_y=0.08
        ))
        
        self.add_widget(layout)
        self._update_button_states()
    
    def _create_button(self, text, is_sim):
        from kivy.uix.button import Button
        btn = Button(
            text=text,
            font_size='18sp',
            background_color=(0.3, 0.3, 0.3, 1)
        )
        btn.bind(on_press=lambda x: self._select_source(is_sim))
        return btn
    
    def _create_port_button(self, port):
        from kivy.uix.button import Button
        btn = Button(
            text=port.split('/')[-1],  # Show just ttyUSB0 etc
            font_size='14sp',
            background_color=(0.3, 0.3, 0.3, 1)
        )
        btn.bind(on_press=lambda x: self._select_port(port))
        return btn
    
    def _create_apply_button(self):
        from kivy.uix.button import Button
        btn = Button(
            text='APPLY & RESTART DATA SOURCE',
            font_size='20sp',
            background_color=(0.2, 0.5, 0.2, 1),
            size_hint_y=0.15
        )
        btn.bind(on_press=lambda x: self._apply_settings())
        return btn
    
    def _select_source(self, is_sim):
        self.app_ref.simulate = is_sim
        self._update_button_states()
    
    def _select_port(self, port):
        self.app_ref.serial_port = port
        self.port_label.text = port
    
    def _update_button_states(self):
        if self.app_ref.simulate:
            self.sim_btn.background_color = (0, 0.6, 0, 1)
            self.serial_btn.background_color = (0.3, 0.3, 0.3, 1)
            self.status_label.text = 'Mode: SIMULATOR (test data)'
            self.status_label.color = (0, 1, 0, 1)
        else:
            self.sim_btn.background_color = (0.3, 0.3, 0.3, 1)
            self.serial_btn.background_color = (0, 0.6, 0, 1)
            self.status_label.text = f'Mode: SERIAL ({self.app_ref.serial_port})'
            self.status_label.color = (1, 1, 0, 1)
    
    def _apply_settings(self):
        """Stop current thread and restart with new settings"""
        # Stop existing thread
        self.app_ref.can_thread.stop()
        self.app_ref.can_thread.join(timeout=0.5)
        
        # Create and start new thread with current settings
        self.app_ref.can_thread = CANThread(
            self.app_ref.signal_buffer,
            simulate=self.app_ref.simulate,
            serial_port=self.app_ref.serial_port,
            baud_rate=int(self.baud_label.text)
        )
        self.app_ref.can_thread.start()
        
        # Update status
        if self.app_ref.simulate:
            self.status_label.text = 'Status: Restarted in SIMULATOR mode'
            self.status_label.color = (0, 1, 0, 1)
        else:
            self.status_label.text = f'Status: Connected to {self.app_ref.serial_port}'
            self.status_label.color = (0, 1, 0, 1)


class RaceDashApp(App):
    """Main Kivy Application"""
    
    # Class-level config (set from command line)
    simulate = True
    serial_port = '/dev/ttyUSB0'
    baud_rate = 115200
    
    def build(self):
        # Set window size for PC testing (7" screen is 800x480)
        Window.size = (800, 480)
        
        # Create signal buffer and start threads
        self.signal_buffer = SignalBuffer()
        self.can_thread = CANThread(
            self.signal_buffer, 
            simulate=self.simulate,
            serial_port=self.serial_port,
            baud_rate=self.baud_rate
        )
        self.sensor_thread = SensorThread(self.signal_buffer, simulate=True)
        
        self.can_thread.start()
        self.sensor_thread.start()
        
        # Create screen manager
        sm = ScreenManager(transition=SlideTransition())
        
        # Add screens - Lap Timer is now the first/default screen
        sm.add_widget(LapTimerScreen(self.signal_buffer, name='laptimer'))
        sm.add_widget(MainDashScreen(self.signal_buffer, name='main'))
        sm.add_widget(SensorTestScreen(self.signal_buffer, name='sensors'))
        sm.add_widget(SettingsScreen(self, name='settings'))
        
        # Bind touch for swipe gestures
        Window.bind(on_touch_down=self.on_touch_down)
        Window.bind(on_touch_up=self.on_touch_up)
        
        self.sm = sm
        self.touch_start_x = 0
        
        return sm
    
    def on_touch_down(self, instance, touch):
        self.touch_start_x = touch.x
    
    def on_touch_up(self, instance, touch):
        swipe_distance = touch.x - self.touch_start_x
        
        if abs(swipe_distance) > 100:
            screens = ['laptimer', 'main', 'sensors', 'settings']
            current_idx = screens.index(self.sm.current)
            
            if swipe_distance > 0:
                # Swipe right - go to previous screen
                new_idx = (current_idx - 1) % len(screens)
                self.sm.transition.direction = 'right'
            else:
                # Swipe left - go to next screen
                new_idx = (current_idx + 1) % len(screens)
                self.sm.transition.direction = 'left'
            
            self.sm.current = screens[new_idx]
    
    def on_stop(self):
        """Clean shutdown - stop threads and wait for them to finish"""
        print("Shutting down...")
        self.can_thread.stop()
        self.sensor_thread.stop()
        # Wait for threads to finish (with timeout)
        self.can_thread.join(timeout=0.5)
        self.sensor_thread.join(timeout=0.5)
        print("Shutdown complete")


if __name__ == '__main__':
    import sys
    
    # Parse command line arguments
    # Usage: python race_dash_gui.py [--serial /dev/ttyUSB0] [--baud 115200]
    simulate = True
    serial_port = '/dev/ttyUSB0'
    baud_rate = 115200
    
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == '--serial':
            simulate = False
            if i + 1 < len(args) and not args[i + 1].startswith('--'):
                serial_port = args[i + 1]
                i += 1
        elif args[i] == '--baud':
            if i + 1 < len(args):
                baud_rate = int(args[i + 1])
                i += 1
        elif args[i] == '--simulate':
            simulate = True
        i += 1
    
    if not simulate:
        print(f"Running with Arduino serial input on {serial_port} at {baud_rate} baud")
    else:
        print("Running in simulation mode")
    
    # Store config for the app to use
    RaceDashApp.simulate = simulate
    RaceDashApp.serial_port = serial_port
    RaceDashApp.baud_rate = baud_rate
    
    RaceDashApp().run()