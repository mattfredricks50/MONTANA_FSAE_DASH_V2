/*
 * Race Dash - Arduino Nano Firmware
 *
 * Reads from Speeduino via RS232 secondary serial, GPS, IMU, thermocouples,
 * VSS wheel speed, and sends CSV to Raspberry Pi for display.
 *
 * HARDWARE CONNECTIONS:
 *
 *   Hardware Serial (shared, 115200):
 *     D0 (RX) ← Speeduino secondary serial TX  (TTL 5V, direct)
 *     D1 (TX) → Pi GPIO15 (RX)
 *              ⚠ NANO IS 5V — Pi GPIO is 3.3V MAX
 *              Use a voltage divider on D1:
 *                D1 → 10KΩ → Pi GPIO15
 *                           → 20KΩ → GND
 *
 *   SoftwareSerial GPS (9600):
 *     D4 (RX) ← GPS TX (u-blox NEO-6M/7M)
 *     GPS TX is 3.3V — fine into Nano 5V RX (above VIH threshold)
 *
 *   SPI → SD Card (5V module):
 *     D10 = CS
 *     D11 = MOSI
 *     D12 = MISO
 *     D13 = SCK
 *
 *   I2C → MPU-6050 + 4x MCP9600 (all share the bus):
 *     A4  = SDA
 *     A5  = SCL
 *     ⚠ MPU-6050 is 3.3V — use a 3.3V breakout with level shifters
 *       or add 4.7KΩ pull-ups to 3.3V (not 5V!) on SDA/SCL
 *     MCP9600 is 3.3-5V tolerant — check your breakout
 *
 *   Digital Inputs:
 *     D2  = VSS pulse (rising edge interrupt, from LM393 comparator)
 *     D5  = Clutch switch (LOW = clutch in, internal pullup)
 *     D6  = Sim mode jumper (pull LOW = sim mode, internal pullup)
 *
 *   Analog Inputs (0-5V direct — Nano ADC is 5V):
 *     A0  = Brake pressure sensor
 *     A1  = Steering angle pot
 *
 *   LED:
 *     D9  = Status LED (D13 is shared with SCK, avoid it)
 *
 * SPEEDUINO SECONDARY SERIAL:
 *   Send byte 'A' (0x41) to request real-time data packet.
 *   Response: SPEEDUINO_PACKET_LEN bytes.
 *   ⚠ VERIFY byte offsets below match your Speeduino firmware version!
 *   Reference: https://wiki.speeduino.com/en/Secondary_Serial_IO_interface
 *
 * CSV TO PI:
 *   RPM,SPEED,THROTTLE,BRAKE,CLT,OIL,LAT,LON,GPS_SPD,GPS_SATS,
 *   AX,AY,AZ,GEAR,CLUTCH,T1,T2,T3,T4
 *
 * ALL UNITS: imperial (°F, mph, psi)
 */

#include <Arduino.h>
#include <SoftwareSerial.h>
#include <SPI.h>
#include <Wire.h>
#include <SD.h>
#include <TinyGPSPlus.h>

// ============================================================
// PIN DEFINITIONS
// ============================================================

#define GPS_RX_PIN      4       // SoftwareSerial GPS receive
#define GPS_TX_PIN      255     // GPS TX not needed (255 = unused)
#define VSS_PIN         2       // Speed sensor pulse (INT0)
#define CLUTCH_PIN      5       // Clutch switch (LOW = engaged)
#define SIM_MODE_PIN    6       // Pull LOW = simulation mode
#define SD_CS_PIN       10      // SD card chip select
#define LED_PIN         9       // Status LED

// I2C devices (A4=SDA, A5=SCL — hardware fixed on Nano)
#define MPU6050_ADDR    0x68

#define MCP9600_COUNT   4
const uint8_t MCP9600_ADDR[MCP9600_COUNT] = {0x60, 0x61, 0x62, 0x63};
#define MCP9600_REG_HOT_JUNCTION  0x00
#define MCP9600_REG_DEVICE_ID     0x20

