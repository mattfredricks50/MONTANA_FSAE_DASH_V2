/*
 * Race Dash - STM32F103RCT6 Firmware
 * 
 * HARDWARE CONNECTIONS:
 *   CAN Bus (Speeduino Dropbear v2):
 *     PA11 = CAN_RX  (through SN65HVD230 transceiver)
 *     PA12 = CAN_TX  (through SN65HVD230 transceiver)
 * 
 *   UART1 → Pi (CSV data output):
 *     PA9  = TX1  (to Pi RX GPIO15)
 *     PA10 = RX1  (from Pi TX GPIO14) [unused for now]
 * 
 *   UART2 → GPS (u-blox NEO-6M/7M):
 *     PA2  = TX2  (to GPS RX)
 *     PA3  = RX2  (from GPS TX)
 * 
 *   SPI1 → SD Card (Adafruit 4682, 3.3V native):
 *     PA5  = SCK
 *     PA6  = MISO
 *     PA7  = MOSI
 *     PA4  = CS (active low)
 * 
 *   SPI2 → nRF24L01+PA+LNA (telemetry to pit):
 *     PB13 = SCK
 *     PB14 = MISO
 *     PB15 = MOSI
 *     PB12 = CSN
 *     PB1  = CE
 *
 *   I2C1 → MPU-6050 (6-axis IMU: 3-axis accel + 3-axis gyro):
 *     PB6  = SCL
 *     PB7  = SDA
 *     AD0 to GND = address 0x68
 * 
 *   Analog Inputs (3.3V max, use voltage dividers for 5V sensors):
 *     PA0  = Analog 0 (spare / brake pressure)
 *     PA1  = Analog 1 (spare / steering angle)
 * 
 *   Debug LED:
 *     PC13 = Onboard LED (active low on most boards)
 * 
 *   Simulation Mode:
 *     PB0  = Pull LOW at boot to enable sim mode (internal pullup)
 *            Leave floating or HIGH for real sensor mode
 *
 *   Clutch Switch:
 *     PB8  = Pull LOW = clutch lever pulled (internal pullup)
 *
 *   Vehicle Speed Sensor (VSS):
 *     PB3  = Conditioned pulse input (interrupt on rising edge)
 *            CBR 600RR: reluctor reads 28 teeth on countershaft
 *            Requires LM393 comparator to convert sine wave to 3.3V square
 * 
 * DATA FLOW:
 *   CAN/Analog/GPS → STM32 → SD card (full rate, ~100Hz)
 *                           → UART to Pi (20-30Hz CSV for display)
 *                           → nRF24 to pit (10-20Hz telemetry)
 * 
 * CSV FORMAT (UART to Pi):
 *   RPM,SPEED_MPH,THROTTLE_PCT,BRAKE_PCT,CLT_F,OIL_PSI,LAT,LON,GPS_SPEED_MPH,GPS_SATS,ACCEL_X,ACCEL_Y,ACCEL_Z,GEAR,CLUTCH\n
 * 
 * SD LOG FORMAT:
 *   TIMESTAMP_MS,RPM,SPEED_MPH,THROTTLE_PCT,BRAKE_PCT,CLT_F,OIL_PSI,AFR,VOLTAGE,
 *   LAT,LON,GPS_SPEED_MPH,GPS_ALT_FT,GPS_SATS,GPS_FIX\n
 * 
 * BUILD: PlatformIO with framework = stm32cube or arduino
 *   platformio.ini included in this project
 * 
 * ALL UNITS ARE IMPERIAL (°F, mph, psi) — Pi handles display conversion
 */

#include <Arduino.h>
#include <SPI.h>
#include <Wire.h>
#include <SD.h>
#include <TinyGPSPlus.h>

// ============================================================
// PIN DEFINITIONS
// ============================================================

// UART
#define PI_SERIAL       Serial1     // PA9/PA10
#define GPS_SERIAL      Serial2     // PA2/PA3

// SPI1 - SD Card
#define SD_CS_PIN       PA4

// SPI2 - nRF24 (define if using RF24 library)
#define NRF_CSN_PIN     PB12
#define NRF_CE_PIN      PB1

// Analog
#define ANALOG_0_PIN    PA0
#define ANALOG_1_PIN    PA1

// Control
#define LED_PIN         PC13
#define SIM_MODE_PIN    PB0     // Pull LOW = simulation mode

// I2C1 - MPU-6050 IMU (PB6=SCL, PB7=SDA)
#define MPU6050_ADDR    0x68    // AD0 pin to GND

// Clutch switch (digital input)
#define CLUTCH_PIN      PB8     // Pull LOW = clutch engaged (closed switch to GND)

