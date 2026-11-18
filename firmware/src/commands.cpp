#include "commands.h"
#include <cstring>
#include <cstdlib>
#include "version.h"
#include "config.h"
#include "radio.h"
#include "audio.h"
#include "web.h"
#include "health.h"
#include "show.h"

bool radioOk = false, audioOk = false;
int micMonitorLevel = 0;   // 0 off, 1 levels every 100 ms, 2 onset/flash timestamps
volatile bool rebootPending = false;
uint32_t wakeUntil = 0;
static SemaphoreHandle_t cmdLock = nullptr;   // serialises runCommand (see below)

void commandsLoop() {
  // End a wake period only if nothing else took over the radio meanwhile.
  if (wakeUntil && int32_t(millis() - wakeUntil) >= 0) {
    if (cmdLock && xSemaphoreTake(cmdLock, 0) != pdTRUE) return;   // a command is running: try next loop
    struct Unlock { ~Unlock() { if (cmdLock) xSemaphoreGive(cmdLock); } } unlock;
    wakeUntil = 0;
    if (radioStatus().mode == RadioMode::Hold) radioOff();
    Serial.println("{\"evt\":\"wake_done\"}");
  }
}

static void ok(Print &o) { o.println("{\"ok\":true}"); }
static void err(Print &o, const char *msg) { o.printf("{\"ok\":false,\"err\":\"%s\"}\n", msg); }

static void printHello(Print &o) {
  const uint64_t mac = ESP.getEfuseMac();
  o.printf("{\"ok\":true,\"fw\":\"%s\",\"ver\":\"%s\",\"proto\":%d,\"built\":\"%s %s\","
           "\"mac\":\"%02X%02X%02X%02X%02X%02X\",\"radio\":%s,\"audio\":%s,\"wifi\":%s,\"ssid\":\"%s\",\"pwdef\":%s,\"reset\":\"%s\",\"boots\":%u}\n",
           FW_NAME, FW_VERSION, FW_PROTO, __DATE__, __TIME__,
           uint8_t(mac), uint8_t(mac >> 8), uint8_t(mac >> 16), uint8_t(mac >> 24),
           uint8_t(mac >> 32), uint8_t(mac >> 40),
           radioOk ? "true" : "false", audioOk ? "true" : "false",
           webRunning() ? "true" : "false", webSsid(),
           strcmp(cfg.apPass, Config().apPass) == 0 ? "true" : "false",   // still the factory password? (never the password itself)
           healthResetReason(), healthBoots());
}

static void printStatus(Print &o) {
  const RadioStatus r = radioStatus();
  const AudioStatus a = audioStatus();
  o.printf("{\"ok\":true,\"mode\":\"%s\",\"tailing\":%s,\"radio\":%s,\"freq\":%.4f,\"dbm\":%d,"
           "\"frames\":%u,\"tx_errors\":%u,\"max_ready_wait_us\":%u,"
           "\"mic\":%s,\"level\":%.4f,\"beats\":%u,\"bpm\":%.1f,\"uptime_s\":%u,\"wifi_clients\":%d,\"color\":\"#%02x%02x%02x\",",
           radioModeName(r.mode), r.tailing ? "true" : "false", r.ready ? "true" : "false",
           r.freqMHz, r.dbm, r.frames, r.txErrors, r.maxReadyWaitUs,
           a.micDetected ? "true" : "false", a.level, a.beats, a.bpm, unsigned(millis() / 1000), webClients(), r.rgb[0], r.rgb[1], r.rgb[2]);
  int slot; uint32_t pos, dur;
  if (r.mode == RadioMode::Show && showActive(slot, pos, dur)) o.printf("\"show\":{\"slot\":%d,\"pos_ms\":%u,\"dur_ms\":%u},", slot, pos, dur);
  webPrintApJson(o);
  healthPrintJson(o);
  o.println("}");
}

static bool parseRgb(const char *args, uint8_t &r, uint8_t &g, uint8_t &b) {
  unsigned rr, gg, bb; char extra;
  if (sscanf(args, "%u %u %u %c", &rr, &gg, &bb, &extra) != 3 || rr > 255 || gg > 255 || bb > 255) return false;
  r = rr; g = gg; b = bb; return true;
}

static void runCommandImpl(char *s, Print &o);
void commandsBegin() { if (!cmdLock) cmdLock = xSemaphoreCreateMutex(); }
// Commands arrive from the Arduino loop (USB serial) and from the web task: run one at a time.
void runCommand(char *s, Print &o) {
  if (!cmdLock) return runCommandImpl(s, o);
  xSemaphoreTake(cmdLock, portMAX_DELAY);
  runCommandImpl(s, o);
  xSemaphoreGive(cmdLock);
}

