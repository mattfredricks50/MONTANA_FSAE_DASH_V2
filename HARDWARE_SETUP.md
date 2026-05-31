# Race Dash — Hardware Setup

Complete build guide for **Raspberry Pi (display) + Arduino Nano (data acquisition)**.

The Nano reads engine data from Speeduino (RS232), reads acceleration from an MPU-6050 IMU, and streams a CSV to the Pi at 25 Hz over UART. The Pi runs the pygame dashboard. GPS comes from a phone app uploading to Google Drive — not wired to the Nano.

---

## 1. Bill of Materials

### Required (minimum viable dash)

| # | Item | Notes |
|---|------|-------|
| 1 | Raspberry Pi (Zero 2W, 3B, 3B+, or 4B) | Any model with 40-pin GPIO + HDMI |
| 1 | Arduino Nano (ATmega328P) | Genuine or clone — both work |
| 1 | HDMI display | 5–10" with HDMI input. 800×480 or 1024×600 typical |
| 1 | Pi power supply | 5V 2.5A min (Pi Zero) or 3A (Pi 3/4) — buck from car 12V |
| 1 | MicroSD card (16 GB+ Class 10) | For Pi OS |
| 1 | USB cable | For programming the Nano |
| 1 | MPU-6050 IMU breakout (3.3V GY-521 or similar) | Acceleration + gyro. Most "3.3V" breakouts include an onboard 3.3V regulator and I2C pull-ups, making them safe to wire directly to a 5V Nano. |
| 2 | Resistors: 10 KΩ + 20 KΩ | Voltage divider, Nano D7 → Pi GPIO15 |
| — | Hookup wire, breadboard or perfboard, JST/Dupont connectors | |

### Optional — only if your IMU breakout is "bare" (no onboard regulator/pull-ups)