// Vehicle Speed Sensor (VSS) — hall/reluctor pulse input
// CBR 600RR: 28 pulses per countershaft revolution
// Signal must be conditioned to 3.3V square wave (use LM393 comparator)
#define VSS_PIN         PB3     // External interrupt on rising edge

// ============================================================
// CONFIGURATION
// ============================================================

#define PI_BAUD             115200
#define GPS_BAUD            9600
#define CAN_BITRATE         500000

// ── CBR 600RR Drivetrain Config ──
// Internal gear ratios from Honda service manual (2003-2006 CBR600RR)
// These only change if you swap transmission gears (you won't).
#define NUM_GEARS           6
const float GEAR_RATIOS[NUM_GEARS] = {
    2.666f,   // 1st (32/12)
    1.937f,   // 2nd (31/16)
    1.661f,   // 3rd (29/18)
    1.409f,   // 4th (31/22)
    1.260f,   // 5th (29/23)
    1.166f    // 6th (28/24)
};
const float PRIMARY_RATIO  = 2.111f;   // 76/36 — internal, doesn't change

// ═══════════════════════════════════════════════════════════
// THE ONE NUMBER YOU NEED TO CALIBRATE
// ═══════════════════════════════════════════════════════════
//
// VSS_PULSES_PER_MPH: how many VSS pulses per second at exactly 1 MPH.
// This single value encodes: tooth count, final drive ratio, and tire size.
//
// Formula:
//   vss_pulses_per_mph = (teeth × final_ratio) / (tire_circ_m / 0.44704)
//
// Stock CBR 600RR (28 teeth, 43/16 sprockets, 180/55-17 tire):
//   = (28 × 2.6875) / (2.02 / 0.44704)
//   = 75.25 / 4.5188
//   = 16.65
//
// If you change sprockets or tires, recalculate:
//   final_ratio = rear_teeth / front_teeth
//   tire_circ_m ≈ measure it, or use: (rim_dia_mm + 2 × section_width_mm × aspect_ratio / 100) × π / 1000
//
// Or just calibrate empirically: drive at a known GPS speed and adjust until they match.
//
// This can be changed from the Pi settings screen at runtime.

float VSS_PULSES_PER_MPH   = 16.65f;  // stock CBR 600RR, 43/16, 180/55-17

// Precomputed RPM per MPH for each gear (used for gear detection).
// rpm_per_mph[g] = primary × gear_ratio[g] × final × 60 × 0.44704 / tire_circ
// With stock values (primary 2.111, final 2.6875, tire 2.02m):
//   constant_factor = 2.111 × 2.6875 × 60 × 0.44704 / 2.02 = 75.284
// Then multiply by each gear ratio.
// These are recalculated at boot from VSS_PULSES_PER_MPH so they
// stay in sync when you change sprockets/tires.

float RPM_PER_MPH[NUM_GEARS];  // filled by recalc_drivetrain()

void recalc_drivetrain() {
    // Derive RPM-per-MPH for each gear from VSS_PULSES_PER_MPH.
    //
    // VSS_PULSES_PER_MPH = (teeth × final) / (tire / 0.44704)
    // So: final / tire = VSS_PULSES_PER_MPH × 0.44704 / teeth  ... (*)
    //
    // RPM_PER_MPH[g] = primary × gear[g] × final × 60 × 0.44704 / tire
    //                = primary × gear[g] × (final/tire) × 60 × 0.44704
    //
    // But we can simplify: at 1 MPH, countershaft does
    // VSS_PULSES_PER_MPH / teeth revolutions per second.
    // Engine RPM = countershaft_rps × primary × gear_ratio × 60
    //
    // So: RPM_PER_MPH[g] = (VSS_PULSES_PER_MPH / teeth) × primary × gear[g] × 60

    float countershaft_rps_per_mph = VSS_PULSES_PER_MPH / 28.0f;  // 28 teeth

    for (uint8_t g = 0; g < NUM_GEARS; g++) {
        RPM_PER_MPH[g] = countershaft_rps_per_mph * PRIMARY_RATIO * GEAR_RATIOS[g] * 60.0f;
    }

    PI_SERIAL.print("# VSS cal: ");
    PI_SERIAL.print(VSS_PULSES_PER_MPH, 2);
    PI_SERIAL.print(" pulses/mph  |  RPM/MPH per gear: ");
    for (uint8_t g = 0; g < NUM_GEARS; g++) {
        PI_SERIAL.print(RPM_PER_MPH[g], 1);
        if (g < NUM_GEARS - 1) PI_SERIAL.print(", ");
    }
    PI_SERIAL.println();
}

