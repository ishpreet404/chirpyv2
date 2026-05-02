// =============================================================================
//  CHIRPY v2 — FINAL PRODUCTION FIRMWARE
//  Version: 1.1  (bug-fix release)
//
//  Hardware:
//    ESP32 DevKit V1 (DOIT, 30-pin)
//    L298N Motor Driver — ENA/ENB jumpered (full voltage, coast stop)
//    2× Geared DC Motors 115:1
//    MPU6050 / ICM clone (GY-521, raw Wire — no Adafruit library)
//    HC-SR04 Ultrasonic (voltage divider on ECHO pin — MANDATORY)
//
//  Wiring:
//    LEFT  IN1 → GPIO 21    LEFT  IN2 → GPIO 22
//    RIGHT IN3 → GPIO 23    RIGHT IN4 → GPIO 19
//    I2C SDA   → GPIO 16    I2C SCL   → GPIO 17
//    TRIG      → GPIO 32    ECHO      → GPIO 33 (via 1kΩ+2kΩ divider)
//    Pi UART   TX2→GPIO 26  RX2→GPIO 27
//
//  Kinematic model (physically measured):
//    Linear velocity:  20.0 cm/s  (163cm/7.75s × 0.92 battery factor)
//    Pivot rate:       286.4 deg/s (derived from velocity + 16cm wheelbase)
//    Output shaft RPM: 60.1 RPM   (15 rev/14.96s)
//    Gear ratio:       115:1
//
//  Telemetry packet (15 fields, 20Hz, on Serial2/Pi — format unchanged):
//    $CHR,<ms>,<rpm>,<dist>,<accelY>,<gyroZ>,<x>,<y>,<heading>,
//         <distLap>,<distTotal>,<estV>,<obstacle>,<state>,<flags>
//
//  USB Serial: human-readable summary (NOT the raw packet)
//  Serial2 (Pi): raw CSV packet — unchanged
//
//  Commands (Pi = primary, USB = secondary, both accepted):
//    F → Forward    B → Backward
//    L → Left pivot R → Right pivot
//    S → Stop (coasts, resets lap odometry)
//
//  Obstacle avoidance:
//    ALWAYS active after boot calibration — no restrictions
//    dist < 25cm → auto-reverse regardless of current state or commands
//    Stays reversing until dist >= 25cm — full authority, overrides all
//
//  Serial Monitor: 115200 baud, Both NL & CR
//
//  Fixes vs v1.0:
//    - USB Serial now shows human-readable summary (Pi packet unchanged)
//    - Obstacle avoidance triggers from ANY state (not just FORWARD)
//    - Obstacle avoidance continuously reverses until dist >= 25cm
//    - Obstacle avoidance active during turns too
//    - After obstacle clears: stop cleanly, let user/Pi issue next command
//    - Battery dt bug fixed (no large first-loop voltage drop)
//    - Redundant zuptPending flag removed
// =============================================================================

#include <Arduino.h>
#include <Wire.h>

// ---------------------------------------------------------------------------
// ENUMS AND STRUCTS — at top, mandatory for Arduino IDE 1.8.x
// ---------------------------------------------------------------------------

enum MotorState { MS_STOP, MS_FORWARD, MS_BACKWARD, MS_LEFT, MS_RIGHT };

struct MPUData {
  float accelY;  // m/s² — forward axis, filtered
  float gyroZ;   // deg/s — yaw rate, bias corrected, filtered
  float tempC;   // chip temperature °C
};

struct OdomState {
  float x;          // cm — positive = forward from last stop
  float y;          // cm — positive = left from last stop
  float heading;    // deg — positive = left turn, 0 = start direction
  float distLap;    // cm — distance since last stop
  float distTotal;  // cm — total session distance (never resets)
};

// ---------------------------------------------------------------------------
// KINEMATIC CONSTANTS
// ---------------------------------------------------------------------------
const float WHEEL_VELOCITY_CMS  = 20.0f;   // cm/s linear velocity (battery corrected)
const float PIVOT_RATE_DEGS     = 286.4f;  // deg/s during pivot turns
const float ESTIMATED_RPM       = 60.1f;   // output shaft RPM at full voltage

