#include "web.h"
#include <WiFi.h>
#include <WebServer.h>
#include <Update.h>
#include <StreamString.h>
#include <DNSServer.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <esp_wifi.h>
#include <esp_netif.h>
#include "config.h"
#include "commands.h"
#include "radio.h"
#include "webpage.h"

static WebServer server(80);
// The web server runs in its own FreeRTOS task. WebServer can block for several seconds per request when a
// phone drops off Wi-Fi mid-transfer (HTTP_MAX_DATA_WAIT / HTTP_MAX_SEND_WAIT are 5 s each); in the Arduino
// loop task that tripped the 8 s task watchdog and restarted the controller (soak test 2026-11-12 23:37).
// Here a stuck request only delays the web page; radio, buttons and USB serial keep running.
static volatile bool running = false;
static volatile bool wantRun = false;
static TaskHandle_t webTask = nullptr;
static char ssid[24] = "";
static String updateError;

// Hotspot diagnostics (investigating "phone can't find the hotspot" reports, 2026-11-13): every Wi-Fi AP event
// goes to USB serial as {"evt":"ap",...}, and the web task checks every 5 s that the radio is still in AP mode.
static volatile uint32_t apStarts = 0, apStops = 0, apJoins = 0, apLeaves = 0, apModeLost = 0;
static volatile bool apModeOk = false;
static void onWifiEvent(arduino_event_id_t e, arduino_event_info_t) {
  const char *what = nullptr;
  switch (e) {
    case ARDUINO_EVENT_WIFI_AP_START: ++apStarts; what = "start"; break;
    case ARDUINO_EVENT_WIFI_AP_STOP: ++apStops; what = "stop"; break;
    case ARDUINO_EVENT_WIFI_AP_STACONNECTED: ++apJoins; what = "join"; break;
    case ARDUINO_EVENT_WIFI_AP_STADISCONNECTED: ++apLeaves; what = "leave"; break;
    default: return;
  }
  Serial.printf("{\"evt\":\"ap\",\"what\":\"%s\",\"t\":%u}\n", what, unsigned(millis() / 1000));
}
static void checkApMode() {
  static uint32_t last = 0;
  if (millis() - last < 5000) return;
  last = millis();
  wifi_mode_t m = WIFI_MODE_NULL;
  const bool ok = esp_wifi_get_mode(&m) == ESP_OK && (m == WIFI_MODE_AP || m == WIFI_MODE_APSTA);
  if (ok != apModeOk) {
    if (!ok) ++apModeLost;
    Serial.printf("{\"evt\":\"ap\",\"what\":\"%s\",\"mode\":%d,\"t\":%u}\n", ok ? "mode_ok" : "mode_lost", int(m), unsigned(millis() / 1000));
    apModeOk = ok;
  }
}
// Every Afterglow firmware image carries this marker; a Wi-Fi update must contain it, so a wrong .bin
// (another ESP32 program) is refused instead of replacing the controller firmware.
extern const char AFTERGLOW_FW_MARKER[];
const char AFTERGLOW_FW_MARKER[] __attribute__((used)) = "AFTERGLOW-FW-IMAGE/1";
static constexpr size_t MARKER_LEN = sizeof("AFTERGLOW-FW-IMAGE/1") - 1;
static bool markerSeen = false;
static char markerTail[32];
static size_t markerTailLen = 0;
static void scanMarker(const uint8_t *buf, size_t n) {
  if (markerSeen) return;
  // search the previous chunk's tail joined with this chunk's head, then this chunk
  char join[64];
  const size_t head = n < MARKER_LEN ? n : MARKER_LEN;
  memcpy(join, markerTail, markerTailLen); memcpy(join + markerTailLen, buf, head);
  if (memmem(join, markerTailLen + head, AFTERGLOW_FW_MARKER, MARKER_LEN)) { markerSeen = true; return; }
  if (memmem(buf, n, AFTERGLOW_FW_MARKER, MARKER_LEN)) { markerSeen = true; return; }
  markerTailLen = n < MARKER_LEN - 1 ? n : MARKER_LEN - 1;
  memcpy(markerTail, buf + n - markerTailLen, markerTailLen);
}
static DNSServer dns;
// Captive portal: a phone that has never opened the control page is redirected to it (the OS pops it up).
// Once it has, we answer the OS connectivity checks as "online" so the phone stays on this Wi-Fi.
// Phones are remembered by their Wi-Fi MAC address in NVS, so after a restart of the controller a known
// phone gets "online" at once: no pop-up sheet again, and iOS keeps the network (and its password).
static uint32_t acceptedIp[8] = {0};
static unsigned acceptedIpNext = 0;
static constexpr unsigned KNOWN_MAX = 16;
static uint8_t knownMac[KNOWN_MAX][6];
static unsigned knownCount = 0, knownNext = 0;

