#include "radio.h"
#include "audio.h"
#include "config.h"
#include "health.h"
#include "protocol.h"
#include "show.h"
#include <ELECHOUSE_CC1101_SRC_DRV.h>
#include <driver/rmt.h>

// Wiring (unchanged from the lab build): CSN 5, SCK 18, MISO 19, MOSI 23, GDO0 27.
static constexpr int TX_GPIO = 27;
static constexpr rmt_channel_t TX_CHANNEL = RMT_CHANNEL_0;
static constexpr unsigned OFF_TAIL_FRAMES = 10;
static constexpr uint32_t STREAM_TIMEOUT_MS = 1000;

static SemaphoreHandle_t spiLock;            // CC1101 SPI + radio settings
static portMUX_TYPE stateMux = portMUX_INITIALIZER_UNLOCKED;
static bool ready = false;
static volatile RadioMode mode = RadioMode::Off;
static volatile unsigned tail = 0;           // black frames still to send
static band::Body holdBody = band::color(0, 0, 0);
static volatile uint32_t streamDeadline = 0;
static volatile uint32_t frames = 0, txErrors = 0, maxReadyWait = 0;
static float readFreq = 0;
static int appliedDbm = 0;
static uint16_t bitUs = 500, periodMs = 51;
static uint32_t nextKeepalive = 0;
static uint8_t holdRgb[3] = {0, 0, 0};
static volatile bool holdUnlimited = false;   // battery test: send this hold colour without the power limit   // last requested 8-bit colour (for UI feedback)
volatile bool radioSuspended = false;

const char *radioModeName(RadioMode m) {
  switch (m) {
    case RadioMode::Hold: return "hold";
    case RadioMode::Stream: return "stream";
    case RadioMode::Mic: return "mic";
    case RadioMode::Show: return "show";
    default: return "off";
  }
}

static float regFreq() {
  const uint32_t w = (uint32_t(ELECHOUSE_cc1101.SpiReadReg(CC1101_FREQ2)) << 16) |
                     (uint32_t(ELECHOUSE_cc1101.SpiReadReg(CC1101_FREQ1)) << 8) |
                     ELECHOUSE_cc1101.SpiReadReg(CC1101_FREQ0);
  return 26.0f * w / 65536.0f;
}

static bool applyLocked() {
  ELECHOUSE_cc1101.setSidle();
  ELECHOUSE_cc1101.setMHZ(cfg.freqMHz);
  ELECHOUSE_cc1101.setChannel(0);
  ELECHOUSE_cc1101.setPA(cfg.dbm);
  uint8_t pa[8];
  ELECHOUSE_cc1101.SpiReadBurstReg(CC1101_PATABLE, pa, 8);
  const uint8_t expected = cfg.dbm == -10 ? 0x34 : (cfg.dbm == 0 ? 0x60 : (cfg.dbm == 5 ? 0x84 : 0xc0));
  readFreq = regFreq();
  const bool ok = pa[0] == 0 && pa[1] == expected && fabsf(readFreq - cfg.freqMHz) < 0.002f;
  appliedDbm = cfg.dbm;
  bitUs = cfg.bitUs; periodMs = cfg.periodMs;
  return ok;
}

const char *radioApplyConfig() {
  if (!ready) return "radio not ready";
  if (mode != RadioMode::Off || tail) return "stop transmitting first (off)";
  xSemaphoreTake(spiLock, portMAX_DELAY);
  const bool ok = applyLocked();
  xSemaphoreGive(spiLock);
  if (!ok) { ready = false; return "register readback mismatch; radio disabled"; }
  return nullptr;
}

static void startMode(RadioMode m) {
  portENTER_CRITICAL(&stateMux);
  holdUnlimited = false;
  if (mode != m) { frames = 0; maxReadyWait = 0; }
  mode = m; tail = 0;
  if (m == RadioMode::Stream) streamDeadline = millis() + STREAM_TIMEOUT_MS;
  portEXIT_CRITICAL(&stateMux);
}