// Gear detection tolerance: how close (as a ratio) actual RPM must
// be to the predicted RPM for a gear to match. 0.08 = within 8%.
const float GEAR_MATCH_TOL = 0.08f;

// ── Vehicle Speed Sensor (VSS) ──
// CBR 600RR reluctor reads countershaft 3rd gear: 28 teeth
// Minimum microseconds between pulses to reject noise
// At 200mph → ~3130 Hz → 320µs period. Anything under 200µs is noise.
const uint32_t VSS_MIN_PERIOD_US   = 200;
// Maximum microseconds between pulses before speed = 0
// At 2mph → ~33 Hz → ~30000µs. No pulse for 100ms = stopped.
const uint32_t VSS_TIMEOUT_US      = 100000;

// Timing intervals (milliseconds)
#define SD_LOG_INTERVAL_MS  10      // 100Hz full-rate logging
#define PI_SEND_INTERVAL_MS 40      // 25Hz to Pi (plenty for 30fps display)
#define NRF_SEND_INTERVAL_MS 100    // 10Hz wireless telemetry
#define GPS_PARSE_INTERVAL_MS 100   // GPS updates at 10Hz max
#define SIM_UPDATE_INTERVAL_MS 10   // 100Hz sim data update

// SD card
#define LOG_FLUSH_INTERVAL_MS 1000  // Flush SD write buffer every 1s
#define MAX_LOG_FILES       999

// CAN IDs for Speeduino Dropbear v2 (adjust to match your tune)
// See: https://wiki.speeduino.com/en/Secondary_Serial_IO_interface
#define CAN_ID_RPM_STATUS   0x5F0  // RPM, status
#define CAN_ID_CLT_IAT      0x5F1  // Coolant temp, intake air temp
#define CAN_ID_FUEL          0x5F2  // AFR, fuel pressure, etc
#define CAN_ID_THROTTLE      0x5F3  // TPS, MAP, etc

// ============================================================
// DATA STRUCTURE
// ============================================================

struct SensorData {
    // Engine (from CAN)
    uint16_t rpm;
    uint8_t  throttle_pct;      // 0-100
    uint8_t  brake_pct;         // 0-100
    int16_t  coolant_temp_f;    // °F
    uint8_t  oil_pressure_psi;
    uint8_t  afr_x10;           // AFR * 10 (e.g. 147 = 14.7)
    uint16_t map_kpa;           // manifold pressure
    float    battery_voltage;

    // Calculated
    uint16_t speed_mph;
    uint8_t  gear;              // 0 = neutral/unknown, 1-6 = gear
    bool     clutch_in;         // true = clutch lever pulled (disengaged)

    // GPS
    double   lat;
    double   lon;
    float    gps_speed_mph;
    float    gps_alt_ft;
    uint8_t  gps_satellites;
    bool     gps_fix;

    // Analog
    uint16_t analog_0_raw;      // 12-bit ADC
    uint16_t analog_1_raw;

    // IMU (MPU-6050) — in g-force units
    float accel_x_g;            // Lateral (positive = right)
    float accel_y_g;            // Longitudinal (positive = forward/accel)
    float accel_z_g;            // Vertical (positive = up, ~1.0 at rest)

    // Timing
    uint32_t timestamp_ms;
};

// ============================================================
// GLOBALS
// ============================================================

SensorData current_data;
TinyGPSPlus gps;

bool sim_mode = false;
bool sd_ok = false;
File log_file;
char log_filename[16];

// Timing
uint32_t last_sd_log = 0;
uint32_t last_pi_send = 0;
uint32_t last_nrf_send = 0;
uint32_t last_gps_parse = 0;
uint32_t last_sd_flush = 0;
uint32_t last_sim_update = 0;
uint32_t last_led_toggle = 0;

// Simulation state
int16_t sim_rpm = 3000;
int8_t  sim_rpm_dir = 1;
uint8_t sim_gear = 0;         // 0-indexed: 0=1st, 5=6th
bool    sim_accel = true;     // true = accelerating up through gears
uint8_t sim_clutch_ticks = 0; // countdown for clutch engagement

// ============================================================
// FORWARD DECLARATIONS
// ============================================================

void init_sd();
void init_can();
void init_gps();
void init_nrf();
void read_can();
void read_gps();
void read_analog();
void update_sim_data();
void init_vss();
void update_speed_from_vss();
void log_to_sd();
void send_to_pi();
void send_to_nrf();
void create_new_logfile();

// ============================================================
// SETUP
// ============================================================

