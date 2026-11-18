#pragma once
#include <Arduino.h>

// Health telemetry for stability testing: why the last reset happened, how many boots,
// heap now / lowest ever, and a task watchdog (a stuck task reboots the controller and the
// next boot reports reset=task_wdt).
void healthBegin();                 // call first in setup()
void healthWatchThisTask();         // call at the start of a task that must never stall
void healthFeed();                  // call regularly from every watched task
const char *healthResetReason();
uint32_t healthBoots();
void healthPrintJson(Print &out);   // "reset":"...","boots":n,"heap":n,"min_heap":n