// ============================================================
// SPEEDUINO SECONDARY SERIAL CONFIG
// ⚠ Check these against your Speeduino firmware version!
// Reference: https://wiki.speeduino.com/en/Secondary_Serial_IO_interface
// ============================================================

#define SPEEDUINO_REQUEST_CMD   0x41    // 'A' = request real-time data
#define SPEEDUINO_PACKET_LEN    65      // Response packet length in bytes
#define SPEEDUINO_TIMEOUT_MS    50      // Max wait for response

// Byte offsets into the response packet (0-indexed):
#define SPD_RPM_HIGH    14      // RPM high byte (RPM = (high << 8) | low)
#define SPD_RPM_LOW     15      // RPM low byte
#define SPD_CLT         7       // Coolant temp (°C = byte - 40)
#define SPD_TPS         22      // Throttle (0-255, % = value / 2.55)
#define SPD_BATT        9       // Battery x10 (V = byte / 10.0)
#define SPD_AFR         10      // AFR x10 (AFR = byte / 10.0)
#define SPD_MAP_HIGH    4       // MAP high byte (kPa)
#define SPD_MAP_LOW     5       // MAP low byte

// ============================================================
// DRIVETRAIN CONFIG (CBR 600RR — adjust for your engine)
// ============================================================

#define NUM_GEARS       6
const float GEAR_RATIOS[NUM_GEARS] = {2.666f, 1.937f, 1.661f, 1.409f, 1.260f, 1.166f};
const float PRIMARY_RATIO   = 2.111f;
const float VSS_TEETH       = 28.0f;
float VSS_PULSES_PER_MPH    = 16.65f;  // Calibrate for your sprockets/tire
float RPM_PER_MPH[NUM_GEARS];
const float GEAR_MATCH_TOL  = 0.10f;

// VSS debounce / timeout
#define VSS_MIN_PERIOD_US   200UL
#define VSS_TIMEOUT_US      100000UL

// ============================================================
// TIMING
// ============================================================

#define PI_SEND_INTERVAL_MS     40      // 25Hz to Pi
#define SD_LOG_INTERVAL_MS      50      // 20Hz SD logging
#define SD_FLUSH_INTERVAL_MS    2000    // Flush every 2s
#define GPS_PARSE_INTERVAL_MS   200     // 5Hz GPS parse
#define SPEEDUINO_INTERVAL_MS   40      // 25Hz ECU poll

// ============================================================
// DATA STRUCTURE
// ============================================================

struct SensorData {
    // Engine (from Speeduino)
    uint16_t rpm;
    uint8_t  throttle_pct;
    int16_t  coolant_temp_f;
    uint8_t  afr_x10;
    uint16_t map_kpa;
    float    battery_voltage;

    // Derived
    uint16_t speed_mph;
    uint8_t  gear;
    bool     clutch_in;
    uint8_t  brake_pct;     // From analog sensor

    // GPS
    double   lat;
    double   lon;
    float    gps_speed_mph;
    float    gps_alt_ft;
    uint8_t  gps_satellites;
    bool     gps_fix;

    // IMU (MPU-6050)
    float    accel_x_g;
    float    accel_y_g;
    float    accel_z_g;

    // Thermocouples (MCP9600 x4) in °F
    float    temp1_f;
    float    temp2_f;
    float    temp3_f;
    float    temp4_f;

    uint32_t timestamp_ms;
};

// ============================================================
// GLOBALS
// ============================================================

SensorData d;
TinyGPSPlus gps;
SoftwareSerial gpsSerial(GPS_RX_PIN, GPS_TX_PIN);

bool sim_mode  = false;
bool sd_ok     = false;
bool imu_ok    = false;
bool mcp_ok[MCP9600_COUNT] = {false};
File log_file;
char log_filename[16];