void setup() {
    // LED
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);     // LED on (active low)

    // Sim mode pin - internal pullup, pull LOW to enable sim
    pinMode(SIM_MODE_PIN, INPUT_PULLUP);
    delay(10);  // Let pullup settle
    sim_mode = (digitalRead(SIM_MODE_PIN) == LOW);

    // Clutch switch - internal pullup, switch pulls LOW when clutch is in
    pinMode(CLUTCH_PIN, INPUT_PULLUP);

    // UART to Pi
    PI_SERIAL.begin(PI_BAUD);
    PI_SERIAL.println("# Race Dash STM32 starting...");
    PI_SERIAL.print("# Mode: ");
    PI_SERIAL.println(sim_mode ? "SIMULATION" : "LIVE SENSORS");

    // Zero out data
    memset(&current_data, 0, sizeof(current_data));

    // Init peripherals
    if (!sim_mode) {
        // GPS
        GPS_SERIAL.begin(GPS_BAUD);
        PI_SERIAL.println("# GPS UART2 initialized");

        // CAN bus
        init_can();

        // nRF24 telemetry
        // init_nrf();  // Uncomment when nRF24 wired up
    }

    // SD card (always init - log sim data too for testing)
    init_sd();

    // IMU (always init - useful even in sim for bench vibration testing)
    init_imu();

    // Precompute RPM-per-MPH table from VSS calibration
    recalc_drivetrain();

    // VSS (speed sensor) — only in live mode
    if (!sim_mode) {
        init_vss();
    }

    // Send CSV header so Pi knows the format
    PI_SERIAL.println("# CSV: RPM,SPEED,THROTTLE,BRAKE,CLT,OIL,LAT,LON,GPS_SPD,GPS_SATS,AX,AY,AZ,GEAR,CLUTCH");

    digitalWrite(LED_PIN, HIGH);    // LED off - setup complete
    PI_SERIAL.println("# Ready");
}

// ============================================================
// MAIN LOOP
// ============================================================

void loop() {
    uint32_t now = millis();

    // ── Read sensors ──
    if (sim_mode) {
        if (now - last_sim_update >= SIM_UPDATE_INTERVAL_MS) {
            last_sim_update = now;
            update_sim_data();
        }
    } else {
        read_can();                 // Non-blocking CAN poll
        read_analog();              // Fast ADC reads
        read_imu();                 // Accelerometer (I2C, ~0.5ms)
        read_clutch();              // Clutch switch (digital, instant)
        update_speed_from_vss();    // Convert pulse period to mph
        calculate_gear();           // Gear from RPM + wheel speed

        if (now - last_gps_parse >= GPS_PARSE_INTERVAL_MS) {
            last_gps_parse = now;
            read_gps();
        }
    }

    current_data.timestamp_ms = now;

    // ── Log to SD at full rate ──
    if (sd_ok && (now - last_sd_log >= SD_LOG_INTERVAL_MS)) {
        last_sd_log = now;
        log_to_sd();
    }

    // ── Flush SD periodically ──
    if (sd_ok && (now - last_sd_flush >= LOG_FLUSH_INTERVAL_MS)) {
        last_sd_flush = now;
        log_file.flush();
    }

    // ── Send CSV to Pi ──
    if (now - last_pi_send >= PI_SEND_INTERVAL_MS) {
        last_pi_send = now;
        send_to_pi();
    }

    // ── Send telemetry to pit ──
    if (now - last_nrf_send >= NRF_SEND_INTERVAL_MS) {
        last_nrf_send = now;
        // send_to_nrf();  // Uncomment when nRF24 ready
    }

    // ── Heartbeat LED (blink every 500ms in sim, 2s in live) ──
    uint16_t blink_rate = sim_mode ? 500 : 2000;
    if (now - last_led_toggle >= blink_rate) {
        last_led_toggle = now;
        digitalWrite(LED_PIN, !digitalRead(LED_PIN));
    }
}

// ============================================================
// SIMULATION
// ============================================================

