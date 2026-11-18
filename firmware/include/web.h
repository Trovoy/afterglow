#pragma once
#include <Arduino.h>

// Wi-Fi hotspot "Afterglow-XXXX" with a phone control page at http://192.168.4.1/ and firmware upload at /update.
void webBegin();          // starts the hotspot if cfg.wifi == 1
void webStop();
void webLoop();           // call from loop()
bool webRunning();
const char *webSsid();
int webClients();
void webPrintApJson(Print &o);   // "ap":{...} hotspot diagnostics for the status reply