// ---------------------------------------------------------------------------
// BATTERY MODEL CONSTANTS
// ---------------------------------------------------------------------------
const float BATT_START_V        = 12.0f;   // 3 × 4.0V charged
const float BATT_CUTOFF_V       = 10.5f;   // 3 × 3.5V cutoff
const float BATT_MOTOR_DROP     = 0.00090f; // V/s when motors running
const float BATT_IDLE_DROP      = 0.00015f; // V/s when motors stopped

// ---------------------------------------------------------------------------
// OBSTACLE AVOIDANCE
// ---------------------------------------------------------------------------
const int OBSTACLE_THRESHOLD_CM = 25;      // cm — trigger auto-reverse below this

// ---------------------------------------------------------------------------
// TIMING
// ---------------------------------------------------------------------------
const unsigned long PACKET_INTERVAL_MS  = 50UL;   // 20Hz telemetry
const unsigned long SONAR_INTERVAL_MS   = 40UL;   // ultrasonic poll rate
const unsigned long BIAS_DURATION_MS    = 3000UL; // gyro bias capture window
const unsigned long ZUPT_IDLE_MS        = 5000UL; // re-calibrate after this idle time
const unsigned long PULSE_TIMEOUT_US    = 6000UL; // max echo wait (~103cm)
const int           SONAR_SAMPLES       = 2;       // averaging samples
const int           FILTER_N            = 10;      // moving average window

// ---------------------------------------------------------------------------
// PINS
// ---------------------------------------------------------------------------
const int LEFT_PIN_A  = 21;
const int LEFT_PIN_B  = 22;
const int RIGHT_PIN_A = 23;
const int RIGHT_PIN_B = 19;
const int I2C_SDA     = 16;
const int I2C_SCL     = 17;
const int TRIG_PIN    = 32;
const int ECHO_PIN    = 33;
const int PI_TX_PIN   = 26;  // Serial2 TX → Pi RX
const int PI_RX_PIN   = 27;  // Serial2 RX → Pi TX

// ---------------------------------------------------------------------------
// MPU REGISTERS
// ---------------------------------------------------------------------------
#define MPU_ADDR        0x68
#define REG_PWR_MGMT_1  0x6B
#define REG_SMPLRT_DIV  0x19
#define REG_CONFIG      0x1A
#define REG_GYRO_CFG    0x1B
#define REG_ACCEL_CFG   0x1C
#define REG_ACCEL_XOUT  0x3B
#define REG_GYRO_XOUT   0x43
#define REG_TEMP_OUT    0x41
#define REG_WHO_AM_I    0x75

const float ACCEL_SCALE = 9.81f / 8192.0f;  // ±4g  → m/s²
const float GYRO_SCALE  = 1.0f  / 65.5f;    // ±500 deg/s → deg/s

// ---------------------------------------------------------------------------
// FILTER — median-3 spike removal + 10-sample moving average
// ---------------------------------------------------------------------------
struct Filter {
  float buf[10];
  int   idx;
  float p1, p2;

  void init() {
    for (int i = 0; i < FILTER_N; i++) buf[i] = 0.0f;
    idx = 0; p1 = 0.0f; p2 = 0.0f;
  }

  float median3(float a, float b, float c) {
    if ((a >= b && a <= c) || (a <= b && a >= c)) return a;
    if ((b >= a && b <= c) || (b <= a && b >= c)) return b;
    return c;
  }

  float update(float raw) {
    float med = median3(raw, p1, p2);
    p2 = p1;
    p1 = raw;
    buf[idx++] = med;
    if (idx >= FILTER_N) idx = 0;
    float sum = 0.0f;
    for (int i = 0; i < FILTER_N; i++) sum += buf[i];
    return sum / FILTER_N;
  }
};

// ---------------------------------------------------------------------------
// GLOBAL STATE
// ---------------------------------------------------------------------------

// Motor
MotorState currentState    = MS_STOP;
MotorState requestedState  = MS_STOP;  // last command received from Pi/USB

