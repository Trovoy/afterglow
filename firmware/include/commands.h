#pragma once
#include <Arduino.h>

// One command language for USB serial and the Wi-Fi web API. Every reply is one JSON line.
extern bool radioOk, audioOk;
extern int micMonitorLevel;
extern volatile bool rebootPending;
extern uint32_t wakeUntil;   // non-zero while a "wake" period is running
void commandsBegin();   // call once in setup(), before the web server starts
void runCommand(char *line, Print &out);   // thread-safe
void commandsLoop();
