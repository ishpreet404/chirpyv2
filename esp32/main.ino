// =============================================================================
// CHIRPY v2 - DISASTER RESCUE ROVER FIRMWARE
// Hardware: ESP32 DevKit V1, L298N, MPU6050, HC-SR04, NEO-6M GPS
// =============================================================================

#include <Arduino.h>
#include <Wire.h>

// ---------------------------------------------------------------------------
// PINS
// ---------------------------------------------------------------------------
const int LEFT_PIN_A = 21;
const int LEFT_PIN_B = 22;
const int RIGHT_PIN_A = 23;
const int RIGHT_PIN_B = 19;
const int I2C_SDA = 16;
const int I2C_SCL = 17;
const int TRIG_PIN = 32;
const int ECHO_PIN = 33;
const int PI_TX_PIN = 26; // Serial2 TX -> Pi RX
const int PI_RX_PIN = 27; // Serial2 RX -> Pi TX
const int GPS_RX_PIN = 34; // GPS TX -> ESP32 RX1 (input only pin OK)
const int GPS_TX_PIN = 4;  // GPS RX -> ESP32 TX1

// ---------------------------------------------------------------------------
// KINEMATICS
// ---------------------------------------------------------------------------
const float WHEEL_VELOCITY_CMS = 20.0f;
const float PIVOT_RATE_DEGS = 286.4f;
const float ESTIMATED_RPM = 60.1f;

// ---------------------------------------------------------------------------
// BATTERY MODEL
// ---------------------------------------------------------------------------
const float BATT_START_V = 12.0f;
const float BATT_CUTOFF_V = 10.5f;
const float BATT_MOTOR_DROP = 0.00090f;
const float BATT_IDLE_DROP = 0.00015f;

// ---------------------------------------------------------------------------
// TIMING
// ---------------------------------------------------------------------------
const unsigned long PACKET_INTERVAL_MS = 50UL;
const unsigned long SONAR_INTERVAL_MS = 40UL;
const unsigned long BIAS_DURATION_MS = 3000UL;

// ---------------------------------------------------------------------------
// OBSTACLE AVOIDANCE
// ---------------------------------------------------------------------------
const int OBSTACLE_THRESHOLD_CM = 25;

// ---------------------------------------------------------------------------
// MODULE PROTOTYPES
// ---------------------------------------------------------------------------
void motorInit(int leftA, int leftB, int rightA, int rightB);
void motorSetState(char state);
void motorCoast();
char motorGetState();
bool motorIsMoving();

bool imuInit(int sda, int scl);
float imuCaptureBias(unsigned long durationMs);
void imuSetBias(float bias);
void imuRead(float* accelY, float* gyroZ, float* tempC, bool* imuFault);

void odomInit(float wheelVelCms, float pivotRateDegs);
void odomUpdate(char state, float gyroZ, float dt);
void odomResetLap();
void odomGet(float* x, float* y, float* heading, float* lap, float* total);

void sonarInit(int trig, int echo);
int sonarReadCm();
bool sonarIsFault();

void gpsBegin(HardwareSerial* port, int rxPin, int txPin, uint32_t baud);
void gpsPoll();
bool gpsHasFix();
float gpsLat();
float gpsLon();
float gpsHdop();
uint32_t gpsAgeMs();

void telemetrySend(
  HardwareSerial& usb,
  HardwareSerial& pi,
  unsigned long ms,
  float rpm,
  int distCm,
  float accelY,
  float gyroZ,
  float xCm,
  float yCm,
  float heading,
  float distLapCm,
  float distTotalCm,
  float batteryV,
  bool obstacle,
  char state,
  bool flagImu,
  bool flagSonar,
  bool battWarn,
  float lat,
  float lon,
  bool gpsFix,
  float gpsHdop
);

// ---------------------------------------------------------------------------
// GLOBAL STATE
// ---------------------------------------------------------------------------
char requestedState = 'S';
bool obstacleActive = false;

