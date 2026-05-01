#include <Arduino.h>
#include <Wire.h>

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

static const float ACCEL_SCALE = 9.81f / 8192.0f;
static const float GYRO_SCALE = 1.0f / 65.5f;
static const int FILTER_N = 10;

struct Filter {
  float buf[10];
  int idx;
  float p1;
  float p2;

  void init() {
    for (int i = 0; i < FILTER_N; i++) buf[i] = 0.0f;
    idx = 0;
    p1 = 0.0f;
    p2 = 0.0f;
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

static float gyroBias = 0.0f;
static Filter accelFilter;
static Filter gyroFilter;
static bool imuReady = false;

static void mpuWrite(byte reg, byte val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission(true);
}

static byte mpuRead8(byte reg) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)1, (uint8_t)true);
  return Wire.available() ? Wire.read() : 0xFF;
}

static void mpuReadWords(byte reg, int16_t* buf, int count) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)(count * 2), (uint8_t)true);
  for (int i = 0; i < count; i++) {
    byte hi = Wire.available() ? Wire.read() : 0;
    byte lo = Wire.available() ? Wire.read() : 0;
    buf[i] = (int16_t)((hi << 8) | lo);
  }
}

bool imuInit(int sda, int scl) {
  Wire.begin(sda, scl);
  Wire.setClock(400000);

  byte who = mpuRead8(REG_WHO_AM_I);
  if (who != 0x68 && who != 0x70 && who != 0x19) {
    imuReady = false;
    return false;
  }

  mpuWrite(REG_PWR_MGMT_1, 0x80);
  delay(100);
  mpuWrite(REG_PWR_MGMT_1, 0x00);
  delay(100);
  mpuWrite(REG_SMPLRT_DIV, 0x04);
  mpuWrite(REG_CONFIG, 0x03);
  mpuWrite(REG_GYRO_CFG, 0x08);
  mpuWrite(REG_ACCEL_CFG, 0x08);
  delay(50);

  accelFilter.init();
  gyroFilter.init();
  imuReady = true;
  return true;
}

float imuCaptureBias(unsigned long durationMs) {
  if (!imuReady) return 0.0f;
  float sum = 0.0f;
  int count = 0;
  unsigned long start = millis();

  while (millis() - start < durationMs) {
    int16_t gyro[3];
    mpuReadWords(REG_GYRO_XOUT, gyro, 3);
    sum += gyro[2] * GYRO_SCALE;
    count++;
    delay(10);
  }

  gyroBias = (count > 0) ? (sum / count) : 0.0f;
  return gyroBias;
}

void imuSetBias(float bias) {
  gyroBias = bias;
}

void imuRead(float* accelY, float* gyroZ, float* tempC, bool* imuFault) {
  if (!imuReady) {
    if (accelY) *accelY = 0.0f;
    if (gyroZ) *gyroZ = 0.0f;
    if (tempC) *tempC = 0.0f;
    if (imuFault) *imuFault = true;
    return;
  }

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
  float rawGyroZ = gyro[2] * GYRO_SCALE - gyroBias;

  bool fault = (fabsf(rawGyroZ) > 500.0f || fabsf(rawAccelY) > 40.0f);
  float filtAccel = accelFilter.update(rawAccelY);
  float filtGyro = gyroFilter.update(fault ? 0.0f : rawGyroZ);

  if (accelY) *accelY = filtAccel;
  if (gyroZ) *gyroZ = filtGyro;
  if (tempC) *tempC = rawTemp / 340.0f + 36.53f;
  if (imuFault) *imuFault = fault;
}
