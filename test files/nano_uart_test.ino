/*
 * Race Dash — Arduino Nano UART Test Sketch
 * 
 * Mimics the STM32 firmware CSV output so you can test the Pi
 * dashboard with real hardware UART before the STM32 arrives.
 * 
 * Outputs the same 15-field CSV at 25Hz:
 *   RPM,SPEED,THROTTLE,BRAKE,CLT,OIL,LAT,LON,GPS_SPD,GPS_SATS,AX,AY,AZ,GEAR,CLUTCH
 *
 * Cycles through all 6 gears with realistic speed/RPM from
 * CBR 600RR drivetrain ratios, just like the real firmware.
 *
 * WIRING (Nano → Pi 3B+):
 * ─────────────────────────────────────────────────────────
 *
 *   Nano TX (pin 1) ──→ 1KΩ ──┬──→ Pi GPIO15 (RX)
 *                              │
 *                             2KΩ
 *                              │
 *                             GND
 *
 *   Nano GND ──────────────→ Pi GND
 *
 *   ⚠ VOLTAGE DIVIDER IS REQUIRED!
 *   The Nano TX is 5V. Pi GPIO is 3.3V and NOT 5V tolerant.
 *   The 1KΩ + 2KΩ divider drops 5V to 3.33V.
 *   Without this you WILL damage the Pi's GPIO.
 *
 *   Power the Nano from USB (your laptop) — don't power it
 *   from the Pi's 5V pin (they'd share ground through USB
 *   and the Pi, which can cause ground loops).
 *
 * PI SETUP:
 *   1. Serial console must be disabled (raspi-config)
 *   2. config.json: set "simulate": false
 *   3. Run: python3 race_dash_pygame.py
 *
 * ARDUINO IDE SETUP:
 *   Board: Arduino Nano
 *   Processor: ATmega328P (or "Old Bootloader" variant)
 *   Port: your USB serial port
 *   Upload, then disconnect the serial monitor so the Nano
 *   TX line is free to talk to the Pi.
 */

// ── CBR 600RR drivetrain (same constants as STM32 firmware) ──
#define NUM_GEARS 6
const float GEAR_RATIOS[NUM_GEARS] = {
    2.666, 1.937, 1.661, 1.409, 1.260, 1.166
};
const float PRIMARY_RATIO = 2.111;
const float VSS_PULSES_PER_MPH = 16.65;  // stock 43/16, 180/55-17
const float VSS_TEETH = 28.0;

// Precomputed RPM per MPH for each gear
float RPM_PER_MPH[NUM_GEARS];

// ── Sim state ──
int16_t  sim_rpm = 3000;
uint8_t  sim_gear = 0;        // 0-indexed: 0=1st, 5=6th
bool     sim_accel = true;
uint8_t  clutch_ticks = 0;
uint32_t last_send = 0;

void setup() {
    Serial.begin(115200);
    
    // Precompute RPM/MPH table
    float cs_rps_per_mph = VSS_PULSES_PER_MPH / VSS_TEETH;
    for (int g = 0; g < NUM_GEARS; g++) {
        RPM_PER_MPH[g] = cs_rps_per_mph * PRIMARY_RATIO * GEAR_RATIOS[g] * 60.0;
    }
    
    // Boot messages (Pi parser ignores lines starting with #)
    Serial.println("# Race Dash NANO TEST starting...");
    Serial.println("# Mode: SIMULATION (Nano stand-in for STM32)");
    Serial.print("# VSS cal: ");
    Serial.print(VSS_PULSES_PER_MPH, 2);
    Serial.print(" pulses/mph  |  RPM/MPH per gear: ");
    for (int g = 0; g < NUM_GEARS; g++) {
        Serial.print(RPM_PER_MPH[g], 1);
        if (g < NUM_GEARS - 1) Serial.print(", ");
    }
    Serial.println();
    Serial.println("# CSV: RPM,SPEED,THROTTLE,BRAKE,CLT,OIL,LAT,LON,GPS_SPD,GPS_SATS,AX,AY,AZ,GEAR,CLUTCH");
    Serial.println("# Ready");
}

void loop() {
    uint32_t now = millis();
    
    // Send at 25Hz (every 40ms)
    if (now - last_send < 40) return;
    last_send = now;
    
    // ── Gear cycling sim (same logic as STM32 firmware) ──
    uint8_t clutch = 0;
    uint8_t gear_display = 0;
    
    if (clutch_ticks > 0) {
        // Mid-shift
        clutch_ticks--;
        sim_rpm = max(2000, sim_rpm - 200);
        clutch = 1;
        gear_display = 0;
    } else if (sim_accel) {
        // Rev up
        sim_rpm += random(5, 9);
        clutch = 0;
        gear_display = sim_gear + 1;
        
        if (sim_rpm >= 12500) {
            if (sim_gear < 5) {
                clutch_ticks = 4;
                sim_gear++;
            } else {
                sim_accel = false;
            }
        }
    } else {
        // Engine brake down
        sim_rpm -= random(4, 7);
        clutch = 0;
        gear_display = sim_gear + 1;
        
        if (sim_rpm <= 4000) {
            if (sim_gear > 0) {
                clutch_ticks = 3;
                sim_gear--;
                sim_rpm = 8000;
            } else {
                sim_accel = true;
                sim_rpm = 3000;
            }
        }
    }
    
    sim_rpm = constrain(sim_rpm, 2000, 14000);
    
    // Speed from RPM + gear
    int speed = 0;
    if (RPM_PER_MPH[sim_gear] > 0) {
        speed = max(0, (int)((float)sim_rpm / RPM_PER_MPH[sim_gear]));
    }
    
    // Throttle / brake
    int throttle = 0, brake = 0;
    if (clutch) {
        throttle = 0; brake = 0;
    } else if (sim_accel) {
        throttle = min(100, (int)(60 + (sim_rpm - 3000) / 20));
    } else {
        brake = min(100, (int)(30 + (8000 - sim_rpm) / 15));
    }
    
    // Fake sensor values
    int clt = 180 + random(0, 30);
    int oil = 40 + random(0, 25);
    
    // Fake IMU
    float t = now / 1000.0;
    float spd_frac = speed / 150.0;
    float ax = sin(t / 2.0) * spd_frac * 1.5;
    float ay = (sim_accel && !clutch) ? 0.5 : ((!sim_accel && !clutch) ? -0.6 : 0.0);
    float az = 1.0 + sin(t * 12.0) * 0.03;
    
    // ── Send CSV (same format as STM32 firmware) ──
    // RPM,SPEED,THROTTLE,BRAKE,CLT,OIL,LAT,LON,GPS_SPD,GPS_SATS,AX,AY,AZ,GEAR,CLUTCH
    Serial.print(sim_rpm);        Serial.print(',');
    Serial.print(speed);          Serial.print(',');
    Serial.print(throttle);       Serial.print(',');
    Serial.print(brake);          Serial.print(',');
    Serial.print(clt);            Serial.print(',');
    Serial.print(oil);            Serial.print(',');
    Serial.print("40.712800");    Serial.print(',');
    Serial.print("-74.006000");   Serial.print(',');
    Serial.print(speed * 0.95, 1); Serial.print(',');
    Serial.print(8);              Serial.print(',');
    Serial.print(ax, 2);         Serial.print(',');
    Serial.print(ay, 2);         Serial.print(',');
    Serial.print(az, 2);         Serial.print(',');
    Serial.print(gear_display);  Serial.print(',');
    Serial.println(clutch);
}