// Obstacle
bool       obstacleActive  = false;    // true = auto-reverse in progress

// IMU
bool       mpuOK           = false;
float      gyroBias        = 0.0f;
Filter     accelFilter;
Filter     gyroFilter;

// Odometry
OdomState  odom            = {0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
float      headingIMU      = 0.0f;
float      headingOdom     = 0.0f;
unsigned long lastOdomUs   = 0;        // micros for fine dt

// Battery — FIX: lastBattMs initialised in setup() not as 0
unsigned long lastBattMs   = 0;
float      estV            = BATT_START_V;

// Sensor health flags
bool       flagIMU         = false;
bool       flagSonar       = false;
int        lastSonarDist   = 999;

// ZUPT — FIX: removed redundant zuptPending, use ZUPT::active only
unsigned long stoppedSinceMs = 0;

// Timing
unsigned long lastPacketMs   = 0;
unsigned long lastSonarMs    = 0;

// UART buffers — separate for USB and Pi
String usbBuf = "";
String piBuf  = "";

// ---------------------------------------------------------------------------
// MOTOR CONTROL
// Coast stop: both pins LOW — motor spins down naturally, no braking
// ---------------------------------------------------------------------------
void motorsCoast() {
  digitalWrite(LEFT_PIN_A,  LOW); digitalWrite(LEFT_PIN_B,  LOW);
  digitalWrite(RIGHT_PIN_A, LOW); digitalWrite(RIGHT_PIN_B, LOW);
}

void applyMotorState(MotorState s) {
  if (s == currentState) return;

  switch (s) {
    case MS_STOP:
      motorsCoast();
      break;
    case MS_FORWARD:
      digitalWrite(LEFT_PIN_A,  HIGH); digitalWrite(LEFT_PIN_B,  LOW);
      digitalWrite(RIGHT_PIN_A, HIGH); digitalWrite(RIGHT_PIN_B, LOW);
      break;
    case MS_BACKWARD:
      digitalWrite(LEFT_PIN_A,  LOW);  digitalWrite(LEFT_PIN_B,  HIGH);
      digitalWrite(RIGHT_PIN_A, LOW);  digitalWrite(RIGHT_PIN_B, HIGH);
      break;
    case MS_LEFT:
      digitalWrite(LEFT_PIN_A,  LOW);  digitalWrite(LEFT_PIN_B,  HIGH);
      digitalWrite(RIGHT_PIN_A, HIGH); digitalWrite(RIGHT_PIN_B, LOW);
      break;
    case MS_RIGHT:
      digitalWrite(LEFT_PIN_A,  HIGH); digitalWrite(LEFT_PIN_B,  LOW);
      digitalWrite(RIGHT_PIN_A, LOW);  digitalWrite(RIGHT_PIN_B, HIGH);
      break;
  }

  currentState = s;
}

// ---------------------------------------------------------------------------
// MPU RAW WIRE HELPERS
// ---------------------------------------------------------------------------
void mpuWrite(byte reg, byte val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission(true);
}

byte mpuRead8(byte reg) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)1, (uint8_t)true);
  return Wire.available() ? Wire.read() : 0xFF;
}

void mpuReadWords(byte reg, int16_t* buf, int count) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)(count * 2), (uint8_t)true);
  for (int i = 0; i < count; i++) {
    byte hi = Wire.available() ? Wire.read() : 0;
    byte lo = Wire.available() ? Wire.read() : 0;
    buf[i]  = (int16_t)((hi << 8) | lo);
  }
}

