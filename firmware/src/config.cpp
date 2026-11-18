#include "config.h"
#include <Preferences.h>
#include <cstdlib>
#include <cstring>

Config cfg;
static Preferences prefs;

void configLoad() {
  Config d;
  prefs.begin("pixmob", true);
  cfg.freqMHz = prefs.getFloat("freq", d.freqMHz);
  cfg.dbm = prefs.getChar("dbm", d.dbm);
  cfg.bitUs = prefs.getUShort("bitus", d.bitUs);
  cfg.periodMs = prefs.getUShort("period", d.periodMs);
  cfg.micSens = prefs.getFloat("msens", d.micSens);
  cfg.micStyle = prefs.getUChar("mstyle", d.micStyle);
  cfg.micHoldMs = prefs.getUShort("mhold", d.micHoldMs);
  cfg.bright = prefs.getUChar("bright", d.bright);
  cfg.micBase = prefs.getUChar("mbase", d.micBase);
  cfg.powerChan = prefs.getUChar("pchan", d.powerChan);
  cfg.powerSum = prefs.getUShort("psum", d.powerSum);
  cfg.micChannel = prefs.getUChar("mch", d.micChannel);
  cfg.autostart = prefs.getUChar("auto", d.autostart);
  cfg.wifi = prefs.getUChar("wifi", d.wifi);
  cfg.keepalive = prefs.getUChar("ka", d.keepalive);
  cfg.autoOff = prefs.getUChar("aoff", d.autoOff);
  cfg.keepaliveMs = prefs.getUShort("kams", d.keepaliveMs);
  String pw = prefs.getString("appass", d.apPass);
  prefs.end();
  if (pw.length() >= 8 && pw.length() <= 20) strlcpy(cfg.apPass, pw.c_str(), sizeof cfg.apPass);
  if (cfg.wifi > 1) cfg.wifi = d.wifi;
  if (cfg.keepalive > 1) cfg.keepalive = d.keepalive;
  if (cfg.autoOff > 1) cfg.autoOff = d.autoOff;
  if (cfg.keepaliveMs < 51 || cfg.keepaliveMs > 2000) cfg.keepaliveMs = d.keepaliveMs;
  // Re-validate stored values so a corrupted NVS can never produce out-of-range radio settings.
  char buf[24];
  snprintf(buf, sizeof buf, "%.4f", cfg.freqMHz); if (configSet("freq", buf)) cfg.freqMHz = d.freqMHz;
  snprintf(buf, sizeof buf, "%d", cfg.dbm); if (configSet("dbm", buf)) cfg.dbm = d.dbm;
  if (cfg.bitUs < 400 || cfg.bitUs > 700) cfg.bitUs = d.bitUs;
  if (cfg.periodMs < 47 || cfg.periodMs > 250 || cfg.periodMs * 1000u < cfg.bitUs * 90u + 2000u) {
    cfg.bitUs = d.bitUs; cfg.periodMs = d.periodMs;
  }
  if (cfg.micSens < 1.05f || cfg.micSens > 4.0f) cfg.micSens = d.micSens;
  if (cfg.micStyle > 4) cfg.micStyle = d.micStyle;
  if (cfg.micHoldMs < 40 || cfg.micHoldMs > 600) cfg.micHoldMs = d.micHoldMs;
  if (cfg.bright == 0) cfg.bright = d.bright;
  if (cfg.micBase > 60) cfg.micBase = d.micBase;
  if (cfg.powerChan < 20 || cfg.powerChan > 100) cfg.powerChan = d.powerChan;
  if (cfg.powerSum < 50 || cfg.powerSum > 300) cfg.powerSum = d.powerSum;
  if (cfg.micChannel > 1) cfg.micChannel = d.micChannel;
  if (cfg.autostart > 1) cfg.autostart = d.autostart;
}

void configSave() {
  prefs.begin("pixmob", false);
  prefs.putFloat("freq", cfg.freqMHz);
  prefs.putChar("dbm", cfg.dbm);
  prefs.putUShort("bitus", cfg.bitUs);
  prefs.putUShort("period", cfg.periodMs);
  prefs.putFloat("msens", cfg.micSens);
  prefs.putUChar("mstyle", cfg.micStyle);
  prefs.putUShort("mhold", cfg.micHoldMs);
  prefs.putUChar("bright", cfg.bright);
  prefs.putUChar("mbase", cfg.micBase);
  prefs.putUChar("pchan", cfg.powerChan);
  prefs.putUShort("psum", cfg.powerSum);
  prefs.putUChar("mch", cfg.micChannel);
  prefs.putUChar("auto", cfg.autostart);
  prefs.putUChar("wifi", cfg.wifi);
  prefs.putUChar("ka", cfg.keepalive);
  prefs.putUChar("aoff", cfg.autoOff);
  prefs.putUShort("kams", cfg.keepaliveMs);
  prefs.putString("appass", cfg.apPass);
  prefs.end();
}

void configReset() {
  prefs.begin("pixmob", false);
  prefs.clear();
  prefs.end();
  cfg = Config();
}

