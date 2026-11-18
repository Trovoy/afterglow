#include "health.h"
#include <Preferences.h>
#include <esp_system.h>
#include <esp_task_wdt.h>

static constexpr uint32_t WDT_TIMEOUT_S = 8;
static const char *resetName = "unknown";
static uint32_t boots = 0;

static const char *nameOf(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON: return "poweron";
    case ESP_RST_EXT: return "external";
    case ESP_RST_SW: return "software";      // reboot command, OTA update, flashing
    case ESP_RST_PANIC: return "panic";      // crash
    case ESP_RST_INT_WDT: return "int_wdt";
    case ESP_RST_TASK_WDT: return "task_wdt"; // a task got stuck
    case ESP_RST_WDT: return "wdt";
    case ESP_RST_DEEPSLEEP: return "deepsleep";
    case ESP_RST_BROWNOUT: return "brownout"; // supply dipped (USB cable / power)
    case ESP_RST_SDIO: return "sdio";
    default: return "unknown";
  }
}

void healthBegin() {
  resetName = nameOf(esp_reset_reason());
  Preferences p;
  p.begin("health", false);
  boots = p.getUInt("boots", 0) + 1;
  p.putUInt("boots", boots);
  p.end();
  // The Arduino core may already have started the task watchdog; then only reconfigure by adding tasks.
  esp_task_wdt_init(WDT_TIMEOUT_S, true);
  healthWatchThisTask();   // the Arduino loop task
}

void healthWatchThisTask() { esp_task_wdt_add(nullptr); }
void healthFeed() { esp_task_wdt_reset(); }
const char *healthResetReason() { return resetName; }
uint32_t healthBoots() { return boots; }

void healthPrintJson(Print &out) {
  out.printf("\"reset\":\"%s\",\"boots\":%u,\"heap\":%u,\"min_heap\":%u",
             resetName, boots, ESP.getFreeHeap(), ESP.getMinFreeHeap());
}