// ---------------------------------------------------------------------------
// MPU INIT
// ---------------------------------------------------------------------------
bool initMPU() {
  byte w = mpuRead8(REG_WHO_AM_I);
  Serial.print("  WHO_AM_I=0x"); Serial.print(w, HEX);
  if      (w == 0x68) Serial.println(" (MPU6050)");
  else if (w == 0x70) Serial.println(" (MPU6500/ICM clone)");
  else if (w == 0x19) Serial.println(" (ICM-20689)");
  else {
    Serial.println(" — UNKNOWN CHIP");
    return false;
  }

  mpuWrite(REG_PWR_MGMT_1, 0x80);  // hard reset
  delay(100);
  mpuWrite(REG_PWR_MGMT_1, 0x00);  // wake, clear sleep
  delay(100);
  mpuWrite(REG_SMPLRT_DIV, 0x04);  // 200Hz internal rate
  mpuWrite(REG_CONFIG,     0x03);  // DLPF 44Hz
  mpuWrite(REG_GYRO_CFG,   0x08);  // ±500 deg/s
  mpuWrite(REG_ACCEL_CFG,  0x08);  // ±4g
  delay(50);

  Serial.println("  MPU init OK");
  return true;
}

// ---------------------------------------------------------------------------
// GYRO BIAS CAPTURE — blocking, motors must be stopped
// ---------------------------------------------------------------------------
float captureGyroBias() {
  Serial.println("  Sampling gyro bias — keep robot still...");
  float sum = 0.0f;
  int   count = 0;
  unsigned long t0 = millis();

  while (millis() - t0 < BIAS_DURATION_MS) {
    int16_t gyro[3];
    mpuReadWords(REG_GYRO_XOUT, gyro, 3);
    sum += gyro[2] * GYRO_SCALE;
    count++;
    delay(10);
  }

  float bias = (count > 0) ? (sum / count) : 0.0f;
  Serial.print("  Gyro bias = "); Serial.print(bias, 4); Serial.println(" deg/s");

  if (fabsf(bias) > 1.0f) {
    Serial.println("  WARNING: bias > 1.0 deg/s — was robot still during capture?");
  }
  return bias;
}

// ---------------------------------------------------------------------------
// MPU READ — returns filtered, bias-corrected values
// ---------------------------------------------------------------------------
MPUData readMPU() {
  MPUData d = {0.0f, 0.0f, 0.0f};

  int16_t accel[3];
  mpuReadWords(REG_ACCEL_XOUT, accel, 3);

  Wire.beginTransmission(MPU_ADDR);
  Wire.write(REG_TEMP_OUT);
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)2, (uint8_t)true);
  byte th = Wire.available() ? Wire.read() : 0;
  byte tl = Wire.available() ? Wire.read() : 0;
  int16_t rawTemp = (int16_t)((th << 8) | tl);

  int16_t gyro[3];
  mpuReadWords(REG_GYRO_XOUT, gyro, 3);

  float rawAccelY = accel[1] * ACCEL_SCALE;
  float rawGyroZ  = gyro[2]  * GYRO_SCALE - gyroBias;

  // Flag extreme values as noise — do not integrate them
  flagIMU = (fabsf(rawGyroZ) > 500.0f || fabsf(rawAccelY) > 40.0f);

  d.accelY = accelFilter.update(rawAccelY);
  d.gyroZ  = gyroFilter.update(flagIMU ? 0.0f : rawGyroZ);
  d.tempC  = rawTemp / 340.0f + 36.53f;

  return d;
}

// ---------------------------------------------------------------------------
// ULTRASONIC
// ---------------------------------------------------------------------------
int getDistanceRaw() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long dur = pulseIn(ECHO_PIN, HIGH, PULSE_TIMEOUT_US);
  if (dur == 0UL) return -1;
  return (int)(dur * 0.0343f / 2.0f);
}

int getDistance() {
  long sum  = 0;
  int valid = 0;
  for (int i = 0; i < SONAR_SAMPLES; i++) {
    int d = getDistanceRaw();
    if (d > 0 && d < 400) { sum += d; valid++; }
    delayMicroseconds(300);
  }
  if (valid == 0) return 999;
  return (int)(sum / valid);
}