// VSS (interrupt-driven)
volatile uint32_t vss_last_us   = 0;
volatile uint32_t vss_period_us = 0;
volatile bool     vss_fresh     = false;

// Speeduino packet buffer
uint8_t spd_buf[SPEEDUINO_PACKET_LEN];

// Timing
uint32_t last_pi_send       = 0;
uint32_t last_sd_log        = 0;
uint32_t last_sd_flush      = 0;
uint32_t last_gps_parse     = 0;
uint32_t last_speeduino     = 0;
uint32_t last_led_toggle    = 0;

// Sim state
float    sim_rpm   = 3000;
uint8_t  sim_gear  = 0;
bool     sim_accel = true;
uint8_t  sim_clutch_ticks = 0;

// ============================================================
// FORWARD DECLARATIONS
// ============================================================

void recalc_drivetrain();
void init_sd();
void init_imu();
void init_mcp9600();
void init_vss();
void read_speeduino();
void read_analog();
void read_imu();
void read_mcp9600();
void read_clutch();
void read_gps();
void calculate_gear();
void update_speed_from_vss();
void update_sim_data();
void log_to_sd();
void send_to_pi();

// ============================================================
// VSS INTERRUPT
// ============================================================

void vss_isr() {
    uint32_t now = micros();
    uint32_t period = now - vss_last_us;
    if (period >= VSS_MIN_PERIOD_US) {
        vss_period_us = period;
        vss_last_us   = now;
        vss_fresh     = true;
    }
}

// ============================================================
// SETUP
// ============================================================

void setup() {
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, HIGH);    // LED on

    pinMode(SIM_MODE_PIN, INPUT_PULLUP);
    pinMode(CLUTCH_PIN,   INPUT_PULLUP);
    delay(10);
    sim_mode = (digitalRead(SIM_MODE_PIN) == LOW);

    // Hardware serial — shared Speeduino RX + Pi TX
    Serial.begin(115200);
    Serial.println(F("# Race Dash Nano starting..."));
    Serial.print(F("# Mode: "));
    Serial.println(sim_mode ? F("SIMULATION") : F("LIVE SENSORS"));

    memset(&d, 0, sizeof(d));

    // GPS software serial
    if (!sim_mode) {
        gpsSerial.begin(9600);
        Serial.println(F("# GPS SoftwareSerial started"));
    }

    // SD card
    init_sd();

    // IMU and thermocouples
    Wire.begin();
    Wire.setClock(400000);
    init_imu();
    init_mcp9600();

    // Drivetrain tables
    recalc_drivetrain();

    // VSS interrupt
    if (!sim_mode) {
        init_vss();
    }

    Serial.println(F("# CSV: RPM,SPEED,THROTTLE,BRAKE,CLT,OIL,LAT,LON,GPS_SPD,GPS_SATS,AX,AY,AZ,GEAR,CLUTCH,T1,T2,T3,T4"));
    Serial.println(F("# Ready"));
    digitalWrite(LED_PIN, LOW);     // LED off — setup done
}

// ============================================================
// MAIN LOOP
// ============================================================

void loop() {
    uint32_t now = millis();

    if (sim_mode) {
        update_sim_data();
    } else {
        // Poll Speeduino ECU at 25Hz
        if (now - last_speeduino >= SPEEDUINO_INTERVAL_MS) {
            last_speeduino = now;
            read_speeduino();
        }

        read_analog();
        read_imu();
        read_mcp9600();
        read_clutch();
        update_speed_from_vss();
        calculate_gear();

        if (now - last_gps_parse >= GPS_PARSE_INTERVAL_MS) {
            last_gps_parse = now;
            read_gps();
        }
    }

    d.timestamp_ms = now;

    if (sd_ok && (now - last_sd_log >= SD_LOG_INTERVAL_MS)) {
        last_sd_log = now;
        log_to_sd();
    }

    if (sd_ok && (now - last_sd_flush >= SD_FLUSH_INTERVAL_MS)) {
        last_sd_flush = now;
        log_file.flush();
    }

    if (now - last_pi_send >= PI_SEND_INTERVAL_MS) {
        last_pi_send = now;
        send_to_pi();
    }

    // Heartbeat LED
    uint16_t blink = sim_mode ? 500 : 2000;
    if (now - last_led_toggle >= blink) {
        last_led_toggle = now;
        digitalWrite(LED_PIN, !digitalRead(LED_PIN));
    }
}

