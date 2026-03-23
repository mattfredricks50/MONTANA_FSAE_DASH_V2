# FSAE Race Dashboard — Hardware Setup Checklist

> Open this in VS Code and check off items as you go: change `[ ]` to `[x]`
>
> **Read the whole section before soldering anything.**

---

## 1. Tools & Supplies You'll Need

- [ ] Soldering iron + solder (fine tip for headers)
- [ ] Flush cutters, wire strippers
- [ ] Multimeter (continuity, voltage checks)
- [ ] Dupont jumper wires (female-to-female, male-to-female)
- [ ] 22-24 AWG hookup wire (solid core for breadboard, stranded for car)
- [ ] Breadboard (for bench testing before soldering permanent board)
- [ ] Micro USB cables (one for Pi power, one for STM32 programming)
- [ ] MicroSD card (16GB, FAT32 formatted)
- [ ] HDMI cable (mini HDMI for Pi Zero 2W → your 7" display)
- [ ] Header pins (if your STM32 board doesn't have them pre-soldered)
- [ ] Heat shrink tubing or electrical tape
- [ ] Zip ties / cable management for the car

---

## 2. Component Inventory

Verify you have all parts before starting:

| # | Component | Check |
|---|-----------|-------|
| 1 | STM32F103RCT6 board (Blue Pill+ or equivalent) | [ ] |
| 2 | Raspberry Pi Zero 2W | [ ] |
| 3 | 7" 800×480 HDMI LCD display | [ ] |
| 4 | SN65HVD230 CAN transceiver module | [ ] |
| 5 | u-blox NEO-6M or NEO-7M GPS module | [ ] |
| 6 | MPU-6050 breakout board (I2C) | [ ] |
| 7 | MicroSD card module (SPI, 3.3V) | [ ] |
| 8 | nRF24L01+PA+LNA module | [ ] |
| 9 | 5V buck converter (12V car battery → 5V) | [ ] |
| 10 | Brake pressure sensor (100 PSI, 0.5–4.5V) | [ ] |
| 11 | Steering angle potentiometer | [ ] |
| 12 | Clutch switch (normally open, closes to GND) | [ ] |
| 13 | LM393 comparator DIP-8 (VSS signal conditioning) | [ ] |
| 14 | MicroSD card (16GB, FAT32) | [ ] |
| 14 | 120Ω resistor ×2 (CAN termination) | [ ] |
| 15 | 10KΩ resistor ×2 (voltage divider for 5V sensors) | [ ] |
| 16 | 20KΩ resistor ×2 (voltage divider for 5V sensors) | [ ] |

---

## 3. Raspberry Pi Zero 2W Setup

Do this first — it takes the longest and doesn't need any other hardware.

### 3.1 Flash the OS

- [ ] Download **Raspberry Pi OS Lite (64-bit)** from https://www.raspberrypi.com/software/
- [ ] Flash to MicroSD using Raspberry Pi Imager
  - In the imager settings (gear icon), configure:
  - [ ] Set hostname: `racedash`
  - [ ] Enable SSH (password authentication)
  - [ ] Set username: `pi`, password: (your choice)
  - [ ] Configure WiFi (your phone hotspot or shop WiFi — needed for setup only)
  - [ ] Set locale/timezone
- [ ] Insert MicroSD into Pi, power on, wait ~90 seconds for first boot
- [ ] SSH in: `ssh pi@racedash.local`

### 3.2 System Configuration

```bash
# Update everything
sudo apt update && sudo apt upgrade -y

# Install dependencies
sudo apt install -y python3-pygame python3-serial git

# Disable serial console (frees /dev/ttyAMA0 for our UART data)
sudo raspi-config
#   → Interface Options
#   → Serial Port
#   → "Would you like a login shell over serial?" → NO
#   → "Would you like the serial port hardware enabled?" → YES
#   → Finish → Reboot

# Verify serial is free after reboot
ls -la /dev/ttyAMA0
# Should show the device with no getty process using it
```

- [ ] OS flashed and first boot complete
- [ ] SSH access working
- [ ] `apt update && upgrade` done
- [ ] `python3-pygame` and `python3-serial` installed
- [ ] Serial console disabled, hardware serial enabled
- [ ] Rebooted after raspi-config changes

### 3.3 Deploy Dashboard Code

```bash
# Create project directory
mkdir -p /home/pi/dash
cd /home/pi/dash

# Copy the three Python files here (via scp, USB stick, or git):
#   race_dash_config.py
#   race_dash_core.py
#   race_dash_pygame.py

# Test that it runs (will start in sim mode with no STM32 connected)
python3 race_dash_pygame.py
# You should see the dashboard on the HDMI display
# Press Escape to quit
```

- [ ] Dashboard files copied to `/home/pi/dash/`
- [ ] Test run successful (sim mode shows moving gauges)

### 3.4 Auto-Start on Boot

```bash
# Edit rc.local to start the dash automatically
sudo nano /etc/rc.local

# Add this line BEFORE "exit 0":
cd /home/pi/dash && python3 race_dash_pygame.py &

# Save and exit (Ctrl+O, Enter, Ctrl+X)
```

- [ ] rc.local edited
- [ ] Verified: reboot and dash appears automatically

### 3.5 Boot Speed Optimization (Optional)

```bash
# Disable services we don't need on the car
sudo systemctl disable bluetooth
sudo systemctl disable hciuart
sudo systemctl disable avahi-daemon
sudo systemctl disable triggerhappy
sudo systemctl disable wpa_supplicant  # ONLY if you won't need WiFi anymore

# Add to /boot/firmware/config.txt:
sudo nano /boot/firmware/config.txt
# Add these lines at the bottom:
boot_delay=0
disable_splash=1
dtoverlay=disable-wifi      # Remove this line if you still want WiFi
dtoverlay=disable-bt

# Add to /boot/firmware/cmdline.txt:
# Append to the existing single line (don't create a new line):
quiet fastboot
```

- [ ] Unnecessary services disabled
- [ ] config.txt boot optimizations added
- [ ] cmdline.txt quiet/fastboot added
- [ ] Tested: boot to dashboard in ~10-15 seconds

---

## 4. STM32 Development Environment

Do this on your **laptop/desktop** (not the Pi).

### 4.1 Install PlatformIO

- [ ] Install VS Code: https://code.visualstudio.com/
- [ ] Install the **PlatformIO IDE** extension from the Extensions marketplace
- [ ] Restart VS Code after installation
- [ ] Open the `stm32_firmware/` folder in VS Code
- [ ] Wait for PlatformIO to download the STM32 toolchain (first time takes a few minutes)
- [ ] Build: `Ctrl+Alt+B` (or click the checkmark in the bottom toolbar)
- [ ] Build should succeed with no errors

### 4.2 First Flash (USB DFU — No Programmer Needed)

Before wiring anything, verify the STM32 board works:

```
1. Set the BOOT0 jumper to HIGH (1) on the STM32 board
2. Plug the STM32's USB into your computer
3. The board should enumerate as a DFU device
```

```bash
# In VS Code / PlatformIO terminal:
pio run -t upload --upload-port /dev/ttyUSB0
# Or on Windows: pio run -t upload --upload-port COM3

# If DFU doesn't work, your board may need the USB pull-up fix:
# Solder a 1.5KΩ resistor between PA12 and 3.3V
# (many cheap boards have 10KΩ here instead — wrong value)
```

- [ ] PlatformIO installed and STM32 toolchain downloaded
- [ ] Firmware compiles successfully
- [ ] STM32 board flashed via USB DFU (LED should blink)
- [ ] Set BOOT0 back to LOW (0) after flashing

---

## 5. Wiring — Bench Test Phase

**Do all bench wiring on a breadboard first.** Don't solder permanent connections until everything works.

**IMPORTANT: The STM32F103 is 3.3V logic. Never connect 5V directly to any STM32 pin.**

### 5.1 STM32 → Pi (UART Data Link)

This is the most important connection — it's how the dash gets data.

```
STM32 PA9  (UART1 TX) ──────→ Pi GPIO15 (RX)
STM32 GND  ──────────────────→ Pi GND

Optional (not used yet):
STM32 PA10 (UART1 RX) ←────── Pi GPIO14 (TX)

Pi-controlled flashing (allows firmware updates from the dash settings screen):
Pi GPIO17 (pin 11) ──────────→ STM32 BOOT0   (HIGH = bootloader mode)
Pi GPIO27 (pin 13) ──────────→ STM32 NRST    (pulse LOW to reset)
```

**No pull-ups needed.** UART idles high, and both devices are 3.3V. BOOT0 and NRST are active-driven by the Pi.

- [ ] PA9 → GPIO15 wired
- [ ] GND → GND wired
- [ ] GPIO17 → BOOT0 wired
- [ ] GPIO27 → NRST wired
- [ ] **TEST:** Power both on. Pi should show data in `python3 -c "import serial; s=serial.Serial('/dev/ttyAMA0', 115200, timeout=1); [print(s.readline()) for _ in range(10)]"`
  - With PB0 floating (live mode), you'll see `# Ready` then lines of zeros
  - With PB0 pulled LOW (sim mode), you'll see CSV data streaming

### 5.2 GPS Module (u-blox NEO-6M/7M)

```
GPS VCC ────→ STM32 3.3V
GPS GND ────→ STM32 GND
GPS TX  ────→ STM32 PA3  (UART2 RX)
GPS RX  ────→ STM32 PA2  (UART2 TX)
```

**No pull-ups needed.** The GPS module has its own pull-ups on the UART lines.

> **Antenna:** The ceramic patch antenna must face the sky. On a bench, put it near a window. In the car, mount it on top of the bodywork or behind a fiberglass panel (not carbon fiber — it blocks GPS signals).

- [ ] GPS VCC/GND connected to 3.3V and GND
- [ ] GPS TX → PA3, GPS RX → PA2
- [ ] **TEST:** In sim mode off (PB0 floating), watch serial output. After 30-60 seconds outdoors, you should see non-zero lat/lon values in the CSV.

### 5.3 MPU-6050 IMU (Accelerometer/Gyroscope)

```
MPU VCC ────→ STM32 3.3V
MPU GND ────→ STM32 GND
MPU SCL ────→ STM32 PB6  (I2C1 SCL)
MPU SDA ────→ STM32 PB7  (I2C1 SDA)
MPU AD0 ────→ GND         (sets I2C address to 0x68)
```

**Pull-ups: Most MPU-6050 breakout boards have 4.7KΩ pull-ups to VCC on SDA and SCL already.** Check your board — if it has two resistors near the I2C pins, you're good. If not, add **4.7KΩ pull-ups from SDA to 3.3V and SCL to 3.3V**.

> **INT pin:** Leave unconnected. We poll the sensor, we don't use interrupts.

- [ ] MPU wired: VCC, GND, SCL→PB6, SDA→PB7, AD0→GND
- [ ] Verified pull-ups exist on breakout board (or added 4.7KΩ)
- [ ] **TEST:** Boot STM32, serial output should show `# IMU MPU-6050 OK`. If it says `# IMU not found on I2C`, check wiring and pull-ups.

### 5.4 SD Card Module

```
SD VCC  ────→ STM32 3.3V   (USE 3.3V MODULE — not 5V!)
SD GND  ────→ STM32 GND
SD SCK  ────→ STM32 PA5    (SPI1 SCK)
SD MISO ────→ STM32 PA6    (SPI1 MISO)
SD MOSI ────→ STM32 PA7    (SPI1 MOSI)
SD CS   ────→ STM32 PA4    (SPI1 CS)
```

**No pull-ups needed on SPI.** The SD module handles this.

> **WARNING:** Many cheap SD modules are 5V with a voltage regulator. If yours has a regulator and you feed it 3.3V, it won't work — the regulator drops ~1V so the SD card only sees 2.3V. Use a **3.3V native** module (like Adafruit 4682) or bypass the regulator.

- [ ] SD module wired (3.3V native module confirmed)
- [ ] FAT32-formatted MicroSD card inserted
- [ ] **TEST:** Boot STM32, serial should show `# Logging to: LOG_001.csv`. Power off, pull the SD card, check on a computer — you should see the CSV file with data rows.

### 5.5 Clutch Switch

```
Clutch switch wire A ────→ STM32 PB8
Clutch switch wire B ────→ GND
```

**Pull-up: PB8 uses the internal pull-up (configured in firmware).** No external resistor needed. When the clutch lever is pulled, the switch closes, PB8 goes LOW, firmware reads `clutch_in = true`.

> If your switch is normally closed (closes when clutch is released), swap the logic in firmware: change `current_data.clutch_in = (digitalRead(CLUTCH_PIN) == LOW)` to `== HIGH`.

- [ ] Clutch switch wired: one terminal to PB8, other to GND
- [ ] **TEST:** Watch serial output. Gear should show `0` (displays as N) when you short PB8 to GND (simulating clutch pull). Should show `1-6` when PB8 is floating and RPM/speed are present.

### 5.6 Simulation Mode Jumper

```
To enable sim mode (for bench testing without the car):
PB0 ────→ GND      (jumper wire or switch)

For live mode (real sensors):
PB0 ────→ floating  (internal pull-up holds it HIGH)
```

**Pull-up: Internal (configured in firmware).** No external resistor needed.

- [ ] Sim jumper accessible on the board
- [ ] **TEST:** Boot with PB0→GND, serial shows `# Mode: SIMULATION` and data sweeps through gears 1→6. Boot with PB0 floating, shows `# Mode: LIVE SENSORS`.

### 5.7 CAN Bus (Speeduino Dropbear v2)

```
STM32 PA11 ────→ SN65HVD230 "R" (RX/receive)
STM32 PA12 ────→ SN65HVD230 "D" (TX/transmit)
STM32 3.3V ────→ SN65HVD230 VCC
STM32 GND  ────→ SN65HVD230 GND

SN65HVD230 CANH ────→ Speeduino CAN_H
SN65HVD230 CANL ────→ Speeduino CAN_L

120Ω termination resistor across CANH and CANL at EACH end of the bus
(one at the Speeduino, one at the transceiver module)
```

**Pull-ups: None needed.** The CAN transceiver handles bus levels. The SN65HVD230 "Rs" (slope control) pin should be tied to GND for maximum speed.

> **NOTE:** CAN decoding is not yet implemented in firmware (marked TODO). The wiring is ready but you won't see real engine data until the eXoCAN code is added. All other sensors work independently of CAN.

- [ ] CAN transceiver wired to PA11/PA12
- [ ] CANH/CANL connected to Speeduino with twisted pair wire
- [ ] 120Ω termination at both ends
- [ ] Rs pin on SN65HVD230 tied to GND

### 5.8 Vehicle Speed Sensor (VSS) — Reluctor Pickup

The CBR 600RR speed sensor is a **passive reluctor** (magnetic pickup) that reads 28 teeth on the countershaft 3rd gear inside the engine case. It outputs a low-voltage AC sine wave whose frequency is proportional to speed. **This signal cannot be connected directly to the STM32** — it needs a comparator circuit to convert it to a clean 3.3V digital square wave.

**Signal conditioning circuit (LM393 comparator):**

```
                            3.3V
                             │
                            4.7KΩ  (pull-up on output)
                             │
VSS reluctor wire A ──┬── LM393 IN+ (pin 3)     LM393 OUT (pin 1) ──→ STM32 PB3
                      │                                │
                     10KΩ (bias to midpoint)           │
                      │                          (open collector,
VSS reluctor wire B ──┴── LM393 IN- (pin 2)      pulled high by 4.7K)
                      │
                     10KΩ
                      │
                     GND

LM393 power:
  VCC (pin 8) ──→ 3.3V
  GND (pin 4) ──→ GND

Optional: 100pF cap from IN+ to GND (noise filter on long wire runs)
Optional: 100KΩ feedback from OUT to IN+ (hysteresis, prevents chatter)
```

**How it works:** The reluctor outputs a sine wave centered around 0V. The two 10KΩ resistors bias the negative input to a virtual ground (midpoint). When the sine wave swings positive (tooth passing), the comparator output goes LOW; when negative (gap), it goes HIGH. The 4.7KΩ pull-up creates a clean 3.3V square wave. The STM32 counts rising edges via interrupt.

**Alternative — if the Speeduino already conditions the VSS signal:** If the Speeduino's wiring harness provides a clean 5V square wave VSS output, you can skip the LM393 and just use a simple voltage divider (10KΩ + 20KΩ) to step it down to 3.3V for PB3.

> **Parts needed:** LM393 comparator (DIP-8, ~$0.50), 2× 10KΩ, 1× 4.7KΩ, optional 100pF cap and 100KΩ for hysteresis.

- [ ] LM393 comparator circuit built on breadboard
- [ ] Verify output with multimeter or oscilloscope: 0V/3.3V square wave when spinning the wheel
- [ ] Comparator output → STM32 PB3
- [ ] **TEST:** Spin the front wheel by hand. Watch serial output — `speed_mph` should show a low value (1-5 mph). Faster spin = higher reading. Stopped wheel = 0.

### 5.9 Analog Sensors (Brake Pressure / Steering Angle)

**5V sensors need a voltage divider to bring the signal down to 3.3V max for the STM32 ADC.**

```
Voltage divider for each 5V sensor:

Sensor output ──┬── 10KΩ ──→ STM32 analog pin (PA0 or PA1)
                │
               20KΩ
                │
               GND

This divides by 3: 5V × (20K / (10K+20K)) = 3.33V max at the STM32 pin.
The ADC reads 0-4095 for 0-3.3V.
```

```
Brake pressure sensor (3-wire, 5V):
  Red   ────→ 5V supply
  Black ────→ GND
  White ────→ voltage divider → PA0

Steering angle pot (3-wire, 5V):
  One end   ────→ 5V supply
  Other end ────→ GND
  Wiper     ────→ voltage divider → PA1
```

- [ ] Voltage dividers built and tested with multimeter (confirm <3.3V at STM32 pin when sensor outputs 5V)
- [ ] Brake sensor → divider → PA0
- [ ] Steering pot → divider → PA1
- [ ] **TEST:** Watch `analog_0_raw` and `analog_1_raw` in the SD log. Should vary 0-4095 as you apply pressure / turn the pot.

### 5.10 nRF24L01+ Telemetry (Wire Now, Enable Later)

```
nRF VCC  ────→ STM32 3.3V   (⚠ 3.3V ONLY — 5V will destroy it!)
nRF GND  ────→ STM32 GND
nRF SCK  ────→ STM32 PB13   (SPI2 SCK)
nRF MISO ────→ STM32 PB14   (SPI2 MISO)
nRF MOSI ────→ STM32 PB15   (SPI2 MOSI)
nRF CSN  ────→ STM32 PB12   (SPI2 CS)
nRF CE   ────→ STM32 PB1
nRF IRQ  ────→ not connected (unused)
```

**⚠ CRITICAL: Add a 10µF electrolytic capacitor across VCC and GND right at the nRF24 module.** The PA+LNA version draws high current spikes during transmit that can brown-out the 3.3V rail and crash the STM32. Solder the cap directly to the module's power pins.

> **NOTE:** nRF24 code is not yet implemented (marked TODO in firmware). Wire it now so it's ready when the software is added. The module will simply be unpowered/idle until then.

- [ ] nRF24 wired to SPI2 pins
- [ ] 10µF capacitor across VCC/GND at the module
- [ ] **Confirmed:** VCC is 3.3V, NOT 5V

### 5.11 Screen Cycle Button (Pi GPIO)

A single momentary push button wired directly to the Pi for cycling through screens with gloves on. No STM32 involvement.

```
Button terminal A ────→ Pi GPIO16 (pin 36)
Button terminal B ────→ Pi GND    (pin 34 or any GND)
```

**Pull-up: Internal (configured in software).** No external resistor needed. GPIO16 is held HIGH by the Pi's internal pull-up. Pressing the button pulls it LOW, the software detects the falling edge and advances to the next screen. 200ms debounce is built in.

**Any momentary NO (normally open) push button works.** A waterproof panel-mount button is ideal for the car. If you only have an NC (normally closed) button, just swap the logic in the code: change `if state == False` to `if state == True`.

> **Why GPIO16?** It's on the outer edge of the Pi header (pin 36), easy to solder one wire to. It's not used by UART, I2C, SPI, or any other peripheral. Any free GPIO would work — just change `self.btn_pin` in `race_dash_pygame.py`.

- [ ] Button wired: one terminal to GPIO16 (pin 36), other to GND (pin 34)
- [ ] **TEST:** Run dashboard, press button — screen should advance. Press again — next screen. Cycles through all enabled screens plus settings.

---

## 6. Bench Integration Test

With everything wired on the breadboard, run through this full system test:

### 6.1 Simulation Mode Test

- [ ] Connect PB0 to GND (sim mode)
- [ ] Power on STM32 and Pi
- [ ] Wait for Pi to boot (~15-20s)
- [ ] Dashboard appears with data cycling through all 6 gears
- [ ] Gear display shows 1→2→3→4→5→6 then back down
- [ ] "N" flashes briefly during each shift
- [ ] Speed increases with each gear, matches RPM
- [ ] G-force screen shows moving dot and trace history
- [ ] C4 Corvette screen shows sweeping bars
- [ ] Pull SD card — verify LOG_001.csv has data rows with all columns

### 6.2 Live Mode Test (Without CAN)

- [ ] Disconnect PB0 from GND (live mode)
- [ ] Power on both boards
- [ ] Dashboard shows zeros (no CAN data yet, which is expected)
- [ ] If GPS has sky view: lat/lon should populate after 30-60s
- [ ] If MPU-6050 is wired: tilt the breadboard, accel values should change on the G-force screen
- [ ] Clutch: short PB8 to GND, gear should show "N"

### 6.3 Pi → STM32 Flashing Test

Verify you can flash the STM32 from the Pi (for in-car updates).

**Automated (from dashboard):** Go to Settings → Update tab → press "FLASH STM32".
The Pi controls BOOT0 and NRST via GPIO17/GPIO27 automatically — no jumper changes needed.

**Manual (command line):**

```bash
# On the Pi:
sudo apt install -y stm32flash

# The Pi controls BOOT0 (GPIO17) and NRST (GPIO27) automatically,
# but if testing manually, you can set BOOT0 HIGH and reset:
#   gpio -g write 17 1 && gpio -g write 27 0 && sleep 0.1 && gpio -g write 27 1

# Flash:
stm32flash -w /home/pi/dash/firmware.bin -v -g 0x0 /dev/ttyAMA0

# Return to normal mode:
#   gpio -g write 17 0 && gpio -g write 27 0 && sleep 0.1 && gpio -g write 27 1
```

- [ ] `stm32flash` installed on Pi (`sudo apt install -y stm32flash`)
- [ ] GPIO17 → BOOT0 and GPIO27 → NRST wired
- [ ] Place `firmware.bin` in `/home/pi/dash/` (copy from PlatformIO build: `.pio/build/genericSTM32F103RC/firmware.bin`)
- [ ] Successfully flashed STM32 from Settings → Update → FLASH STM32
- [ ] STM32 runs new firmware after automatic reset

---

## 7. Car Installation

Only after bench testing is 100% working.

### 7.1 Power

```
Car 12V battery ──→ 5V buck converter ──┬──→ Pi 5V (via USB or GPIO pin 2/4)
                                         ├──→ STM32 5V pin (board has its own 3.3V regulator)
                                         └──→ 5V sensor supply (brake, steering)

⚠ Add a 1A fuse between the battery and buck converter
⚠ Use a common ground point — all GND wires star-grounded to one spot
⚠ Keep power wires away from CAN/UART signal wires (noise!)
```

- [ ] Buck converter mounted, outputting clean 5V (verify with multimeter)
- [ ] Fuse installed
- [ ] Star ground point established
- [ ] Pi and STM32 power up cleanly from car battery

### 7.2 Mounting

- [ ] Display mounted in driver's line of sight (consider sun glare)
- [ ] Pi mounted behind display (ventilation — it runs hot at 100% CPU)
- [ ] STM32 + CAN transceiver mounted near the wiring harness
- [ ] MPU-6050 mounted flat, near center of gravity, screwed down solid (vibration = noise)
- [ ] GPS antenna facing sky (top of chassis, not under carbon fiber)
- [ ] SD card accessible for removal between sessions
- [ ] Clutch switch mounted on clutch lever/perch
- [ ] All connectors strain-relieved and secured with zip ties

### 7.3 Wire Routing

- [ ] CAN bus (CANH/CANL) is twisted pair, separate from power wires
- [ ] UART line (PA9→GPIO15) kept short and away from ignition coils
- [ ] Analog sensor wires (brake, steering) shielded or routed away from spark plug wires
- [ ] All wires secured — nothing hanging near exhaust, chain, or suspension

---

## 8. Quick Reference — Complete Pin Map

```
STM32F103RCT6 Pin Assignments
═══════════════════════════════════════════════════════════

PA0  ── Analog 0 (brake pressure, through voltage divider)
PA1  ── Analog 1 (steering angle, through voltage divider)
PA2  ── UART2 TX → GPS RX
PA3  ── UART2 RX ← GPS TX
PA4  ── SPI1 CS  → SD card CS
PA5  ── SPI1 SCK → SD card SCK
PA6  ── SPI1 MISO ← SD card MISO
PA7  ── SPI1 MOSI → SD card MOSI
PA9  ── UART1 TX → Pi GPIO15 (RX)   ★ Main data link
PA10 ── UART1 RX ← Pi GPIO14 (TX)   (reserved, unused)
PA11 ── CAN RX ← SN65HVD230 R
PA12 ── CAN TX → SN65HVD230 D

PB0  ── Sim mode jumper (LOW = sim, internal pull-up)
PB1  ── nRF24 CE
PB3  ── VSS pulse input (from LM393 comparator, rising edge interrupt)
PB6  ── I2C1 SCL → MPU-6050 SCL
PB7  ── I2C1 SDA → MPU-6050 SDA
PB8  ── Clutch switch (LOW = clutch in, internal pull-up)
PB12 ── SPI2 CSN → nRF24 CSN
PB13 ── SPI2 SCK → nRF24 SCK
PB14 ── SPI2 MISO ← nRF24 MISO
PB15 ── SPI2 MOSI → nRF24 MOSI

PC13 ── Onboard LED (active low)

Pi Zero 2W GPIO:
  GPIO14 (TX)  → STM32 PA10 (RX)    (reserved)
  GPIO15 (RX)  ← STM32 PA9 (TX)     ★ Main data link
  GPIO16       ← Screen cycle button (to GND, internal pull-up)
  GPIO17       → STM32 BOOT0        ★ Flash control (HIGH = bootloader)
  GPIO27       → STM32 NRST         ★ Flash control (pulse LOW = reset)
  GND ─────────── STM32 GND         ★ Common ground
```

---

## 9. Troubleshooting

### Pi shows no data (all zeros, no screen changes)

1. Check UART wiring: PA9 → GPIO15, GND → GND
2. Verify serial console is disabled: `cat /boot/firmware/cmdline.txt` should NOT contain `console=serial0`
3. Test manually: `python3 -c "import serial; s=serial.Serial('/dev/ttyAMA0',115200,timeout=2); print(s.readline())"`
4. Check STM32 is running: LED should be blinking (500ms sim, 2s live)

### IMU says "not found on I2C"

1. Check SDA (PB7) and SCL (PB6) — don't swap them
2. Verify AD0 is connected to GND
3. Check pull-ups: measure voltage on SDA/SCL with multimeter — should be ~3.3V when idle
4. Try a shorter I2C cable (I2C is sensitive to long wires)

### SD card fails to initialize

1. Confirm card is FAT32 (not exFAT — cards >32GB default to exFAT)
2. Verify you're using a 3.3V module (not 5V with regulator)
3. Check SPI wiring, especially MISO/MOSI (easy to swap)
4. Try a different SD card — some cheap ones don't support SPI mode

### GPS never gets a fix

1. Needs clear sky view — won't work indoors
2. First fix takes 30-60 seconds, cold start can take 5+ minutes
3. Check UART wiring: GPS TX → PA3, GPS RX → PA2
4. Verify GPS module LED blinks (1 PPS blink = has fix)

### Gear always shows N / 0

1. Clutch switch: verify PB8 is HIGH when clutch is out (multimeter)
2. Need both RPM >1500 AND speed >5 mph for gear detection
3. If you changed sprockets: update `FINAL_RATIO` in firmware and reflash
4. Check `GEAR_MATCH_TOL` — increase to 0.10 if gears aren't matching

### CAN bus not working

1. CAN is not yet implemented in firmware (TODO) — this is expected
2. When implemented: verify 120Ω termination at both ends
3. Check that SN65HVD230 Rs pin is tied to GND
4. Verify Speeduino is configured to broadcast on CAN (not just serial)

### Speed sensor (VSS) reads zero or erratic values

1. Check LM393 comparator output with multimeter: should toggle 0V / 3.3V when spinning wheel
2. If output stays at 3.3V constantly: check bias resistors on IN- (should sit at ~1.65V)
3. If output is noisy/jittery: add 100pF cap on IN+ and 100KΩ hysteresis feedback
4. Verify PB3 wiring — it must be the comparator output, not the raw reluctor signal
5. If speed reads way too high or low: check VSS_TEETH constant (28 for CBR 600RR stock)
6. If you changed sprockets: update FINAL_RATIO in firmware

---

## 10. File Inventory

```
stm32_firmware/
├── platformio.ini          # PlatformIO build config
└── src/
    └── main.cpp            # All STM32 firmware

Pi dashboard (copy to /home/pi/dash/):
├── race_dash_config.py     # Configuration, units, colors, settings
├── race_dash_core.py       # UART thread, CSV parser, signal buffer
├── race_dash_pygame.py     # PyGame rendering, 10 screens, settings UI
└── race_dash_updater.py    # STM32 flashing (GPIO + stm32flash) & Pi git pull
```

---

## 11. What's Working vs TODO

| Feature | Status |
|---------|--------|
| UART CSV to Pi (15 fields, 25Hz) | ✅ Working |
| GPS position + speed | ✅ Working |
| MPU-6050 accelerometer (3-axis g-force) | ✅ Working |
| SD card logging (100Hz, 22 columns) | ✅ Working |
| Gear calculation (CBR 600RR ratios) | ✅ Working |
| Clutch switch input | ✅ Working |
| Simulation mode | ✅ Working |
| Analog inputs (brake, steering) | ✅ Working (needs calibration) |
| 10 dashboard screens + settings | ✅ Working |
| G-force display with trace history | ✅ Working |
| CAN bus (Speeduino decode) | ❌ TODO — wiring ready, firmware needs eXoCAN |
| nRF24 telemetry to pit | ❌ TODO — wiring ready, firmware needs RF24 |
| Lap timing | ❌ TODO — needs GPS geofence or IR beacon |
| In-app STM32 flashing (Settings → Update) | ✅ Working (needs GPIO17→BOOT0, GPIO27→NRST) |
| In-app Pi software update (git pull) | ✅ Working |
| Pi boot optimization | ⚡ Optional — works now, just slow (~15-20s) |