// ---------------------------------------------------------------------------
// ODOMETRY UPDATE — called every loop with current gyroZ
// ---------------------------------------------------------------------------
void updateOdometry(float gyroZ) {
  unsigned long nowUs = micros();
  float dt = (nowUs - lastOdomUs) / 1000000.0f;
  lastOdomUs = nowUs;

  // Guard against stale dt on first call or after long pause
  if (dt <= 0.0f || dt > 0.5f) return;

  float headingRad = odom.heading * (PI / 180.0f);

  switch (currentState) {
    case MS_FORWARD: {
      float d = WHEEL_VELOCITY_CMS * dt;
      odom.distLap   += d;
      odom.distTotal += d;
      odom.x += d * cosf(headingRad);
      odom.y += d * sinf(headingRad);
      headingIMU  += gyroZ * dt;
      odom.heading = 0.7f * headingIMU + 0.3f * headingOdom;
      break;
    }
    case MS_BACKWARD: {
      float d = WHEEL_VELOCITY_CMS * dt;
      odom.distLap   += d;
      odom.distTotal += d;
      odom.x -= d * cosf(headingRad);
      odom.y -= d * sinf(headingRad);
      headingIMU  += gyroZ * dt;
      odom.heading = 0.7f * headingIMU + 0.3f * headingOdom;
      break;
    }
    case MS_LEFT: {
      headingOdom  -= PIVOT_RATE_DEGS * dt;
      headingIMU   += gyroZ * dt;
      odom.heading  = 0.3f * headingOdom + 0.7f * headingIMU;
      break;
    }
    case MS_RIGHT: {
      headingOdom  += PIVOT_RATE_DEGS * dt;
      headingIMU   += gyroZ * dt;
      odom.heading  = 0.3f * headingOdom + 0.7f * headingIMU;
      break;
    }
    case MS_STOP:
    default:
      break;
  }
}

// Reset lap odometry (on Stop command). Session total preserved.
void resetLapOdometry() {
  odom.x        = 0.0f;
  odom.y        = 0.0f;
  odom.heading  = 0.0f;
  odom.distLap  = 0.0f;
  headingIMU    = 0.0f;
  headingOdom   = 0.0f;
}

// ---------------------------------------------------------------------------
// BATTERY ESTIMATOR — call every loop with dt in seconds
// ---------------------------------------------------------------------------
void updateBattery(float dt) {
  if (currentState != MS_STOP) {
    estV -= BATT_MOTOR_DROP * dt;
  } else {
    estV -= BATT_IDLE_DROP * dt;
  }
  estV = constrain(estV, BATT_CUTOFF_V, BATT_START_V);
}

// ---------------------------------------------------------------------------
// FLAGS STRING BUILDER
// ---------------------------------------------------------------------------
String buildFlags() {
  bool battWarn  = (estV <= BATT_CUTOFF_V);
  int  warnCount = (int)flagIMU + (int)flagSonar + (int)battWarn;

  if (warnCount == 0)  return "OK";
  if (warnCount >= 2)  return "W:MULTI";
  if (flagIMU)         return "W:IMU";
  if (flagSonar)       return "W:SONAR";
  if (battWarn)        return "W:BATT";
  return "OK";
}

// ---------------------------------------------------------------------------
// PACKET TRANSMIT
//   Serial2 (Pi): raw CSV — $CHR format, UNCHANGED
//   Serial (USB): human-readable summary — easy to read in monitor
// ---------------------------------------------------------------------------
void transmitPacket(const MPUData& imu, int dist) {
  const char* stateStr;
  switch (currentState) {
    case MS_FORWARD:  stateStr = "FWD"; break;
    case MS_BACKWARD: stateStr = "BCK"; break;
    case MS_LEFT:     stateStr = "LFT"; break;
    case MS_RIGHT:    stateStr = "RGT"; break;
    default:          stateStr = "STP"; break;
  }

  String flags = buildFlags();

  // ── Pi packet: raw CSV — format must never change ──────────────────────
  char pkt[128];
  snprintf(pkt, sizeof(pkt),
    "$CHR,%lu,%.1f,%d,%.2f,%.2f,%.1f,%.1f,%.1f,%.1f,%.1f,%.1f,%d,%s,%s",
    millis(),
    (currentState != MS_STOP) ? ESTIMATED_RPM : 0.0f,
    dist,
    imu.accelY,
    imu.gyroZ,
    odom.x,
    odom.y,
    odom.heading,
    odom.distLap,
    odom.distTotal,
    estV,
    obstacleActive ? 1 : 0,
    stateStr,
    flags.c_str()
  );
  Serial2.println(pkt);  // GPIO 26/27 → Raspberry Pi (raw CSV, unchanged)

  // ── USB monitor: human-readable summary ────────────────────────────────
  char usb[160];
  snprintf(usb, sizeof(usb),
    "[%6.1fs] %-3s | Dist:%3dcm %s | X:%6.1f Y:%5.1f H:%6.1f | Lap:%5.1fcm Tot:%6.1fcm | %4.1fV | %s",
    millis() / 1000.0f,
    stateStr,
    dist,
    obstacleActive ? "OBSTACLE!" : "clear     ",
    odom.x,
    odom.y,
    odom.heading,
    odom.distLap,
    odom.distTotal,
    estV,
    flags.c_str()
  );
  Serial.println(usb);
}