// ============================================================
// DRIVETRAIN
// ============================================================

void recalc_drivetrain() {
    float cs_rps_per_mph = VSS_PULSES_PER_MPH / VSS_TEETH;
    for (uint8_t g = 0; g < NUM_GEARS; g++) {
        RPM_PER_MPH[g] = cs_rps_per_mph * PRIMARY_RATIO * GEAR_RATIOS[g] * 60.0f;
    }
}

// ============================================================
// SPEEDUINO SECONDARY SERIAL
// ============================================================

void read_speeduino() {
    // Flush any stale bytes
    while (Serial.available()) Serial.read();

    // Request real-time data
    Serial.write(SPEEDUINO_REQUEST_CMD);

    // Wait for response
    uint32_t start = millis();
    uint8_t  idx   = 0;
    while (idx < SPEEDUINO_PACKET_LEN) {
        if (millis() - start > SPEEDUINO_TIMEOUT_MS) return; // Timeout
        if (Serial.available()) {
            spd_buf[idx++] = Serial.read();
        }
    }

    // Parse packet
    d.rpm          = ((uint16_t)spd_buf[SPD_RPM_HIGH] << 8) | spd_buf[SPD_RPM_LOW];
    d.coolant_temp_f = (int16_t)((spd_buf[SPD_CLT] - 40) * 9 / 5 + 32); // °C → °F
    d.throttle_pct = (uint8_t)(spd_buf[SPD_TPS] / 2.55f);
    d.battery_voltage = spd_buf[SPD_BATT] / 10.0f;
    d.afr_x10      = spd_buf[SPD_AFR];
    d.map_kpa      = ((uint16_t)spd_buf[SPD_MAP_HIGH] << 8) | spd_buf[SPD_MAP_LOW];
}

// ============================================================
// ANALOG (brake pressure, steering)
// ============================================================

void read_analog() {
    // Nano ADC is 10-bit (0-1023), 5V reference
    // Brake: 0-100 psi sensor → 0.5-4.5V → map to psi
    uint16_t brake_raw = analogRead(A0);
    // Map 0-1023 → 0-100 (simple linear, calibrate for your sensor)
    d.brake_pct = (uint8_t)map(brake_raw, 0, 1023, 0, 100);
}

// ============================================================
// IMU (MPU-6050)
// ============================================================

void init_imu() {
    // Wake up
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(0x6B); Wire.write(0x00);
    Wire.endTransmission(true);
    delay(10);

    // ±4g range
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(0x1C); Wire.write(0x08);
    Wire.endTransmission(true);

    // 44Hz low-pass filter
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(0x1A); Wire.write(0x03);
    Wire.endTransmission(true);

    // Check WHO_AM_I
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(0x75);
    Wire.endTransmission(false);
    Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)1, (uint8_t)true);
    if (Wire.available()) {
        uint8_t who = Wire.read();
        imu_ok = (who == 0x68 || who == 0x72);
        Serial.print(F("# IMU: "));
        Serial.println(imu_ok ? F("OK") : F("not found"));
    }
}

void read_imu() {
    if (!imu_ok) return;
    Wire.beginTransmission(MPU6050_ADDR);
    Wire.write(0x3B);
    Wire.endTransmission(false);
    Wire.requestFrom((uint8_t)MPU6050_ADDR, (uint8_t)6, (uint8_t)true);
    if (Wire.available() >= 6) {
        int16_t ax = (Wire.read() << 8) | Wire.read();
        int16_t ay = (Wire.read() << 8) | Wire.read();
        int16_t az = (Wire.read() << 8) | Wire.read();
        d.accel_x_g = ax / 8192.0f;
        d.accel_y_g = ay / 8192.0f;
        d.accel_z_g = az / 8192.0f;
    }
}