void update_sim_data() {
    uint32_t now = millis();

    // ── Shift logic: cycle through all 6 gears ──
    if (sim_clutch_ticks > 0) {
        // Mid-shift: clutch in, RPM drops
        sim_clutch_ticks--;
        sim_rpm = max((int16_t)2000, (int16_t)(sim_rpm - 200));
        current_data.clutch_in = true;
        current_data.gear = 0;
    } else if (sim_accel) {
        // Rev up in current gear
        sim_rpm += random(5, 9);  // ~50-90 per 100Hz tick
        current_data.clutch_in = false;
        current_data.gear = sim_gear + 1;

        if (sim_rpm >= 12500) {
            if (sim_gear < 5) {
                sim_clutch_ticks = 4;   // ~40ms clutch pull
                sim_gear++;
            } else {
                sim_accel = false;      // top gear, start decel
            }
        }
    } else {
        // Engine braking back down
        sim_rpm -= random(4, 7);
        current_data.clutch_in = false;
        current_data.gear = sim_gear + 1;

        if (sim_rpm <= 4000) {
            if (sim_gear > 0) {
                sim_clutch_ticks = 3;
                sim_gear--;
                sim_rpm = 8000;         // RPM jumps on downshift
            } else {
                sim_accel = true;       // back in 1st, start over
                sim_rpm = 3000;
            }
        }
    }

    // Clamp
    sim_rpm = constrain(sim_rpm, 2000, 14000);
    current_data.rpm = sim_rpm;

    // Speed from RPM + gear using precomputed RPM_PER_MPH
    // speed = rpm / rpm_per_mph[gear]
    if (RPM_PER_MPH[sim_gear] > 0) {
        current_data.speed_mph = max(0, (int)((float)sim_rpm / RPM_PER_MPH[sim_gear]));
    } else {
        current_data.speed_mph = 0;
    }

    // Throttle/brake
    if (current_data.clutch_in) {
        current_data.throttle_pct = 0;
        current_data.brake_pct = 0;
    } else if (sim_accel) {
        current_data.throttle_pct = min(100, (int)(60 + (sim_rpm - 3000) / 20));
        current_data.brake_pct = 0;
    } else {
        current_data.throttle_pct = 0;
        current_data.brake_pct = min(100, (int)(30 + (8000 - sim_rpm) / 15));
    }

    // Realistic-ish sensor values
    current_data.coolant_temp_f = 180 + random(0, 30);
    current_data.oil_pressure_psi = 40 + random(0, 25);
    current_data.afr_x10 = 140 + random(0, 15);
    current_data.battery_voltage = 13.2 + random(0, 10) / 10.0;

    // Fake GPS
    current_data.lat = 40.7128;
    current_data.lon = -74.0060;
    current_data.gps_speed_mph = current_data.speed_mph * 0.95;
    current_data.gps_alt_ft = 33.0;
    current_data.gps_satellites = 8;
    current_data.gps_fix = true;

    // IMU
    float spd_frac = current_data.speed_mph / 150.0f;
    current_data.accel_x_g = sin(now / 2000.0f) * spd_frac * 1.5f;
    current_data.accel_y_g = sim_accel && !current_data.clutch_in ? 0.5f : (!sim_accel && !current_data.clutch_in ? -0.6f : 0.0f);
    current_data.accel_z_g = 1.0f + sin(now / 500.0f) * 0.05f;
}

// ============================================================
// CAN BUS
// ============================================================

void init_can() {
    // TODO: Initialize STM32 bxCAN peripheral at CAN_BITRATE
    // 
    // Using STM32 HAL or libmaple CAN:
    //   CAN.begin(CAN_BITRATE);
    //   CAN.setFilter(CAN_ID_RPM_STATUS, 0x7F0);  // Accept 0x5F0-0x5FF
    //
    // The STM32F103RCT6 has a built-in CAN controller on PA11/PA12.
    // You still need the SN65HVD230 transceiver for the physical layer.
    //
    // Libraries to consider:
    //   - eXoCAN (lightweight, STM32-native)
    //   - STM32_CAN
    //   - HAL_CAN (via STM32Cube)
    
    PI_SERIAL.println("# CAN initialized (stub)");
}

void read_can() {
    // TODO: Poll CAN for new frames and decode Speeduino data
    //
    // Pseudocode:
    // if (CAN.available()) {
    //     CanMsg msg;
    //     CAN.read(msg);
    //     
    //     switch (msg.id) {
    //         case CAN_ID_RPM_STATUS:
    //             current_data.rpm = (msg.data[0] << 8) | msg.data[1];
    //             break;
    //         case CAN_ID_CLT_IAT:
    //             // Speeduino sends in °F or °C depending on tune
    //             // Convert to °F if needed
    //             current_data.coolant_temp_f = (msg.data[0] << 8) | msg.data[1];
    //             break;
    //         case CAN_ID_THROTTLE:
    //             current_data.throttle_pct = msg.data[0];
    //             current_data.map_kpa = (msg.data[2] << 8) | msg.data[3];
    //             break;
    //         case CAN_ID_FUEL:
    //             current_data.afr_x10 = msg.data[0];
    //             break;
    //     }
    // }
}

// ============================================================
// GPS
// ============================================================

void init_gps() {
    // GPS should start outputting NMEA at default 9600 baud
    // Optional: send UBX commands to set 10Hz update rate
    PI_SERIAL.println("# GPS initialized");
}

