/*
  Papilio Arcade - MCP Debug Firmware
  ====================================
  
  This firmware provides a debug interface for the Papilio Arcade FPGA board.
  It allows AI assistants (via MCP) or manual serial commands to:
  - Read/write Wishbone bus registers on the FPGA
  - Control RGB LED, video modes, text display
  - Program the FPGA via USB JTAG bridge
  
  Usage:
  1. Add this environment to platformio.ini or use the provided one
  2. Build and upload: pio run -e mcp_debug_firmware -t upload
  3. Configure the MCP server in VS Code (.vscode/mcp.json)
  4. Use Copilot to control the FPGA!
  
  Serial Commands (115200 baud):
    H             - Help
    W AAAA DD     - Write DD to Wishbone address AAAA
    R AAAA        - Read from Wishbone address AAAA
    M AAAA NN     - Read NN bytes starting at AAAA
    D             - Dump debug registers
    F CC          - Fill framebuffer with color CC
    P XXXX YYYY CC - Put pixel at (x,y) with color
    S XX YY CC text - Draw text string
    T             - Draw test pattern
    J [1|0]       - Enable/disable JTAG bridge
    G             - GPIO loopback test
  
  Hardware:
  - ESP32-S3 with USB CDC Serial
  - SPI connection to FPGA Wishbone bus
  - USB JTAG bridge for FPGA programming
  
  Based on: https://github.com/emard/esp32s3-jtag
*/

#include <SPI.h>
#include "soc/usb_serial_jtag_reg.h"
#include "soc/gpio_sig_map.h"
#include "esp_rom_gpio.h"
#include "hal/usb_serial_jtag_ll.h"

// ============================================================================
// Pin Configuration - Adjust for your board
// ============================================================================

// SPI pins for Wishbone communication
#define SPI_CLK   12
#define SPI_MOSI  11
#define SPI_MISO  9    // FPGA pin C11
#define SPI_CS    10

// JTAG pins routed to FPGA
#define PIN_TCK   6
#define PIN_TMS   8
#define PIN_TDI   7
#define PIN_TDO   5
#define PIN_SRST  13   // Active low reset to FPGA

// LED for status
#ifndef LED_BUILTIN
#define LED_BUILTIN 48
#endif
#define LED_ON  LOW
#define LED_OFF HIGH

// SPI clock speed - 8MHz works well with the FPGA bridge
#define SPI_SPEED 8000000

// ============================================================================
// Global State
// ============================================================================

SPIClass* fpgaSPI = nullptr;
String mcpBuffer = "";
bool usb_was_connected = false;
bool jtag_enabled = false;

// ============================================================================
// USB JTAG Bridge Functions
// ============================================================================

void route_usb_jtag_to_gpio() {
  Serial.println("[JTAG] Routing USB JTAG to FPGA pins...");
  
  pinMode(PIN_TCK, OUTPUT);
  pinMode(PIN_TMS, OUTPUT);
  pinMode(PIN_TDI, OUTPUT);
  pinMode(PIN_TDO, INPUT);
  pinMode(PIN_SRST, OUTPUT);
  digitalWrite(PIN_SRST, HIGH);  // Keep FPGA out of reset
  
  // Enable JTAG bridge in USB peripheral
  WRITE_PERI_REG(USB_SERIAL_JTAG_CONF0_REG,
    READ_PERI_REG(USB_SERIAL_JTAG_CONF0_REG)
    | USB_SERIAL_JTAG_USB_JTAG_BRIDGE_EN);
  
  // Route signals through GPIO matrix
  esp_rom_gpio_connect_out_signal(PIN_TCK,  USB_JTAG_TCK_IDX, false, false);
  esp_rom_gpio_connect_out_signal(PIN_TMS,  USB_JTAG_TMS_IDX, false, false);
  esp_rom_gpio_connect_out_signal(PIN_TDI,  USB_JTAG_TDI_IDX, false, false);
  esp_rom_gpio_connect_out_signal(PIN_SRST, USB_JTAG_TRST_IDX, false, false);
  esp_rom_gpio_connect_in_signal(PIN_TDO,   USB_JTAG_TDO_BRIDGE_IDX, false);
  
  jtag_enabled = true;
  digitalWrite(LED_BUILTIN, LED_ON);
  Serial.println("[JTAG] Bridge enabled - FPGA ready for programming");
}