// ============================================================
// THERMOCOUPLES (MCP9600 x4)
// ============================================================

void init_mcp9600() {
    for (uint8_t i = 0; i < MCP9600_COUNT; i++) {
        Wire.beginTransmission(MCP9600_ADDR[i]);
        Wire.write(MCP9600_REG_DEVICE_ID);
        if (Wire.endTransmission(false) != 0) {
            Serial.print(F("# Temp")); Serial.print(i + 1); Serial.println(F(" not found"));
            continue;
        }
        Wire.requestFrom(MCP9600_ADDR[i], (uint8_t)2);
        if (Wire.available() >= 2) {
            uint8_t id = Wire.read(); Wire.read();
            mcp_ok[i] = ((id & 0xFC) == 0x40);
            Serial.print(F("# Temp")); Serial.print(i + 1);
            Serial.println(mcp_ok[i] ? F(": OK") : F(": unknown ID"));
        }
        // Type K, filter off
        Wire.beginTransmission(MCP9600_ADDR[i]);
        Wire.write(0x05); Wire.write(0x00);
        Wire.endTransmission(true);
    }
}

void read_mcp9600() {
    float *temps[MCP9600_COUNT] = {&d.temp1_f, &d.temp2_f, &d.temp3_f, &d.temp4_f};
    for (uint8_t i = 0; i < MCP9600_COUNT; i++) {
        if (!mcp_ok[i]) continue;
        Wire.beginTransmission(MCP9600_ADDR[i]);
        Wire.write(MCP9600_REG_HOT_JUNCTION);
        if (Wire.endTransmission(false) != 0) continue;
        Wire.requestFrom(MCP9600_ADDR[i], (uint8_t)2);
        if (Wire.available() >= 2) {
            int16_t raw = ((int16_t)Wire.read() << 8) | Wire.read();
            float c = raw * 0.0625f;
            *temps[i] = c * 9.0f / 5.0f + 32.0f;  // °C → °F
        }
    }
}

// ============================================================
// CLUTCH
// ============================================================

void read_clutch() {
    d.clutch_in = (digitalRead(CLUTCH_PIN) == LOW);
}

// ============================================================
// GPS
// ============================================================

void read_gps() {
    // Drain software serial buffer into TinyGPS
    while (gpsSerial.available()) {
        gps.encode(gpsSerial.read());
    }
    if (gps.location.isValid()) {
        d.lat = gps.location.lat();
        d.lon = gps.location.lng();
        d.gps_fix = true;
    } else {
        d.gps_fix = false;
    }
    if (gps.speed.isValid())    d.gps_speed_mph = gps.speed.mph();
    if (gps.altitude.isValid()) d.gps_alt_ft    = gps.altitude.feet();
    if (gps.satellites.isValid()) d.gps_satellites = gps.satellites.value();
}

// ============================================================
// VEHICLE SPEED SENSOR
// ============================================================

void init_vss() {
    pinMode(VSS_PIN, INPUT);
    attachInterrupt(digitalPinToInterrupt(VSS_PIN), vss_isr, RISING);
    Serial.println(F("# VSS interrupt armed (D2)"));
}

void update_speed_from_vss() {
    uint32_t period;
    bool fresh;

    // Atomic read of ISR values
    noInterrupts();
    period = vss_period_us;
    fresh  = vss_fresh;
    vss_fresh = false;
    interrupts();

    // Timeout — if no pulse recently, speed = 0
    uint32_t elapsed;
    noInterrupts();
    elapsed = micros() - vss_last_us;
    interrupts();

    if (elapsed > VSS_TIMEOUT_US || !fresh) {
        d.speed_mph = 0;
        return;
    }

    if (period > 0) {
        // frequency = 1e6 / period_us  (Hz)
        // speed_mph = frequency / VSS_PULSES_PER_MPH
        float freq_hz = 1000000.0f / period;
        d.speed_mph = (uint16_t)(freq_hz / VSS_PULSES_PER_MPH);
    }
}

