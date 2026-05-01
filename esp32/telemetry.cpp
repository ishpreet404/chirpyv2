#include <Arduino.h>

static void buildFlags(char* buf, size_t len, bool flagImu, bool flagSonar, bool battWarn) {
  int warnCount = (int)flagImu + (int)flagSonar + (int)battWarn;
  if (warnCount == 0) {
    snprintf(buf, len, "OK");
    return;
  }
  if (warnCount >= 2) {
    snprintf(buf, len, "W:MULTI");
    return;
  }
  if (flagImu) {
    snprintf(buf, len, "W:IMU");
    return;
  }
  if (flagSonar) {
    snprintf(buf, len, "W:SONAR");
    return;
  }
  if (battWarn) {
    snprintf(buf, len, "W:BATT");
    return;
  }
  snprintf(buf, len, "OK");
}

static const char* stateToStr(char state) {
  switch (toupper(state)) {
    case 'F': return "FWD";
    case 'B': return "BCK";
    case 'L': return "LFT";
    case 'R': return "RGT";
    default: return "STP";
  }
}

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
) {
  char flags[16];
  buildFlags(flags, sizeof(flags), flagImu, flagSonar, battWarn);

  const char* stateStr = stateToStr(state);

  char pkt[160];
  snprintf(
    pkt,
    sizeof(pkt),
    "$CHR,%lu,%.1f,%d,%.2f,%.2f,%.1f,%.1f,%.1f,%.1f,%.1f,%.2f,%d,%s,%s,%.6f,%.6f,%d,%.2f",
    ms,
    rpm,
    distCm,
    accelY,
    gyroZ,
    xCm,
    yCm,
    heading,
    distLapCm,
    distTotalCm,
    batteryV,
    obstacle ? 1 : 0,
    stateStr,
    flags,
    lat,
    lon,
    gpsFix ? 1 : 0,
    gpsHdop
  );
  pi.println(pkt);

  char usbLine[200];
  snprintf(
    usbLine,
    sizeof(usbLine),
    "[%6.1fs] %s | Dist:%3dcm | X:%6.1f Y:%6.1f H:%6.1f | Lap:%6.1f Tot:%6.1f | %.2fV | %s",
    ms / 1000.0f,
    stateStr,
    distCm,
    xCm,
    yCm,
    heading,
    distLapCm,
    distTotalCm,
    batteryV,
    flags
  );
  usb.println(usbLine);
}
