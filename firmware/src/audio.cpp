#include "audio.h"
#include "config.h"
#include "health.h"
#include <driver/i2s.h>
#include <algorithm>
#include <cmath>

static constexpr i2s_port_t PORT = I2S_NUM_0;
static constexpr int PIN_BCK = 26, PIN_WS = 25, PIN_SD = 33;
static constexpr int RATE = 16000;
static constexpr int BLOCK = 256;           // 16 ms per analysis block
static constexpr uint32_t MIN_BEAT_MS = 270; // ~220 BPM upper bound
static constexpr float NOISE_GATE = 4.0f;    // bass energy must be ~6 dB above the quiet-room average
static constexpr float NOISE_GATE_CAP = 3e-5f;   // quiet-room bass avg measured 4-7e-6; cap = ~5x that
static constexpr float ABS_MUSIC_LEVEL = 0.006f; // full-band RMS that always counts as music

static portMUX_TYPE mux = portMUX_INITIALIZER_UNLOCKED;
static AudioStatus st{};
static uint32_t lastBeatMs = 0;
static uint8_t paletteIndex = 0;
static float levelPeak = 0.02f;
static uint32_t intervals[8]{};
// "mix" style state, written by the audio task under mux
static float mixBand[3] = {0, 0, 0}, mixGate = 0, mixLevel = 0, beatStrength = 1;
static float beatBand[3] = {1, 0, 0};
static unsigned intervalCount = 0;
// "concert" style: beat tracker that locks to the tempo and fires flashes on predicted beats.
static uint32_t flashAt = 0;       // time of the last flash (written under mux)
static uint8_t flashCount = 0;     // increments every flash, selects the colour
static uint32_t trackPeriod = 0;   // flash period in ms (tempo folded into 400..900 ms), 0 = not locked
static uint32_t musicOffSince = 0;
static float levelMid = 0, levelSlow = 0;
static bool climax = false, musicActive = false;
static uint8_t sceneIdx = 0, flashesInScene = 0;
static uint32_t sceneAt = 0, whiteHitAt = 0;
static int regularBeats = 0;       // beats heard since music started; flashing waits for a few

// RBJ biquad low-pass, 150 Hz, Q 0.707 at 16 kHz: isolates kick/bass for beat detection.
struct Biquad {
  float b0, b1, b2, a1, a2, z1 = 0, z2 = 0;
  void lowpass(float fc, float q) {
    const float w = 2.0f * float(M_PI) * fc / RATE, c = cosf(w), s = sinf(w), alpha = s / (2 * q);
    const float a0 = 1 + alpha;
    b0 = (1 - c) / 2 / a0; b1 = (1 - c) / a0; b2 = b0; a1 = -2 * c / a0; a2 = (1 - alpha) / a0;
  }
  void bandpass(float fc, float q) {   // constant 0 dB peak gain
    const float w = 2.0f * float(M_PI) * fc / RATE, c = cosf(w), s = sinf(w), alpha = s / (2 * q);
    const float a0 = 1 + alpha;
    b0 = alpha / a0; b1 = 0; b2 = -alpha / a0; a1 = -2 * c / a0; a2 = (1 - alpha) / a0;
  }
  void highpass(float fc, float q) {
    const float w = 2.0f * float(M_PI) * fc / RATE, c = cosf(w), s = sinf(w), alpha = s / (2 * q);
    const float a0 = 1 + alpha;
    b0 = (1 + c) / 2 / a0; b1 = -(1 + c) / a0; b2 = b0; a1 = -2 * c / a0; a2 = (1 - alpha) / a0;
  }
  float step(float x) {
    const float y = b0 * x + z1;
    z1 = b1 * x - a1 * y + z2; z2 = b2 * x - a2 * y;
    return y;
  }
};

static const uint8_t PALETTE[][3] = {
  {255, 0, 0}, {0, 255, 0}, {0, 0, 255}, {200, 0, 255},
  {0, 255, 255}, {255, 200, 0}, {255, 255, 255}, {255, 80, 0},
};
static constexpr unsigned PALETTE_N = sizeof(PALETTE) / sizeof(PALETTE[0]);

static float medianBpm() {
  if (intervalCount < 3) return 0;
  const unsigned n = std::min(intervalCount, 8u);
  uint32_t tmp[8];
  std::copy(intervals, intervals + n, tmp);
  std::sort(tmp, tmp + n);
  return 60000.0f / tmp[n / 2];
}