void radioHold(uint8_t r, uint8_t g, uint8_t b) {
  portENTER_CRITICAL(&stateMux); holdBody = band::color(r, g, b); holdRgb[0] = r; holdRgb[1] = g; holdRgb[2] = b; portEXIT_CRITICAL(&stateMux);
  startMode(RadioMode::Hold);
}
void radioHoldBody(const band::Body &body) {
  if (body[0] != 0x00 && body[0] != 0x10) return;   // live modes only
  portENTER_CRITICAL(&stateMux); holdBody = body; portEXIT_CRITICAL(&stateMux);
  startMode(RadioMode::Hold);
}
void radioHoldUnlimited(uint8_t r, uint8_t g, uint8_t b) {
  radioHold(r, g, b);
  holdUnlimited = true;   // set after startMode() cleared it
}
void radioStream(uint8_t r, uint8_t g, uint8_t b) {
  portENTER_CRITICAL(&stateMux); holdBody = band::color(r, g, b); portEXIT_CRITICAL(&stateMux);
  startMode(RadioMode::Stream);
}
void radioMic() { startMode(RadioMode::Mic); }
void radioShow() { startMode(RadioMode::Show); }
void radioMute() {   // stop instantly without the dark tail (tests: simulates losing the signal)
  portENTER_CRITICAL(&stateMux); mode = RadioMode::Off; tail = 0; portEXIT_CRITICAL(&stateMux);
}
void radioOff() {
  portENTER_CRITICAL(&stateMux);
  if (mode != RadioMode::Off || tail) tail = OFF_TAIL_FRAMES;
  mode = RadioMode::Off;
  portEXIT_CRITICAL(&stateMux);
}

RadioStatus radioStatus() {
  RadioStatus s;
  portENTER_CRITICAL(&stateMux);
  s.ready = ready; s.mode = mode; s.tailing = tail > 0; s.frames = frames;
  s.txErrors = txErrors; s.maxReadyWaitUs = maxReadyWait;
  s.rgb[0] = holdRgb[0]; s.rgb[1] = holdRgb[1]; s.rgb[2] = holdRgb[2];
  portEXIT_CRITICAL(&stateMux);
  s.freqMHz = readFreq; s.dbm = appliedDbm;
  return s;
}

// Coin-cell wristbands brown out (flicker) when too many LED channels are driven hard
// (2026-11-12: white 100% flickers on both bands, red 100% / two-colour mixes on the old-battery band;
// white 40% and red 80% are steady). Cap each 6-bit channel and the channel sum before sending.
static band::Body powerLimit(band::Body b) {
  const unsigned chanCap = cfg.powerChan * 63u / 100u;   // % of full scale per channel
  const unsigned sumCap = cfg.powerSum * 63u / 100u;     // % of one full channel, summed over R+G+B
  unsigned c[3] = {b[1], b[2], b[3]};
  // Scale all channels by the same factor (never clip one channel alone) so the hue is kept:
  // clipping made purple (200,0,255) and pink (255,0,120) look the same under a low cap.
  const unsigned mx = c[0] > c[1] ? (c[0] > c[2] ? c[0] : c[2]) : (c[1] > c[2] ? c[1] : c[2]);
  if (mx > chanCap) for (auto &v : c) v = (v * chanCap + mx / 2) / mx;
  const unsigned sum = c[0] + c[1] + c[2];
  if (sum > sumCap) for (auto &v : c) v = v * sumCap / sum;
  b[1] = c[0]; b[2] = c[1]; b[3] = c[2];
  // Auto-off: plain live colours carry hold = 7 (infinite); use hold 6 so bands go dark ~30-40 s after the signal stops.
  if (cfg.autoOff && b[0] == 0x00 && (b[5] & 7) == 7) b[5] = (b[5] & 0x38) | 6;
  return b;
}

static bool sendFrame(const band::Body &raw, bool limit) {
  const auto body = limit ? powerLimit(raw) : raw;
  const auto data = band::bits(body);
  rmt_item32_t items[45]{};
  for (unsigned i = 0; i < 45; ++i) {
    items[i].level0 = data[2 * i]; items[i].duration0 = bitUs;
    items[i].level1 = data[2 * i + 1]; items[i].duration1 = bitUs;
  }
  ELECHOUSE_cc1101.SetTx();
  delayMicroseconds(800);
  const uint32_t start = micros();
  uint8_t state = ELECHOUSE_cc1101.SpiReadStatus(CC1101_MARCSTATE) & 0x1f;
  while (state != 0x13 && uint32_t(micros() - start) < 3000) {
    delayMicroseconds(100);
    state = ELECHOUSE_cc1101.SpiReadStatus(CC1101_MARCSTATE) & 0x1f;
  }
  const uint32_t wait = micros() - start;
  if (wait > maxReadyWait) maxReadyWait = wait;
  bool ok = state == 0x13;
  if (ok) ok = rmt_write_items(TX_CHANNEL, items, 45, true) == ESP_OK;
  ELECHOUSE_cc1101.setSidle();
  return ok;
}