bool imuOk = false;
bool flagImu = false;
bool flagSonar = false;
int lastSonarDist = 999;

float estV = BATT_START_V;

unsigned long lastPacketMs = 0;
unsigned long lastSonarMs = 0;
unsigned long lastBattMs = 0;
unsigned long lastOdomUs = 0;

char usbBuf[8];
int usbLen = 0;
char piBuf[8];
int piLen = 0;

HardwareSerial GPS(1);

// ---------------------------------------------------------------------------
// HELPERS
// ---------------------------------------------------------------------------
void applyMotorState(char state) {
  motorSetState(state);
}

void ackCommand(char cmd) {
  Serial.print("ACK:");
  Serial.println(cmd);
  Serial2.print("ACK:");
  Serial2.println(cmd);
}

void nakCommand(char cmd) {
  Serial.print("NAK:");
  Serial.println(cmd);
  Serial2.print("NAK:");
  Serial2.println(cmd);
}

void processCommand(char cmd, bool fromPi) {
  char c = toupper(cmd);

  if (obstacleActive && c != 'S') {
    if (fromPi) {
      Serial2.println("BUSY:OBSTACLE");
    } else {
      Serial.println("BUSY: obstacle avoidance active - send S to stop");
    }
    return;
  }

  switch (c) {
    case 'F':
    case 'B':
    case 'L':
    case 'R':
      requestedState = c;
      applyMotorState(c);
      ackCommand(c);
      break;
    case 'S':
      obstacleActive = false;
      requestedState = 'S';
      applyMotorState('S');
      odomResetLap();
      ackCommand('S');
      break;
    default:
      nakCommand(c);
      break;
  }
}

void readChannel(HardwareSerial& port, char* buf, int* len, bool fromPi) {
  while (port.available()) {
    char ch = port.read();
    if (ch == '\n' || ch == '\r') {
      if (*len > 0) {
        buf[*len] = '\0';
        processCommand(buf[0], fromPi);
      }
      *len = 0;
    } else if (*len < 7) {
      buf[(*len)++] = ch;
    }
  }
}

void readUART() {
  readChannel(Serial2, piBuf, &piLen, true);
  readChannel(Serial, usbBuf, &usbLen, false);
}

void handleObstacle(int dist) {
  if (!obstacleActive) {
    if (dist < OBSTACLE_THRESHOLD_CM && dist != 999) {
      obstacleActive = true;
      requestedState = 'S';
      applyMotorState('B');
      Serial.println("OBSTACLE");
      Serial2.println("OBSTACLE");
    }
  } else {
    if (dist >= OBSTACLE_THRESHOLD_CM) {
      obstacleActive = false;
      applyMotorState('S');
      odomResetLap();
      Serial.println("CLEAR");
      Serial2.println("CLEAR");
    }
  }
}

void updateBattery(float dt) {
  if (motorIsMoving()) {
    estV -= BATT_MOTOR_DROP * dt;
  } else {
    estV -= BATT_IDLE_DROP * dt;
  }
  estV = constrain(estV, BATT_CUTOFF_V, BATT_START_V);
}

// ---------------------------------------------------------------------------
// SETUP
// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  Serial2.begin(115200, SERIAL_8N1, PI_RX_PIN, PI_TX_PIN);

  motorInit(LEFT_PIN_A, LEFT_PIN_B, RIGHT_PIN_A, RIGHT_PIN_B);
  sonarInit(TRIG_PIN, ECHO_PIN);

  imuOk = imuInit(I2C_SDA, I2C_SCL);
  if (imuOk) {
    imuCaptureBias(BIAS_DURATION_MS);
  }

  gpsBegin(&GPS, GPS_RX_PIN, GPS_TX_PIN, 9600);
  odomInit(WHEEL_VELOCITY_CMS, PIVOT_RATE_DEGS);

  unsigned long now = millis();
  lastPacketMs = now;
  lastSonarMs = now;
  lastBattMs = now;
  lastOdomUs = micros();

  Serial.println("CHIRPY_READY");
  Serial2.println("CHIRPY_READY");
}