| Item | When you need it |
|------|------------------|
| Bidirectional I2C level shifter (BSS138 module) | Bare MPU-6050 chip on a breakout that exposes the raw 3.3V I/O directly |
| 2× 4.7 KΩ resistors | I2C pull-ups (only if your breakout doesn't include them — most do) |

### Optional / future

| Item | Purpose |
|------|---------|
| Smartphone | GPS + acceleration via Sensor Logger or RaceChrono |
| 4× MCP9600 + K-type thermocouples | EGT or oil temp |
| Hall-effect VSS sensor + LM393 comparator | Wheel speed for gear detection |
| 0.5–4.5V brake pressure sensor | Brake telemetry |
| MicroSD card module (5V) | On-Nano data logging |
| 7805 or buck converter (12V → 5V) | Power Nano + Pi from car |
| Anderson PowerPoles or fused harness | Clean install |

### No longer needed (legacy STM32 build)

- ❌ ST-Link V2 programmer
- ❌ MCP2515 or SN65HVD230 CAN transceiver
- ❌ nRF24L01+
- ❌ STM32F103 board

---

## 2. Pi Setup

### 2.1 Flash Pi OS

Use Raspberry Pi Imager:
- **OS:** Raspberry Pi OS (Lite is fine — we don't need a desktop)
- **Settings (gear icon):**
  - Hostname: `racedash`
  - Username: `pi`
  - Enable SSH (use password or key)
  - Configure WiFi (for first-boot setup; can disable later)

- [ ] OS flashed
- [ ] Pi boots, SSH works

### 2.2 Install Software

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3-pygame python3-serial git
```

### 2.3 Free Up the Hardware UART

The Pi's serial console has to be disabled to use `/dev/ttyAMA0` for the Nano data link.

```bash
sudo raspi-config
#   Interface Options → Serial Port
#   "Login shell over serial?"      → NO
#   "Hardware serial port enabled?" → YES
#   Finish → Reboot

# After reboot, verify the port is free:
ls -la /dev/ttyAMA0
```

- [ ] Serial console disabled, hardware serial enabled
- [ ] `/dev/ttyAMA0` exists with no getty using it

### 2.4 Deploy Dash Code

```bash
mkdir -p /home/pi/dash
cd /home/pi/dash
# Copy these files (scp / USB / git):
#   race_dash_config.py
#   race_dash_core.py
#   race_dash_pygame.py
#   race_dash_updater.py
#   start_dash.sh
#   racedash.service

# Smoke test (will run in sim mode if no Nano connected):
python3 race_dash_pygame.py
# Should see dashboard on HDMI. Press Q in settings or Escape to quit.
```

- [ ] Code on Pi
- [ ] Sim-mode dash visible on the display

### 2.5 Auto-Start on Boot

```bash
chmod +x /home/pi/dash/start_dash.sh
sudo cp /home/pi/dash/racedash.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable racedash
sudo systemctl start racedash
sudo systemctl status racedash    # check it started
```

- [ ] systemd service installed
- [ ] Reboot → dash appears automatically

### 2.6 Display Rotation (if needed)

If your display is mounted upside-down in the dash housing:
```bash
sudo nano /boot/firmware/config.txt
# Add this line:
display_rotate=2     # 0=normal, 1=90°, 2=180°, 3=270°
```

### 2.7 Faster Boot (optional)

```bash
sudo systemctl disable bluetooth hciuart avahi-daemon triggerhappy
# Only if you don't need WiFi at the car:
sudo systemctl disable wpa_supplicant

# Edit /boot/firmware/config.txt — append:
boot_delay=0
disable_splash=1
dtoverlay=disable-bt

# Edit /boot/firmware/cmdline.txt — append to the existing single line:
quiet fastboot
```

- [ ] Boot time ≤ 15 seconds to dashboard

---

## 3. Arduino Nano Setup

### 3.1 Install Arduino IDE

Download from <https://www.arduino.cc/en/software>. Install on your laptop (not the Pi — easier to develop on a real keyboard/screen).

### 3.2 Driver for Clone Nanos

Most cheap Nanos use a **CH340** USB-serial chip. If Windows doesn't detect a COM port when you plug it in, install the CH340 driver from <https://www.wch-ic.com/downloads/CH341SER_EXE.html>.

Genuine Arduino Nanos use FTDI and need no driver on modern Windows.

- [ ] COM port appears in Device Manager when Nano is plugged in

### 3.3 Open the Sketch

1. **File → Open** → `dash_nano/dash_nano.ino`
2. **Tools → Board** → Arduino AVR Boards → **Arduino Nano**
3. **Tools → Processor** → **ATmega328P**
   *(if upload fails with `stk500_recv()`, switch to "ATmega328P (Old Bootloader)")*
4. **Tools → Port** → the COM port from step 3.2
5. **Sketch → Verify** (Ctrl+R) — should compile with zero errors
6. **Sketch → Upload** (Ctrl+U)

> ⚠ **Disconnect D0 from Speeduino before uploading.** The USB bootloader uses the same UART. Reconnect after the upload finishes.

### 3.4 Smoke Test

Open the Arduino IDE Serial Monitor at **115200 baud** with the Nano still on USB and Speeduino still disconnected. You should see:

```
# Race Dash Nano (minimum) starting
# CSV: RPM,SPEED,THROTTLE,BRAKE,...
# No Speeduino response (got 0/65 bytes)
```

The "no response" message every ~10 seconds confirms the Nano is alive and polling.

- [ ] Sketch compiles
- [ ] Sketch uploads
- [ ] Serial Monitor shows the banner

---

## 4. Wiring

### 4.1 Power & Ground

Everything shares one ground. **Tie all GNDs together first**, then worry about signal.

```
Car 12V ──┬── Buck/regulator → 5V ──┬── Pi USB-C / micro-USB
          │                         └── Nano 5V pin (or just power Nano via USB during dev)
          │
          └── Common chassis ground

Pi GND ──┬── Nano GND ──┬── Speeduino GND ──┬── IMU GND
         │              │                   │
        ─┴─────────────────────────────────────────  common ground rail
```

- [ ] One unbroken ground between Pi, Nano, Speeduino, IMU

### 4.2 Nano ↔ Speeduino (RS232 Secondary Serial)

Speeduino's secondary serial is 5V TTL — direct connect to the Nano's 5V hardware UART, no level shifter needed. **The hardware UART (D0/D1) is dedicated to Speeduino — nothing else shares it.**

```
Speeduino 2nd Serial TX ──────────────► Nano D0 (RX)
Speeduino 2nd Serial RX ◄────────────── Nano D1 (TX)
Speeduino GND ────────────────────────── common GND
```

- [ ] Speeduino TX → Nano D0
- [ ] Nano D1 → Speeduino RX (NOT also to the Pi)

### 4.3 Nano ↔ Pi (SoftwareSerial, with Voltage Divider)

The Pi link uses a **separate** SoftwareSerial TX pin (D7) so the CSV stream never reaches Speeduino. (If the Pi link shared D1 with Speeduino, every CSV digit would arrive at Speeduino's RX as random ASCII — Speeduino's parser could interpret bytes as commands and trigger unwanted protocol events or flash burns.)

The Nano TX is 5V; the Pi GPIO max is 3.3V. **A voltage divider is mandatory** — without it you will eventually kill GPIO15 on the Pi.

```
Nano D7 (SoftwareSerial TX) ─── 10KΩ ──┬─────── Pi GPIO15 (RX, pin 10)
                                       │
                                      20KΩ
                                       │
                                      GND ──── common GND

Pi GPIO TX (GPIO14) is NOT connected — communication is one-way (Nano → Pi).
```

Output of divider: 5 V × (20 / (10 + 20)) = **3.33 V** ✓

**Baud rate:** 57600 (Pi `race_dash_config.py` → `uart_baud: 57600`, Nano sketch `piSerial.begin(57600)`). They must match.

- [ ] 10 KΩ resistor in series with D7
- [ ] 20 KΩ resistor from divider midpoint to GND
- [ ] Divider output → Pi GPIO15 (pin 10 on the 40-pin header)
- [ ] Pi `uart_baud` set to 57600

### 4.4 Nano ↔ MPU-6050 IMU (I2C, direct connect)

The MPU-6050 chip itself is a 3.3V part, but virtually every breakout sold as "MPU-6050" or "GY-521" includes:

- An **onboard 3.3V LDO regulator** — so the VCC pin safely accepts either 3.3V or 5V
- **Onboard 4.7 KΩ I2C pull-up resistors** wired to the breakout's 3.3V rail (after the regulator)

These two features make the breakout safe to wire directly to a 5V Nano. I2C is open-drain, so the bus HIGH level is set by the breakout's 3.3V pull-ups (which dominate over the Nano's weak ~30 KΩ internal pull-ups). The Nano's input HIGH threshold is ~3 V, so it reliably reads the 3.3V signal as a logical 1. **No external level shifter or pull-up resistors needed.**

#### Standard wiring (GY-521 / "3.3V MPU-6050" breakout)

```
MPU-6050 breakout            Nano
────────────────────────────────────────
VCC  ──────────────────────► 5V    (uses onboard 3.3V regulator)
GND  ──────────────────────► GND
SCL  ──────────────────────► A5    (I2C SCL)
SDA  ──────────────────────► A4    (I2C SDA)
AD0  ──────────────────────► GND   (sets I2C address to 0x68 — most breakouts already tie this internally)
INT  ──────────────────────► n/c   (not used)
XDA, XCL, FSYNC ───────────► n/c   (auxiliary I2C, not used)
```

That's all four wires. No resistors, no level shifter, no extra parts.

- [ ] MPU-6050 VCC → Nano 5V (or 3.3V — both work)
- [ ] MPU-6050 GND → Nano GND
- [ ] MPU-6050 SCL → Nano A5
- [ ] MPU-6050 SDA → Nano A4
- [ ] AD0 grounded (check breakout — usually wired internally)

#### When you DO need a level shifter

Skip this unless your breakout is unusual:

- A "bare" breakout that exposes raw 3.3V I/O with **no onboard regulator** (rare — typically these are labeled "3.3V only" and have only 4 pins). Apply 3.3V to VCC and put a BSS138-type level shifter between the Nano's A4/A5 and the breakout's SDA/SCL.
- You measured the breakout's pull-ups and they go to a different rail than 3.3V (very rare).

If you're not sure: power your breakout from 3.3V and direct-connect SDA/SCL. If the IMU isn't detected, **then** add a level shifter.

> The current minimum-viable sketch (`dash_nano.ino`) does not yet read the IMU. When you're ready to add it, the I2C wiring above is what the IMU code will expect.

### 4.5 Pinout Summary (quick reference)

```
Arduino Nano               Function                       Goes to
────────────────────────────────────────────────────────────────────────────────
D0  (RX)                   Hardware UART RX               Speeduino 2nd Serial TX  (only)
D1  (TX)                   Hardware UART TX               Speeduino 2nd Serial RX  (only)
D7  (SoftwareSerial TX)    Pi data link                   10K/20K divider → Pi GPIO15
A4  (SDA)                  I2C data                       MPU-6050 SDA  (direct)
A5  (SCL)                  I2C clock                      MPU-6050 SCL  (direct)
5V                         5V out                         Speeduino I/O ref, MPU-6050 VCC (via onboard regulator)
3.3V                       3.3V out                       (unused for this build)
GND                        Ground                         Everything

Raspberry Pi (40-pin GPIO header)
────────────────────────────────────────────────────────────────────────────────
Pin 6   GND                Common ground
Pin 10  GPIO15 (RX, UART)  ← from Nano D1 voltage divider midpoint
Pin 8   GPIO14 (TX, UART)  Not connected
```

### 4.6 Wiring Checklist

- [ ] Common ground between Pi, Nano, Speeduino, IMU
- [ ] Speeduino TX → Nano D0
- [ ] Nano D1 → Speeduino RX (and ONLY Speeduino — does NOT also go to the Pi)
- [ ] Nano D7 → 10K/20K divider → Pi GPIO15
- [ ] Pi `race_dash_config.py` `uart_baud` = 57600
- [ ] MPU-6050 VCC → Nano 5V (uses onboard regulator)
- [ ] MPU-6050 SDA → Nano A4, SCL → Nano A5 (direct, no level shifter)

---

## 5. Phone-Based GPS + Acceleration

To save Nano IO and avoid running GPS antenna wiring to the dash, log GPS + phone IMU on a phone and auto-upload to Google Drive after each session. (The on-board MPU-6050 is still the source of live G-force on the dash itself; the phone is for post-session telemetry.)

### Recommended apps

| App | Platform | Cost | Drive sync |
|-----|----------|------|------------|
| **Sensor Logger** by Kelvin Choi | iOS + Android | Free / $5 mo Pro | ✅ Built-in (Pro tier) |
| **RaceChrono** | iOS + Android | Free / $20 Pro | ✅ via Autosync (~$5) |
| **GPSLogger for Android** | Android only | Free + open source | ✅ Built-in |

**Easiest setup:** Sensor Logger Pro — single app, GPS + accel + gyro at high rate, auto-uploads CSV to Drive when each recording stops.

**Best racing UX:** RaceChrono Pro — designed for lap timing, video overlay, exports `.vbo` and CSV.

### Mounting

Mount the phone rigidly to the chassis (not the steering column or anything that moves independently of the car). A RAM mount on the roll cage works. The accelerometer needs to feel the car's motion, not your hand.

---

## 6. First Power-On Test

In order:

1. **Pi boot test (no Nano)** — power Pi alone. Dashboard appears in sim mode within ~15 sec. RPM sweeps, gear changes, gauges animate.
2. **Nano standalone test** — Nano on USB, Serial Monitor at 115200, no Speeduino. See `# Race Dash Nano starting` and `# No Speeduino response`.
3. **Nano ↔ Speeduino test** — Nano on USB, Speeduino powered. Open Serial Monitor — you should see CSV lines like `8500,0,75,0,180,98,0,0,0,0,...`. RPM should change with throttle.
4. **Nano ↔ Pi test** — disconnect Nano from USB, power both from the car (or bench supply). Voltage divider must be wired. Dashboard should switch out of sim mode and show live RPM/CLT/throttle.
5. **End-to-end** — engine running, dashboard live, no flickering, no `# parse error` messages on the Pi log.

- [ ] All five tests pass

---

## 7. Future Expansion

Sections to add when you wire up the matching hardware. Code stubs for these already exist in earlier firmware versions and can be ported in:

| Feature | Pin | Wiring |
|---------|-----|--------|
| **VSS speed sensor** | D2 (INT0) | Hall sensor → LM393 comparator → D2; `INPUT_PULLUP` |
| **Brake pressure** | A0 | 0.5–4.5V sensor direct to A0 (5V supply) |
| **Clutch switch** | D5 | Switch between D5 and GND; `INPUT_PULLUP` |
| **MCP9600 thermocouples (×4)** | A4/A5 (same I2C bus) | Addresses 0x60–0x63 via ADDR resistor |
| **SD card logging** | D10–D13 (SPI) | 5V SD breakout, CS = D10 |
| **Status LED** | D9 | LED + 330Ω to GND |

> **Don't wire all of these at once.** Add one feature, flash matching firmware, verify it on the dash, then move on. That way if something breaks you know exactly which connection introduced it.

---

## 8. Troubleshooting

| Symptom | Likely cause |
|---------|--------------|
| Pi shows sim mode forever | UART wiring wrong; Pi serial console not disabled; wrong baud |
| Pi shows "no data" then sim mode falls back | Voltage divider wired backward (10K/20K swapped — output too low) |
| Garbage on Pi: `# parse error` flooding | Baud mismatch; ground bounce (no common GND); wrong pin for divider tap |
| Nano won't upload, `stk500_recv()` error | Wrong processor option; Speeduino still on D0; wrong COM port |
| Nano upload OK but no Serial Monitor output | Wrong baud in monitor (must be 115200) |
| `# No Speeduino response` forever | Wrong RX/TX direction; Speeduino secondary serial not enabled in TunerStudio |
| MPU-6050 not detected | SDA/SCL swapped; AD0 floating (changes address from 0x68 to 0x69); no power; bare breakout without onboard regulator/pull-ups (then add a level shifter) |
| Dashboard runs but won't autostart | systemd service not enabled; check `journalctl -u racedash` |
| Display upside down | `display_rotate=2` in `/boot/firmware/config.txt` |

---

## 9. Differences From The Old STM32 Build

If you previously had the STM32 + CAN bus version working, here's what changed:

| Old (STM32) | New (Nano) |
|-------------|------------|
| STM32F103RCT6 | Arduino Nano (ATmega328P) |
| CAN bus + transceiver | Speeduino RS232 secondary serial |
| ST-Link or DFU upload | USB upload via Arduino IDE |
| Pi flashed STM32 over UART (BOOT0/NRST) | Just plug Nano into a laptop USB |
| 3.3V everywhere | 5V Nano — voltage divider on Pi link, level shifter on I2C |
| nRF24 telemetry to pit | Phone app uploads to Google Drive instead |
| GPS on Nano UART2 | GPS on phone (no wiring) |

The Pi side (pygame app, CSV format, autostart) is unchanged.
