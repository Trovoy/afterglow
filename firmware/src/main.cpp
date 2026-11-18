// Afterglow 余场 controller firmware (compatible with 433 MHz concert wristbands).
// USB serial and the Wi-Fi web page share one command language (commands.cpp).
// Boot is RF-silent unless the user saved "auto 1" (follow music at boot).
#include <Arduino.h>
#include "version.h"
#include "config.h"
#include "radio.h"
#include "audio.h"
#include "commands.h"
#include "web.h"
#include "health.h"
#include "show.h"

static constexpr int BUTTON_PIN = 0;   // on-board BOOT button, active low
static char line[128];
static unsigned used = 0;
static bool dropping = false;
static uint32_t lastMon = 0;

// BOOT button: short press cycles off -> music -> red -> green -> blue -> white -> off;
// hold 3 s toggles the Wi-Fi hotspot (saved).
static const uint8_t BUTTON_COLORS[][3] = {{255, 0, 0}, {0, 255, 0}, {0, 0, 255}, {255, 255, 255}};
static uint8_t buttonStep = 0;
static void buttonLoop() {
  static bool wasDown = false, longDone = false;
  static uint32_t downAt = 0, rawSince = 0;
  static bool rawLast = false;
  const uint32_t now = millis();
  // Debounce: the level must be stable for 50 ms before it counts.
  const bool raw = digitalRead(BUTTON_PIN) == LOW;
  if (raw != rawLast) { rawLast = raw; rawSince = now; }
  if (now - rawSince < 50) return;
  const bool down = raw;
  if (down && !wasDown) { downAt = now; longDone = false; }
  if (down && !longDone && now - downAt > 3000) {
    longDone = true;
    cfg.wifi = webRunning() ? 0 : 1; configSave();
    if (cfg.wifi) webBegin(); else webStop();
    Serial.printf("{\"evt\":\"button\",\"wifi\":%u}\n", cfg.wifi);
  }
  if (!down && wasDown && !longDone && now - downAt > 40) {
    buttonStep = (buttonStep + 1) % 6;
    wakeUntil = 0;
    if (buttonStep == 0 || !radioOk) radioOff();
    else if (buttonStep == 1) { if (audioOk) radioMic(); }
    else { const uint8_t *c = BUTTON_COLORS[buttonStep - 2]; radioHold(c[0], c[1], c[2]); }
    Serial.printf("{\"evt\":\"button\",\"step\":%u}\n", buttonStep);
  }
  wasDown = down;
}

void setup() {
  Serial.begin(115200);
  delay(300);
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  healthBegin();
  configLoad();
  showInit();
  commandsBegin();
  radioOk = radioInit();
  audioOk = audioInit();
  webBegin();
  Serial.printf("{\"evt\":\"boot\",\"fw\":\"%s\",\"ver\":\"%s\",\"proto\":%d,\"radio\":%s,\"audio\":%s,\"auto\":%u,\"wifi\":%s}\n",
                FW_NAME, FW_VERSION, FW_PROTO, radioOk ? "true" : "false", audioOk ? "true" : "false", cfg.autostart,
                webRunning() ? "true" : "false");
  if (radioOk && audioOk && cfg.autostart == 1) { radioMic(); buttonStep = 1; }
}

void loop() {
  while (Serial.available()) {
    const char c = Serial.read();
    if (c == '\r') continue;
    if (c == '\n') {
      if (dropping) Serial.println("{\"ok\":false,\"err\":\"line too long\"}");
      else if (used) { line[used] = 0; runCommand(line, Serial); }
      used = 0; dropping = false;
    } else if (!dropping) {
      if (used < sizeof(line) - 1) line[used++] = c; else { dropping = true; used = 0; }
    }
  }
  webLoop();
  buttonLoop();
  commandsLoop();
  const uint32_t now = millis();
  {  // "micmon 2": exact onset / flash timestamps for timing analysis
    static uint32_t seenBeats = 0, seenFlashes = 0;
    const AudioStatus a = audioStatus();
    if (micMonitorLevel == 2) {
      if (a.beats != seenBeats) Serial.printf("{\"evt\":\"onset\",\"t\":%u,\"bpm\":%.1f}\n", unsigned(now), a.bpm);
      if (a.flashes != seenFlashes) Serial.printf("{\"evt\":\"flash\",\"t\":%u}\n", unsigned(now));
    }
    seenBeats = a.beats; seenFlashes = a.flashes;
  }
  if (micMonitorLevel == 1 && now - lastMon >= 100) {
    lastMon = now;
    const AudioStatus a = audioStatus();
    Serial.printf("{\"evt\":\"mic\",\"mic\":%s,\"level\":%.4f,\"bass\":%.3g,\"avg\":%.3g,\"noise\":%.3g,\"beats\":%u,\"bpm\":%.1f}\n",
                  a.micDetected ? "true" : "false", a.level, a.bass, a.bassAvg, a.noise, a.beats, a.bpm);
  }
  if (rebootPending) { Serial.flush(); delay(300); ESP.restart(); }
  healthFeed();
  delay(2);
}