static void runCommandImpl(char *s, Print &o) {
  char *args = strchr(s, ' ');
  if (args) *args++ = 0; else args = s + strlen(s);
  uint8_t r, g, b;
  if (!strcmp(s, "hello")) return printHello(o);
  if (!strcmp(s, "status")) return printStatus(o);
  if (!strcmp(s, "config")) { o.print("{\"ok\":true,\"config\":"); configPrintJson(o); o.println("}"); return; }
  if (!strcmp(s, "set")) {
    char *value = strchr(args, ' ');
    if (!value) return err(o, "usage: set KEY VALUE");
    *value++ = 0;
    const bool radioKey = !strcmp(args, "freq") || !strcmp(args, "dbm") || !strcmp(args, "bitus") || !strcmp(args, "period");
    if (radioKey && radioStatus().mode != RadioMode::Off) return err(o, "stop transmitting first (off)");
    const Config before = cfg;
    if (const char *e = configSet(args, value)) return err(o, e);
    if (radioKey) {
      if (const char *e = radioApplyConfig()) { cfg = before; return err(o, e); }   // roll back on a failed register write
    }
    return ok(o);
  }
  if (!strcmp(s, "save")) { configSave(); return ok(o); }
  if (!strcmp(s, "factory")) {
    if (radioStatus().mode != RadioMode::Off) return err(o, "stop transmitting first (off)");
    configReset(); showClearAll(); radioApplyConfig(); return ok(o);
  }
  if (!radioOk && (!strcmp(s, "color") || !strcmp(s, "battest") || !strcmp(s, "stream") || !strcmp(s, "mic")))
    return err(o, "radio not ready");
  if (!strcmp(s, "color")) {
    if (!parseRgb(args, r, g, b)) return err(o, "usage: color R G B");
    wakeUntil = 0; radioHold(r, g, b); return ok(o);
  }
  if (!strcmp(s, "battest")) {   // battery test colour: same as color but bypasses the power limit
    if (!parseRgb(args, r, g, b)) return err(o, "usage: battest R G B");
    wakeUntil = 0; radioHoldUnlimited(r, g, b); return ok(o);
  }
  if (!strcmp(s, "stream")) {    // no reply: the PC streams ~20 colours per second
    if (!parseRgb(args, r, g, b)) return err(o, "usage: stream R G B");
    wakeUntil = 0; radioStream(r, g, b); return;
  }
  if (!strcmp(s, "mic")) {
    if (!audioOk) return err(o, "audio not ready");
    wakeUntil = 0; radioMic(); return ok(o);
  }
  if (!strcmp(s, "fx")) {
    // fx R G B ATTACK RANDOM RELEASE HOLD ONESHOT  (envelope codes 0..7, ONESHOT 0/1) - for effect research
    unsigned v[8]; char extra;
    if (sscanf(args, "%u %u %u %u %u %u %u %u %c", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6], &v[7], &extra) != 8 ||
        v[0] > 255 || v[1] > 255 || v[2] > 255 || v[3] > 7 || v[4] > 7 || v[5] > 7 || v[6] > 7 || v[7] > 1)
      return err(o, "usage: fx R G B ATTACK(0-7) RANDOM(0-7) RELEASE(0-7) HOLD(0-7) ONESHOT(0/1)");
    if (!radioOk) return err(o, "radio not ready");
    wakeUntil = 0;
    radioHoldBody(band::colorFx(v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7]));
    return ok(o);
  }
  if (!strcmp(s, "shows")) return showList(o);
  if (!strcmp(s, "showput")) {     // showput SLOT SIZE, then showdata OFFSET HEX..., then showend
    unsigned slot, size; char extra;
    if (sscanf(args, "%u %u %c", &slot, &size, &extra) != 2) return err(o, "usage: showput SLOT SIZE");
    if (const char *e = showPutBegin(slot, size)) return err(o, e);
    return ok(o);
  }
  if (!strcmp(s, "showdata")) {
    char *hex = strchr(args, ' ');
    if (!hex) return err(o, "usage: showdata OFFSET HEX");
    *hex++ = 0;
    if (const char *e = showPutData(strtoul(args, nullptr, 10), hex)) return err(o, e);
    return ok(o);
  }
  if (!strcmp(s, "showend")) { if (const char *e = showPutEnd()) return err(o, e); return ok(o); }
  if (!strcmp(s, "showclear")) { showClearAll(); return ok(o); }
  if (!strcmp(s, "showdel")) { if (const char *e = showDelete(atoi(args))) return err(o, e); return ok(o); }
  if (!strcmp(s, "showplay")) {    // showplay SLOT [FROM_MS]
    if (!radioOk) return err(o, "radio not ready");
    unsigned slot, from = 0;
    if (sscanf(args, "%u %u", &slot, &from) < 1) return err(o, "usage: showplay SLOT [FROM_MS]");
    wakeUntil = 0;
    if (const char *e = showPlay(slot, from)) return err(o, e);
    return ok(o);
  }
  if (!strcmp(s, "showsync")) { showSync(strtoul(args, nullptr, 10)); return ok(o); }
  if (!strcmp(s, "off")) { wakeUntil = 0; radioOff(); return ok(o); }
  if (!strcmp(s, "mute")) { wakeUntil = 0; radioMute(); return ok(o); }
  if (!strcmp(s, "wake")) {
    // Cold wristbands need ~30 s of continuous frames before they react. Send black frames, then stop.
    if (!radioOk) return err(o, "radio not ready");
    long secs = atol(args); if (secs <= 0) secs = 30; if (secs > 120) secs = 120;
    radioHold(0, 0, 0); wakeUntil = millis() + secs * 1000UL; if (!wakeUntil) wakeUntil = 1;
    return ok(o);
  }
  if (!strcmp(s, "micmon")) { micMonitorLevel = constrain(atoi(args), 0, 2); return ok(o); }
  if (!strcmp(s, "diag")) return radioDiag(o);
  if (!strcmp(s, "reboot")) { ok(o); rebootPending = true; return; }
  if (!strcmp(s, "help")) {
    o.println("{\"ok\":true,\"help\":\"hello|status|config|set KEY VALUE|save|factory|color R G B|stream R G B|mic|off|"
              "shows|showplay SLOT [MS]|showsync MS|showput SLOT SIZE|showdata OFF HEX|showend|showdel SLOT|showclear|micmon 0/1|diag|reboot  keys: freq dbm bitus period msens mstyle mhold bright mch auto wifi appass\"}");
    return;
  }
  err(o, "unknown command");
}
