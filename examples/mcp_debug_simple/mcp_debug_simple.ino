/*
  Papilio Arcade - MCP Debug Firmware
  ====================================
  
  This is the simple version that uses the PapilioMCP header library.
  
  Build with: pio run -e mcp_debug_firmware -t upload
  
  The mcp_debug_firmware environment automatically defines PAPILIO_MCP_ENABLED
  via build_flags in platformio.ini.
  
  For the full-featured version with framebuffer commands and test patterns,
  see: libs/papilio_mcp_server/examples/mcp_debug_firmware_full/
*/

// Note: PAPILIO_MCP_ENABLED is defined via build_flags in platformio.ini
// Do not define it here to avoid redefinition warning
#include <PapilioMCP.h>

void setup() {
  Serial.begin(115200);
  delay(2000);
  
  Serial.println("\n========================================");
  Serial.println("  Papilio Arcade - MCP Debug Firmware");
  Serial.println("========================================\n");
  
  // Initialize MCP debug interface
  PapilioMCP.begin();
  
  Serial.println("Type H for help, or use MCP server for AI control.\n");
}

void loop() {
  PapilioMCP.update();
}