// ---------------------------------------------------------------------------
// COMMAND PROCESSOR
// During obstacle avoidance: all external motion commands are blocked.
// The robot has full autonomous authority until the path is clear.
// Stop commands are always allowed so the user can emergency-halt.
// ---------------------------------------------------------------------------
void processCommand(char c, bool isFromPi) {
  // During obstacle avoidance, block motion commands — robot is autonomously
  // reversing. Allow S (stop) as an emergency override.
  if (obstacleActive && c != 'S') {
    if (isFromPi) {
      Serial2.println("BUSY:OBSTACLE");
    } else {
      Serial.println("  [CMD blocked] Obstacle avoidance active — send S to force stop");
    }
    return;
  }

  switch (c) {
    case 'F':
      requestedState = MS_FORWARD;
      applyMotorState(MS_FORWARD);
      Serial.println("  ACK:F");
      Serial2.println("ACK:F");
      break;
    case 'B':
      requestedState = MS_BACKWARD;
      applyMotorState(MS_BACKWARD);
      Serial.println("  ACK:B");
      Serial2.println("ACK:B");
      break;
    case 'L':
      requestedState = MS_LEFT;
      applyMotorState(MS_LEFT);
      Serial.println("  ACK:L");
      Serial2.println("ACK:L");
      break;
    case 'R':
      requestedState = MS_RIGHT;
      applyMotorState(MS_RIGHT);
      Serial.println("  ACK:R");
      Serial2.println("ACK:R");
      break;
    case 'S':
      // S always works — even during obstacle avoidance (emergency stop)
      obstacleActive = false;
      requestedState = MS_STOP;
      applyMotorState(MS_STOP);
      resetLapOdometry();
      stoppedSinceMs = millis();
      Serial.println("  ACK:S");
      Serial2.println("ACK:S");
      break;
    default:
      Serial.print("  NAK:"); Serial.println(c);
      Serial2.print("NAK:"); Serial2.println(c);
      break;
  }
}

// ---------------------------------------------------------------------------
// UART READERS — separate buffers for USB and Pi
// Pi has command priority — processed first each loop
// ---------------------------------------------------------------------------
void readUART() {
  // Pi (Serial2) — read first (higher priority)
  while (Serial2.available()) {
    char ch = Serial2.read();
    if (ch == '\n' || ch == '\r') {
      piBuf.trim();
      if (piBuf.length() > 0) {
        processCommand(toupper(piBuf.charAt(0)), true);
      }
      piBuf = "";
    } else {
      if (piBuf.length() < 8) piBuf += ch;
    }
  }

  // USB (Serial) — secondary, for testing
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') {
      usbBuf.trim();
      if (usbBuf.length() > 0) {
        processCommand(toupper(usbBuf.charAt(0)), false);
      }
      usbBuf = "";
    } else {
      if (usbBuf.length() < 8) usbBuf += ch;
    }
  }
}

