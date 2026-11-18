#pragma once
#include <Arduino.h>

// INMP441 on I2S0: SCK(BCLK)=GPIO26, WS(LRCLK)=GPIO25, SD=GPIO33, L/R=GND, VDD=3V3.
struct AudioStatus {
  bool running;      // I2S driver installed and task alive
  bool micDetected;  // samples are changing (not stuck at 0 / -1 as with no mic wired)
  float level;       // full-band RMS, 0..1 of full scale
  float bass;        // low-pass energy of the last block
  float bassAvg;     // running average used for the beat threshold
  float noise;       // tracked room noise floor of the bass energy
  uint32_t beats;    // beats detected since boot
  float bpm;         // median of recent beat intervals, 0 if unknown
  uint32_t flashes;  // concert-style flashes fired since boot
};

bool audioInit();
AudioStatus audioStatus();
// Colour to transmit right now in mic mode (uses cfg.micStyle / micHoldMs / bright).
void audioColor(uint32_t nowMs, uint8_t &r, uint8_t &g, uint8_t &b);
