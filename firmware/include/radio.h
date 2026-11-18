#pragma once
#include <Arduino.h>
#include "protocol.h"

enum class RadioMode : uint8_t { Off, Hold, Stream, Mic, Show };

struct RadioStatus {
  bool ready;
  RadioMode mode;
  bool tailing;            // sending the final black frames before going idle
  uint32_t frames;         // frames sent since the current mode started
  uint32_t txErrors;       // TX state / RMT errors since boot
  uint32_t maxReadyWaitUs; // worst CC1101 TX-ready wait since mode start
  float freqMHz;           // value read back from the CC1101 registers
  int dbm;
  uint8_t rgb[3];          // colour last set by "color" (8-bit), for UI feedback
};

bool radioInit();
// Applies cfg radio settings. Only allowed while Off; returns nullptr or an error.
const char *radioApplyConfig();
// All transmit entry points use ordinary mode 0x00 frames only (never the persistent 0x11 mode).
void radioHold(uint8_t r, uint8_t g, uint8_t b);    // keep sending this colour until changed/off
void radioHoldBody(const band::Body &body);
void radioHoldUnlimited(uint8_t r, uint8_t g, uint8_t b);   // battery test only: no power limit       // keep sending a prebuilt live body (see protocol.h colorFx)
void radioStream(uint8_t r, uint8_t g, uint8_t b);  // PC live colour; 1 s watchdog then black + off
void radioMic();                                    // colour comes from the microphone beat engine
void radioShow();                                   // colour comes from the stored show timeline (show.cpp)
void radioOff();
void radioMute();                                   // stop instantly, no dark frames (signal-loss tests)                                    // ~0.5 s of black frames, then silent
RadioStatus radioStatus();
const char *radioModeName(RadioMode m);
void radioDiag(Print &out);
extern volatile bool radioSuspended;   // true while the firmware is being updated: no frames at all