void unroute_usb_jtag_to_gpio() {
  Serial.println("[JTAG] Disabling USB JTAG bridge...");
  
  // Disable JTAG bridge
  WRITE_PERI_REG(USB_SERIAL_JTAG_CONF0_REG,
    READ_PERI_REG(USB_SERIAL_JTAG_CONF0_REG)
    & ~USB_SERIAL_JTAG_USB_JTAG_BRIDGE_EN);
  
  // Release pins
  pinMode(PIN_TCK,  INPUT);
  pinMode(PIN_TMS,  INPUT);
  pinMode(PIN_TDI,  INPUT);
  pinMode(PIN_TDO,  INPUT);
  pinMode(PIN_SRST, INPUT);
  
  jtag_enabled = false;
  digitalWrite(LED_BUILTIN, LED_OFF);
  Serial.println("[JTAG] Bridge disabled");
}

// ============================================================================
// Simple 5x7 Font (ASCII 32-90)
// ============================================================================
const uint8_t font5x7[][5] PROGMEM = {
  {0x00, 0x00, 0x00, 0x00, 0x00}, // space
  {0x00, 0x00, 0x5F, 0x00, 0x00}, // !
  {0x00, 0x07, 0x00, 0x07, 0x00}, // "
  {0x14, 0x7F, 0x14, 0x7F, 0x14}, // #
  {0x24, 0x2A, 0x7F, 0x2A, 0x12}, // $
  {0x23, 0x13, 0x08, 0x64, 0x62}, // %
  {0x36, 0x49, 0x55, 0x22, 0x50}, // &
  {0x00, 0x05, 0x03, 0x00, 0x00}, // '
  {0x00, 0x1C, 0x22, 0x41, 0x00}, // (
  {0x00, 0x41, 0x22, 0x1C, 0x00}, // )
  {0x08, 0x2A, 0x1C, 0x2A, 0x08}, // *
  {0x08, 0x08, 0x3E, 0x08, 0x08}, // +
  {0x00, 0x50, 0x30, 0x00, 0x00}, // ,
  {0x08, 0x08, 0x08, 0x08, 0x08}, // -
  {0x00, 0x60, 0x60, 0x00, 0x00}, // .
  {0x20, 0x10, 0x08, 0x04, 0x02}, // /
  {0x3E, 0x51, 0x49, 0x45, 0x3E}, // 0
  {0x00, 0x42, 0x7F, 0x40, 0x00}, // 1
  {0x42, 0x61, 0x51, 0x49, 0x46}, // 2
  {0x21, 0x41, 0x45, 0x4B, 0x31}, // 3
  {0x18, 0x14, 0x12, 0x7F, 0x10}, // 4
  {0x27, 0x45, 0x45, 0x45, 0x39}, // 5
  {0x3C, 0x4A, 0x49, 0x49, 0x30}, // 6
  {0x01, 0x71, 0x09, 0x05, 0x03}, // 7
  {0x36, 0x49, 0x49, 0x49, 0x36}, // 8
  {0x06, 0x49, 0x49, 0x29, 0x1E}, // 9
  {0x00, 0x36, 0x36, 0x00, 0x00}, // :
  {0x00, 0x56, 0x36, 0x00, 0x00}, // ;
  {0x00, 0x08, 0x14, 0x22, 0x41}, // <
  {0x14, 0x14, 0x14, 0x14, 0x14}, // =
  {0x41, 0x22, 0x14, 0x08, 0x00}, // >
  {0x02, 0x01, 0x51, 0x09, 0x06}, // ?
  {0x32, 0x49, 0x79, 0x41, 0x3E}, // @
  {0x7E, 0x11, 0x11, 0x11, 0x7E}, // A
  {0x7F, 0x49, 0x49, 0x49, 0x36}, // B
  {0x3E, 0x41, 0x41, 0x41, 0x22}, // C
  {0x7F, 0x41, 0x41, 0x22, 0x1C}, // D
  {0x7F, 0x49, 0x49, 0x49, 0x41}, // E
  {0x7F, 0x09, 0x09, 0x01, 0x01}, // F
  {0x3E, 0x41, 0x41, 0x51, 0x32}, // G
  {0x7F, 0x08, 0x08, 0x08, 0x7F}, // H
  {0x00, 0x41, 0x7F, 0x41, 0x00}, // I
  {0x20, 0x40, 0x41, 0x3F, 0x01}, // J
  {0x7F, 0x08, 0x14, 0x22, 0x41}, // K
  {0x7F, 0x40, 0x40, 0x40, 0x40}, // L
  {0x7F, 0x02, 0x04, 0x02, 0x7F}, // M
  {0x7F, 0x04, 0x08, 0x10, 0x7F}, // N
  {0x3E, 0x41, 0x41, 0x41, 0x3E}, // O
  {0x7F, 0x09, 0x09, 0x09, 0x06}, // P
  {0x3E, 0x41, 0x51, 0x21, 0x5E}, // Q
  {0x7F, 0x09, 0x19, 0x29, 0x46}, // R
  {0x46, 0x49, 0x49, 0x49, 0x31}, // S
  {0x01, 0x01, 0x7F, 0x01, 0x01}, // T
  {0x3F, 0x40, 0x40, 0x40, 0x3F}, // U
  {0x1F, 0x20, 0x40, 0x20, 0x1F}, // V
  {0x7F, 0x20, 0x18, 0x20, 0x7F}, // W
  {0x63, 0x14, 0x08, 0x14, 0x63}, // X
  {0x03, 0x04, 0x78, 0x04, 0x03}, // Y
  {0x61, 0x51, 0x49, 0x45, 0x43}, // Z
};

