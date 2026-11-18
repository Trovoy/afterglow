#pragma once
#include <array>
#include <cstdint>

// On-air orientation from weeknds/pixmob-wave2-flipper-zero (MIT).
// Protocol research: sueppchen/PixMob_waveband and Serge-45.
namespace band {
using Body = std::array<uint8_t, 7>;
using Frame = std::array<uint8_t, 9>;
using Bits = std::array<uint8_t, 90>;
constexpr uint8_t code[64] = {
  0x84,0xac,0x34,0x2c,0x66,0x64,0x35,0x24,0x62,0x6a,0x22,0x2a,0x26,0xb6,0x32,0x36,
  0x49,0x4d,0x65,0x45,0x2d,0x29,0x61,0x69,0x42,0x46,0x54,0x56,0x6d,0x6c,0x44,0x4c,
  0x8c,0x8d,0xa9,0xad,0x89,0x99,0xa1,0x91,0xa5,0x25,0x31,0x21,0x85,0x95,0xb1,0xb5,
  0x59,0x51,0x5a,0x52,0x92,0x9a,0x4a,0x8a,0xa4,0xb4,0x96,0x94,0xb2,0xa2,0x86,0xa6
};
inline Frame encode(const Body &body) {
  Frame frame{};
  uint16_t crc = 0xc69;
  for (unsigned n=0; n<7; ++n) {
    frame[n+1] = code[body[n] & 63];
    for (int bit=7; bit>=0; --bit) {
      crc ^= (frame[n+1] >> bit) & 1;
      crc = (crc & 1) ? (crc >> 1) ^ 0x8f3 : crc >> 1;
    }
  }
  frame[0]=code[crc & 63]; frame[8]=code[(crc >> 6) & 63];
  return frame;
}
inline Bits bits(const Body &body) {
  Bits out{};
  for (unsigned i=0; i<16; ++i) out[i]=(i%2==0);
  out[16]=0; out[17]=1;
  const auto frame=encode(body);
  unsigned i=18;
  for (auto b: frame) for (int bit=7; bit>=0; --bit) out[i++]=(b >> bit)&1;
  return out;
}
// Ordinary live color only. Mode 0x11 survives power cycles; do not use it
// for refresh, music, OFF, or watchdog frames.
inline Body color(uint8_t r, uint8_t g, uint8_t b) {
  return Body{{0,
    static_cast<uint8_t>(g >> 2), static_cast<uint8_t>(r >> 2),
    static_cast<uint8_t>(b >> 2), 0, 7, 0}};
}
// Live colour with the band's own envelope (sueppchen wiki "mode"): byte4 = attack<<3 | tRandom,
// byte5 = release<<3 | hold, each 0..7. attack/release 0,30,100,200,500,1000,2000,4000 ms;
// tRandom 0,10,20,35,50,65,80,95 %; hold 0,30,100,200,500,1000,2500 ms, 7 = infinite.
// Only mode 0x00 (live) and 0x10 (one shot) are allowed here; never 0x11 (saved) or 0x0F (EEPROM write).
inline Body colorFx(uint8_t r, uint8_t g, uint8_t b, uint8_t attack, uint8_t rnd,
                    uint8_t release, uint8_t hold, bool oneShot) {
  return Body{{static_cast<uint8_t>(oneShot ? 0x10 : 0x00),
    static_cast<uint8_t>(g >> 2), static_cast<uint8_t>(r >> 2), static_cast<uint8_t>(b >> 2),
    static_cast<uint8_t>(((attack & 7) << 3) | (rnd & 7)),
    static_cast<uint8_t>(((release & 7) << 3) | (hold & 7)), 0}};
}
inline Body wake() { return Body{{0,0,0,0,8,15,0}}; }
inline bool selfTest() {
  // Independent published wake vector validates encoding; these ordinary
  // color checks prevent reintroducing a power-cycle-persistent command.
  if (encode(wake()) != Frame{{0x56,0x84,0x84,0x84,0x84,0x62,0x36,0x84,0x29}}) return false;
  const Body red=color(128,0,0), off=color(0,0,0);
  if (colorFx(128,0,0,0,0,0,7,false) != red) return false;          // fx with default envelope == plain colour
  if (colorFx(0,0,0,7,7,7,7,true)[0] != 0x10) return false;         // one-shot stays live mode 0x10
  return red==Body{{0,0,32,0,0,7,0}} && off==Body{{0,0,0,0,0,7,0}};
}
}