static bool parseLong(const char *s, long lo, long hi, long &out) {
  char *end = nullptr;
  const long v = strtol(s, &end, 10);
  if (!s[0] || *end) return false;
  if (v < lo || v > hi) return false;
  out = v; return true;
}
static bool parseFloat(const char *s, float lo, float hi, float &out) {
  char *end = nullptr;
  const float v = strtof(s, &end);
  if (!s[0] || *end) return false;
  if (!(v >= lo && v <= hi)) return false;
  out = v; return true;
}

const char *configSet(const char *key, const char *value) {
  long l; float f;
  if (!strcmp(key, "freq")) {
    if (!parseFloat(value, 433.05f, 434.79f, f)) return "freq must be 433.05..434.79";
    cfg.freqMHz = f; return nullptr;
  }
  if (!strcmp(key, "dbm")) {
    if (!parseLong(value, -10, 10, l) || (l != -10 && l != 0 && l != 5 && l != 10)) return "dbm must be -10,0,5,10";
    cfg.dbm = l; return nullptr;
  }
  if (!strcmp(key, "bitus")) {
    if (!parseLong(value, 400, 700, l)) return "bitus must be 400..700";
    if (cfg.periodMs * 1000L < l * 90L + 2000L) return "bitus too long for current period";
    cfg.bitUs = l; return nullptr;
  }
  if (!strcmp(key, "period")) {
    if (!parseLong(value, 47, 250, l)) return "period must be 47..250";
    if (l * 1000L < cfg.bitUs * 90L + 2000L) return "period too short for current bitus";
    cfg.periodMs = l; return nullptr;
  }
  if (!strcmp(key, "msens")) {
    if (!parseFloat(value, 1.05f, 4.0f, f)) return "msens must be 1.05..4.0";
    cfg.micSens = f; return nullptr;
  }
  if (!strcmp(key, "mstyle")) {
    if (!parseLong(value, 0, 4, l)) return "mstyle must be 0 pulse,1 cycle,2 level,3 mix,4 concert";
    cfg.micStyle = l; return nullptr;
  }
  if (!strcmp(key, "mhold")) {
    if (!parseLong(value, 40, 600, l)) return "mhold must be 40..600";
    cfg.micHoldMs = l; return nullptr;
  }
  if (!strcmp(key, "bright")) {
    if (!parseLong(value, 1, 255, l)) return "bright must be 1..255";
    cfg.bright = l; return nullptr;
  }
  if (!strcmp(key, "pchan")) {
    if (!parseLong(value, 20, 100, l)) return "pchan must be 20..100 (%)";
    cfg.powerChan = l; return nullptr;
  }
  if (!strcmp(key, "psum")) {
    if (!parseLong(value, 30, 300, l)) return "psum must be 30..300 (%)";
    cfg.powerSum = l; return nullptr;
  }
  if (!strcmp(key, "mbase")) {
    if (!parseLong(value, 0, 60, l)) return "mbase must be 0..60 (%)";
    cfg.micBase = l; return nullptr;
  }
  if (!strcmp(key, "mch")) {
    if (!parseLong(value, 0, 1, l)) return "mch must be 0 left or 1 right";
    cfg.micChannel = l; return nullptr;
  }
  if (!strcmp(key, "auto")) {
    if (!parseLong(value, 0, 1, l)) return "auto must be 0 none or 1 mic";
    cfg.autostart = l; return nullptr;
  }
  if (!strcmp(key, "aoff")) {
    if (!parseLong(value, 0, 1, l)) return "aoff must be 0 or 1";
    cfg.autoOff = l; return nullptr;
  }
  if (!strcmp(key, "ka")) {
    if (!parseLong(value, 0, 1, l)) return "ka must be 0 or 1";
    cfg.keepalive = l; return nullptr;
  }
  if (!strcmp(key, "kams")) {
    if (!parseLong(value, 51, 2000, l)) return "kams must be 51..2000";
    cfg.keepaliveMs = l; return nullptr;
  }
  if (!strcmp(key, "wifi")) {
    if (!parseLong(value, 0, 1, l)) return "wifi must be 0 or 1 (applies after save + reboot)";
    cfg.wifi = l; return nullptr;
  }
  if (!strcmp(key, "appass")) {
    const size_t n = strlen(value);
    if (n < 8 || n > 20) return "appass must be 8..20 characters";
    for (size_t i = 0; i < n; ++i) if (value[i] < 33 || value[i] > 126 || value[i] == '"' || value[i] == '\\') return "appass: letters, digits, symbols only";
    strlcpy(cfg.apPass, value, sizeof cfg.apPass); return nullptr;
  }
  return "unknown key";
}

void configPrintJson(Print &out) {
  out.printf("{\"freq\":%.4f,\"dbm\":%d,\"bitus\":%u,\"period\":%u,\"msens\":%.2f,\"mstyle\":%u,"
             "\"mhold\":%u,\"bright\":%u,\"mbase\":%u,\"pchan\":%u,\"psum\":%u,\"mch\":%u,\"auto\":%u,\"ka\":%u,\"kams\":%u,\"aoff\":%u,\"wifi\":%u}",
             cfg.freqMHz, cfg.dbm, cfg.bitUs, cfg.periodMs, cfg.micSens, cfg.micStyle,
             cfg.micHoldMs, cfg.bright, cfg.micBase, cfg.powerChan, cfg.powerSum, cfg.micChannel, cfg.autostart, cfg.keepalive, cfg.keepaliveMs, cfg.autoOff, cfg.wifi);
}