void read_gps() {
    // Feed all available bytes to TinyGPS++
    while (GPS_SERIAL.available()) {
        gps.encode(GPS_SERIAL.read());
    }

    if (gps.location.isUpdated()) {
        current_data.lat = gps.location.lat();
        current_data.lon = gps.location.lng();
        current_data.gps_fix = true;
    }

    if (gps.speed.isUpdated()) {
        current_data.gps_speed_mph = gps.speed.mph();
    }

    if (gps.altitude.isUpdated()) {
        current_data.gps_alt_ft = gps.altitude.feet();
    }

    current_data.gps_satellites = gps.satellites.value();
    
    if (gps.satellites.value() == 0) {
        current_data.gps_fix = false;
    }
}

// ============================================================
// IMU (MPU-6050)
// ============================================================

bool imu_ok = false;

void init_imu() {
    Wire.begin();               // PB6=SCL, PB7=SDA on STM32F103
    Wire.setClock(400000);      // 400kHz fast I2C

    // Wake up MPU-6050 (default is sleep mode)
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(0x6B);           // PWR_MGMT_1 register
    Wire.write(0x00);           // Clear sleep bit
    Wire.endTransmission(true);
    delay(10);

    // Set accelerometer to ±4g range (good for FSAE: max ~2-3g)
    // Register 0x1C: 0x08 = ±4g (sensitivity: 8192 LSB/g)
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(0x1C);           // ACCEL_CONFIG register
    Wire.write(0x08);           // ±4g
    Wire.endTransmission(true);

    // Set low-pass filter to 44Hz (smooths vibration noise)
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(0x1A);           // CONFIG register
    Wire.write(0x03);           // DLPF = 44Hz
    Wire.endTransmission(true);

    // Verify device is responding
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(0x75);           // WHO_AM_I register
    Wire.endTransmission(false);
    Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)1, (uint8_t)true);
    if (Wire.available()) {
        uint8_t who = Wire.read();
        if (who == 0x68 || who == 0x72) {  // MPU6050 or MPU6500
            imu_ok = true;
            PI_SERIAL.println("# IMU MPU-6050 OK");
        } else {
            PI_SERIAL.print("# IMU unknown ID: 0x");
            PI_SERIAL.println(who, HEX);
        }
    } else {
        PI_SERIAL.println("# IMU not found on I2C");
    }
}

void read_imu() {
    if (!imu_ok) return;

    // Read 6 bytes of accelerometer data (registers 0x3B-0x40)
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(0x3B);           // ACCEL_XOUT_H
    Wire.endTransmission(false);
    Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)6, (uint8_t)true);

    if (Wire.available() >= 6) {
        int16_t ax_raw = (Wire.read() << 8) | Wire.read();
        int16_t ay_raw = (Wire.read() << 8) | Wire.read();
        int16_t az_raw = (Wire.read() << 8) | Wire.read();

        // Convert to g-force (±4g range = 8192 LSB/g)
        // Orientation: mount board flat, chip up
        //   X axis = lateral (positive = right turn)
        //   Y axis = longitudinal (positive = acceleration)
        //   Z axis = vertical (positive = up, ~1.0g at rest)
        // Adjust signs here if your mounting orientation differs!
        current_data.accel_x_g = ax_raw / 8192.0f;
        current_data.accel_y_g = ay_raw / 8192.0f;
        current_data.accel_z_g = az_raw / 8192.0f;
    }
}

// ============================================================
// ANALOG SENSORS
// ============================================================

void read_analog() {
    // 12-bit ADC on STM32 (0-4095 = 0-3.3V)
    // Use voltage dividers for 5V sensors!
    current_data.analog_0_raw = analogRead(ANALOG_0_PIN);
    current_data.analog_1_raw = analogRead(ANALOG_1_PIN);

    // Example: convert analog_0 to brake pressure PSI
    // Assuming 0.5V-4.5V sensor through 2:1 divider = 0.25V-2.25V at ADC
    // current_data.brake_pct = map(current_data.analog_0_raw, 310, 2790, 0, 100);
}

// ============================================================
// VEHICLE SPEED SENSOR (VSS) — Interrupt-driven pulse counting
// ============================================================
//
// The CBR 600RR speed sensor is a reluctor (passive magnetic pickup)
// reading 28 teeth on the countershaft 3rd gear. It outputs an AC
// sine wave that must be conditioned into a 3.3V square wave using
// an LM393 comparator before connecting to the STM32.
//
// Speed calculation uses a single calibration value:
//   speed_mph = pulse_frequency / VSS_PULSES_PER_MPH
//
// This value is configurable from the Pi settings screen.
// At low speed: few pulses, so we measure period between pulses.
// At high speed: thousands of pulses/sec, very accurate.
// Below ~2 mph: too few pulses for reliable measurement, reads 0.