// ============================================================
// GEAR DETECTION
// ============================================================

void calculate_gear() {
    if (d.clutch_in || d.speed_mph < 3 || d.rpm < 800) {
        d.gear = 0;
        return;
    }
    float ratio = (float)d.rpm / (float)d.speed_mph;
    for (uint8_t g = 0; g < NUM_GEARS; g++) {
        float expected = RPM_PER_MPH[g];
        if (fabsf(ratio - expected) / expected <= GEAR_MATCH_TOL) {
            d.gear = g + 1;
            return;
        }
    }
    d.gear = 0;
}

// ============================================================
// SIMULATION
// ============================================================

void update_sim_data() {
    if (sim_clutch_ticks > 0) {
        sim_clutch_ticks--;
        sim_rpm = max(2000.0f, sim_rpm - 200.0f);
        d.clutch_in = true;
        d.gear = 0;
    } else if (sim_accel) {
        sim_rpm += random(5, 9);
        d.clutch_in = false;
        d.gear = sim_gear + 1;
        if (sim_rpm >= 12500) {
            if (sim_gear < 5) { sim_clutch_ticks = 4; sim_gear++; }
            else              { sim_accel = false; }
        }
    } else {
        sim_rpm -= random(4, 7);
        d.clutch_in = false;
        d.gear = sim_gear + 1;
        if (sim_rpm <= 4000) {
            if (sim_gear > 0) { sim_clutch_ticks = 3; sim_gear--; sim_rpm = 8000; }
            else              { sim_accel = true; sim_rpm = 3000; }
        }
    }

    sim_rpm = constrain(sim_rpm, 2000, 14000);
    d.rpm   = (uint16_t)sim_rpm;

    if (RPM_PER_MPH[sim_gear] > 0)
        d.speed_mph = (uint16_t)(sim_rpm / RPM_PER_MPH[sim_gear]);
    else
        d.speed_mph = 0;

    if (d.clutch_in) {
        d.throttle_pct = 0; d.brake_pct = 0;
    } else if (sim_accel) {
        d.throttle_pct = min(100, (int)(60 + (sim_rpm - 3000) / 20));
        d.brake_pct = 0;
    } else {
        d.throttle_pct = 0;
        d.brake_pct = min(100, (int)(30 + (8000 - sim_rpm) / 15));
    }

    d.coolant_temp_f    = 180 + random(0, 30);
    d.battery_voltage   = 13.2f + random(0, 10) / 10.0f;
    d.afr_x10           = 140 + random(0, 15);
    d.lat               = 40.7128;
    d.lon               = -74.0060;
    d.gps_speed_mph     = d.speed_mph * 0.95f;
    d.gps_satellites    = 8;
    d.gps_fix           = true;

    float spd = d.speed_mph / 150.0f;
    uint32_t t = millis();
    d.accel_x_g = sin(t / 2000.0f) * spd * 1.5f;
    d.accel_y_g = (sim_accel && !d.clutch_in) ? 0.5f : ((!sim_accel && !d.clutch_in) ? -0.6f : 0.0f);
    d.accel_z_g = 1.0f + sin(t / 500.0f) * 0.05f;

    float rf = sim_rpm / 13500.0f;
    d.temp1_f = 400 + rf * 800 + random(-10, 10);
    d.temp2_f = 380 + rf * 820 + random(-10, 10);
    d.temp3_f = 410 + rf * 790 + random(-10, 10);
    d.temp4_f = 390 + rf * 810 + random(-10, 10);
}

// ============================================================
// SD CARD LOGGING
// ============================================================