static void audioTask(void *) {
  static int32_t raw[BLOCK];
  Biquad lp; lp.lowpass(150, 0.707f);
  Biquad bp; bp.bandpass(800, 0.6f);       // voice / melody
  Biquad hp; hp.highpass(3000, 0.707f);    // cymbals / hi-hats
  float bandPeak[3] = {1e-6f, 1e-6f, 1e-6f}, bandSmooth[3] = {0, 0, 0};
  float levelEma = 0, levelFloor = 0;
  float avg = 0, prev = 0, noise = 0;
  uint32_t settleUntil = millis() + 1500;   // first I2S blocks after start-up contain garbage
  int32_t first = 0; bool varied = false; uint32_t windowStart = millis();
  healthWatchThisTask();
  for (;;) {
    healthFeed();
    size_t got = 0;
    if (i2s_read(PORT, raw, sizeof raw, &got, pdMS_TO_TICKS(100)) != ESP_OK || got == 0) continue;
    const int n = got / sizeof(int32_t);
    double sumSq = 0, bassSq = 0, midSq = 0, highSq = 0;
    for (int i = 0; i < n; ++i) {
      const int32_t v = raw[i] >> 8;            // INMP441: 24-bit left-justified in 32 bits
      if (i == 0 && !varied) first = v;
      if (v != first) varied = true;
      const float x = v / 8388608.0f;
      const float y = lp.step(x), m = bp.step(x), h = hp.step(x);
      sumSq += x * x; bassSq += y * y; midSq += m * m; highSq += h * h;
    }
    const float level = sqrtf(sumSq / n), bass = bassSq / n;
    const uint32_t now = millis();
    if (int32_t(now - settleUntil) < 0) continue;
    // Per-band loudness normalised by its own slowly decaying peak (~10 s), then smoothed (~50 ms).
    const float bandE[3] = {sqrtf(bass), sqrtf(float(midSq / n)), sqrtf(float(highSq / n))};
    float bandN[3];
    for (int k = 0; k < 3; ++k) {
      bandPeak[k] = std::max(bandE[k], bandPeak[k] * 0.9985f);
      bandSmooth[k] += (bandE[k] / std::max(bandPeak[k], 1e-6f) - bandSmooth[k]) * 0.3f;
      bandN[k] = bandSmooth[k];
    }
    // Music gate from overall level vs. its quiet floor: 0 in a quiet room, 1 when music is clearly on.
    levelEma = levelEma == 0 ? level : levelEma + (level - levelEma) * 0.05f;
    // Floor creeps up only ~0.25%/s so hours of continuous music cannot be mistaken for silence.
    if (levelFloor == 0 || levelEma < levelFloor) levelFloor = levelEma; else levelFloor *= 1.00004f;
    const float relGate = (levelEma / std::max(levelFloor, 1e-5f) - 1.6f) / 1.5f;
    // Absolute gate: room/INMP441 noise measured ~0.001-0.003 here; music at ~0.006+ counts even if the
    // board booted while music was already playing (floor then equals the music level).
    const float absGate = (levelEma - ABS_MUSIC_LEVEL) / ABS_MUSIC_LEVEL;
    const float gate = std::min(1.0f, std::max({0.0f, relGate, absGate}));
    bool detected = st.micDetected;
    if (now - windowStart > 1000) { detected = varied; varied = false; windowStart = now; }
    avg = avg == 0 ? bass : avg + (bass - avg) * 0.03f;      // ~0.5 s time constant
    // Noise floor follows the quietest stretches of the running average (not single blocks):
    // drops at once when the room gets quieter, rises only ~0.25%/s while music plays.
    if (noise == 0 || avg < noise) noise = avg;
    else noise *= 1.00004f;
    // The noise term is capped so a floor learned during music never blocks beats.
    const float threshold = std::max({avg * cfg.micSens, std::min(noise * NOISE_GATE, NOISE_GATE_CAP), 2e-6f});
    const bool beat = detected && bass > threshold && bass > prev && now - lastBeatMs > MIN_BEAT_MS;
    prev = bass;
    levelPeak = std::max(level, levelPeak * 0.995f);
    portENTER_CRITICAL(&mux);
    st.running = true; st.micDetected = detected; st.level = level; st.bass = bass; st.bassAvg = avg; st.noise = noise;
    for (int k = 0; k < 3; ++k) mixBand[k] = bandN[k];
    mixGate = gate; mixLevel = std::min(1.0f, level / std::max(levelPeak, 1e-4f));
    if (beat) {
      beatStrength = std::min(1.0f, 0.55f + 0.45f * (bass / threshold - 1.0f));
      for (int k = 0; k < 3; ++k) beatBand[k] = bandN[k];   // colour is latched on the beat only
      if (lastBeatMs && now - lastBeatMs < 2000) {
        intervals[intervalCount % 8] = now - lastBeatMs; ++intervalCount;
      }
      lastBeatMs = now; ++st.beats; paletteIndex = (paletteIndex + 1) % PALETTE_N;
      st.bpm = medianBpm();
    }
    // ---- concert beat tracker ----
    const bool musicOn = gate > 0.3f && detected;
    if (st.bpm > 0) {
      float p = 60000.0f / st.bpm;
      while (p < 400) p *= 2;          // fast songs: flash every 2nd (or 4th) beat
      while (p > 900) p /= 2;
      trackPeriod = uint32_t(p);
    }
    // v0.4.1: react to the detected onset itself (prediction drifted off the beat in user tests);
    // the tempo only limits density, and flashing starts after several beats of real music.
    if (!musicOn) { if (now - musicOffSince > 1000) regularBeats = 0; }
    else musicOffSince = now;
    if (beat && musicOn) ++regularBeats;
    // ---- concert scenes (v0.5): theme colour per section, energy-driven climax / quiet parts ----
    levelMid = levelMid == 0 ? level : levelMid + (level - levelMid) * 0.008f;     // ~2 s
    levelSlow = levelSlow == 0 ? level : levelSlow + (level - levelSlow) * 0.002f; // ~8 s
    const float energy = levelMid / std::max(levelSlow, 1e-5f);
    climax = musicOn && energy > 1.3f;
    const uint32_t beatPeriod = st.bpm > 0 ? uint32_t(60000.0f / st.bpm) : 0;
    // Climax flashes every beat (but never faster than 300 ms); otherwise the folded period limits density.
    uint32_t minGap = trackPeriod ? trackPeriod * 8 / 10 : 400;
    if (climax && beatPeriod) minGap = std::max<uint32_t>(300, beatPeriod * 8 / 10);
    if (beat && musicOn && regularBeats >= 4 && now - flashAt >= minGap) {
      flashAt = now; ++flashCount; ++flashesInScene;
      const bool sectionJump = energy > 1.5f && now - sceneAt > 4000;
      if (flashesInScene >= 16 || sectionJump) {
        sceneIdx = (sceneIdx + 1) % 7; flashesInScene = 0; sceneAt = now;
        if (sectionJump) whiteHitAt = now;           // new section: one white hit
      }
    }
    st.flashes = flashCount;
    musicActive = musicOn && regularBeats >= 4;
    portEXIT_CRITICAL(&mux);
  }
}

