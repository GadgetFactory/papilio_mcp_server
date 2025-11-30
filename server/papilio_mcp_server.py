#!/usr/bin/env python3
"""
Papilio Arcade MCP Server
=========================
An MCP (Model Context Protocol) server that provides tools to control
the Papilio Arcade FPGA board via serial commands.

Features:
- RGB LED control (set colors, get status)
- Wishbone bus read/write access
- Framebuffer operations
- JTAG bridge control
- Screenshot capture from webcam

Usage:
    python papilio_mcp_server.py [--port COM4] [--baud 115200]
"""

import sys
import json
import asyncio
import serial
import serial.tools.list_ports
from typing import Optional
import argparse
import base64
import os
import time

# Try to import OpenCV for webcam support
try:
    import cv2
    OPENCV_AVAILABLE = True
except ImportError:
    OPENCV_AVAILABLE = False

# MCP Protocol version
MCP_VERSION = "2024-11-05"

class PapilioController:
    """Controls the Papilio Arcade board via serial commands."""
    
    def __init__(self, port: str = None, baud: int = 115200):
        self.port = port
        self.baud = baud
        self.serial: Optional[serial.Serial] = None
        
    def find_port(self) -> Optional[str]:
        """Auto-detect the Papilio board COM port."""
        ports = serial.tools.list_ports.comports()
        for p in ports:
            # Look for ESP32-S3 USB Serial/JTAG
            if "USB" in p.description or "Serial" in p.description:
                return p.device
        return None
    
    def connect(self) -> bool:
        """Connect to the board."""
        if self.serial and self.serial.is_open:
            return True
            
        port = self.port or self.find_port()
        if not port:
            return False
            
        try:
            self.serial = serial.Serial(port, self.baud, timeout=0.5)
            # Clear any pending data
            self.serial.reset_input_buffer()
            return True
        except Exception as e:
            self.serial = None
            return False
    
    def disconnect(self):
        """Disconnect from the board."""
        if self.serial:
            self.serial.close()
            self.serial = None
    
    def send_command(self, cmd: str) -> str:
        """Send a command and read the response."""
        if not self.connect():
            return "ERROR: Not connected to board"
        
        try:
            # Clear input buffer
            self.serial.reset_input_buffer()
            
            # Send command
            self.serial.write(f"{cmd}\n".encode())
            self.serial.flush()
            
            # Read response lines
            response_lines = []
            timeout_count = 0
            while timeout_count < 2:
                line = self.serial.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    response_lines.append(line)
                    timeout_count = 0
                    # Check for end markers
                    if line.startswith("OK") or line.startswith("ERR") or line == "END" or "DONE" in line:
                        break
                else:
                    timeout_count += 1
            
            return "\n".join(response_lines) if response_lines else "No response"
        except Exception as e:
            return f"ERROR: {str(e)}"
    
    def set_rgb_led(self, red: int, green: int, blue: int) -> str:
        """Set the RGB LED color (0-255 for each channel)."""
        # RGB LED is at Wishbone address 0x8100-0x8103
        # Note: WS2812B uses GRB order
        # Address map: 0x8100=Green, 0x8101=Red, 0x8102=Blue, 0x8103=Status
        results = []
        results.append(self.send_command(f"W 8100 {green:02X}"))  # Green
        results.append(self.send_command(f"W 8101 {red:02X}"))    # Red  
        results.append(self.send_command(f"W 8102 {blue:02X}"))   # Blue
        return "\n".join(results)
    
    def get_rgb_led(self) -> dict:
        """Get current RGB LED values."""
        g = self.send_command("R 8100")  # Green
        r = self.send_command("R 8101")  # Red
        b = self.send_command("R 8102")  # Blue
        
        # Parse responses like "OK R 0000=FF"
        def parse_value(resp):
            try:
                if "=" in resp:
                    return int(resp.split("=")[1].strip(), 16)
            except:
                pass
            return 0
        
        return {
            "red": parse_value(r),
            "green": parse_value(g),
            "blue": parse_value(b)
        }
    
    def wishbone_read(self, address: int) -> int:
        """Read from Wishbone bus address."""
        resp = self.send_command(f"R {address:04X}")
        try:
            if "=" in resp:
                return int(resp.split("=")[1].strip(), 16)
        except:
            pass
        return 0
    
    def wishbone_write(self, address: int, data: int) -> str:
        """Write to Wishbone bus address."""
        return self.send_command(f"W {address:04X} {data:02X}")
    
    def get_debug_dump(self) -> str:
        """Get debug register dump."""
        return self.send_command("D")
    
    def get_jtag_status(self) -> str:
        """Get JTAG bridge status."""
        return self.send_command("J")
    
    def set_jtag_enabled(self, enabled: bool) -> str:
        """Enable/disable JTAG bridge."""
        return self.send_command(f"J {'1' if enabled else '0'}")


