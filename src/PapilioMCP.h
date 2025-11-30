/*
  PapilioMCP.h - MCP Debug Interface for Papilio Arcade
  ======================================================
  
  Add MCP (Model Context Protocol) debug support to any sketch.
  
  Usage:
  1. Add to your sketch BEFORE setup():
       #define PAPILIO_MCP_ENABLED  // Comment out to disable
       #include <PapilioMCP.h>
  
  2. Call in setup() AFTER Serial.begin():
       PapilioMCP.begin();
  
  3. Call in loop():
       if (PapilioMCP.isPaused()) return;  // Skip sketch code when paused
       // ... your sketch code ...
  
  When enabled, you can use AI assistants (via MCP server) or
  serial commands to read/write FPGA registers, control LED, etc.
  
  Serial Commands (115200 baud):
    H             - Help
    W AAAA DD     - Write DD to Wishbone address AAAA
    R AAAA        - Read from Wishbone address AAAA  
    D             - Dump debug registers
    J [1|0]       - Enable/disable JTAG bridge
    P [1|0]       - Pause/resume sketch (MCP takes full control)
*/

#ifndef PAPILIO_MCP_H
#define PAPILIO_MCP_H

#include <Arduino.h>
#include <SPI.h>

#ifdef PAPILIO_MCP_ENABLED

#include "soc/usb_serial_jtag_reg.h"
#include "soc/gpio_sig_map.h"
#include "esp_rom_gpio.h"
#include "hal/usb_serial_jtag_ll.h"

// Default pin configuration (can override before including)
#ifndef MCP_SPI_CLK
#define MCP_SPI_CLK   12
#endif
#ifndef MCP_SPI_MOSI
#define MCP_SPI_MOSI  11
#endif
#ifndef MCP_SPI_MISO
#define MCP_SPI_MISO  9
#endif
#ifndef MCP_SPI_CS
#define MCP_SPI_CS    10
#endif

// JTAG pins
#ifndef MCP_PIN_TCK
#define MCP_PIN_TCK   6
#endif
#ifndef MCP_PIN_TMS
#define MCP_PIN_TMS   8
#endif
#ifndef MCP_PIN_TDI
#define MCP_PIN_TDI   7
#endif
#ifndef MCP_PIN_TDO
#define MCP_PIN_TDO   5
#endif
#ifndef MCP_PIN_SRST
#define MCP_PIN_SRST  13
#endif

#define MCP_SPI_SPEED 8000000

class PapilioMCPClass {
public:
  void begin(SPIClass* spi = nullptr);
  void update();
  
  // Direct Wishbone access (usable by sketch)
  void wishboneWrite(uint16_t address, uint8_t data);
  uint8_t wishboneRead(uint16_t address);
  
  // JTAG control
  void enableJTAG();
  void disableJTAG();
  bool isJTAGEnabled() { return _jtagEnabled; }
  
  // Pause control - allows MCP to take full control
  void pause();
  void resume();
  bool isPaused() { return _paused; }

private:
  SPIClass* _spi = nullptr;
  bool _ownSpi = false;
  String _cmdBuffer;
  bool _jtagEnabled = false;
  bool _paused = false;
  
  void processCommand(String cmd);
  void sendResponse(const char* response);
};

// Implementation inline to keep as single header
inline void PapilioMCPClass::begin(SPIClass* spi) {
  if (spi) {
    _spi = spi;
    _ownSpi = false;
  } else {
    _spi = new SPIClass(HSPI);
    _spi->begin(MCP_SPI_CLK, MCP_SPI_MISO, MCP_SPI_MOSI, MCP_SPI_CS);
    _ownSpi = true;
  }
  
  pinMode(MCP_SPI_CS, OUTPUT);
  digitalWrite(MCP_SPI_CS, HIGH);
  pinMode(MCP_SPI_MISO, INPUT);
  
  Serial.println("[MCP] Debug interface ready. Type H for help.");
}

inline void PapilioMCPClass::update() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (_cmdBuffer.length() > 0) {
        processCommand(_cmdBuffer);
        _cmdBuffer = "";
      }
    } else if (_cmdBuffer.length() < 256) {
      _cmdBuffer += c;
    }
  }
}