static void radioTask(void *) {
  TickType_t last = xTaskGetTickCount();
  healthWatchThisTask();
  for (;;) {
    healthFeed();
    band::Body body;
    bool send = false;
    const uint32_t now = millis();
    portENTER_CRITICAL(&stateMux);
    if (mode == RadioMode::Stream && int32_t(now - streamDeadline) >= 0) {
      mode = RadioMode::Off; tail = OFF_TAIL_FRAMES / 2;   // host stopped streaming: black, then silent
    }
    const RadioMode m = mode;
    if (m == RadioMode::Hold || m == RadioMode::Stream) { body = holdBody; send = true; }
    else if (m == RadioMode::Off && tail) { body = band::color(0, 0, 0); --tail; send = true; }
    else if (m == RadioMode::Off && cfg.keepalive && int32_t(now - nextKeepalive) >= 0) {
      // Keep-alive: dark frames keep the wristbands awake so they react at once (cold bands need ~30 s).
      body = band::color(0, 0, 0); send = true; nextKeepalive = now + cfg.keepaliveMs;
    }
    portEXIT_CRITICAL(&stateMux);
    if (m == RadioMode::Mic) {
      uint8_t r, g, b; audioColor(now, r, g, b);
      body = band::color(r, g, b); send = true;
    }
    if (m == RadioMode::Show) {
      uint8_t r, g, b;
      if (showColor(now, r, g, b)) { body = band::color(r, g, b); send = true; }
      else { radioOff(); continue; }   // show finished: dark tail, then silent
    }
    if (radioSuspended) send = false;
    if (!send || !ready) { vTaskDelay(pdMS_TO_TICKS(5)); last = xTaskGetTickCount(); continue; }
    xSemaphoreTake(spiLock, portMAX_DELAY);
    const bool ok = sendFrame(body, !(m == RadioMode::Hold && holdUnlimited));
    xSemaphoreGive(spiLock);
    portENTER_CRITICAL(&stateMux);
    if (ok) ++frames;
    else { ++txErrors; mode = RadioMode::Off; tail = 0; }
    portEXIT_CRITICAL(&stateMux);
    if (!ok) Serial.println("{\"evt\":\"tx_error\",\"msg\":\"TX state or RMT error; stopped\"}");
    vTaskDelayUntil(&last, pdMS_TO_TICKS(periodMs));
  }
}

bool radioInit() {
  spiLock = xSemaphoreCreateMutex();
  if (!band::selfTest()) return false;
  ELECHOUSE_cc1101.setSpiPin(18, 19, 23, 5);
  ELECHOUSE_cc1101.Init();
  const uint8_t version = ELECHOUSE_cc1101.SpiReadStatus(CC1101_VERSION);
  const uint8_t part = ELECHOUSE_cc1101.SpiReadStatus(CC1101_PARTNUM);
  if (part != 0 || version == 0 || version == 255) return false;
  ELECHOUSE_cc1101.setCCMode(0);       // asynchronous serial; GDO0 = TX data in
  ELECHOUSE_cc1101.setModulation(2);   // ASK/OOK
  if (!applyLocked()) return false;
  rmt_config_t c{};
  c.rmt_mode = RMT_MODE_TX; c.channel = TX_CHANNEL;
  c.gpio_num = static_cast<gpio_num_t>(TX_GPIO);
  c.clk_div = 80; c.mem_block_num = 1;
  c.tx_config.loop_en = false; c.tx_config.carrier_en = false;
  c.tx_config.idle_output_en = true; c.tx_config.idle_level = RMT_IDLE_LEVEL_LOW;
  if (rmt_config(&c) != ESP_OK || rmt_driver_install(TX_CHANNEL, 0, 0) != ESP_OK) return false;
  ready = true;
  xTaskCreatePinnedToCore(radioTask, "radio", 4096, nullptr, 3, nullptr, 1);
  return true;
}

void radioDiag(Print &out) {
  if (!ready) { out.println("{\"ok\":false,\"err\":\"radio not ready\"}"); return; }
  xSemaphoreTake(spiLock, portMAX_DELAY);
  uint8_t pa[8];
  ELECHOUSE_cc1101.SpiReadBurstReg(CC1101_PATABLE, pa, 8);
  out.printf("{\"ok\":true,\"diag\":{\"partnum\":%u,\"version\":%u,\"freq_reg_mhz\":%.6f,\"iocfg0\":%u,"
             "\"pktctrl0\":%u,\"mdmcfg2\":%u,\"frend0\":%u,\"marcstate\":%u,\"patable\":[%u,%u]}}\n",
             ELECHOUSE_cc1101.SpiReadStatus(CC1101_PARTNUM), ELECHOUSE_cc1101.SpiReadStatus(CC1101_VERSION),
             regFreq(), ELECHOUSE_cc1101.SpiReadReg(CC1101_IOCFG0), ELECHOUSE_cc1101.SpiReadReg(CC1101_PKTCTRL0),
             ELECHOUSE_cc1101.SpiReadReg(CC1101_MDMCFG2), ELECHOUSE_cc1101.SpiReadReg(CC1101_FREND0),
             ELECHOUSE_cc1101.SpiReadStatus(CC1101_MARCSTATE) & 0x1f, pa[0], pa[1]);
  xSemaphoreGive(spiLock);
}