bool audioInit() {
  i2s_config_t c{};
  c.mode = i2s_mode_t(I2S_MODE_MASTER | I2S_MODE_RX);
  c.sample_rate = RATE;
  c.bits_per_sample = I2S_BITS_PER_SAMPLE_32BIT;
  c.channel_format = cfg.micChannel ? I2S_CHANNEL_FMT_ONLY_RIGHT : I2S_CHANNEL_FMT_ONLY_LEFT;
  c.communication_format = I2S_COMM_FORMAT_STAND_I2S;
  c.intr_alloc_flags = ESP_INTR_FLAG_LEVEL1;
  c.dma_buf_count = 6; c.dma_buf_len = BLOCK;
  i2s_pin_config_t p{};
  // mck_io_num must be set explicitly: a zeroed struct routes MCLK (4 MHz) to GPIO0, the BOOT button pin.
  p.mck_io_num = I2S_PIN_NO_CHANGE;
  p.bck_io_num = PIN_BCK; p.ws_io_num = PIN_WS; p.data_out_num = I2S_PIN_NO_CHANGE; p.data_in_num = PIN_SD;
  if (i2s_driver_install(PORT, &c, 0, nullptr) != ESP_OK) return false;
  if (i2s_set_pin(PORT, &p) != ESP_OK) return false;
  xTaskCreatePinnedToCore(audioTask, "audio", 4096, nullptr, 2, nullptr, 0);
  return true;
}

AudioStatus audioStatus() {
  portENTER_CRITICAL(&mux); const AudioStatus s = st; portEXIT_CRITICAL(&mux);
  return s;
}

