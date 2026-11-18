#include "show.h"
#include <LittleFS.h>
#include <sys/stat.h>
#include "config.h"
#include "radio.h"

namespace {
struct Cue { uint32_t t; uint8_t r, g, b, mode; };

bool fsOk = false;
SemaphoreHandle_t lock;
// Loaded show (owned by this module, read by the radio task under `lock`).
Cue *cues = nullptr; uint16_t nCues = 0;
uint32_t *beats = nullptr; uint16_t nBeats = 0;
uint32_t durMs = 0, startMs = 0;
int playing = -1;
// Upload in progress.
File upFile; size_t upSize = 0, upDone = 0; int upSlot = -1;

constexpr uint32_t LEAD_MS = 60;   // lights lead the music slightly (radio frame + phone audio output delay)

String slotPath(unsigned s) { return String("/show") + s + ".bin"; }
// LittleFS.exists() opens the file and logs an error to the serial port when it is missing; stat() is silent.
bool fileExists(const String &path) { struct stat st; return stat((String("/littlefs") + path).c_str(), &st) == 0; }

uint32_t rd32(const uint8_t *p) { return p[0] | (p[1] << 8) | (p[2] << 16) | (uint32_t(p[3]) << 24); }
uint16_t rd16(const uint8_t *p) { return p[0] | (p[1] << 8); }

// Validates a whole file image; fills the header fields. Returns nullptr when it is a valid show.
const char *parse(const uint8_t *d, size_t n, String *name, uint32_t *dur, uint16_t *nc, uint16_t *nb, size_t *cueOff) {
  if (n < 13 || memcmp(d, "FLS1", 4)) return "not a show file";
  const size_t nameLen = d[4];
  size_t p = 5 + nameLen;
  if (p + 8 > n) return "truncated header";
  if (name) { name->reserve(nameLen); *name = ""; for (size_t i = 0; i < nameLen; ++i) { char c = d[5 + i]; if (c != '"' && c != '\\' && uint8_t(c) >= 0x20) *name += c; } }
  *dur = rd32(d + p); *nc = rd16(d + p + 4); *nb = rd16(d + p + 6); p += 8;
  if (p + size_t(*nc) * 8 + size_t(*nb) * 4 != n) return "size does not match header";
  if (!*nc || *dur == 0) return "empty show";
  *cueOff = p;
  return nullptr;
}

bool readFile(unsigned slot, std::unique_ptr<uint8_t[]> &buf, size_t &n) {
  if (!fileExists(slotPath(slot))) return false;   // open() of a missing file logs to the serial port
  File f = LittleFS.open(slotPath(slot), "r");
  if (!f) return false;
  n = f.size();
  if (n > SHOW_MAX_BYTES) { f.close(); return false; }
  buf.reset(new (std::nothrow) uint8_t[n]);
  const bool ok = buf && f.read(buf.get(), n) == n;
  f.close();
  return ok;
}

void freeShow() {
  delete[] cues; cues = nullptr; nCues = 0;
  delete[] beats; beats = nullptr; nBeats = 0;
  playing = -1;
}
}  // namespace

bool showInit() {
  lock = xSemaphoreCreateMutex();
  fsOk = LittleFS.begin(true);   // formats the data partition on first boot
  return fsOk;
}

void showList(Print &out) {
  out.print("{\"ok\":true,\"fs\":"); out.print(fsOk ? "true" : "false");
  out.print(",\"shows\":[");
  bool first = true;
  for (unsigned s = 0; fsOk && s < SHOW_SLOTS; ++s) {
    std::unique_ptr<uint8_t[]> buf; size_t n;
    if (!readFile(s, buf, n)) continue;
    String name; uint32_t dur; uint16_t nc, nb; size_t off;
    if (parse(buf.get(), n, &name, &dur, &nc, &nb, &off)) continue;
    out.printf("%s{\"slot\":%u,\"name\":\"%s\",\"dur_ms\":%u,\"cues\":%u,\"beats\":%u}", first ? "" : ",", s, name.c_str(), dur, nc, nb);
    first = false;
  }
  out.println("]}");
}

const char *showPutBegin(unsigned slot, size_t size) {
  if (!fsOk) return "storage not available";
  if (slot >= SHOW_SLOTS) return "slot must be 0..3";
  if (size < 13 || size > SHOW_MAX_BYTES) return "show too large (max 24 KB)";
  if (upFile) upFile.close();
  upFile = LittleFS.open("/upload.tmp", "w");
  if (!upFile) return "cannot open file";
  upSize = size; upDone = 0; upSlot = slot;
  return nullptr;
}

const char *showPutData(size_t offset, const char *hex) {
  if (!upFile) return "no upload in progress";
  if (offset != upDone) return "offset mismatch";
  uint8_t chunk[64]; size_t n = 0;
  for (const char *p = hex; p[0] && p[1]; p += 2) {
    if (n >= sizeof chunk) return "chunk too long";
    char h[3] = {p[0], p[1], 0}; char *end;
    chunk[n++] = uint8_t(strtoul(h, &end, 16));
    if (*end) return "bad hex";
  }
  if (upDone + n > upSize) return "more data than announced";
  if (upFile.write(chunk, n) != n) return "write failed";
  upDone += n;
  return nullptr;
}

