#include <Arduino.h>

static int trigPin = 0;
static int echoPin = 0;
static int lastDist = 999;
static bool sonarFault = false;

static const unsigned long PULSE_TIMEOUT_US = 6000UL;
static const int SONAR_SAMPLES = 2;

void sonarInit(int trig, int echo) {
  trigPin = trig;
  echoPin = echo;
  pinMode(trigPin, OUTPUT);
  digitalWrite(trigPin, LOW);
  pinMode(echoPin, INPUT);
}

static int getDistanceRaw() {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  unsigned long dur = pulseIn(echoPin, HIGH, PULSE_TIMEOUT_US);
  if (dur == 0UL) return -1;
  return (int)(dur * 0.0343f / 2.0f);
}

int sonarReadCm() {
  long sum = 0;
  int valid = 0;
  for (int i = 0; i < SONAR_SAMPLES; i++) {
    int d = getDistanceRaw();
    if (d > 0 && d < 400) {
      sum += d;
      valid++;
    }
    delayMicroseconds(300);
  }

  int newDist = (valid == 0) ? 999 : (int)(sum / valid);
  if (lastDist != 999 && newDist != 999 && abs(newDist - lastDist) > 50) {
    sonarFault = true;
  } else {
    sonarFault = false;
  }
  lastDist = newDist;
  return newDist;
}

bool sonarIsFault() {
  return sonarFault;
}