volatile uint32_t vss_last_pulse_us = 0;   // micros() of last valid pulse
volatile uint32_t vss_period_us = 0;       // time between last two pulses
volatile uint32_t vss_pulse_count = 0;     // total pulse count (for distance)

void vss_isr() {
    uint32_t now_us = micros();
    uint32_t dt = now_us - vss_last_pulse_us;

    // Debounce: reject pulses faster than physically possible
    if (dt < VSS_MIN_PERIOD_US) return;

    vss_period_us = dt;
    vss_last_pulse_us = now_us;
    vss_pulse_count++;
}

void init_vss() {
    pinMode(VSS_PIN, INPUT_PULLUP);
    attachInterrupt(digitalPinToInterrupt(VSS_PIN), vss_isr, RISING);
    PI_SERIAL.println("# VSS initialized on PB3 (28 teeth/rev)");
}

void update_speed_from_vss() {
    // Check for timeout (vehicle stopped)
    uint32_t now_us = micros();
    uint32_t elapsed = now_us - vss_last_pulse_us;

    if (elapsed > VSS_TIMEOUT_US || vss_period_us == 0) {
        current_data.speed_mph = 0;
        return;
    }

    // Read the period (volatile, so grab a local copy)
    noInterrupts();
    uint32_t period = vss_period_us;
    interrupts();

    // speed = pulse_frequency / VSS_PULSES_PER_MPH
    float freq = 1000000.0f / (float)period;
    float speed_mph = freq / VSS_PULSES_PER_MPH;

    current_data.speed_mph = (uint16_t)max(0.0f, min(speed_mph, 255.0f));
}

// ============================================================
// CLUTCH & GEAR DETECTION
// ============================================================

void read_clutch() {
    // Clutch switch: closed (LOW) = clutch lever pulled = disengaged
    current_data.clutch_in = (digitalRead(CLUTCH_PIN) == LOW);
}

void calculate_gear() {
    // Detect current gear by comparing actual RPM to expected RPM
    // at the current speed for each gear.
    //
    // RPM_PER_MPH[g] is precomputed at boot from VSS_PULSES_PER_MPH,
    // so it automatically stays in sync with the speed calibration.
    //
    // expected_rpm = speed_mph × RPM_PER_MPH[g]
    // Pick the gear whose expected RPM is closest to actual RPM.

    if (current_data.clutch_in) {
        current_data.gear = 0;
        return;
    }

    uint16_t rpm = current_data.rpm;
    uint16_t speed = current_data.speed_mph;

    if (rpm < 1500 || speed < 5) {
        current_data.gear = 0;
        return;
    }

    float best_error = 999999.0f;
    uint8_t best_gear = 0;

    for (uint8_t g = 0; g < NUM_GEARS; g++) {
        float expected_rpm = (float)speed * RPM_PER_MPH[g];
        float error = fabsf((float)rpm - expected_rpm);
        float error_pct = error / expected_rpm;

        if (error_pct < GEAR_MATCH_TOL && error < best_error) {
            best_error = error;
            best_gear = g + 1;
        }
    }

    current_data.gear = best_gear;
}

// ============================================================
// SD CARD LOGGING
// ============================================================

void init_sd() {
    PI_SERIAL.print("# SD card init... ");

    // SPI1 is default on STM32, CS on PA4
    if (!SD.begin(SD_CS_PIN)) {
        PI_SERIAL.println("FAILED");
        sd_ok = false;
        return;
    }

    sd_ok = true;
    PI_SERIAL.println("OK");
    create_new_logfile();
}

void create_new_logfile() {
    // Find next available log number: LOG_001.csv, LOG_002.csv, etc
    for (int i = 1; i <= MAX_LOG_FILES; i++) {
        snprintf(log_filename, sizeof(log_filename), "LOG_%03d.csv", i);
        if (!SD.exists(log_filename)) {
            break;
        }
    }

    log_file = SD.open(log_filename, FILE_WRITE);
    if (!log_file) {
        PI_SERIAL.println("# SD file create FAILED");
        sd_ok = false;
        return;
    }

    // Write CSV header
    log_file.println("TIME_MS,RPM,SPEED_MPH,THROTTLE,BRAKE,"
                     "CLT_F,OIL_PSI,AFR_X10,VOLTS,"
                     "LAT,LON,GPS_SPD_MPH,GPS_ALT_FT,GPS_SATS,GPS_FIX,"
                     "AN0,AN1,ACCEL_X,ACCEL_Y,ACCEL_Z,GEAR,CLUTCH");
    log_file.flush();

    PI_SERIAL.print("# Logging to: ");
    PI_SERIAL.println(log_filename);
}