const char *showPutEnd() {
  if (!upFile) return "no upload in progress";
  upFile.close();
  if (upDone != upSize) { LittleFS.remove("/upload.tmp"); return "upload incomplete"; }
  std::unique_ptr<uint8_t[]> buf(new (std::nothrow) uint8_t[upSize]);
  if (!buf) return "out of memory";
  File f = LittleFS.open("/upload.tmp", "r");
  const bool rd = f && f.read(buf.get(), upSize) == upSize; f.close();
  uint32_t dur; uint16_t nc, nb; size_t off;
  const char *e = rd ? parse(buf.get(), upSize, nullptr, &dur, &nc, &nb, &off) : "read back failed";
  if (e) { LittleFS.remove("/upload.tmp"); return e; }
  if (playing == upSlot) { radioOff(); xSemaphoreTake(lock, portMAX_DELAY); freeShow(); xSemaphoreGive(lock); }
  if (fileExists(slotPath(upSlot))) LittleFS.remove(slotPath(upSlot));
  if (!LittleFS.rename("/upload.tmp", slotPath(upSlot))) return "rename failed";
  upSlot = -1;
  return nullptr;
}

const char *showDelete(unsigned slot) {
  if (!fsOk) return "storage not available";
  if (slot >= SHOW_SLOTS) return "slot must be 0..3";
  if (playing == int(slot)) { radioOff(); xSemaphoreTake(lock, portMAX_DELAY); freeShow(); xSemaphoreGive(lock); }
  if (fileExists(slotPath(slot))) LittleFS.remove(slotPath(slot));
  return nullptr;
}

void showClearAll() {
  if (!fsOk) return;
  for (unsigned s = 0; s < SHOW_SLOTS; ++s) showDelete(s);
  if (upFile) upFile.close();
  if (fileExists("/upload.tmp")) LittleFS.remove("/upload.tmp");
  upSlot = -1;
}

const char *showPlay(unsigned slot, uint32_t fromMs) {
  if (!fsOk) return "storage not available";
  if (slot >= SHOW_SLOTS) return "slot must be 0..3";
  std::unique_ptr<uint8_t[]> buf; size_t n;
  if (!readFile(slot, buf, n)) return "no show in this slot";
  uint32_t dur; uint16_t nc, nb; size_t off;
  if (const char *e = parse(buf.get(), n, nullptr, &dur, &nc, &nb, &off)) return e;
  Cue *c = new (std::nothrow) Cue[nc];
  uint32_t *bt = nb ? new (std::nothrow) uint32_t[nb] : nullptr;
  if (!c || (nb && !bt)) { delete[] c; delete[] bt; return "out of memory"; }
  const uint8_t *p = buf.get() + off;
  for (unsigned i = 0; i < nc; ++i, p += 8) c[i] = {rd32(p), p[4], p[5], p[6], p[7]};
  for (unsigned i = 0; i < nb; ++i, p += 4) bt[i] = rd32(p);
  xSemaphoreTake(lock, portMAX_DELAY);
  freeShow();
  cues = c; nCues = nc; beats = bt; nBeats = nb; durMs = dur;
  startMs = millis() - min(fromMs, dur); playing = slot;
  xSemaphoreGive(lock);
  radioShow();
  return nullptr;
}

void showSync(uint32_t posMs) {
  xSemaphoreTake(lock, portMAX_DELAY);
  if (playing >= 0) startMs = millis() - min(posMs, durMs);
  xSemaphoreGive(lock);
}

bool showColor(uint32_t now, uint8_t &r, uint8_t &g, uint8_t &b) {
  r = g = b = 0;
  if (xSemaphoreTake(lock, pdMS_TO_TICKS(5)) != pdTRUE) return true;   // being reloaded: one dark frame
  if (playing < 0) { xSemaphoreGive(lock); return false; }
  const uint32_t pos = now - startMs;
  if (pos >= durMs) { freeShow(); xSemaphoreGive(lock); return false; }
  const uint32_t t = pos + LEAD_MS;
  // Last cue at or before t (cues are sorted by time).
  unsigned lo = 0, hi = nCues;
  while (hi - lo > 1) { const unsigned mid = (lo + hi) / 2; if (cues[mid].t <= t) lo = mid; else hi = mid; }
  const Cue &c = cues[lo];
  float k;
  uint8_t cr = c.r, cg = c.g, cb = c.b;
  switch (c.mode) {
    case 1: k = 0.85f; break;                              // steady
    case 2: {                                              // strobe, 8 Hz, every 4th flash white
      const uint32_t ph = t % 125;
      k = ph < 62 ? 1.0f : 0.0f;
      if (k > 0 && (t / 125) % 4 == 0) cr = cg = cb = 255;
      break;
    }
    case 3: k = 0.0f; break;                               // dark
    default: {                                             // punches on the drum beats
      unsigned blo = 0, bhi = nBeats; uint32_t since = 9999;
      if (nBeats && beats[0] <= t) {
        while (bhi - blo > 1) { const unsigned mid = (blo + bhi) / 2; if (beats[mid] <= t) blo = mid; else bhi = mid; }
        since = t - beats[blo];
      }
      k = since < 110 ? 1.0f : since < 220 ? 0.6f : since < 330 ? 0.25f : cfg.micBase / 100.0f;
    }
  }
  xSemaphoreGive(lock);
  const float s = k * cfg.bright / 255.0f;
  r = uint8_t(cr * s); g = uint8_t(cg * s); b = uint8_t(cb * s);
  return true;
}

bool showActive(int &slot, uint32_t &posMs, uint32_t &dur) {
  xSemaphoreTake(lock, portMAX_DELAY);
  slot = playing; posMs = playing >= 0 ? millis() - startMs : 0; dur = durMs;
  xSemaphoreGive(lock);
  return slot >= 0;
}
