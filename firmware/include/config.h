#pragma once
#include <Arduino.h>

// Persistent settings (NVS). Radio defaults are the verified working values from the lab firmware.
struct Config {
  float freqMHz = 433.92f;     // allowed 433.05..434.79
  int8_t dbm = 10;             // -10, 0, 5, 10 (applied only while transmitting; boot is always silent)
  uint16_t bitUs = 500;        // 400..700
  uint16_t periodMs = 51;      // 47..250, must exceed 90 bits * bitUs
  float micSens = 1.8f;       // beat threshold = average bass energy * micSens (1.05..4.0)
  uint8_t micStyle = 4;        // 0 pulse, 1 cycle, 2 level, 3 mix (spectrum colour + beat flash), 4 concert (tempo-locked)
  uint16_t micHoldMs = 120;    // pulse length after a beat (40..600)
  uint8_t bright = 200;        // 1..255
  uint8_t micBase = 0;         // concert style: theme-colour glow between beats, 0..60 %
  uint8_t powerChan = 80;      // power limit: max per LED channel, 20..100 % (coin cells flicker above)
  uint16_t powerSum = 125;     // power limit: max R+G+B sum, 50..300 % of one full channel
  uint8_t micChannel = 1;      // I2S slot. INMP441 L/R=GND is read as slot 1 on this IDF4 core (verified 2026-11-12)
  uint8_t autostart = 0;       // 0 none (silent boot), 1 start mic mode at boot
  uint8_t autoOff = 1;         // 1: band envelope hold code 6 -> bands go dark ~30-40 s after the signal stops (verified, instant resume)
  uint8_t keepalive = 1;       // send dark frames while "off" so bands stay awake (react instantly)
  uint16_t keepaliveMs = 51;   // keep-alive frame interval, 51..2000 ms
  uint8_t wifi = 1;            // 1 = phone hotspot on at boot
  char apPass[21] = "afterglow88";   // hotspot password, 8..20 chars
};

extern Config cfg;
void configLoad();
void configSave();
void configReset();
// Returns nullptr on success, else an error string.
const char *configSet(const char *key, const char *value);
void configPrintJson(Print &out);