void drawChar(int16_t x, int16_t y, char c, uint8_t color) {
  if (c < 32 || c > 90) c = 32;  // Default to space for unsupported chars
  int idx = c - 32;
  
  fpgaSPI->beginTransaction(SPISettings(SPI_SPEED, MSBFIRST, SPI_MODE0));
  for (int col = 0; col < 5; col++) {
    uint8_t line = pgm_read_byte(&font5x7[idx][col]);
    for (int row = 0; row < 7; row++) {
      if (line & (1 << row)) {
        int16_t px = x + col;
        int16_t py = y + row;
        if (px >= 0 && px < 160 && py >= 0 && py < 120) {
          uint16_t addr = ((py * 160 + px) << 2) & 0x7FFF;
          digitalWrite(SPI_CS, LOW);
          fpgaSPI->transfer(0x01);
          fpgaSPI->transfer((addr >> 8) & 0xFF);
          fpgaSPI->transfer(addr & 0xFF);
          fpgaSPI->transfer(color);
          digitalWrite(SPI_CS, HIGH);
        }
      }
    }
  }
  fpgaSPI->endTransaction();
}

void drawString(int16_t x, int16_t y, const char* str, uint8_t color) {
  while (*str) {
    drawChar(x, y, *str, color);
    x += 6;  // 5 pixels + 1 space
    str++;
  }
}

// ============================================================================
// Wishbone SPI Functions
// ============================================================================

void wishboneWrite(uint16_t address, uint8_t data) {
  fpgaSPI->beginTransaction(SPISettings(SPI_SPEED, MSBFIRST, SPI_MODE0));
  digitalWrite(SPI_CS, LOW);
  fpgaSPI->transfer(0x01);                    // CMD_WRITE
  fpgaSPI->transfer((address >> 8) & 0xFF);   // Address high byte
  fpgaSPI->transfer(address & 0xFF);          // Address low byte
  fpgaSPI->transfer(data);                    // Data
  digitalWrite(SPI_CS, HIGH);
  fpgaSPI->endTransaction();
}