inline void PapilioMCPClass::wishboneWrite(uint16_t address, uint8_t data) {
  if (!_spi) return;
  _spi->beginTransaction(SPISettings(MCP_SPI_SPEED, MSBFIRST, SPI_MODE0));
  digitalWrite(MCP_SPI_CS, LOW);
  _spi->transfer(0x01);
  _spi->transfer((address >> 8) & 0xFF);
  _spi->transfer(address & 0xFF);
  _spi->transfer(data);
  digitalWrite(MCP_SPI_CS, HIGH);
  _spi->endTransaction();
}

inline uint8_t PapilioMCPClass::wishboneRead(uint16_t address) {
  if (!_spi) return 0;
  uint8_t result;
  _spi->beginTransaction(SPISettings(MCP_SPI_SPEED, MSBFIRST, SPI_MODE0));
  digitalWrite(MCP_SPI_CS, LOW);
  _spi->transfer(0x00);
  _spi->transfer((address >> 8) & 0xFF);
  _spi->transfer(address & 0xFF);
  delayMicroseconds(2);
  result = _spi->transfer(0x00);
  digitalWrite(MCP_SPI_CS, HIGH);
  _spi->endTransaction();
  return result;
}

inline void PapilioMCPClass::enableJTAG() {
  pinMode(MCP_PIN_TCK, OUTPUT);
  pinMode(MCP_PIN_TMS, OUTPUT);
  pinMode(MCP_PIN_TDI, OUTPUT);
  pinMode(MCP_PIN_TDO, INPUT);
  pinMode(MCP_PIN_SRST, OUTPUT);
  digitalWrite(MCP_PIN_SRST, HIGH);
  
  WRITE_PERI_REG(USB_SERIAL_JTAG_CONF0_REG,
    READ_PERI_REG(USB_SERIAL_JTAG_CONF0_REG)
    | USB_SERIAL_JTAG_USB_JTAG_BRIDGE_EN);
  
  esp_rom_gpio_connect_out_signal(MCP_PIN_TCK,  USB_JTAG_TCK_IDX, false, false);
  esp_rom_gpio_connect_out_signal(MCP_PIN_TMS,  USB_JTAG_TMS_IDX, false, false);
  esp_rom_gpio_connect_out_signal(MCP_PIN_TDI,  USB_JTAG_TDI_IDX, false, false);
  esp_rom_gpio_connect_out_signal(MCP_PIN_SRST, USB_JTAG_TRST_IDX, false, false);
  esp_rom_gpio_connect_in_signal(MCP_PIN_TDO,   USB_JTAG_TDO_BRIDGE_IDX, false);
  
  _jtagEnabled = true;
  Serial.println("[MCP] JTAG bridge enabled");
}

inline void PapilioMCPClass::disableJTAG() {
  WRITE_PERI_REG(USB_SERIAL_JTAG_CONF0_REG,
    READ_PERI_REG(USB_SERIAL_JTAG_CONF0_REG)
    & ~USB_SERIAL_JTAG_USB_JTAG_BRIDGE_EN);
  
  pinMode(MCP_PIN_TCK,  INPUT);
  pinMode(MCP_PIN_TMS,  INPUT);
  pinMode(MCP_PIN_TDI,  INPUT);
  pinMode(MCP_PIN_TDO,  INPUT);
  pinMode(MCP_PIN_SRST, INPUT);
  
  _jtagEnabled = false;
  Serial.println("[MCP] JTAG bridge disabled");
}

inline void PapilioMCPClass::pause() {
  _paused = true;
  Serial.println("[MCP] Sketch PAUSED - MCP has full control");
}

inline void PapilioMCPClass::resume() {
  _paused = false;
  Serial.println("[MCP] Sketch RESUMED");
}

inline void PapilioMCPClass::sendResponse(const char* response) {
  Serial.println(response);
}