// ---------------------------------------------------------------------------
// OBSTACLE AVOIDANCE — always active, full authority
//
// Triggers from ANY state (forward, backward, turning — doesn't matter).
// Once triggered: forces BACKWARD and stays there until dist >= 25cm.
// No external commands can change direction until path is clear.
// After clearing: stops cleanly. Pi/user issues the next move command.
// S command is the only override (emergency stop).
// ---------------------------------------------------------------------------
void handleObstacle(int dist) {
  if (!obstacleActive) {
    // FIX: trigger from ANY state, not just FORWARD
    if (dist < OBSTACLE_THRESHOLD_CM && dist != 999) {
      obstacleActive = true;
      applyMotorState(MS_BACKWARD);
      Serial.println("  *** OBSTACLE DETECTED — auto-reversing ***");
      Serial2.println("OBSTACLE");
    }
  } else {
    // Already reversing — keep reversing until dist >= threshold
    if (dist >= OBSTACLE_THRESHOLD_CM) {
      // Path clear — stop cleanly, let user/Pi send next command
      obstacleActive = false;
      applyMotorState(MS_STOP);
      resetLapOdometry();
      stoppedSinceMs = millis();
      Serial.println("  *** OBSTACLE CLEAR — stopped. Send next command. ***");
      Serial2.println("CLEAR");
    }
    // If still obstructed, motor state stays BACKWARD — no action needed
    // handleObstacle() will be called again next loop iteration
  }
}

// ---------------------------------------------------------------------------
// ZUPT — zero velocity update, re-calibrates gyro bias after idle
// Non-blocking: accumulates samples over time, applies when ready
// FIX: removed redundant zuptPending — use ZUPT::active only
// ---------------------------------------------------------------------------
namespace ZUPT {
  float         sum     = 0.0f;
  int           count   = 0;
  bool          active  = false;
  unsigned long startMs = 0;

  void begin() {
    sum = 0.0f; count = 0; active = true; startMs = millis();
    Serial.println("  ZUPT: recalibrating gyro bias...");
  }

  void accumulate() {
    if (!active) return;
    int16_t gyro[3];
    mpuReadWords(REG_GYRO_XOUT, gyro, 3);
    sum += gyro[2] * GYRO_SCALE;
    count++;
    if (millis() - startMs >= BIAS_DURATION_MS) {
      gyroBias = (count > 0) ? (sum / count) : gyroBias;
      active   = false;
      Serial.print("  ZUPT: new bias = "); Serial.println(gyroBias, 4);
    }
  }

  void reset() { active = false; sum = 0.0f; count = 0; }
}

// ---------------------------------------------------------------------------
// SETUP
// ---------------------------------------------------------------------------
void setup() {
  // --- Serial ---
  Serial.begin(115200);
  Serial2.begin(115200, SERIAL_8N1, PI_RX_PIN, PI_TX_PIN);

  // --- Motor pins — set LOW immediately, before anything else ---
  pinMode(LEFT_PIN_A,  OUTPUT); digitalWrite(LEFT_PIN_A,  LOW);
  pinMode(LEFT_PIN_B,  OUTPUT); digitalWrite(LEFT_PIN_B,  LOW);
  pinMode(RIGHT_PIN_A, OUTPUT); digitalWrite(RIGHT_PIN_A, LOW);
  pinMode(RIGHT_PIN_B, OUTPUT); digitalWrite(RIGHT_PIN_B, LOW);

  // --- Ultrasonic ---
  pinMode(TRIG_PIN, OUTPUT); digitalWrite(TRIG_PIN, LOW);
  pinMode(ECHO_PIN, INPUT);

  // --- Banner ---
  delay(1000);  // power-on stabilisation
  Serial.println();
  Serial.println("==========================================");
  Serial.println("  CHIRPY v2 — PRODUCTION FIRMWARE v1.1");
  Serial.println("==========================================");
  Serial.print  ("  Velocity:   "); Serial.print(WHEEL_VELOCITY_CMS, 1); Serial.println(" cm/s");
  Serial.print  ("  Pivot rate: "); Serial.print(PIVOT_RATE_DEGS, 1);    Serial.println(" deg/s");
  Serial.print  ("  RPM est:    "); Serial.print(ESTIMATED_RPM, 1);       Serial.println(" RPM");
  Serial.print  ("  Obstacle:   <"); Serial.print(OBSTACLE_THRESHOLD_CM); Serial.println(" cm — always active");
  Serial.println("==========================================");

  // --- I2C ---
  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);

  // --- Filters ---
  accelFilter.init();
  gyroFilter.init();

  // --- MPU init ---
  Serial.println("[ INIT ] MPU...");
  mpuOK = initMPU();
  if (!mpuOK) {
    Serial.println("  WARNING: MPU unavailable — heading fusion disabled");
  }

  // --- Gyro bias capture — blocking, motors locked ---
  Serial.println("[ CAL  ] Gyro bias capture (3s) — keep robot still");
  if (mpuOK) {
    gyroBias = captureGyroBias();
  } else {
    Serial.println("  Skipped — MPU not available");
    delay(3000);  // maintain same startup time regardless
  }

  // --- FIX: initialise lastBattMs here so first dt is not huge ---
  unsigned long nowMs = millis();
  lastOdomUs     = micros();
  lastPacketMs   = nowMs;
  lastSonarMs    = nowMs;
  lastBattMs     = nowMs;   // <-- FIX: was uninitialised (defaulted to 0)
  stoppedSinceMs = nowMs;

  // --- Ready ---
  Serial.println("==========================================");
  Serial.println("  CHIRPY_READY");
  Serial.println("  Commands: F B L R S");
  Serial.println("  USB monitor: human-readable");
  Serial.println("  Pi (Serial2): raw CSV packet");
  Serial.println("  Obstacle avoidance: ALWAYS ACTIVE");
  Serial.println("==========================================");
  Serial2.println("CHIRPY_READY");
}

