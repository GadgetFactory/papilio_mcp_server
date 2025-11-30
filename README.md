# Papilio Arcade MCP Server

An MCP (Model Context Protocol) server and debug firmware that allows AI assistants like GitHub Copilot to directly control the Papilio Arcade FPGA board.

## Components

This library contains:

1. **MCP Server** (Python) - Runs on host PC, translates MCP tool calls to serial commands
2. **PapilioMCP.h** (Arduino) - Header-only library to add MCP debug to any sketch
3. **Example Firmware** - Ready-to-use debug firmware sketches

## Quick Start - Adding MCP Debug to Any Sketch

The easiest way to add MCP debug capability is with the header library:

```cpp
// Add BEFORE setup() - comment out to disable
#define PAPILIO_MCP_ENABLED
#include <PapilioMCP.h>

void setup() {
  Serial.begin(115200);
  // ... your setup code ...
  
  PapilioMCP.begin();  // Initialize MCP (does nothing if disabled)
}

void loop() {
  PapilioMCP.update();  // Process MCP commands (does nothing if disabled)
  
  // ... your loop code ...
}
```

When `PAPILIO_MCP_ENABLED` is NOT defined, `PapilioMCP.begin()` and `PapilioMCP.update()` compile to empty stubs - zero overhead.

## Quick Start - Using the Debug Firmware

### 1. Upload the Debug Firmware

```bash
# From project root
pio run -e mcp_debug_firmware -t upload
```

Or use the Makefile:
```bash
make mcp_debug_firmware-upload
```

### 2. Configure VS Code MCP

The `.vscode/mcp.json` should already be configured. If not, add:

```json
{
  "servers": {
    "papilio": {
      "type": "stdio",
      "command": "python",
      "args": ["libs/papilio_mcp_server/server/papilio_mcp_server.py", "--port", "COM4"]
    }
  }
}
```

### 3. Install Python Dependencies

```bash
pip install pyserial opencv-python
```

## PlatformIO Build Environments

In your `platformio.ini`, you can add MCP debug to any environment via build flags:

```ini
; Normal build - MCP disabled
[env:my_project]
extends = env:papilio_arcade

; Debug build - MCP enabled
[env:my_project_debug]
extends = env:papilio_arcade
build_flags = ${env:papilio_arcade.build_flags}
              -DPAPILIO_MCP_ENABLED
```

## Features

- **RGB LED Control**: Set and read RGB LED colors
- **Wishbone Bus Access**: Read/write to any Wishbone bus address
- **FPGA Status**: Get debug dumps and status information
- **Serial Port Management**: List ports and connect to the board
- **Screenshot Capture**: Capture webcam images of HDMI output
- **Video Mode Control**: Switch between test patterns, text mode, and framebuffer
- **Text Mode**: Write text to 80x26 text display
- **JTAG Bridge**: Enable USB JTAG passthrough for FPGA programming

## Serial Commands (via PapilioMCP.h)

| Command | Description |
|---------|-------------|
| `H` | Help |
| `W AAAA DD` | Write DD to Wishbone address AAAA |
| `R AAAA` | Read from Wishbone address AAAA |
| `M AAAA NN` | Read NN bytes starting at AAAA |
| `D` | Dump debug registers |
| `J [1\|0]` | Enable/disable JTAG bridge |

## Available MCP Tools

### RGB LED Control

| Tool | Description |
|------|-------------|
| `set_rgb_led` | Set the RGB LED color (0-255 per channel) |
| `get_rgb_led` | Read the current RGB LED color values |

### Wishbone Bus Access

| Tool | Description |
|------|-------------|
| `wishbone_read` | Read a byte from a Wishbone bus address |
| `wishbone_write` | Write a byte to a Wishbone bus address |

### Board Management

| Tool | Description |
|------|-------------|
| `list_serial_ports` | List available serial ports |
| `connect_board` | Connect to board on specific port |
| `disconnect_board` | Disconnect from board (free serial port) |
| `get_fpga_status` | Get debug status and register dump |
| `send_raw_command` | Send raw command with streaming output |

### Screenshot Capture

| Tool | Description |
|------|-------------|
| `capture_screenshot` | Capture webcam image of HDMI monitor |
| `list_cameras` | List available camera indices |
| `set_camera` | Select which camera to use |
| `set_screenshot_crop` | Set crop region for screenshots |
| `clear_screenshot_crop` | Clear crop region |

### Video Mode Control

| Tool | Description |
|------|-------------|
| `set_video_mode` | Set video mode (0-4) |
| `get_video_mode` | Get current video mode |

Video modes:
- 0: Color bars
- 1: Grid pattern
- 2: Grayscale gradient
- 3: Text mode (80x26)
- 4: Framebuffer (160x120 RGB332)

### Text Mode

| Tool | Description |
|------|-------------|
| `text_clear` | Clear text screen |
| `text_set_cursor` | Set cursor position |
| `text_set_color` | Set text color (CGA 16-color palette) |
| `text_write` | Write text at cursor |
| `text_write_at` | Write text at specific position with color |

## Wishbone Address Map

| Address Range | Peripheral |
|--------------|------------|
| 0x8010 | Video mode register |
| 0x8020-0x802B | Text mode control |
| 0x8100-0x8103 | RGB LED Controller |
| 0x0000-0x4B00 | Framebuffer (160x120 RGB332) |

## Usage Examples

Once the MCP server is configured, you can ask Copilot:

- "Set the RGB LED to red"
- "Make the LED blue"
- "Read the current LED color"
- "Write 0xFF to address 0x8100"
- "Switch to text mode"
- "Write 'Hello World' at position 10,5"
- "Capture a screenshot"
- "Run raw command H"

## File Structure

```
papilio_mcp_server/
├── library.json           # PlatformIO library manifest
├── README.md              # This file
├── src/
│   └── PapilioMCP.h       # Header-only library for sketches
├── server/
│   └── papilio_mcp_server.py  # Main MCP server
└── examples/
    ├── mcp_debug_simple/      # Minimal debug firmware
    └── mcp_debug_firmware_full/  # Full-featured debug firmware
```