void audioColor(uint32_t now, uint8_t &r, uint8_t &g, uint8_t &b) {
  portENTER_CRITICAL(&mux);
  const uint32_t since = now - lastBeatMs; const bool any = lastBeatMs != 0;
  const uint8_t idx = paletteIndex; const float level = st.level; const bool mic = st.micDetected;
  const float band[3] = {beatBand[0], beatBand[1], beatBand[2]};
  const float gate = mixGate, lvl = mixLevel, strength = beatStrength;
  const uint32_t sinceFlash = now - flashAt; const uint8_t fc = flashCount;
  const uint8_t scene = sceneIdx; const bool hot = climax, active = musicActive;
  const uint32_t sinceWhite = now - whiteHitAt, period = trackPeriod;
  portEXIT_CRITICAL(&mux);
  if (cfg.micStyle == 4) {
    // concert: theme colour stays lit (35 %), beats punch to full, theme changes per section,
    // climax = every beat alternating white/theme, quiet stretch = slow breathing.
    static const uint8_t SHOW[][3] = {{255, 0, 0}, {0, 0, 255}, {200, 0, 255}, {0, 255, 255},
                                      {0, 255, 0}, {255, 0, 120}, {255, 80, 0}};
    static const uint8_t WHITE[3] = {255, 255, 255};
    const uint8_t *c = SHOW[scene % 7];
    float k = 0;
    if (mic && active) {
      const uint32_t quietAfter = std::max<uint32_t>(1500, 2 * period);
      if (sinceFlash < 110) { k = 1.0f; if (hot && (fc & 1)) c = WHITE; }
      else if (sinceFlash < 220) k = 0.7f;
      else if (sinceFlash > quietAfter) k = 0.15f + 0.25f * (0.5f + 0.5f * sinf(2.0f * float(M_PI) * (now % 2200) / 2200.0f));
      else if (cfg.micBase == 0 && sinceFlash >= 330) k = 0.0f;   // default: black between beats (punchier)
      else k = std::max(cfg.micBase / 100.0f, cfg.micBase == 0 ? 0.25f : 0.0f);   // 220-330 ms: short tail
      if (whiteHitAt && sinceWhite < 300) { c = WHITE; k = 1.0f; }
    }
    const float s = k * cfg.bright / 255.0f;
    r = uint8_t(c[0] * s); g = uint8_t(c[1] * s); b = uint8_t(c[2] * s);
    return;
  }
  if (cfg.micStyle == 3) {   // mix: colour = spectrum (bass red / mid green / treble blue), flash = beat, base = loudness
    if (!mic) { r = g = b = 0; return; }
    const float m = std::max({band[0], band[1], band[2], 0.05f});
    float c[3];
    // Saturated colours only: each channel snaps to 0, half or full, so mixes look clean (red/yellow/green/cyan/blue/purple).
    for (int i = 0; i < 3; ++i) { const float v = band[i] / m; c[i] = v > 0.8f ? 1.0f : (v > 0.55f ? 0.5f : 0.0f); }
    // Discrete brightness steps (smooth ramps look uneven on the band's 6-bit LEDs and 51 ms frames):
    // full for ~2 frames, then half, then dim, then off until the next beat.
    float flash = 0;
    if (any) flash = since < 100 ? 1.0f : since < 200 ? 0.5f : since < 300 ? 0.2f : 0.0f;
    if (flash > 0 && strength < 0.75f) flash *= 0.6f;   // weak beats flash softer
    (void)lvl;
    const float s = flash * (gate > 0.3f ? 1.0f : 0.0f) * cfg.bright / 255.0f;
    r = uint8_t(255 * c[0] * s); g = uint8_t(255 * c[1] * s); b = uint8_t(255 * c[2] * s);
    return;
  }
  float k = 0;
  if (mic && any) {
    if (cfg.micStyle == 0) k = since < cfg.micHoldMs ? 1.0f : 0.0f;                    // pulse
    else if (cfg.micStyle == 1) k = std::max(0.25f, 1.0f - since / 600.0f);           // cycle
    else k = std::min(1.0f, level / std::max(levelPeak, 1e-4f));                     // level
  }
  const float s = k * cfg.bright / 255.0f;
  r = uint8_t(PALETTE[idx][0] * s); g = uint8_t(PALETTE[idx][1] * s); b = uint8_t(PALETTE[idx][2] * s);
}