// ---------------------------------------------------------------------------
// LOOP
// ---------------------------------------------------------------------------
void loop() {
  unsigned long nowMs = millis();

  readUART();
  gpsPoll();

  float accelY = 0.0f;
  float gyroZ = 0.0f;
  float tempC = 0.0f;
  imuRead(&accelY, &gyroZ, &tempC, &flagImu);

  unsigned long nowUs = micros();
  float dtOdom = (nowUs - lastOdomUs) / 1000000.0f;
  lastOdomUs = nowUs;
  odomUpdate(motorGetState(), gyroZ, dtOdom);

  float dtBatt = (nowMs - lastBattMs) / 1000.0f;
  if (dtBatt > 0.0f && dtBatt < 1.0f) {
    updateBattery(dtBatt);
  }
  lastBattMs = nowMs;

  if (nowMs - lastSonarMs >= SONAR_INTERVAL_MS) {
    lastSonarMs = nowMs;
    lastSonarDist = sonarReadCm();
    flagSonar = sonarIsFault();
  }

  handleObstacle(lastSonarDist);

  if (nowMs - lastPacketMs >= PACKET_INTERVAL_MS) {
    lastPacketMs = nowMs;
    float x = 0.0f, y = 0.0f, heading = 0.0f, lap = 0.0f, total = 0.0f;
    odomGet(&x, &y, &heading, &lap, &total);

    telemetrySend(
      Serial,
      Serial2,
      nowMs,
      motorIsMoving() ? ESTIMATED_RPM : 0.0f,
      lastSonarDist,
      accelY,
      gyroZ,
      x,
      y,
      heading,
      lap,
      total,
      estV,
      obstacleActive,
      motorGetState(),
      flagImu,
      flagSonar,
      estV <= BATT_CUTOFF_V,
      gpsLat(),
      gpsLon(),
      gpsHasFix(),
      gpsHdop()
    );
  }
}
// =============================================================================
// CHIRPY v2 - DISASTER RESCUE ROVER FIRMWARE
// Hardware: ESP32 DevKit V1, L298N, MPU6050, HC-SR04, NEO-6M GPS
// =============================================================================

#include <Arduino.h>
#include <Wire.h>

// ---------------------------------------------------------------------------
// PINS
// ---------------------------------------------------------------------------
const int LEFT_PIN_A = 21;
const int LEFT_PIN_B = 22;
const int RIGHT_PIN_A = 23;
const int RIGHT_PIN_B = 19;
const int I2C_SDA = 16;
const int I2C_SCL = 17;
const int TRIG_PIN = 32;
const int ECHO_PIN = 33;
const int PI_TX_PIN = 26; // Serial2 TX -> Pi RX
const int PI_RX_PIN = 27; // Serial2 RX -> Pi TX
const int GPS_RX_PIN = 34; // GPS TX -> ESP32 RX1 (input only pin OK)
const int GPS_TX_PIN = 4;  // GPS RX -> ESP32 TX1

// ---------------------------------------------------------------------------
// KINEMATICS
// ---------------------------------------------------------------------------
const float WHEEL_VELOCITY_CMS = 20.0f;
const float PIVOT_RATE_DEGS = 286.4f;
const float ESTIMATED_RPM = 60.1f;

// ---------------------------------------------------------------------------
// BATTERY MODEL
// ---------------------------------------------------------------------------
const float BATT_START_V = 12.0f;
const float BATT_CUTOFF_V = 10.5f;
const float BATT_MOTOR_DROP = 0.00090f;
const float BATT_IDLE_DROP = 0.00015f;

// ---------------------------------------------------------------------------
// TIMING
// ---------------------------------------------------------------------------
const unsigned long PACKET_INTERVAL_MS = 50UL;
const unsigned long SONAR_INTERVAL_MS = 40UL;
const unsigned long BIAS_DURATION_MS = 3000UL;

