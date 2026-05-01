#include <Arduino.h>

static float odomX = 0.0f;
static float odomY = 0.0f;
static float odomHeading = 0.0f;
static float distLap = 0.0f;
static float distTotal = 0.0f;
static float headingIMU = 0.0f;
static float headingOdom = 0.0f;
static float wheelVelCms = 20.0f;
static float pivotRateDegs = 286.4f;

void odomInit(float wheelVelCmsIn, float pivotRateDegsIn) {
  wheelVelCms = wheelVelCmsIn;
  pivotRateDegs = pivotRateDegsIn;
}

void odomUpdate(char state, float gyroZ, float dt) {
  if (dt <= 0.0f || dt > 0.5f) return;

  float headingRad = odomHeading * (PI / 180.0f);
  switch (toupper(state)) {
    case 'F': {
      float d = wheelVelCms * dt;
      distLap += d;
      distTotal += d;
      odomX += d * cosf(headingRad);
      odomY += d * sinf(headingRad);
      headingIMU += gyroZ * dt;
      odomHeading = 0.7f * headingIMU + 0.3f * headingOdom;
      break;
    }
    case 'B': {
      float d = wheelVelCms * dt;
      distLap += d;
      distTotal += d;
      odomX -= d * cosf(headingRad);
      odomY -= d * sinf(headingRad);
      headingIMU += gyroZ * dt;
      odomHeading = 0.7f * headingIMU + 0.3f * headingOdom;
      break;
    }
    case 'L': {
      headingOdom -= pivotRateDegs * dt;
      headingIMU += gyroZ * dt;
      odomHeading = 0.3f * headingOdom + 0.7f * headingIMU;
      break;
    }
    case 'R': {
      headingOdom += pivotRateDegs * dt;
      headingIMU += gyroZ * dt;
      odomHeading = 0.3f * headingOdom + 0.7f * headingIMU;
      break;
    }
    default:
      break;
  }
}

void odomResetLap() {
  odomX = 0.0f;
  odomY = 0.0f;
  odomHeading = 0.0f;
  distLap = 0.0f;
  headingIMU = 0.0f;
  headingOdom = 0.0f;
}

void odomGet(float* x, float* y, float* heading, float* lap, float* total) {
  if (x) *x = odomX;
  if (y) *y = odomY;
  if (heading) *heading = odomHeading;
  if (lap) *lap = distLap;
  if (total) *total = distTotal;
}