static void loadKnown() {
  Preferences p; p.begin("pixmob", true);
  knownCount = p.getBytes("pmacs", knownMac, sizeof knownMac) / 6;
  knownNext = p.getUChar("pmnext", knownCount % KNOWN_MAX);
  p.end();
}
static bool macForIp(uint32_t ip, uint8_t mac[6]) {
  wifi_sta_list_t wl; esp_netif_sta_list_t nl;
  if (esp_wifi_ap_get_sta_list(&wl) != ESP_OK || esp_netif_get_sta_list(&wl, &nl) != ESP_OK) return false;
  for (int i = 0; i < nl.num; ++i) if (nl.sta[i].ip.addr == ip) { memcpy(mac, nl.sta[i].mac, 6); return true; }
  return false;
}
static bool isKnownMac(const uint8_t mac[6]) {
  for (unsigned i = 0; i < knownCount; ++i) if (!memcmp(knownMac[i], mac, 6)) return true;
  return false;
}
static bool isAccepted(uint32_t ip) {
  for (uint32_t a : acceptedIp) if (a == ip) return true;
  uint8_t mac[6];
  if (macForIp(ip, mac) && isKnownMac(mac)) {
    acceptedIp[acceptedIpNext] = ip; acceptedIpNext = (acceptedIpNext + 1) % 8;
    return true;
  }
  return false;
}
static void accept(uint32_t ip) {
  bool ipKnown = false;
  for (uint32_t a : acceptedIp) if (a == ip) ipKnown = true;
  if (!ipKnown) { acceptedIp[acceptedIpNext] = ip; acceptedIpNext = (acceptedIpNext + 1) % 8; }
  uint8_t mac[6];
  if (!macForIp(ip, mac) || isKnownMac(mac)) return;
  memcpy(knownMac[knownNext], mac, 6);
  knownNext = (knownNext + 1) % KNOWN_MAX;
  if (knownCount < KNOWN_MAX) ++knownCount;
  Preferences p; p.begin("pixmob", false);   // same namespace as the settings: "factory" forgets the phones too
  p.putBytes("pmacs", knownMac, knownCount * 6); p.putUChar("pmnext", knownNext);
  p.end();
}
static void toPortal() {
  server.sendHeader("Location", String("http://") + WiFi.softAPIP().toString() + "/");
  server.sendHeader("Cache-Control", "no-store");
  server.send(302, "text/plain", "");
}
// Shown when a person (not the OS probe) opens the Apple check URL, e.g. via "保持连接并转到 Safari".
// Keeps "Success" in the title and body so the captive sheet still treats the network as online.
static const char CONNECTED_PAGE[] PROGMEM = R"HTML(<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>Success</title>
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover"><meta name="color-scheme" content="dark">
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#0C0C0E;color:#EDEBE7;font:15px/1.6 system-ui,-apple-system,"PingFang SC",sans-serif}
.w{width:100%;max-width:360px;padding:32px 20px;text-align:center;box-sizing:border-box}.ok{width:104px;height:104px;margin:0 auto 10px}
h1{font-size:22px;margin:0 0 6px}.m{color:#8D8A85;font-size:14px;margin:0 0 24px}.c{background:#17171A;border:1px solid #2A2A2F;border-radius:16px;padding:16px 18px;text-align:left}
.c b{display:block;font-size:13px;color:#8D8A85;font-weight:500;margin-bottom:8px}ol{margin:0;padding-left:20px}li{margin:6px 0}code{color:#FF8A4C;font:inherit;font-weight:600}
a{display:block;margin-top:20px;padding:13px;border-radius:12px;background:#EDEBE7;color:#121214;text-decoration:none;font-weight:600}.h{display:none}</style></head>
<body><div class="w"><div class="ok"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 120" width="104" height="104" aria-hidden="true"><defs><mask id="agdm" maskUnits="userSpaceOnUse" x="0" y="0" width="120" height="120"><path d="M13.65 72.48L16.27 78.14L27.86 69.85L26.78 68.22Z" fill="rgb(255,255,255)"/><path d="M15.08 76.11L18.75 81.21L28.89 70.85L27.39 69.26Z" fill="rgb(255,255,255)"/><path d="M17.19 79.42L21.73 83.84L30.26 71.84L28.24 70.25Z" fill="rgb(255,255,255)"/><path d="M19.89 82.32L25.14 86.02L32.02 72.81L29.39 71.25Z" fill="rgb(255,255,255)"/><path d="M23.05 84.77L28.89 87.77L34.19 73.69L30.91 72.24Z" fill="rgb(255,255,255)"/><path d="M26.60 86.77L32.94 89.09L36.75 74.44L32.84 73.17Z" fill="rgb(255,255,255)"/><path d="M30.48 88.35L37.23 90.02L39.67 75.03L35.17 74.01Z" fill="rgb(255,255,255)"/><path d="M34.63 89.51L41.72 90.56L42.91 75.41L37.87 74.70Z" fill="rgb(255,255,255)"/><path d="M39.00 90.28L46.38 90.72L46.42 75.57L40.93 75.21Z" fill="rgb(255,255,255)"/><path d="M43.57 90.67L51.16 90.52L50.15 75.50L44.28 75.50Z" fill="rgb(255,255,255)"/><path d="M48.28 90.69L56.01 89.96L54.04 75.18L47.89 75.57Z" fill="rgb(255,255,255)"/><path d="M53.09 90.34L60.89 89.06L58.05 74.61L51.69 75.40Z" fill="rgb(255,255,255)"/><path d="M57.96 89.64L65.76 87.82L62.11 73.81L55.64 74.98Z" fill="rgb(255,255,255)"/><path d="M62.84 88.60L70.56 86.27L66.18 72.77L59.67 74.32Z" fill="rgb(255,255,255)"/><path d="M67.69 87.24L75.24 84.42L70.19 71.51L63.74 73.42Z" fill="rgb(255,255,255)"/><path d="M72.45 85.57L79.76 82.30L74.10 70.05L67.79 72.29Z" fill="rgb(255,255,255)"/><path d="M77.07 83.61L84.07 79.92L77.85 68.40L71.77 70.95Z" fill="rgb(255,255,255)"/><path d="M81.51 81.38L88.12 77.30L81.40 66.59L75.62 69.41Z" fill="rgb(255,255,255)"/><path d="M85.72 78.90L91.88 74.48L84.70 64.64L79.30 67.69Z" fill="rgb(255,255,255)"/><path d="M89.66 76.20L95.29 71.48L87.72 62.58L82.75 65.82Z" fill="rgb(255,255,255)"/><path d="M93.29 73.30L98.33 68.33L90.41 60.45L85.94 63.83Z" fill="rgb(250,250,250)"/><path d="M96.55 70.24L100.95 65.05L92.74 58.27L88.83 61.73Z" fill="rgb(244,244,244)"/><path d="M99.43 67.03L103.13 61.67L94.70 56.08L91.38 59.58Z" fill="rgb(238,238,238)"/><path d="M101.88 63.70L104.82 58.22L96.27 53.93L93.57 57.39Z" fill="rgb(232,232,232)"/><path d="M103.87 60.29L105.99 54.73L97.45 51.83L95.37 55.22Z" fill="rgb(226,226,226)"/><path d="M105.35 56.82L106.60 51.25L98.25 49.81L96.79 53.08Z" fill="rgb(220,220,220)"/><path d="M106.30 53.34L106.62 47.84L98.68 47.88L97.81 51.01Z" fill="rgb(215,215,215)"/><path d="M106.68 49.88L106.04 44.58L98.76 46.01L98.46 49.03Z" fill="rgb(209,209,209)"/><path d="M106.46 46.52L104.87 41.55L98.48 44.18L98.76 47.12Z" fill="rgb(203,203,203)"/><path d="M105.64 43.34L103.16 38.84L97.79 42.36L98.69 45.27Z" fill="rgb(197,197,197)"/><path d="M104.25 40.43L100.98 36.47L96.67 40.57L98.25 43.45Z" fill="rgb(191,191,191)"/><path d="M102.34 37.85L98.41 34.47L95.07 38.85L97.40 41.64Z" fill="rgb(185,185,185)"/><path d="M100.00 35.63L95.48 32.81L93.00 37.26L96.09 39.87Z" fill="rgb(179,179,179)"/><path d="M97.27 33.77L92.24 31.49L90.48 35.84L94.30 38.20Z" fill="rgb(174,174,174)"/><path d="M94.22 32.24L88.72 30.48L87.54 34.64L92.04 36.67Z" fill="rgb(168,168,168)"/><path d="M90.86 31.05L84.94 29.78L84.23 33.71L89.35 35.33Z" fill="rgb(162,162,162)"/><path d="M87.24 30.16L80.95 29.39L80.60 33.05L86.26 34.24Z" fill="rgb(156,156,156)"/><path d="M83.37 29.59L76.76 29.29L76.70 32.69L82.81 33.41Z" fill="rgb(150,150,150)"/><path d="M79.29 29.31L72.43 29.50L72.59 32.63L79.07 32.87Z" fill="rgb(144,144,144)"/><path d="M75.04 29.34L67.99 30.00L68.33 32.88L75.08 32.63Z" fill="rgb(138,138,138)"/><path d="M70.66 29.67L63.48 30.79L63.96 33.43L70.90 32.69Z" fill="rgb(129,129,129)"/><path d="M66.19 30.28L58.96 31.86L59.56 34.28L66.59 33.06Z" fill="rgb(121,121,121)"/><path d="M61.67 31.18L54.47 33.20L55.16 35.41L62.20 33.73Z" fill="rgb(113,113,113)"/><path d="M57.16 32.36L50.07 34.80L50.82 36.81L57.79 34.69Z" fill="rgb(104,104,104)"/><path d="M52.70 33.81L45.79 36.64L46.60 38.45L53.41 35.93Z" fill="rgb(96,96,96)"/><path d="M48.34 35.51L41.70 38.70L42.55 40.33L49.12 37.44Z" fill="rgb(88,88,88)"/><path d="M44.13 37.44L37.83 40.96L38.71 42.41L44.96 39.18Z" fill="rgb(79,79,79)"/><path d="M40.12 39.58L34.23 43.40L35.12 44.67L40.99 41.14Z" fill="rgb(71,71,71)"/><path d="M36.35 41.92L30.95 46.00L31.84 47.08L37.24 43.30Z" fill="rgb(63,63,63)"/><path d="M32.88 44.42L28.02 48.71L28.88 49.61L33.77 45.62Z" fill="rgb(54,54,54)"/><path d="M29.73 47.07L25.48 51.52L26.29 52.22L30.61 48.08Z" fill="rgb(46,46,46)"/><path d="M26.95 49.83L23.36 54.39L24.09 54.90L27.80 50.64Z" fill="rgb(38,38,38)"/><path d="M24.58 52.67L21.70 57.29L22.29 57.60L25.36 53.29Z" fill="rgb(29,29,29)"/><path d="M22.64 55.55L20.52 60.17L20.92 60.32L23.32 55.98Z" fill="rgb(21,21,21)"/><path d="M21.17 58.44L19.84 62.99L19.98 63.02L21.69 58.69Z" fill="rgb(13,13,13)"/><path d="M20.19 61.31L19.72 64.09L19.72 64.09L20.50 61.40Z" fill="rgb(4,4,4)"/><circle cx="20.22" cy="70.35" r="6.90" fill="#fff"/></mask><radialGradient id="agdg"><stop offset="0" stop-color="#FFE2AA" stop-opacity="0.75"/><stop offset="0.38" stop-color="#FF9655" stop-opacity="0.28"/><stop offset="1" stop-color="#FF7850" stop-opacity="0"/></radialGradient></defs><circle cx="20.22" cy="70.35" r="18.00" fill="url(#agdg)"/><g mask="url(#agdm)"><path d="M13.65 72.48L16.27 78.14L27.86 69.85L26.78 68.22Z" fill="#FFE3B2"/><path d="M15.08 76.11L18.75 81.21L28.89 70.85L27.39 69.26Z" fill="#FFDBA6"/><path d="M17.19 79.42L21.73 83.84L30.26 71.84L28.24 70.25Z" fill="#FFD39A"/><path d="M19.89 82.32L25.14 86.02L32.02 72.81L29.39 71.25Z" fill="#FFCA8E"/><path d="M23.05 84.77L28.89 87.77L34.19 73.69L30.91 72.24Z" fill="#FFC282"/><path d="M26.60 86.77L32.94 89.09L36.75 74.44L32.84 73.17Z" fill="#FFBA76"/><path d="M30.48 88.35L37.23 90.02L39.67 75.03L35.17 74.01Z" fill="#FFB26A"/><path d="M34.63 89.51L41.72 90.56L42.91 75.41L37.87 74.70Z" fill="#FFAD66"/><path d="M39.00 90.28L46.38 90.72L46.42 75.57L40.93 75.21Z" fill="#FFA965"/><path d="M43.57 90.67L51.16 90.52L50.15 75.50L44.28 75.50Z" fill="#FFA463"/><path d="M48.28 90.69L56.01 89.96L54.04 75.18L47.89 75.57Z" fill="#FFA062"/><path d="M53.09 90.34L60.89 89.06L58.05 74.61L51.69 75.40Z" fill="#FF9C60"/><path d="M57.96 89.64L65.76 87.82L62.11 73.81L55.64 74.98Z" fill="#FF985F"/><path d="M62.84 88.60L70.56 86.27L66.18 72.77L59.67 74.32Z" fill="#FF945E"/><path d="M67.69 87.24L75.24 84.42L70.19 71.51L63.74 73.42Z" fill="#FF8F5C"/><path d="M72.45 85.57L79.76 82.30L74.10 70.05L67.79 72.29Z" fill="#FF8B5B"/><path d="M77.07 83.61L84.07 79.92L77.85 68.40L71.77 70.95Z" fill="#FF8759"/><path d="M81.51 81.38L88.12 77.30L81.40 66.59L75.62 69.41Z" fill="#FF8358"/><path d="M85.72 78.90L91.88 74.48L84.70 64.64L79.30 67.69Z" fill="#FF7F57"/><path d="M89.66 76.20L95.29 71.48L87.72 62.58L82.75 65.82Z" fill="#FF7A55"/><path d="M93.29 73.30L98.33 68.33L90.41 60.45L85.94 63.83Z" fill="#FE7857"/><path d="M96.55 70.24L100.95 65.05L92.74 58.27L88.83 61.73Z" fill="#FD7659"/><path d="M99.43 67.03L103.13 61.67L94.70 56.08L91.38 59.58Z" fill="#FC745B"/><path d="M101.88 63.70L104.82 58.22L96.27 53.93L93.57 57.39Z" fill="#FA725D"/><path d="M103.87 60.29L105.99 54.73L97.45 51.83L95.37 55.22Z" fill="#F9705F"/><path d="M105.35 56.82L106.60 51.25L98.25 49.81L96.79 53.08Z" fill="#F86D61"/><path d="M106.30 53.34L106.62 47.84L98.68 47.88L97.81 51.01Z" fill="#F76B63"/><path d="M106.68 49.88L106.04 44.58L98.76 46.01L98.46 49.03Z" fill="#F66965"/><path d="M106.46 46.52L104.87 41.55L98.48 44.18L98.76 47.12Z" fill="#F56767"/><path d="M105.64 43.34L103.16 38.84L97.79 42.36L98.69 45.27Z" fill="#F36569"/><path d="M104.25 40.43L100.98 36.47L96.67 40.57L98.25 43.45Z" fill="#F2636B"/><path d="M102.34 37.85L98.41 34.47L95.07 38.85L97.40 41.64Z" fill="#F1606D"/><path d="M100.00 35.63L95.48 32.81L93.00 37.26L96.09 39.87Z" fill="#F05E6F"/><path d="M97.27 33.77L92.24 31.49L90.48 35.84L94.30 38.20Z" fill="#EF5C71"/><path d="M94.22 32.24L88.72 30.48L87.54 34.64L92.04 36.67Z" fill="#EE5A73"/><path d="M90.86 31.05L84.94 29.78L84.23 33.71L89.35 35.33Z" fill="#EC5875"/><path d="M87.24 30.16L80.95 29.39L80.60 33.05L86.26 34.24Z" fill="#EB5677"/><path d="M83.37 29.59L76.76 29.29L76.70 32.69L82.81 33.41Z" fill="#EA5479"/><path d="M79.29 29.31L72.43 29.50L72.59 32.63L79.07 32.87Z" fill="#E9527B"/><path d="M75.04 29.34L67.99 30.00L68.33 32.88L75.08 32.63Z" fill="#E7507C"/><path d="M70.66 29.67L63.48 30.79L63.96 33.43L70.90 32.69Z" fill="#E54F7C"/><path d="M66.19 30.28L58.96 31.86L59.56 34.28L66.59 33.06Z" fill="#E34E7C"/><path d="M61.67 31.18L54.47 33.20L55.16 35.41L62.20 33.73Z" fill="#E14D7C"/><path d="M57.16 32.36L50.07 34.80L50.82 36.81L57.79 34.69Z" fill="#DE4D7D"/><path d="M52.70 33.81L45.79 36.64L46.60 38.45L53.41 35.93Z" fill="#DC4C7D"/><path d="M48.34 35.51L41.70 38.70L42.55 40.33L49.12 37.44Z" fill="#DA4B7D"/><path d="M44.13 37.44L37.83 40.96L38.71 42.41L44.96 39.18Z" fill="#D74A7D"/><path d="M40.12 39.58L34.23 43.40L35.12 44.67L40.99 41.14Z" fill="#D54A7D"/><path d="M36.35 41.92L30.95 46.00L31.84 47.08L37.24 43.30Z" fill="#D3497D"/><path d="M32.88 44.42L28.02 48.71L28.88 49.61L33.77 45.62Z" fill="#D1487D"/><path d="M29.73 47.07L25.48 51.52L26.29 52.22L30.61 48.08Z" fill="#CE477D"/><path d="M26.95 49.83L23.36 54.39L24.09 54.90L27.80 50.64Z" fill="#CC467D"/><path d="M24.58 52.67L21.70 57.29L22.29 57.60L25.36 53.29Z" fill="#CA467E"/><path d="M22.64 55.55L20.52 60.17L20.92 60.32L23.32 55.98Z" fill="#C8457E"/><path d="M21.17 58.44L19.84 62.99L19.98 63.02L21.69 58.69Z" fill="#C5447E"/><path d="M20.19 61.31L19.72 64.09L19.72 64.09L20.50 61.40Z" fill="#C3437E"/><circle cx="20.22" cy="70.35" r="6.90" fill="#FFE7B8"/></g><circle cx="20.22" cy="70.35" r="5.38" fill="#FFF6E2"/></svg></div>
<h1>已连接控制器</h1><p class="m">%SSID% · 连接已保持</p>
<div class="c"><b>下一步</b><ol><li>点击右上角“完成”</li><li>打开 Safari，输入 <code>http://afterglow.local</code><br>或 <code>192.168.4.1</code></li></ol></div>
<a href="/">留在此处继续控制</a><span class="h">Success</span></div></body></html>)HTML";

static void appleCheck() {      // captive.apple.com/hotspot-detect.html and friends
  if (!isAccepted(server.client().remoteIP())) { toPortal(); return; }
  // The OS probe (User-Agent "CaptiveNetworkSupport") gets the exact reply Apple expects.
  if (server.header("User-Agent").indexOf("CaptiveNetworkSupport") >= 0 || server.header("User-Agent").length() == 0) {
    server.send(200, "text/html", "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>");
    return;
  }
  String page = FPSTR(CONNECTED_PAGE);
  page.replace("%SSID%", WiFi.softAPSSID());
  server.sendHeader("Cache-Control", "no-store");
  server.send(200, "text/html; charset=utf-8", page);
}
static void androidCheck() {    // connectivitycheck.gstatic.com/generate_204
  if (isAccepted(server.client().remoteIP())) server.send(204, "text/plain", ""); else toPortal();
}
static void windowsCheck() {    // msftconnecttest.com/connecttest.txt, ncsi.txt
  if (isAccepted(server.client().remoteIP())) server.send(200, "text/plain", server.uri().indexOf("ncsi") >= 0 ? "Microsoft NCSI" : "Microsoft Connect Test");
  else toPortal();
}

static void handleApi() {
  accept(server.client().remoteIP());   // the control page is open on this phone
  String c = server.arg("c");
  if (c.length() == 0 || c.length() > 120) { server.send(400, "application/json", "{\"ok\":false,\"err\":\"bad command\"}"); return; }
  char buf[128];
  c.toCharArray(buf, sizeof buf);
  StreamString out;
  runCommand(buf, out);
  if (out.length() == 0) out.print("{\"ok\":true}");   // stream has no reply on serial
  server.sendHeader("Cache-Control", "no-store");
  server.send(200, "application/json", out);
}

static void handleUpdateDone() {
  const bool ok = !Update.hasError() && updateError.length() == 0;
  server.sendHeader("Connection", "close");
  server.send(ok ? 200 : 500, "text/plain; charset=utf-8", ok ? "OK" : (updateError.length() ? updateError : String(Update.errorString())));
  if (ok) rebootPending = true; else radioSuspended = false;
}

static void handleUpload() {
  HTTPUpload &up = server.upload();
  if (up.status == UPLOAD_FILE_START) {
    updateError = ""; markerSeen = false; markerTailLen = 0;
    radioOff(); radioSuspended = true;            // no RF while flash is being written
    Serial.printf("{\"evt\":\"ota\",\"stage\":\"start\",\"file\":\"%s\"}\n", up.filename.c_str());
    if (!Update.begin(UPDATE_SIZE_UNKNOWN)) updateError = String("无法开始更新：") + Update.errorString();
  } else if (up.status == UPLOAD_FILE_WRITE) {
    if (up.totalSize == 0 && up.currentSize && up.buf[0] != 0xE9) { updateError = "这不是固件文件，请选择 firmware.bin"; Update.abort(); }
    if (updateError.length() == 0) scanMarker(up.buf, up.currentSize);
    if (updateError.length() == 0 && Update.write(up.buf, up.currentSize) != up.currentSize) updateError = String("写入失败：") + Update.errorString();
  } else if (up.status == UPLOAD_FILE_END) {
    if (updateError.length() == 0 && !markerSeen) { updateError = "这不是 Afterglow 控制器的固件，已取消更新"; Update.abort(); }
    if (updateError.length() == 0 && !Update.end(true)) updateError = String("校验失败：") + Update.errorString();
    Serial.printf("{\"evt\":\"ota\",\"stage\":\"end\",\"bytes\":%u,\"ok\":%s}\n", unsigned(up.totalSize),
                  updateError.length() ? "false" : "true");
  } else if (up.status == UPLOAD_FILE_ABORTED) {
    Update.abort(); updateError = "上传中断，请重试"; radioSuspended = false;
  }
}

static void addRoutes();

static void startServer() {
  if (running) return;
  const uint64_t mac = ESP.getEfuseMac();
  snprintf(ssid, sizeof ssid, "Afterglow-%02X%02X", uint8_t(mac >> 32), uint8_t(mac >> 40));
  static bool evRegistered = false;
  if (!evRegistered) { evRegistered = true; WiFi.onEvent(onWifiEvent); }
  WiFi.mode(WIFI_AP);
  if (!WiFi.softAP(ssid, cfg.apPass)) {
    Serial.println("{\"evt\":\"wifi\",\"ok\":false}");
    vTaskDelay(pdMS_TO_TICKS(5000));   // retry later, without flooding the log
    return;
  }
  loadKnown();
  static bool routes = false;          // register handlers once: the hotspot can be stopped and restarted
  if (!routes) { routes = true; addRoutes(); }
  dns.setErrorReplyCode(DNSReplyCode::NoError);
  dns.start(53, "*", WiFi.softAPIP());      // every name resolves to the controller
  if (MDNS.begin("afterglow")) MDNS.addService("http", "tcp", 80);   // http://afterglow.local
  server.begin();
  running = true;
  Serial.printf("{\"evt\":\"wifi\",\"ok\":true,\"ssid\":\"%s\",\"ip\":\"%s\"}\n", ssid, WiFi.softAPIP().toString().c_str());
}

static void addRoutes() {
  server.on("/", HTTP_GET, [] {
    server.sendHeader("Content-Encoding", "gzip");
    server.sendHeader("Cache-Control", "no-cache");
    server.send_P(200, "text/html; charset=utf-8", reinterpret_cast<PGM_P>(WEB_PAGE_GZ), WEB_PAGE_GZ_LEN);
  });
  for (const char *u : {"/apple-touch-icon.png", "/apple-touch-icon-precomposed.png"}) server.on(u, HTTP_GET, [] {
    server.sendHeader("Cache-Control", "max-age=86400");
    server.send_P(200, "image/png", reinterpret_cast<PGM_P>(APPLE_ICON), APPLE_ICON_LEN);
  });
  server.on("/api", HTTP_GET, handleApi);
  server.on("/update", HTTP_POST, handleUpdateDone, handleUpload);
  for (const char *u : {"/hotspot-detect.html", "/library/test/success.html", "/success.txt"}) server.on(u, HTTP_GET, appleCheck);
  for (const char *u : {"/generate_204", "/gen_204"}) server.on(u, HTTP_GET, androidCheck);
  for (const char *u : {"/connecttest.txt", "/ncsi.txt", "/redirect"}) server.on(u, HTTP_GET, windowsCheck);
  server.onNotFound(toPortal);
  const char *hdrs[] = {"User-Agent"};
  server.collectHeaders(hdrs, 1);
}

static void stopServer() {
  if (!running) return;
  server.stop();
  dns.stop();
  MDNS.end();
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_OFF);
  running = false;
}

static void webTaskMain(void *) {
  for (;;) {
    if (wantRun && !running) startServer();
    if (!wantRun && running) stopServer();
    if (running) { dns.processNextRequest(); server.handleClient(); checkApMode(); }
    vTaskDelay(pdMS_TO_TICKS(2));
  }
}

void webBegin() {
  if (!cfg.wifi) return;
  wantRun = true;
  if (!webTask) xTaskCreatePinnedToCore(webTaskMain, "web", 12288, nullptr, 1, &webTask, 0);
  for (int i = 0; i < 100 && !running; ++i) delay(20);   // up to 2 s, so callers can report the state
}

void webStop() {
  wantRun = false;
  for (int i = 0; i < 100 && running; ++i) delay(20);
}

void webLoop() {}   // kept for compatibility: the web task does the work
bool webRunning() { return running; }
const char *webSsid() { return ssid; }
int webClients() { return running ? WiFi.softAPgetStationNum() : 0; }

void webPrintApJson(Print &o) {
  uint8_t ch = 0; wifi_second_chan_t ch2;
  if (running) esp_wifi_get_channel(&ch, &ch2);
  int8_t pwr = 0;
  if (running) esp_wifi_get_max_tx_power(&pwr);
  o.printf("\"ap\":{\"up\":%s,\"mode_ok\":%s,\"ch\":%u,\"tx_qdbm\":%d,\"starts\":%u,\"stops\":%u,\"joins\":%u,\"leaves\":%u,\"mode_lost\":%u},",
           running ? "true" : "false", apModeOk ? "true" : "false", unsigned(ch), int(pwr),
           unsigned(apStarts), unsigned(apStops), unsigned(apJoins), unsigned(apLeaves), unsigned(apModeLost));
}
