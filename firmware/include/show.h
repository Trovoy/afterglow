#pragma once
#include <Arduino.h>

// Concert replica shows stored on the controller (LittleFS, slots 0..SHOW_SLOTS-1) and played by the
// radio task. File format "FLS1" (little endian), written by the desktop app:
//   "FLS1" u8 nameLen, name (UTF-8), u32 durationMs, u16 nCues, u16 nBeats,
//   nCues x {u32 tMs, u8 r, g, b, mode}   mode: 0 beat punches, 1 steady, 2 strobe, 3 dark
//   nBeats x u32 tMs                      (already thinned by the desktop app)
constexpr unsigned SHOW_SLOTS = 4;
constexpr size_t SHOW_MAX_BYTES = 24 * 1024;

bool showInit();
void showList(Print &out);                               // {"ok":true,"shows":[...]}
const char *showPutBegin(unsigned slot, size_t size);    // upload: begin / data / end (nullptr = ok)
const char *showPutData(size_t offset, const char *hex);
const char *showPutEnd();
const char *showDelete(unsigned slot);
void showClearAll();                                     // factory reset: no show may stay on a controller that is sold
const char *showPlay(unsigned slot, uint32_t fromMs);    // loads the show and starts it (radio mode Show)
void showSync(uint32_t posMs);                           // re-align the clock (phone audio drift)
bool showColor(uint32_t now, uint8_t &r, uint8_t &g, uint8_t &b);   // false = show finished
bool showActive(int &slot, uint32_t &posMs, uint32_t &durMs);