// ---------------------------------------------------------------------------
// OBSTACLE AVOIDANCE
// ---------------------------------------------------------------------------
const int OBSTACLE_THRESHOLD_CM = 25;

// ---------------------------------------------------------------------------
// MODULE PROTOTYPES
// ---------------------------------------------------------------------------
void motorInit(int leftA, int leftB, int rightA, int rightB);
void motorSetState(char state);
void motorCoast();
char motorGetState();
bool motorIsMoving();

bool imuInit(int sda, int scl);
float imuCaptureBias(unsigned long durationMs);
void imuSetBias(float bias);
void imuRead(float* accelY, float* gyroZ, float* tempC, bool* imuFault);

void odomInit(float wheelVelCms, float pivotRateDegs);
void odomUpdate(char state, float gyroZ, float dt);
void odomResetLap();
void odomGet(float* x, float* y, float* heading, float* lap, float* total);

void sonarInit(int trig, int echo);
int sonarReadCm();
bool sonarIsFault();

void gpsBegin(HardwareSerial* port, int rxPin, int txPin, uint32_t baud);
void gpsPoll();
bool gpsHasFix();
float gpsLat();
float gpsLon();
float gpsHdop();
uint32_t gpsAgeMs();

void telemetrySend(
  HardwareSerial& usb,
  HardwareSerial& pi,
  unsigned long ms,
  float rpm,
  int distCm,
  float accelY,
  float gyroZ,
  float xCm,
  float yCm,
  float heading,
  float distLapCm,
  float distTotalCm,
  float batteryV,
  bool obstacle,
  char state,
  bool flagImu,
  bool flagSonar,
  bool battWarn,
  float lat,
  float lon,
  bool gpsFix,
  float gpsHdop
);

// ---------------------------------------------------------------------------
// GLOBAL STATE
// ---------------------------------------------------------------------------
char requestedState = 'S';
bool obstacleActive = false;

bool imuOk = false;
bool flagImu = false;
bool flagSonar = false;
int lastSonarDist = 999;

float estV = BATT_START_V;

unsigned long lastPacketMs = 0;
unsigned long lastSonarMs = 0;
unsigned long lastBattMs = 0;
unsigned long lastOdomUs = 0;

char usbBuf[8];
int usbLen = 0;
char piBuf[8];
int piLen = 0;

HardwareSerial GPS(1);

// ---------------------------------------------------------------------------
// HELPERS
// ---------------------------------------------------------------------------
void applyMotorState(char state) {
  motorSetState(state);
}

void ackCommand(char cmd) {
  Serial.print("ACK:");
  Serial.println(cmd);
  Serial2.print("ACK:");
  Serial2.println(cmd);
}

void nakCommand(char cmd) {
  Serial.print("NAK:");
  Serial.println(cmd);
  Serial2.print("NAK:");
  Serial2.println(cmd);
}

void processCommand(char cmd, bool fromPi) {
  char c = toupper(cmd);

  if (obstacleActive && c != 'S') {
    if (fromPi) {
      Serial2.println("BUSY:OBSTACLE");
    } else {
      Serial.println("BUSY: obstacle avoidance active - send S to stop");
    }
    return;
  }

  switch (c) {
    case 'F':
    case 'B':
    case 'L':
    case 'R':
      requestedState = c;
      applyMotorState(c);
      ackCommand(c);
      break;
    case 'S':
      obstacleActive = false;
      requestedState = 'S';
      applyMotorState('S');
      odomResetLap();
      ackCommand('S');
      break;
    default:
      nakCommand(c);
      break;
  }
}

void readChannel(HardwareSerial& port, char* buf, int* len, bool fromPi) {
  while (port.available()) {
    char ch = port.read();
    if (ch == '\n' || ch == '\r') {
      if (*len > 0) {
        buf[*len] = '\0';
        processCommand(buf[0], fromPi);
      }
      *len = 0;
    } else if (*len < 7) {
      buf[(*len)++] = ch;
    }
  }
}