inline void PapilioMCPClass::processCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;
  
  Serial.print("[MCP] ");
  Serial.println(cmd);
  
  char cmdType = cmd.charAt(0);
  
  switch (cmdType) {
    case 'W':
    case 'w': {
      if (cmd.length() >= 9) {
        uint16_t addr = strtol(cmd.substring(2, 6).c_str(), NULL, 16);
        uint8_t data = strtol(cmd.substring(7, 9).c_str(), NULL, 16);
        wishboneWrite(addr, data);
        Serial.printf("OK W %04X=%02X\n", addr, data);
      } else {
        sendResponse("ERR: W AAAA DD");
      }
      break;
    }
    
    case 'R':
    case 'r': {
      if (cmd.length() >= 6) {
        uint16_t addr = strtol(cmd.substring(2, 6).c_str(), NULL, 16);
        uint8_t data = wishboneRead(addr);
        Serial.printf("OK R %04X=%02X\n", addr, data);
      } else {
        sendResponse("ERR: R AAAA");
      }
      break;
    }
    
    case 'M':
    case 'm': {
      if (cmd.length() >= 9) {
        uint16_t addr = strtol(cmd.substring(2, 6).c_str(), NULL, 16);
        uint8_t count = strtol(cmd.substring(7, 9).c_str(), NULL, 16);
        if (count > 64) count = 64;
        Serial.printf("OK M %04X:", addr);
        for (int i = 0; i < count; i++) {
          Serial.printf(" %02X", wishboneRead(addr + i));
        }
        Serial.println();
      } else {
        sendResponse("ERR: M AAAA NN");
      }
      break;
    }
    
    case 'D':
    case 'd': {
      sendResponse("=== DEBUG DUMP ===");
      Serial.printf("JTAG Bridge: %s\n", _jtagEnabled ? "ENABLED" : "disabled");
      sendResponse("--- RGB LED (0x8100-0x8103) ---");
      for (uint16_t i = 0x8100; i < 0x8104; i++) {
        Serial.printf("  [%04X] = %02X\n", i, wishboneRead(i));
      }
      sendResponse("--- Video Mode ---");
      Serial.printf("  Video mode: %d\n", wishboneRead(0x8010) & 0x07);
      sendResponse("=== END DUMP ===");
      break;
    }
    
    case 'J':
    case 'j': {
      if (cmd.length() >= 3) {
        char action = cmd.charAt(2);
        if (action == '1') enableJTAG();
        else if (action == '0') disableJTAG();
        else Serial.printf("JTAG: %s\n", _jtagEnabled ? "ENABLED" : "disabled");
      } else {
        Serial.printf("JTAG: %s\n", _jtagEnabled ? "ENABLED" : "disabled");
      }
      break;
    }
    
    case 'P':
    case 'p': {
      if (cmd.length() >= 3) {
        char action = cmd.charAt(2);
        if (action == '1') pause();
        else if (action == '0') resume();
        else Serial.printf("Sketch: %s\n", _paused ? "PAUSED" : "running");
      } else {
        // Toggle if no argument
        if (_paused) resume();
        else pause();
      }
      break;
    }
    
    case 'H':
    case 'h':
    case '?': {
      sendResponse("=== PAPILIO MCP DEBUG ===");
      sendResponse("W AAAA DD  - Write DD to addr AAAA");
      sendResponse("R AAAA     - Read from addr AAAA");
      sendResponse("M AAAA NN  - Read NN bytes from AAAA");
      sendResponse("D          - Dump debug registers");
      sendResponse("J [1|0]    - Enable/disable JTAG");
      sendResponse("P [1|0]    - Pause/resume sketch");
      sendResponse("H          - This help");
      Serial.printf("Status: Sketch %s, JTAG %s\n", 
                    _paused ? "PAUSED" : "running",
                    _jtagEnabled ? "ENABLED" : "disabled");
      break;
    }
    
    default:
      sendResponse("ERR: Unknown command (H for help)");
      break;
  }
}

// Global instance
PapilioMCPClass PapilioMCP;

#else // PAPILIO_MCP_ENABLED not defined

// Stub class when MCP is disabled - compiles to nothing
class PapilioMCPClass {
public:
  void begin(SPIClass* spi = nullptr) {}
  void update() {}
  void wishboneWrite(uint16_t address, uint8_t data) {}
  uint8_t wishboneRead(uint16_t address) { return 0; }
  void enableJTAG() {}
  void disableJTAG() {}
  bool isJTAGEnabled() { return false; }
  void pause() {}
  void resume() {}
  bool isPaused() { return false; }  // Never paused when MCP disabled
};

PapilioMCPClass PapilioMCP;

#endif // PAPILIO_MCP_ENABLED

#endif // PAPILIO_MCP_H
