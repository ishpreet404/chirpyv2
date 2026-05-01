#include <Arduino.h>

static HardwareSerial* gpsPort = nullptr;
static char lineBuf[120];
static int linePos = 0;

static float lastLat = 0.0f;
static float lastLon = 0.0f;
static float lastHdop = 0.0f;
static bool hasFix = false;
static unsigned long lastFixMs = 0;

static float parseCoord(const char* val, const char hemi, bool isLat) {
  if (!val || val[0] == '\0') return 0.0f;
  float raw = atof(val);
  int deg = isLat ? (int)(raw / 100.0f) : (int)(raw / 100.0f);
  float minutes = raw - (deg * 100.0f);
  float dec = deg + minutes / 60.0f;
  if (hemi == 'S' || hemi == 'W') dec = -dec;
  return dec;
}

static void parseGGA(char* payload) {
  char* save = nullptr;
  int idx = 0;
  char* token = strtok_r(payload, ",", &save);
  char* lat = nullptr;
  char* latH = nullptr;
  char* lon = nullptr;
  char* lonH = nullptr;
  char* fix = nullptr;
  char* hdop = nullptr;

  while (token) {
    idx++;
    if (idx == 3) lat = token;
    if (idx == 4) latH = token;
    if (idx == 5) lon = token;
    if (idx == 6) lonH = token;
    if (idx == 7) fix = token;
    if (idx == 9) hdop = token;
    token = strtok_r(nullptr, ",", &save);
  }

  if (fix && atoi(fix) > 0) {
    lastLat = parseCoord(lat, latH ? latH[0] : 'N', true);
    lastLon = parseCoord(lon, lonH ? lonH[0] : 'E', false);
    lastHdop = hdop ? atof(hdop) : lastHdop;
    hasFix = true;
    lastFixMs = millis();
  }
}

static void parseRMC(char* payload) {
  char* save = nullptr;
  int idx = 0;
  char* status = nullptr;
  char* lat = nullptr;
  char* latH = nullptr;
  char* lon = nullptr;
  char* lonH = nullptr;

  char* token = strtok_r(payload, ",", &save);
  while (token) {
    idx++;
    if (idx == 3) status = token;
    if (idx == 4) lat = token;
    if (idx == 5) latH = token;
    if (idx == 6) lon = token;
    if (idx == 7) lonH = token;
    token = strtok_r(nullptr, ",", &save);
  }

  if (status && status[0] == 'A') {
    lastLat = parseCoord(lat, latH ? latH[0] : 'N', true);
    lastLon = parseCoord(lon, lonH ? lonH[0] : 'E', false);
    hasFix = true;
    lastFixMs = millis();
  }
}

void gpsBegin(HardwareSerial* port, int rxPin, int txPin, uint32_t baud) {
  gpsPort = port;
  if (!gpsPort) return;
  gpsPort->begin(baud, SERIAL_8N1, rxPin, txPin);
}

void gpsPoll() {
  if (!gpsPort) return;
  while (gpsPort->available()) {
    char c = gpsPort->read();
    if (c == '\n') {
      lineBuf[linePos] = '\0';
      linePos = 0;

      if (lineBuf[0] != '$') continue;
      char* payload = lineBuf + 1;
      char* star = strchr(payload, '*');
      if (star) *star = '\0';

      if (strncmp(payload, "GPGGA", 5) == 0 || strncmp(payload, "GNGGA", 5) == 0) {
        parseGGA(payload);
      } else if (strncmp(payload, "GPRMC", 5) == 0 || strncmp(payload, "GNRMC", 5) == 0) {
        parseRMC(payload);
      }
    } else if (c != '\r') {
      if (linePos < (int)sizeof(lineBuf) - 1) {
        lineBuf[linePos++] = c;
      }
    }
  }
}

bool gpsHasFix() {
  return hasFix;
}

float gpsLat() {
  return lastLat;
}

float gpsLon() {
  return lastLon;
}

float gpsHdop() {
  return lastHdop;
}

uint32_t gpsAgeMs() {
  if (!hasFix) return 0;
  return millis() - lastFixMs;
}