// ---------------------------------------------------------------------------
// LOOP
// ---------------------------------------------------------------------------
void loop() {
  unsigned long nowMs = millis();

  // ── 1. UART — Pi first (priority), then USB ──────────────────────────────
  readUART();

  // ── 2. IMU READ — every loop for tight heading integration ───────────────
  MPUData imu = {0.0f, 0.0f, 0.0f};
  if (mpuOK) imu = readMPU();

  // ── 3. ODOMETRY UPDATE — every loop with fine dt from micros() ───────────
  updateOdometry(imu.gyroZ);

  // ── 4. BATTERY ESTIMATOR ─────────────────────────────────────────────────
  {
    float dt = (nowMs - lastBattMs) / 1000.0f;
    // Guard: only update if dt is sane (avoids first-loop spike after fix)
    if (dt > 0.0f && dt < 1.0f) updateBattery(dt);
    lastBattMs = nowMs;
  }

  // ── 5. ULTRASONIC — polled at SONAR_INTERVAL_MS ──────────────────────────
  if (nowMs - lastSonarMs >= SONAR_INTERVAL_MS) {
    lastSonarMs = nowMs;
    int newDist = getDistance();

    // Sonar health: flag if reading jumps more than 50cm in one cycle
    flagSonar = (lastSonarDist != 999 &&
                 newDist       != 999 &&
                 abs(newDist - lastSonarDist) > 50);

    lastSonarDist = newDist;
  }

  // ── 6. OBSTACLE AVOIDANCE — checked every loop, always active ────────────
  // This runs unconditionally regardless of commanded state or Pi input.
  // It has full authority to override any motor state.
  handleObstacle(lastSonarDist);

  // ── 7. ZUPT — non-blocking gyro recalibration after idle ─────────────────
  if (mpuOK) {
    if (currentState == MS_STOP && !obstacleActive) {
      if (ZUPT::active) {
        ZUPT::accumulate();
      } else if ((nowMs - stoppedSinceMs) >= ZUPT_IDLE_MS) {
        ZUPT::begin();
      }
    } else {
      // Robot moving or in obstacle avoidance — cancel ZUPT
      if (ZUPT::active) ZUPT::reset();
      stoppedSinceMs = nowMs;
    }
  }

  // ── 8. PACKET TRANSMIT — 20Hz ────────────────────────────────────────────
  if (nowMs - lastPacketMs >= PACKET_INTERVAL_MS) {
    lastPacketMs = nowMs;
    transmitPacket(imu, lastSonarDist);
  }
}