void init_sd() {
    if (!SD.begin(SD_CS_PIN)) {
        Serial.println(F("# SD init failed"));
        return;
    }
    // Find next available log file
    uint16_t n = 1;
    do {
        snprintf(log_filename, sizeof(log_filename), "LOG_%03d.csv", n++);
    } while (SD.exists(log_filename) && n < 999);

    log_file = SD.open(log_filename, FILE_WRITE);
    if (log_file) {
        log_file.println(F("MS,RPM,SPEED,THR,BRK,CLT,BATT,AFR,LAT,LON,GPS_SPD,GPS_ALT,SATS,FIX,AX,AY,AZ,GEAR,CLUTCH,T1,T2,T3,T4"));
        sd_ok = true;
        Serial.print(F("# Logging: ")); Serial.println(log_filename);
    } else {
        Serial.println(F("# SD open failed"));
    }
}

void log_to_sd() {
    if (!log_file) return;
    log_file.print(d.timestamp_ms);    log_file.print(',');
    log_file.print(d.rpm);             log_file.print(',');
    log_file.print(d.speed_mph);       log_file.print(',');
    log_file.print(d.throttle_pct);    log_file.print(',');
    log_file.print(d.brake_pct);       log_file.print(',');
    log_file.print(d.coolant_temp_f);  log_file.print(',');
    log_file.print(d.battery_voltage, 1); log_file.print(',');
    log_file.print(d.afr_x10);        log_file.print(',');
    log_file.print(d.lat, 6);          log_file.print(',');
    log_file.print(d.lon, 6);          log_file.print(',');
    log_file.print(d.gps_speed_mph, 1);log_file.print(',');
    log_file.print(d.gps_alt_ft, 1);   log_file.print(',');
    log_file.print(d.gps_satellites);  log_file.print(',');
    log_file.print(d.gps_fix ? 1 : 0); log_file.print(',');
    log_file.print(d.accel_x_g, 3);   log_file.print(',');
    log_file.print(d.accel_y_g, 3);   log_file.print(',');
    log_file.print(d.accel_z_g, 3);   log_file.print(',');
    log_file.print(d.gear);            log_file.print(',');
    log_file.print(d.clutch_in ? 1 : 0); log_file.print(',');
    log_file.print(d.temp1_f, 1);     log_file.print(',');
    log_file.print(d.temp2_f, 1);     log_file.print(',');
    log_file.print(d.temp3_f, 1);     log_file.print(',');
    log_file.println(d.temp4_f, 1);
}

// ============================================================
// UART TO PI (CSV)
// ============================================================

void send_to_pi() {
    // Oil pressure placeholder — Nano has no dedicated oil sensor input
    // Wire an analog pressure sensor to A2 and add read_analog() for it if needed
    const uint8_t oil_psi = 0;

    Serial.print(d.rpm);              Serial.print(',');
    Serial.print(d.speed_mph);        Serial.print(',');
    Serial.print(d.throttle_pct);     Serial.print(',');
    Serial.print(d.brake_pct);        Serial.print(',');
    Serial.print(d.coolant_temp_f);   Serial.print(',');
    Serial.print(oil_psi);            Serial.print(',');
    Serial.print(d.lat, 6);           Serial.print(',');
    Serial.print(d.lon, 6);           Serial.print(',');
    Serial.print(d.gps_speed_mph, 1); Serial.print(',');
    Serial.print(d.gps_satellites);   Serial.print(',');
    Serial.print(d.accel_x_g, 2);    Serial.print(',');
    Serial.print(d.accel_y_g, 2);    Serial.print(',');
    Serial.print(d.accel_z_g, 2);    Serial.print(',');
    Serial.print(d.gear);             Serial.print(',');
    Serial.print(d.clutch_in ? 1 : 0); Serial.print(',');
    Serial.print(d.temp1_f, 1);      Serial.print(',');
    Serial.print(d.temp2_f, 1);      Serial.print(',');
    Serial.print(d.temp3_f, 1);      Serial.print(',');
    Serial.println(d.temp4_f, 1);
}