void readUART() {
  readChannel(Serial2, piBuf, &piLen, true);
  readChannel(Serial, usbBuf, &usbLen, false);
}

void handleObstacle(int dist) {
  if (!obstacleActive) {
    if (dist < OBSTACLE_THRESHOLD_CM && dist != 999) {
      obstacleActive = true;
      requestedState = 'S';
      applyMotorState('B');
      Serial.println("OBSTACLE");
      Serial2.println("OBSTACLE");
    }
  } else {
    if (dist >= OBSTACLE_THRESHOLD_CM) {
      obstacleActive = false;
      applyMotorState('S');
      odomResetLap();
      Serial.println("CLEAR");
      Serial2.println("CLEAR");
    }
  }
}

void updateBattery(float dt) {
  if (motorIsMoving()) {
    estV -= BATT_MOTOR_DROP * dt;
  } else {
    estV -= BATT_IDLE_DROP * dt;
  }
  estV = constrain(estV, BATT_CUTOFF_V, BATT_START_V);
}

// ---------------------------------------------------------------------------
// SETUP
// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  Serial2.begin(115200, SERIAL_8N1, PI_RX_PIN, PI_TX_PIN);

  motorInit(LEFT_PIN_A, LEFT_PIN_B, RIGHT_PIN_A, RIGHT_PIN_B);
  sonarInit(TRIG_PIN, ECHO_PIN);

  imuOk = imuInit(I2C_SDA, I2C_SCL);
  if (imuOk) {
    imuCaptureBias(BIAS_DURATION_MS);
  }

  gpsBegin(&GPS, GPS_RX_PIN, GPS_TX_PIN, 9600);
  odomInit(WHEEL_VELOCITY_CMS, PIVOT_RATE_DEGS);

  unsigned long now = millis();
  lastPacketMs = now;
  lastSonarMs = now;
  lastBattMs = now;
  lastOdomUs = micros();

  Serial.println("CHIRPY_READY");
  Serial2.println("CHIRPY_READY");
}

// ---------------------------------------------------------------------------
// LOOP
// ---------------------------------------------------------------------------
void loop() {
  unsigned long nowMs = millis();

  readUART();
  gpsPoll();

  float accelY = 0.0f;
  float gyroZ = 0.0f;
  float tempC = 0.0f;
  imuRead(&accelY, &gyroZ, &tempC, &flagImu);

  unsigned long nowUs = micros();
  float dtOdom = (nowUs - lastOdomUs) / 1000000.0f;
  lastOdomUs = nowUs;
  odomUpdate(motorGetState(), gyroZ, dtOdom);

  float dtBatt = (nowMs - lastBattMs) / 1000.0f;
  if (dtBatt > 0.0f && dtBatt < 1.0f) {
    updateBattery(dtBatt);
  }
  lastBattMs = nowMs;

  if (nowMs - lastSonarMs >= SONAR_INTERVAL_MS) {
    lastSonarMs = nowMs;
    lastSonarDist = sonarReadCm();
    flagSonar = sonarIsFault();
  }

  handleObstacle(lastSonarDist);

  if (nowMs - lastPacketMs >= PACKET_INTERVAL_MS) {
    lastPacketMs = nowMs;
    float x = 0.0f, y = 0.0f, heading = 0.0f, lap = 0.0f, total = 0.0f;
    odomGet(&x, &y, &heading, &lap, &total);

    telemetrySend(
      Serial,
      Serial2,
      nowMs,
      motorIsMoving() ? ESTIMATED_RPM : 0.0f,
      lastSonarDist,
      accelY,
      gyroZ,
      x,
      y,
      heading,
      lap,
      total,
      estV,
      obstacleActive,
      motorGetState(),
      flagImu,
      flagSonar,
      estV <= BATT_CUTOFF_V,
      gpsLat(),
      gpsLon(),
      gpsHasFix(),
      gpsHdop()
    );
  }
}