uint8_t wishboneRead(uint16_t address) {
  uint8_t result = 0;
  fpgaSPI->beginTransaction(SPISettings(SPI_SPEED, MSBFIRST, SPI_MODE0));
  digitalWrite(SPI_CS, LOW);
  fpgaSPI->transfer(0x00);                    // CMD_READ
  fpgaSPI->transfer((address >> 8) & 0xFF);   // Address high byte
  fpgaSPI->transfer(address & 0xFF);          // Address low byte
  delayMicroseconds(2);                       // Wait for Wishbone read
  result = fpgaSPI->transfer(0x00);           // Read result
  digitalWrite(SPI_CS, HIGH);
  fpgaSPI->endTransaction();
  return result;
}

// ============================================================================
// MCP Command Processing
// ============================================================================

void mcpSendResponse(const char* response) {
  Serial.println(response);
}

void mcpProcessCommand(String cmd) {
  cmd.trim();
  if (cmd.length() == 0) return;
  
  Serial.print("[MCP] ");
  Serial.println(cmd);
  
  char cmdType = cmd.charAt(0);
  
  switch (cmdType) {
    case 'W':
    case 'w': {
      // Write command: W AAAA DD
      if (cmd.length() >= 9) {
        uint16_t addr = strtol(cmd.substring(2, 6).c_str(), NULL, 16);
        uint8_t data = strtol(cmd.substring(7, 9).c_str(), NULL, 16);
        wishboneWrite(addr, data);
        char response[64];
        snprintf(response, sizeof(response), "OK W %04X=%02X", addr, data);
        mcpSendResponse(response);
      } else {
        mcpSendResponse("ERR: W AAAA DD");
      }
      break;
    }
    
    case 'R':
    case 'r': {
      // Read command: R AAAA
      if (cmd.length() >= 6) {
        uint16_t addr = strtol(cmd.substring(2, 6).c_str(), NULL, 16);
        uint8_t data = wishboneRead(addr);
        char response[64];
        snprintf(response, sizeof(response), "OK R %04X=%02X", addr, data);
        mcpSendResponse(response);
      } else {
        mcpSendResponse("ERR: R AAAA");
      }
      break;
    }
    
    case 'M':
    case 'm': {
      // Multi-read command: M AAAA NN
      if (cmd.length() >= 9) {
        uint16_t addr = strtol(cmd.substring(2, 6).c_str(), NULL, 16);
        uint8_t count = strtol(cmd.substring(7, 9).c_str(), NULL, 16);
        if (count > 64) count = 64;
        
        Serial.printf("OK M %04X:", addr);
        for (int i = 0; i < count; i++) {
          uint8_t data = wishboneRead(addr + i);
          Serial.printf(" %02X", data);
        }
        Serial.println();
      } else {
        mcpSendResponse("ERR: M AAAA NN");
      }
      break;
    }
    
    case 'D':
    case 'd': {
      // Dump debug registers
      mcpSendResponse("=== DEBUG DUMP ===");
      Serial.printf("JTAG Bridge: %s\n", jtag_enabled ? "ENABLED" : "disabled");
      Serial.printf("USB Connected: %s\n", usb_serial_jtag_ll_txfifo_writable() ? "YES" : "NO");
      mcpSendResponse("--- RGB LED (0x8100-0x8103) ---");
      for (uint16_t i = 0x8100; i < 0x8104; i++) {
        uint8_t data = wishboneRead(i);
        Serial.printf("  [%04X] = %02X\n", i, data);
      }
      mcpSendResponse("--- Video Mode ---");
      uint8_t mode = wishboneRead(0x8000);
      Serial.printf("  Video mode: %d\n", mode & 0x07);
      mcpSendResponse("=== END DUMP ===");
      break;
    }
    
    case 'F':
    case 'f': {
      // Fill framebuffer: F CC
      if (cmd.length() >= 4) {
        uint8_t color = strtol(cmd.substring(2, 4).c_str(), NULL, 16);
        Serial.printf("Filling framebuffer with 0x%02X...\n", color);
        
        unsigned long startTime = millis();
        fpgaSPI->beginTransaction(SPISettings(SPI_SPEED, MSBFIRST, SPI_MODE0));
        for (uint16_t pixel = 0; pixel < 19200; pixel++) {
          uint16_t addr = (pixel << 2) & 0x7FFF;
          digitalWrite(SPI_CS, LOW);
          fpgaSPI->transfer(0x01);
          fpgaSPI->transfer((addr >> 8) & 0xFF);
          fpgaSPI->transfer(addr & 0xFF);
          fpgaSPI->transfer(color);
          digitalWrite(SPI_CS, HIGH);
        }
        fpgaSPI->endTransaction();
        unsigned long elapsed = millis() - startTime;
        
        Serial.printf("OK FILL DONE in %lu ms\n", elapsed);
      } else {
        mcpSendResponse("ERR: F CC");
      }
      break;
    }
    
    case 'P':
    case 'p': {
      // Put pixel: P XXXX YYYY CC
      if (cmd.length() >= 14) {
        uint16_t x = strtol(cmd.substring(2, 6).c_str(), NULL, 16);
        uint16_t y = strtol(cmd.substring(7, 11).c_str(), NULL, 16);
        uint8_t color = strtol(cmd.substring(12, 14).c_str(), NULL, 16);
        if (x < 160 && y < 120) {
          uint16_t pixel = y * 160 + x;
          uint16_t addr = (pixel << 2) & 0x7FFF;
          wishboneWrite(addr, color);
          char response[64];
          snprintf(response, sizeof(response), "OK P %d,%d=%02X", x, y, color);
          mcpSendResponse(response);
        } else {
          mcpSendResponse("ERR: X<160 Y<120");
        }
      } else {
        mcpSendResponse("ERR: P XXXX YYYY CC");
      }
      break;
    }
    
    case 'S':
    case 's': {
      // String drawing: S XX YY CC text...
      if (cmd.length() >= 12) {
        uint16_t x = strtol(cmd.substring(2, 4).c_str(), NULL, 16);
        uint16_t y = strtol(cmd.substring(5, 7).c_str(), NULL, 16);
        uint8_t color = strtol(cmd.substring(8, 10).c_str(), NULL, 16);
        String text = cmd.substring(11);
        text.toUpperCase();
        drawString(x, y, text.c_str(), color);
        char response[64];
        snprintf(response, sizeof(response), "OK S \"%s\" at %d,%d", text.c_str(), x, y);
        mcpSendResponse(response);
      } else {
        mcpSendResponse("ERR: S XX YY CC text");
      }
      break;
    }
    
    case 'T':
    case 't': {
      // Test pattern
      mcpSendResponse("DRAWING TEST PATTERN...");
      for (uint16_t y = 0; y < 120; y++) {
        for (uint16_t x = 0; x < 160; x++) {
          uint8_t color = (x >> 1) & 0xFF;
          uint16_t pixel = y * 160 + x;
          uint16_t addr = (pixel << 2) & 0x7FFF;
          wishboneWrite(addr, color);
        }
        if ((y % 20) == 0) {
          Serial.printf("  Row %d/120\n", y);
        }
      }
      mcpSendResponse("OK TEST DONE");
      break;
    }
    
    case 'J':
    case 'j': {
      // JTAG control: J 1 = enable, J 0 = disable
      if (cmd.length() >= 3) {
        char action = cmd.charAt(2);
        if (action == '1' || action == 'e' || action == 'E') {
          route_usb_jtag_to_gpio();
        } else if (action == '0' || action == 'd' || action == 'D') {
          unroute_usb_jtag_to_gpio();
        } else {
          Serial.printf("JTAG Bridge: %s\n", jtag_enabled ? "ENABLED" : "disabled");
        }
      } else {
        Serial.printf("JTAG Bridge: %s\n", jtag_enabled ? "ENABLED" : "disabled");
      }
      break;
    }
    
    case 'H':
    case 'h':
    case '?': {
      // Help
      mcpSendResponse("=== PAPILIO MCP DEBUG + JTAG ===");
      mcpSendResponse("W AAAA DD     - Write DD to addr AAAA");
      mcpSendResponse("R AAAA        - Read from addr AAAA");
      mcpSendResponse("M AAAA NN     - Read NN bytes from AAAA");
      mcpSendResponse("D             - Dump debug registers");
      mcpSendResponse("F CC          - Fill framebuffer with CC");
      mcpSendResponse("P XXXX YYYY CC - Put pixel");
      mcpSendResponse("S XX YY CC text - Draw text (uppercase)");
      mcpSendResponse("T             - Draw test pattern");
      mcpSendResponse("J [1|0]       - Enable/disable JTAG bridge");
      mcpSendResponse("G             - GPIO debug (loopback test)");
      mcpSendResponse("H             - This help");
      mcpSendResponse("(All values in hex)");
      break;
    }
    
    case 'G':
    case 'g': {
      // GPIO loopback test
      Serial.println("=== GPIO LOOPBACK TEST ===");
      Serial.printf("MOSI=GPIO%d  MISO=GPIO%d\n", SPI_MOSI, SPI_MISO);
      
      pinMode(SPI_MISO, INPUT_PULLDOWN);
      delay(10);
      Serial.printf("MISO with PULLDOWN: %d\n", digitalRead(SPI_MISO));
      pinMode(SPI_MISO, INPUT_PULLUP);
      delay(10);
      Serial.printf("MISO with PULLUP: %d\n", digitalRead(SPI_MISO));
      
      pinMode(SPI_MOSI, OUTPUT);
      pinMode(SPI_MISO, INPUT_PULLDOWN);
      pinMode(SPI_CS, OUTPUT);
      digitalWrite(SPI_CS, LOW);
      
      Serial.println("Toggle MOSI, read MISO:");
      for (int i = 0; i < 6; i++) {
        int mosi_val = i % 2;
        digitalWrite(SPI_MOSI, mosi_val);
        delay(50);
        int miso_val = digitalRead(SPI_MISO);
        Serial.printf("  MOSI=%d -> MISO=%d %s\n", mosi_val, miso_val, 
                      (mosi_val == miso_val) ? "OK" : "FAIL");
      }
      
      digitalWrite(SPI_CS, HIGH);
      fpgaSPI->begin(SPI_CLK, SPI_MISO, SPI_MOSI, SPI_CS);
      Serial.println("=== END TEST ===");
      break;
    }
    
    default:
      mcpSendResponse("ERR: Unknown command (H for help)");
      break;
  }
}

