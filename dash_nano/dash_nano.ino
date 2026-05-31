/*
 * Race Dash - Minimum Viable Firmware (Arduino Nano + Arduino IDE)
 * ================================================================
 *
 * Reads Speeduino via secondary RS232 serial, sends CSV to Pi.
 * Nothing else — no GPS, no IMU, no SD, no thermocouples.
 *
 * Arduino IDE settings:
 *   Tools → Board     → Arduino AVR Boards → Arduino Nano
 *   Tools → Processor → ATmega328P  (or "ATmega328P (Old Bootloader)"
 *                                     if upload fails with stk500_recv)
 *   Tools → Port      → whichever COM port appears
 *
 * WIRING (two separate UART links — no shared TX line):
 *
 *   Hardware UART (D0/D1, 115200) — DEDICATED to Speeduino:
 *     Nano D0 (RX) ◄────────── Speeduino 2nd Serial TX  (5V TTL, direct)
 *     Nano D1 (TX) ──────────► Speeduino 2nd Serial RX
 *
 *   SoftwareSerial (D7 → Pi, 57600) — TX-only to Pi:
 *     Nano D7 ─── 10KΩ ──┬───► Pi GPIO15 (RX, /dev/ttyAMA0)
 *                       20KΩ
 *                        │
 *                       GND ──── common GND
 *
 *   Common ground between Nano + Pi + Speeduino.
 *
 *   ⚠ DISCONNECT D0 from Speeduino when uploading via USB.
 *     The bootloader uses the same UART.
 *
 *   ⚠ Voltage divider on D7 is MANDATORY. Nano is 5V, Pi GPIO is 3.3V max.
 *
 * SPEEDUINO SECONDARY SERIAL:
 *   Send byte 'A' (0x41), receive 65-byte real-time data packet.
 *   ⚠ VERIFY byte offsets below match YOUR Speeduino firmware version.
 *   Reference: https://wiki.speeduino.com/en/Secondary_Serial_IO_interface
 *
 * CSV OUTPUT (matches race_dash_core.py CSV_FIELDS):
 *   RPM,SPEED,THROTTLE,BRAKE,CLT,OIL,LAT,LON,GPS_SPD,GPS_SATS,
 *   AX,AY,AZ,GEAR,CLUTCH,T1,T2,T3,T4
 *   (zeros for fields we don't have yet)
 *
 * DEBUG:
 *   Lines starting with '#' go to USB Serial Monitor (Hardware Serial)
 *   only — they are NOT sent to the Pi. The Pi receives only CSV data
 *   on the SoftwareSerial line.
 */

#include <SoftwareSerial.h>

// ──────── Pin assignments ────────
#define PI_RX_PIN    6     // Unused (SoftwareSerial requires both pins)
#define PI_TX_PIN    7     // → 10K/20K voltage divider → Pi GPIO15

SoftwareSerial piSerial(PI_RX_PIN, PI_TX_PIN);

// ──────── Speeduino protocol ────────
#define SPEEDUINO_REQ       0x41    // 'A' = request real-time data
#define PACKET_LEN          65
#define READ_TIMEOUT_MS     50
#define POLL_INTERVAL_MS    40      // 25 Hz

// Byte offsets into the 65-byte response (verify against your firmware!)
const uint8_t IDX_MAP_H  = 4;
const uint8_t IDX_MAP_L  = 5;
const uint8_t IDX_CLT    = 7;       // °C + 40 offset
const uint8_t IDX_BATT   = 9;       // V × 10
const uint8_t IDX_AFR    = 10;      // AFR × 10
const uint8_t IDX_RPM_H  = 14;
const uint8_t IDX_RPM_L  = 15;
const uint8_t IDX_TPS    = 24;      // 0–200 → 0–100%

// ──────── State ────────
uint8_t  buf[PACKET_LEN];
uint32_t lastPoll  = 0;
uint32_t goodPolls = 0;
uint32_t badPolls  = 0;

// ──────── Setup ────────
void setup() {
  // Hardware UART → Speeduino (full duplex, 115200)
  Serial.begin(115200);

  // SoftwareSerial → Pi (TX-only, 57600 — must match race_dash_config.py uart_baud)
  piSerial.begin(57600);

  delay(500);

  // Banner — only visible on USB Serial Monitor (debug)
  Serial.println(F("# Race Dash Nano starting"));
  Serial.println(F("# Speeduino on Hardware Serial (D0/D1) @ 115200"));
  Serial.println(F("# Pi link on SoftwareSerial (D7 → divider → GPIO15) @ 57600"));
}

// ──────── Main loop ────────
void loop() {
  uint32_t now = millis();
  if (now - lastPoll < POLL_INTERVAL_MS) return;
  lastPoll = now;

  // Drain any stale bytes in the RX buffer
  while (Serial.available()) Serial.read();

  // Send request to Speeduino (Hardware Serial only — does NOT reach Pi)
  Serial.write(SPEEDUINO_REQ);

  // Collect the 65-byte response from Speeduino
  uint8_t got = 0;
  uint32_t start = millis();
  while (got < PACKET_LEN && (millis() - start) < READ_TIMEOUT_MS) {
    if (Serial.available()) {
      buf[got++] = Serial.read();
    }
  }

  if (got < PACKET_LEN) {
    badPolls++;
    if ((badPolls % 250) == 0) {
      Serial.print(F("# No Speeduino response (got "));
      Serial.print(got); Serial.print(F("/"));
      Serial.print(PACKET_LEN); Serial.println(F(" bytes)"));
    }
    return;
  }
  goodPolls++;

  // ──────── Parse Speeduino packet ────────
  uint16_t rpm     = ((uint16_t)buf[IDX_RPM_H] << 8) | buf[IDX_RPM_L];
  int16_t  clt_c   = (int16_t)buf[IDX_CLT] - 40;
  int16_t  clt_f   = (clt_c * 9) / 5 + 32;
  uint8_t  tps_pct = buf[IDX_TPS] / 2;
  if (tps_pct > 100) tps_pct = 100;
  uint16_t map_kpa = ((uint16_t)buf[IDX_MAP_H] << 8) | buf[IDX_MAP_L];

  // Sanity check — reject obviously bad RPM (Speeduino can spit garbage at boot)
  if (rpm > 16000) return;

  // ──────── Send CSV to Pi (SoftwareSerial only — does NOT reach Speeduino) ────────
  piSerial.print(rpm);     piSerial.print(',');   // RPM
  piSerial.print(0);       piSerial.print(',');   // SPEED
  piSerial.print(tps_pct); piSerial.print(',');   // THROTTLE
  piSerial.print(0);       piSerial.print(',');   // BRAKE
  piSerial.print(clt_f);   piSerial.print(',');   // CLT
  piSerial.print(map_kpa); piSerial.print(',');   // OIL  (using MAP slot)
  piSerial.print(0);       piSerial.print(',');   // LAT
  piSerial.print(0);       piSerial.print(',');   // LON
  piSerial.print(0);       piSerial.print(',');   // GPS_SPD
  piSerial.print(0);       piSerial.print(',');   // GPS_SATS
  piSerial.print(0);       piSerial.print(',');   // AX
  piSerial.print(0);       piSerial.print(',');   // AY
  piSerial.print(0);       piSerial.print(',');   // AZ
  piSerial.print(0);       piSerial.print(',');   // GEAR
  piSerial.print(0);       piSerial.print(',');   // CLUTCH
  piSerial.print(0);       piSerial.print(',');   // T1
  piSerial.print(0);       piSerial.print(',');   // T2
  piSerial.print(0);       piSerial.print(',');   // T3
  piSerial.println(0);                            // T4
}
