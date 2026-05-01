#include <Arduino.h>

static int leftPinA = 0;
static int leftPinB = 0;
static int rightPinA = 0;
static int rightPinB = 0;
static char currentState = 'S';

void motorInit(int leftA, int leftB, int rightA, int rightB) {
  leftPinA = leftA;
  leftPinB = leftB;
  rightPinA = rightA;
  rightPinB = rightB;

  pinMode(leftPinA, OUTPUT);
  pinMode(leftPinB, OUTPUT);
  pinMode(rightPinA, OUTPUT);
  pinMode(rightPinB, OUTPUT);

  digitalWrite(leftPinA, LOW);
  digitalWrite(leftPinB, LOW);
  digitalWrite(rightPinA, LOW);
  digitalWrite(rightPinB, LOW);

  currentState = 'S';
}

void motorCoast() {
  digitalWrite(leftPinA, LOW);
  digitalWrite(leftPinB, LOW);
  digitalWrite(rightPinA, LOW);
  digitalWrite(rightPinB, LOW);
}

void motorSetState(char state) {
  char s = toupper(state);
  if (s == currentState) return;

  switch (s) {
    case 'F':
      digitalWrite(leftPinA, HIGH);
      digitalWrite(leftPinB, LOW);
      digitalWrite(rightPinA, HIGH);
      digitalWrite(rightPinB, LOW);
      break;
    case 'B':
      digitalWrite(leftPinA, LOW);
      digitalWrite(leftPinB, HIGH);
      digitalWrite(rightPinA, LOW);
      digitalWrite(rightPinB, HIGH);
      break;
    case 'L':
      digitalWrite(leftPinA, LOW);
      digitalWrite(leftPinB, HIGH);
      digitalWrite(rightPinA, HIGH);
      digitalWrite(rightPinB, LOW);
      break;
    case 'R':
      digitalWrite(leftPinA, HIGH);
      digitalWrite(leftPinB, LOW);
      digitalWrite(rightPinA, LOW);
      digitalWrite(rightPinB, HIGH);
      break;
    case 'S':
    default:
      motorCoast();
      s = 'S';
      break;
  }

  currentState = s;
}

char motorGetState() {
  return currentState;
}

bool motorIsMoving() {
  return currentState != 'S';
}