void log_to_sd() {
    if (!log_file) return;

    SensorData *d = &current_data;

    // Full-rate CSV with all fields
    log_file.print(d->timestamp_ms);    log_file.print(',');
    log_file.print(d->rpm);             log_file.print(',');
    log_file.print(d->speed_mph);       log_file.print(',');
    log_file.print(d->throttle_pct);    log_file.print(',');
    log_file.print(d->brake_pct);       log_file.print(',');
    log_file.print(d->coolant_temp_f);  log_file.print(',');
    log_file.print(d->oil_pressure_psi);log_file.print(',');
    log_file.print(d->afr_x10);         log_file.print(',');
    log_file.print(d->battery_voltage, 1); log_file.print(',');
    log_file.print(d->lat, 6);          log_file.print(',');
    log_file.print(d->lon, 6);          log_file.print(',');
    log_file.print(d->gps_speed_mph, 1);log_file.print(',');
    log_file.print(d->gps_alt_ft, 1);   log_file.print(',');
    log_file.print(d->gps_satellites);   log_file.print(',');
    log_file.print(d->gps_fix ? 1 : 0); log_file.print(',');
    log_file.print(d->analog_0_raw);     log_file.print(',');
    log_file.print(d->analog_1_raw);     log_file.print(',');
    log_file.print(d->accel_x_g, 3);    log_file.print(',');
    log_file.print(d->accel_y_g, 3);    log_file.print(',');
    log_file.print(d->accel_z_g, 3);    log_file.print(',');
    log_file.print(d->gear);            log_file.print(',');
    log_file.println(d->clutch_in ? 1 : 0);
}

// ============================================================
// UART TO PI (CSV)
// ============================================================

void send_to_pi() {
    SensorData *d = &current_data;

    // Lighter CSV for display — Pi only needs these for the dash
    // Format: RPM,SPEED,THROTTLE,BRAKE,CLT,OIL,LAT,LON,GPS_SPD,GPS_SATS,AX,AY,AZ,GEAR,CLUTCH
    PI_SERIAL.print(d->rpm);             PI_SERIAL.print(',');
    PI_SERIAL.print(d->speed_mph);       PI_SERIAL.print(',');
    PI_SERIAL.print(d->throttle_pct);    PI_SERIAL.print(',');
    PI_SERIAL.print(d->brake_pct);       PI_SERIAL.print(',');
    PI_SERIAL.print(d->coolant_temp_f);  PI_SERIAL.print(',');
    PI_SERIAL.print(d->oil_pressure_psi);PI_SERIAL.print(',');
    PI_SERIAL.print(d->lat, 6);          PI_SERIAL.print(',');
    PI_SERIAL.print(d->lon, 6);          PI_SERIAL.print(',');
    PI_SERIAL.print(d->gps_speed_mph, 1);PI_SERIAL.print(',');
    PI_SERIAL.print(d->gps_satellites);  PI_SERIAL.print(',');
    PI_SERIAL.print(d->accel_x_g, 2);   PI_SERIAL.print(',');
    PI_SERIAL.print(d->accel_y_g, 2);   PI_SERIAL.print(',');
    PI_SERIAL.print(d->accel_z_g, 2);   PI_SERIAL.print(',');
    PI_SERIAL.print(d->gear);           PI_SERIAL.print(',');
    PI_SERIAL.println(d->clutch_in ? 1 : 0);
}

// ============================================================
// nRF24 TELEMETRY (to pit)
// ============================================================

void init_nrf() {
    // TODO: Initialize RF24 on SPI2
    //
    // #include <RF24.h>
    // RF24 radio(NRF_CE_PIN, NRF_CSN_PIN);
    // radio.begin();
    // radio.setPALevel(RF24_PA_MAX);
    // radio.setDataRate(RF24_250KBPS);  // Longer range
    // radio.setChannel(108);            // Less congested
    // radio.openWritingPipe(0xF0F0F0F0E1LL);
    // radio.stopListening();
    
    PI_SERIAL.println("# nRF24 initialized (stub)");
}

void send_to_nrf() {
    // TODO: Pack key data into a struct and transmit
    //
    // struct TelemetryPacket {
    //     uint16_t rpm;
    //     uint16_t speed;
    //     uint8_t  throttle;
    //     uint8_t  brake;
    //     int16_t  clt;
    //     uint8_t  oil;
    //     float    lat;
    //     float    lon;
    // };  // 18 bytes, fits in single nRF24 payload (32 max)
    //
    // TelemetryPacket pkt = { ... };
    // radio.write(&pkt, sizeof(pkt));
}