// ============================================================================
// Setup and Loop
// ============================================================================

void setup() {
  // Initialize LED
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, LED_OFF);
  
  // Initialize USB Serial (CDC)
  Serial.begin(115200);
  delay(2000);  // Wait for USB enumeration
  
  Serial.println();
  Serial.println("===========================================");
  Serial.println("Papilio Arcade - MCP Debug Firmware");
  Serial.println("===========================================");
  Serial.println();
  Serial.printf("JTAG: TCK=%d TMS=%d TDI=%d TDO=%d SRST=%d\n", 
                PIN_TCK, PIN_TMS, PIN_TDI, PIN_TDO, PIN_SRST);
  Serial.printf("SPI:  CLK=%d MOSI=%d MISO=%d CS=%d\n",
                SPI_CLK, SPI_MOSI, SPI_MISO, SPI_CS);
  Serial.println();
  
  // Initialize SPI for FPGA Wishbone communication
  pinMode(SPI_CS, OUTPUT);
  digitalWrite(SPI_CS, HIGH);
  pinMode(SPI_MISO, INPUT);
  
  fpgaSPI = new SPIClass(HSPI);
  fpgaSPI->begin(SPI_CLK, SPI_MISO, SPI_MOSI, SPI_CS);
  
  Serial.println("SPI initialized for Wishbone communication");
  Serial.println();
  Serial.println("Ready! Type H for help.");
  Serial.println("Use openFPGALoader to program FPGA via USB JTAG.");
  Serial.println();
}

void loop() {
  // Process MCP commands from USB Serial
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (mcpBuffer.length() > 0) {
        mcpProcessCommand(mcpBuffer);
        mcpBuffer = "";
      }
    } else {
      if (mcpBuffer.length() < 256) {
        mcpBuffer += c;
      }
    }
  }
  
  delay(1);
}