class WebcamCapture:
    """Captures screenshots from a webcam pointed at the HDMI monitor."""
    
    def __init__(self, screenshots_dir: str = None):
        self.camera_index = 0
        self.crop_region = None  # (x, y, width, height) or None for full frame
        if screenshots_dir:
            self.save_dir = screenshots_dir
        else:
            self.save_dir = os.path.join(os.path.dirname(__file__), "screenshots")
        self.resolution = (1920, 1080)  # Default to 1080p
        self._cap = None  # Persistent camera connection
        self._cap_initialized = False
    
    def _get_camera(self):
        """Get or create persistent camera connection for faster captures."""
        if self._cap is None or not self._cap.isOpened():
            self._cap = cv2.VideoCapture(self.camera_index)
            if self._cap.isOpened():
                # Set resolution
                self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
                self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
                # Disable auto-focus if supported (reduces capture latency)
                self._cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
                # Set buffer size to 1 to get the latest frame
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                self._cap_initialized = False
        return self._cap
    
    def release_camera(self):
        """Release the persistent camera connection."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None
            self._cap_initialized = False
    
    def list_cameras(self) -> list:
        """List available camera indices."""
        if not OPENCV_AVAILABLE:
            return []
        
        available = []
        for i in range(10):  # Check first 10 indices
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    available.append(i)
                cap.release()
        return available
    
    def capture(self, save_to_file: bool = True, filename: str = None,
                format: str = "jpeg", quality: int = 80, warmup_frames: int = 2) -> dict:
        """Capture a frame from the webcam.
        
        Args:
            save_to_file: Whether to save the screenshot to a file
            filename: Optional filename (auto-generated if None)
            format: Image format - "jpeg" (smaller/faster) or "png" (lossless)
            quality: JPEG quality 1-100 (higher = better quality, larger file)
            warmup_frames: Number of warmup frames (0 for fastest, 2-5 for better exposure)
        
        Returns:
            dict with keys:
            - success: bool
            - message: str
            - image_base64: str (image as base64, if successful)
            - filepath: str (if saved to file)
        """
        if not OPENCV_AVAILABLE:
            return {
                "success": False,
                "message": "OpenCV not installed. Run: pip install opencv-python"
            }
        
        cap = self._get_camera()
        if not cap.isOpened():
            return {
                "success": False,
                "message": f"Could not open camera {self.camera_index}"
            }
        
        # Warmup frames - only on first capture after camera opens (for auto-exposure)
        # After that, just grab one frame to flush the buffer
        if not self._cap_initialized:
            for _ in range(max(warmup_frames, 3)):
                cap.grab()  # grab() is faster than read() for discarding frames
            self._cap_initialized = True
        else:
            # Just flush buffer to get latest frame
            cap.grab()
        
        ret, frame = cap.read()
        
        if not ret:
            self._cap_initialized = False
            return {
                "success": False,
                "message": "Failed to capture frame from camera"
            }
        
        # Apply crop if configured
        if self.crop_region:
            x, y, w, h = self.crop_region
            frame = frame[y:y+h, x:x+w]
        
        # Encode based on format
        format = format.lower()
        if format == "jpeg" or format == "jpg":
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, quality]
            _, buffer = cv2.imencode('.jpg', frame, encode_params)
            mime_type = "image/jpeg"
            ext = ".jpg"
        else:
            # PNG with compression (0-9, higher = smaller but slower)
            encode_params = [cv2.IMWRITE_PNG_COMPRESSION, 6]
            _, buffer = cv2.imencode('.png', frame, encode_params)
            mime_type = "image/png"
            ext = ".png"
        
        image_base64 = base64.b64encode(buffer).decode('utf-8')
        
        result = {
            "success": True,
            "message": f"Captured {frame.shape[1]}x{frame.shape[0]} {format.upper()} ({len(buffer)/1024:.1f}KB)",
            "image_base64": image_base64,
            "mime_type": mime_type,
            "width": frame.shape[1],
            "height": frame.shape[0],
            "size_bytes": len(buffer)
        }
        
        # Save to file if requested
        if save_to_file:
            os.makedirs(self.save_dir, exist_ok=True)
            if filename is None:
                filename = f"screenshot_{int(time.time())}{ext}"
            elif not filename.endswith(ext):
                filename = filename.rsplit('.', 1)[0] + ext
            filepath = os.path.join(self.save_dir, filename)
            cv2.imwrite(filepath, frame, encode_params)
            result["filepath"] = filepath
        
        return result
    
    def set_crop_region(self, x: int, y: int, width: int, height: int):
        """Set the crop region for screenshots."""
        self.crop_region = (x, y, width, height)
    
    def clear_crop_region(self):
        """Clear the crop region (capture full frame)."""
        self.crop_region = None
    
    def calibrate_crop(self) -> dict:
        """Interactive calibration - displays a preview window to set crop region.
        
        Note: This requires a display and won't work in headless mode.
        """
        if not OPENCV_AVAILABLE:
            return {"success": False, "message": "OpenCV not installed"}
        
        cap = cv2.VideoCapture(self.camera_index)
        if not cap.isOpened():
            return {"success": False, "message": f"Could not open camera {self.camera_index}"}
        
        # Variables for mouse callback
        crop_start = [None]
        crop_end = [None]
        drawing = [False]
        
        def mouse_callback(event, x, y, flags, param):
            if event == cv2.EVENT_LBUTTONDOWN:
                crop_start[0] = (x, y)
                drawing[0] = True
            elif event == cv2.EVENT_MOUSEMOVE and drawing[0]:
                crop_end[0] = (x, y)
            elif event == cv2.EVENT_LBUTTONUP:
                crop_end[0] = (x, y)
                drawing[0] = False
        
        cv2.namedWindow("Calibrate - Draw rectangle, press 'c' to confirm, 'q' to cancel")
        cv2.setMouseCallback("Calibrate - Draw rectangle, press 'c' to confirm, 'q' to cancel", mouse_callback)
        
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            
            display = frame.copy()
            
            # Draw current selection
            if crop_start[0] and crop_end[0]:
                cv2.rectangle(display, crop_start[0], crop_end[0], (0, 255, 0), 2)
            
            cv2.imshow("Calibrate - Draw rectangle, press 'c' to confirm, 'q' to cancel", display)
            
            key = cv2.waitKey(1) & 0xFF
            if key == ord('c') and crop_start[0] and crop_end[0]:
                # Confirm selection
                x1, y1 = crop_start[0]
                x2, y2 = crop_end[0]
                x, y = min(x1, x2), min(y1, y2)
                w, h = abs(x2 - x1), abs(y2 - y1)
                self.crop_region = (x, y, w, h)
                cap.release()
                cv2.destroyAllWindows()
                return {
                    "success": True,
                    "message": f"Crop region set to x={x}, y={y}, w={w}, h={h}",
                    "crop_region": {"x": x, "y": y, "width": w, "height": h}
                }
            elif key == ord('q'):
                break
        
        cap.release()
        cv2.destroyAllWindows()
        return {"success": False, "message": "Calibration cancelled"}


# Global instances
controller = PapilioController()
webcam = WebcamCapture()


def handle_initialize(request_id, params):
    """Handle initialize request."""
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "protocolVersion": MCP_VERSION,
            "capabilities": {
                "tools": {}
            },
            "serverInfo": {
                "name": "papilio-mcp-server",
                "version": "1.0.0"
            }
        }
    }


def handle_tools_list(request_id):
    """Handle tools/list request."""
    tools = [
        {
            "name": "set_rgb_led",
            "description": "Set the RGB LED color on the Papilio Arcade FPGA board. Each color channel is 0-255.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "red": {
                        "type": "integer",
                        "description": "Red channel value (0-255)",
                        "minimum": 0,
                        "maximum": 255
                    },
                    "green": {
                        "type": "integer",
                        "description": "Green channel value (0-255)",
                        "minimum": 0,
                        "maximum": 255
                    },
                    "blue": {
                        "type": "integer",
                        "description": "Blue channel value (0-255)",
                        "minimum": 0,
                        "maximum": 255
                    }
                },
                "required": ["red", "green", "blue"]
            }
        },
        {
            "name": "get_rgb_led",
            "description": "Get the current RGB LED color values from the Papilio Arcade FPGA board.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "wishbone_read",
            "description": "Read a byte from a Wishbone bus address on the FPGA.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "address": {
                        "type": "integer",
                        "description": "Wishbone address (0x0000-0xFFFF)",
                        "minimum": 0,
                        "maximum": 65535
                    }
                },
                "required": ["address"]
            }
        },
        {
            "name": "wishbone_write",
            "description": "Write a byte to a Wishbone bus address on the FPGA.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "address": {
                        "type": "integer",
                        "description": "Wishbone address (0x0000-0xFFFF)",
                        "minimum": 0,
                        "maximum": 65535
                    },
                    "data": {
                        "type": "integer",
                        "description": "Data byte to write (0-255)",
                        "minimum": 0,
                        "maximum": 255
                    }
                },
                "required": ["address", "data"]
            }
        },
        {
            "name": "get_fpga_status",
            "description": "Get debug status and register dump from the FPGA.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "pause_sketch",
            "description": "Pause or resume the main Arduino sketch loop. When paused, only MCP commands are processed.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "paused": {
                        "type": "boolean",
                        "description": "True to pause the sketch, False to resume"
                    }
                },
                "required": ["paused"]
            }
        },
        {
            "name": "get_pause_status",
            "description": "Get the current pause status of the sketch.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "list_serial_ports",
            "description": "List available serial ports for connecting to the Papilio board.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "connect_board",
            "description": "Connect to the Papilio board on a specific serial port.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "port": {
                        "type": "string",
                        "description": "Serial port name (e.g., COM4, /dev/ttyUSB0)"
                    }
                },
                "required": ["port"]
            }
        },
        {
            "name": "disconnect_board",
            "description": "Disconnect from the Papilio board to free the serial port. Use this before flashing the FPGA.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "send_raw_command",
            "description": "Send a raw command to the board and return all serial output. Useful for debug commands.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The raw command to send (e.g., 'G' for GPIO debug, 'H' for help)"
                    },
                    "timeout": {
                        "type": "number",
                        "description": "Timeout in seconds to wait for response (default 5)",
                        "default": 5
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "Maximum number of response lines (truncate beyond).",
                        "default": 200
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "Maximum total characters (truncate with ellipsis).",
                        "default": 16000
                    },
                    "stop_on_marker": {
                        "type": "boolean",
                        "description": "Stop when OK/ERR/DONE/END encountered (reduces wait).",
                        "default": True
                    }
                },
                "required": ["command"]
            }
        },
        {
            "name": "capture_screenshot",
            "description": "Capture a screenshot from the webcam pointed at the HDMI monitor. Returns the image as base64 and optionally saves to file. Uses JPEG by default for faster capture and smaller files.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "save_to_file": {
                        "type": "boolean",
                        "description": "Whether to save the screenshot to a file (default true)",
                        "default": True
                    },
                    "filename": {
                        "type": "string",
                        "description": "Optional filename for the screenshot (default: screenshot_<timestamp>.jpg)"
                    },
                    "format": {
                        "type": "string",
                        "description": "Image format: 'jpeg' (smaller/faster, default) or 'png' (lossless)",
                        "enum": ["jpeg", "png"],
                        "default": "jpeg"
                    },
                    "quality": {
                        "type": "integer",
                        "description": "JPEG quality 1-100 (higher = better quality, larger file). Default 80.",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 80
                    },
                    "warmup_frames": {
                        "type": "integer",
                        "description": "Number of warmup frames for camera exposure. 0 for fastest capture, 2-5 for better exposure. Default 2.",
                        "minimum": 0,
                        "maximum": 10,
                        "default": 2
                    },
                    "inline_image": {
                        "type": "boolean",
                        "description": "Include base64 image in response.",
                        "default": True
                    },
                    "scale_percent": {
                        "type": "integer",
                        "description": "Downscale percentage (50=half size).",
                        "default": 100,
                        "minimum": 5,
                        "maximum": 100
                    },
                    "max_inline_bytes": {
                        "type": "integer",
                        "description": "Max base64 length before omitting image.",
                        "default": 300000
                    }
                }
            }
        },
        {
            "name": "list_cameras",
            "description": "List available webcam/camera indices for screenshot capture.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "set_camera",
            "description": "Set which camera index to use for screenshots.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "camera_index": {
                        "type": "integer",
                        "description": "Camera index (0 is usually the default camera)",
                        "minimum": 0
                    }
                },
                "required": ["camera_index"]
            }
        },
        {
            "name": "set_screenshot_crop",
            "description": "Set a crop region for screenshots to capture only the monitor area.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": "X coordinate of top-left corner",
                        "minimum": 0
                    },
                    "y": {
                        "type": "integer",
                        "description": "Y coordinate of top-left corner",
                        "minimum": 0
                    },
                    "width": {
                        "type": "integer",
                        "description": "Width of crop region",
                        "minimum": 1
                    },
                    "height": {
                        "type": "integer",
                        "description": "Height of crop region",
                        "minimum": 1
                    }
                },
                "required": ["x", "y", "width", "height"]
            }
        },
        {
            "name": "clear_screenshot_crop",
            "description": "Clear the screenshot crop region to capture the full camera frame.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "set_video_mode",
            "description": "Set the FPGA video output mode. Modes: 0=Color bars, 1=Grid, 2=Grayscale, 3=Text mode (80x26), 4=Framebuffer (160x120).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "integer",
                        "description": "Video mode (0-4): 0=Color bars, 1=Grid, 2=Grayscale, 3=Text, 4=Framebuffer",
                        "minimum": 0,
                        "maximum": 4
                    }
                },
                "required": ["mode"]
            }
        },
        {
            "name": "get_video_mode",
            "description": "Get the current FPGA video output mode.",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "text_clear",
            "description": "Clear the text mode screen (fill with spaces).",
            "inputSchema": {
                "type": "object",
                "properties": {}
            }
        },
        {
            "name": "text_set_cursor",
            "description": "Set the text cursor position for text mode.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": "Column position (0-79)",
                        "minimum": 0,
                        "maximum": 79
                    },
                    "y": {
                        "type": "integer",
                        "description": "Row position (0-29)",
                        "minimum": 0,
                        "maximum": 29
                    }
                },
                "required": ["x", "y"]
            }
        },
        {
            "name": "text_set_color",
            "description": "Set the text color attribute for subsequent characters. Uses CGA 16-color palette.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "foreground": {
                        "type": "integer",
                        "description": "Foreground color (0-15): 0=Black, 1=Blue, 2=Green, 3=Cyan, 4=Red, 5=Magenta, 6=Brown, 7=LightGray, 8=DarkGray, 9=LightBlue, 10=LightGreen, 11=LightCyan, 12=LightRed, 13=LightMagenta, 14=Yellow, 15=White",
                        "minimum": 0,
                        "maximum": 15
                    },
                    "background": {
                        "type": "integer",
                        "description": "Background color (0-15)",
                        "minimum": 0,
                        "maximum": 15,
                        "default": 0
                    }
                },
                "required": ["foreground"]
            }
        },
        {
            "name": "text_write",
            "description": "Write text at the current cursor position in text mode. Cursor auto-advances.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "Text to write (ASCII characters)"
                    }
                },
                "required": ["text"]
            }
        },
        {
            "name": "text_write_at",
            "description": "Write text at a specific position in text mode.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": "Column position (0-79)",
                        "minimum": 0,
                        "maximum": 79
                    },
                    "y": {
                        "type": "integer",
                        "description": "Row position (0-29)",
                        "minimum": 0,
                        "maximum": 29
                    },
                    "text": {
                        "type": "string",
                        "description": "Text to write (ASCII characters)"
                    },
                    "foreground": {
                        "type": "integer",
                        "description": "Foreground color (0-15)",
                        "minimum": 0,
                        "maximum": 15,
                        "default": 15
                    },
                    "background": {
                        "type": "integer",
                        "description": "Background color (0-15)",
                        "minimum": 0,
                        "maximum": 15,
                        "default": 0
                    }
                },
                "required": ["x", "y", "text"]
            }
        }
    ]
    
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "tools": tools
        }
    }


def handle_tools_call(request_id, params):
    """Handle tools/call request."""
    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    
    try:
        if tool_name == "set_rgb_led":
            red = arguments.get("red", 0)
            green = arguments.get("green", 0)
            blue = arguments.get("blue", 0)
            result = controller.set_rgb_led(red, green, blue)
            content = f"Set RGB LED to R={red}, G={green}, B={blue}\n{result}"
            
        elif tool_name == "get_rgb_led":
            values = controller.get_rgb_led()
            content = f"RGB LED values: Red={values['red']}, Green={values['green']}, Blue={values['blue']}"
            
        elif tool_name == "wishbone_read":
            address = arguments.get("address", 0)
            value = controller.wishbone_read(address)
            content = f"Read from 0x{address:04X}: 0x{value:02X} ({value})"
            
        elif tool_name == "wishbone_write":
            address = arguments.get("address", 0)
            data = arguments.get("data", 0)
            result = controller.wishbone_write(address, data)
            content = f"Write 0x{data:02X} to 0x{address:04X}: {result}"
            
        elif tool_name == "get_fpga_status":
            result = controller.get_debug_dump()
            content = f"FPGA Status:\n{result}"
            
        elif tool_name == "pause_sketch":
            paused = arguments.get("paused", True)
            if not controller.connect():
                content = "ERROR: Not connected to board"
            else:
                result = controller.send_command(f"P {1 if paused else 0}")
                content = f"Sketch {'paused' if paused else 'resumed'}: {result}"
                
        elif tool_name == "get_pause_status":
            if not controller.connect():
                content = "ERROR: Not connected to board"
            else:
                result = controller.send_command("P")
                content = f"Pause status: {result}"
            
        elif tool_name == "list_serial_ports":
            ports = serial.tools.list_ports.comports()
            port_list = [f"{p.device}: {p.description}" for p in ports]
            content = "Available serial ports:\n" + "\n".join(port_list) if port_list else "No serial ports found"
            
        elif tool_name == "connect_board":
            port = arguments.get("port")
            controller.port = port
            controller.disconnect()
            if controller.connect():
                content = f"Connected to {port}"
            else:
                content = f"Failed to connect to {port}"
                
        elif tool_name == "disconnect_board":
            controller.disconnect()
            content = "Disconnected from board. Serial port is now free."
            
        elif tool_name == "send_raw_command":
            command = arguments.get("command", "")
            timeout = arguments.get("timeout", 5)
            max_lines = arguments.get("max_lines", 200)
            max_chars = arguments.get("max_chars", 16000)
            stop_on_marker = arguments.get("stop_on_marker", True)
            if not controller.connect():
                content = "ERROR: Not connected to board"
            else:
                try:
                    controller.serial.reset_input_buffer()
                    controller.serial.write(f"{command}\n".encode())
                    controller.serial.flush()
                    import time
                    start_time = time.time()
                    response_lines = []
                    termination_markers = ("OK", "ERR", "DONE", "END")
                    while (time.time() - start_time) < timeout:
                        if controller.serial.in_waiting:
                            line = controller.serial.readline().decode('utf-8', errors='ignore').strip()
                            if line:
                                response_lines.append(line)
                                if stop_on_marker and (line.startswith(termination_markers) or any(m in line for m in termination_markers)):
                                    break
                                if len(response_lines) >= max_lines:
                                    response_lines.append("[Truncated: max_lines reached]")
                                    break
                        else:
                            time.sleep(0.1)
                        if sum(len(l) for l in response_lines) > max_chars:
                            response_lines.append("[Truncated: max_chars exceeded]")
                            break
                    joined = "\n".join(response_lines)
                    if len(joined) > max_chars:
                        joined = joined[:max_chars] + "... [truncated]"
                    content = joined if joined else "No response"
                except Exception as e:
                    content = f"Error: {str(e)}"
        
        elif tool_name == "capture_screenshot":
            save_to_file = arguments.get("save_to_file", True)
            filename = arguments.get("filename")
            format = arguments.get("format", "jpeg")
            quality = arguments.get("quality", 80)
            warmup_frames = arguments.get("warmup_frames", 2)
            inline_image = arguments.get("inline_image", True)
            scale_percent = arguments.get("scale_percent", 100)
            max_inline_bytes = arguments.get("max_inline_bytes", 300000)
            result = webcam.capture(save_to_file=save_to_file, filename=filename,
                                    format=format, quality=quality, warmup_frames=warmup_frames)
            if result["success"]:
                content = result["message"]
                if "filepath" in result:
                    content += f"\nSaved to: {result['filepath']}"
                image_b64 = result.get("image_base64")
                mime_type = result.get("mime_type", "image/jpeg")
                if scale_percent != 100 and OPENCV_AVAILABLE and image_b64:
                    try:
                        import numpy as np
                        img_bytes = base64.b64decode(image_b64)
                        img_array = np.frombuffer(img_bytes, dtype=np.uint8)
                        frame = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
                        new_w = max(1, int(frame.shape[1] * scale_percent / 100))
                        new_h = max(1, int(frame.shape[0] * scale_percent / 100))
                        resized = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)
                        if format == "jpeg" or format == "jpg":
                            _, buf = cv2.imencode('.jpg', resized, [cv2.IMWRITE_JPEG_QUALITY, quality])
                            mime_type = "image/jpeg"
                        else:
                            _, buf = cv2.imencode('.png', resized)
                            mime_type = "image/png"
                        image_b64 = base64.b64encode(buf).decode('utf-8')
                    except Exception:
                        content += "\n[Warning: scaling failed]"
                if inline_image and image_b64:
                    return {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "content": [
                                {"type": "text", "text": content},
                                {"type": "image", "data": image_b64, "mimeType": mime_type}
                            ]
                        }
                    }
            else:
                content = f"Screenshot failed: {result['message']}"
        
        elif tool_name == "list_cameras":
            cameras = webcam.list_cameras()
            if cameras:
                content = f"Available cameras: {cameras}"
            else:
                content = "No cameras found (or OpenCV not installed)"
        
        elif tool_name == "set_camera":
            camera_index = arguments.get("camera_index", 0)
            # Release old camera if changing index
            if camera_index != webcam.camera_index:
                webcam.release_camera()
            webcam.camera_index = camera_index
            content = f"Camera index set to {camera_index}"
        
        elif tool_name == "set_screenshot_crop":
            x = arguments.get("x", 0)
            y = arguments.get("y", 0)
            width = arguments.get("width", 640)
            height = arguments.get("height", 480)
            webcam.set_crop_region(x, y, width, height)
            content = f"Crop region set to x={x}, y={y}, width={width}, height={height}"
        
        elif tool_name == "clear_screenshot_crop":
            webcam.clear_crop_region()
            content = "Crop region cleared - will capture full frame"
        
        # Video mode control tools
        elif tool_name == "set_video_mode":
            mode = arguments.get("mode", 4)
            # Video mode register is at 0x8000
            result = controller.wishbone_write(0x8000, mode)
            mode_names = {0: "Color bars", 1: "Grid", 2: "Grayscale", 3: "Text mode", 4: "Framebuffer"}
            content = f"Set video mode to {mode} ({mode_names.get(mode, 'Unknown')})"
            
        elif tool_name == "get_video_mode":
            mode = controller.wishbone_read(0x8000) & 0x07
            mode_names = {0: "Color bars", 1: "Grid", 2: "Grayscale", 3: "Text mode", 4: "Framebuffer"}
            content = f"Video mode: {mode} ({mode_names.get(mode, 'Unknown')})"
        
        # Text mode tools
        elif tool_name == "text_clear":
            # Set cursor to 0,0
            controller.wishbone_write(0x8021, 0)  # cursor_x
            controller.wishbone_write(0x8022, 0)  # cursor_y
            # Fill with spaces (80x30 = 2400 characters)
            controller.wishbone_write(0x8023, 0x0F)  # White on black
            for i in range(2400):
                controller.wishbone_write(0x8024, 0x20)  # Space character
            # Reset cursor
            controller.wishbone_write(0x8021, 0)
            controller.wishbone_write(0x8022, 0)
            content = "Text screen cleared"
            
        elif tool_name == "text_set_cursor":
            x = arguments.get("x", 0)
            y = arguments.get("y", 0)
            controller.wishbone_write(0x8021, x & 0x7F)  # cursor_x
            controller.wishbone_write(0x8022, y & 0x1F)  # cursor_y
            content = f"Cursor set to ({x}, {y})"
            
        elif tool_name == "text_set_color":
            fg = arguments.get("foreground", 15)
            bg = arguments.get("background", 0)
            attr = ((bg & 0x0F) << 4) | (fg & 0x0F)
            controller.wishbone_write(0x8023, attr)  # default_attr
            content = f"Text color set to fg={fg}, bg={bg} (attr=0x{attr:02X})"
            
        elif tool_name == "text_write":
            text = arguments.get("text", "")
            for ch in text:
                controller.wishbone_write(0x8024, ord(ch) & 0xFF)
            content = f"Wrote {len(text)} characters"
            
        elif tool_name == "text_write_at":
            x = arguments.get("x", 0)
            y = arguments.get("y", 0)
            text = arguments.get("text", "")
            fg = arguments.get("foreground", 15)
            bg = arguments.get("background", 0)
            # Set position
            controller.wishbone_write(0x8021, x & 0x7F)
            controller.wishbone_write(0x8022, y & 0x1F)
            # Set color
            attr = ((bg & 0x0F) << 4) | (fg & 0x0F)
            controller.wishbone_write(0x8023, attr)
            # Write characters
            for ch in text:
                controller.wishbone_write(0x8024, ord(ch) & 0xFF)
            content = f"Wrote '{text}' at ({x}, {y}) with fg={fg}, bg={bg}"
        
        else:
            content = f"Unknown tool: {tool_name}"
            
    except Exception as e:
        content = f"Error: {str(e)}"
    
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": content
                }
            ]
        }
    }


def process_request(request: dict) -> Optional[dict]:
    """Process an incoming JSON-RPC request."""
    method = request.get("method")
    request_id = request.get("id")
    params = request.get("params", {})
    
    if method == "initialize":
        return handle_initialize(request_id, params)
    elif method == "initialized":
        # Notification, no response needed
        return None
    elif method == "tools/list":
        return handle_tools_list(request_id)
    elif method == "tools/call":
        return handle_tools_call(request_id, params)
    elif method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    else:
        # Unknown method
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": -32601,
                "message": f"Method not found: {method}"
            }
        }


def main():
    """Main entry point - runs the MCP server over stdio."""
    parser = argparse.ArgumentParser(description="Papilio Arcade MCP Server")
    parser.add_argument("--port", help="Serial port (e.g., COM4)", default=None)
    parser.add_argument("--baud", type=int, help="Baud rate", default=115200)
    parser.add_argument("--screenshots-dir", help="Directory to save screenshots", default=None)
    args = parser.parse_args()
    
    # Configure controller
    controller.port = args.port
    controller.baud = args.baud
    
    # Configure webcam screenshot directory
    if args.screenshots_dir:
        webcam.save_dir = args.screenshots_dir
    
    # Read from stdin, write to stdout (MCP stdio transport)
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
                
            line = line.strip()
            if not line:
                continue
            
            request = json.loads(line)
            response = process_request(request)
            
            if response:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
                
        except json.JSONDecodeError as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": None,
                "error": {
                    "code": -32700,
                    "message": f"Parse error: {str(e)}"
                }
            }
            sys.stdout.write(json.dumps(error_response) + "\n")
            sys.stdout.flush()
        except Exception as e:
            # Log to stderr for debugging
            sys.stderr.write(f"Error: {str(e)}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
