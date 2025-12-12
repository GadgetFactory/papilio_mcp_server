#!/usr/bin/env python3
"""
Logic Analyzer Tool for Papilio MCP Server
Provides SUMP-compatible logic analyzer interface via Wishbone bus
"""

import time
from typing import Dict, List, Optional

class LogicAnalyzerTool:
    """SUMP-compatible logic analyzer controller via Wishbone"""
    
    # Base address
    BASE_ADDR = 0x8300
    
    # Register offsets
    REG_CMD = 0x00
    REG_STATUS = 0x00
    REG_ID_0 = 0x02
    REG_ID_1 = 0x03
    REG_TRIGGER_MASK_0 = 0x04
    REG_TRIGGER_MASK_1 = 0x05
    REG_TRIGGER_MASK_2 = 0x06
    REG_TRIGGER_MASK_3 = 0x07
    REG_TRIGGER_VAL_0 = 0x08
    REG_TRIGGER_VAL_1 = 0x09
    REG_TRIGGER_VAL_2 = 0x0A
    REG_TRIGGER_VAL_3 = 0x0B
    REG_DELAY_COUNT_L = 0x0C
    REG_DELAY_COUNT_H = 0x0D
    REG_READ_COUNT_L = 0x10
    REG_READ_COUNT_H = 0x11
    REG_DIVIDER = 0x14
    REG_FLAGS = 0x18
    REG_DATA_START = 0x80
    
    # Commands
    CMD_RESET = 0x00
    CMD_ARM = 0x01
    
    # States
    STATE_IDLE = 0
    STATE_ARMED = 1
    STATE_TRIGGERED = 2
    STATE_CAPTURING = 3
    STATE_DONE = 4
    
    # Channel names for the 32 monitored signals
    CHANNEL_NAMES = [
        # Wishbone bus signals (8 bits)
        "wb_cyc", "wb_stb", "wb_we", "wb_ack",
        "wb_adr[12]", "wb_adr[13]", "wb_adr[14]", "wb_adr[15]",
        # SPI interface (4 bits)  
        "esp_cs_n", "esp_clk", "esp_mosi", "esp_miso",
        # Video/system (4 bits)
        "pix_clk", "hdmi_rst_n", "video_mode[0]", "video_mode[1]",
        # Peripheral selects (16 bits)
        "spi_sel", "rgb_sel", "sid_sel", "ym_sel",
        "tp_sel", "text_sel", "fb_sel", "la_sel",
        "reserved[0]", "reserved[1]", "reserved[2]", "reserved[3]",
        "reserved[4]", "reserved[5]", "reserved[6]", "reserved[7]",
    ]
    
    def __init__(self, controller):
        """Initialize with a PapilioController instance"""
        self.ctrl = controller
        
    def _read_reg(self, reg_offset: int) -> int:
        """Read logic analyzer register"""
        return self.ctrl.wishbone_read(self.BASE_ADDR + reg_offset)
        
    def _write_reg(self, reg_offset: int, value: int):
        """Write logic analyzer register"""
        self.ctrl.wishbone_write(self.BASE_ADDR + reg_offset, value)
        
    def reset(self) -> Dict:
        """Reset the logic analyzer"""
        self._write_reg(self.REG_CMD, self.CMD_RESET)
        time.sleep(0.01)
        return {"status": "reset"}
        
    def get_status(self) -> Dict:
        """Get current status"""
        state = self._read_reg(self.REG_STATUS) & 0x07
        state_names = {
            self.STATE_IDLE: "IDLE",
            self.STATE_ARMED: "ARMED", 
            self.STATE_TRIGGERED: "TRIGGERED",
            self.STATE_CAPTURING: "CAPTURING",
            self.STATE_DONE: "DONE"
        }
        
        id0 = self._read_reg(self.REG_ID_0)
        id1 = self._read_reg(self.REG_ID_1)
        
        return {
            "state": state,
            "state_name": state_names.get(state, "UNKNOWN"),
            "device_id": f"0x{id0:02X}{id1:02X}",
            "channels": 32,
            "depth": 1024
        }
        
    def configure(self, trigger_mask: int = 0, trigger_value: int = 0,
                  samples: int = 1024, post_trigger: int = 512, divider: int = 0) -> Dict:
        """Configure trigger and capture parameters"""
        # Write trigger mask (32-bit)
        self._write_reg(self.REG_TRIGGER_MASK_0, (trigger_mask >> 0) & 0xFF)
        self._write_reg(self.REG_TRIGGER_MASK_1, (trigger_mask >> 8) & 0xFF)
        self._write_reg(self.REG_TRIGGER_MASK_2, (trigger_mask >> 16) & 0xFF)
        self._write_reg(self.REG_TRIGGER_MASK_3, (trigger_mask >> 24) & 0xFF)
        
        # Write trigger value (32-bit)
        self._write_reg(self.REG_TRIGGER_VAL_0, (trigger_value >> 0) & 0xFF)
        self._write_reg(self.REG_TRIGGER_VAL_1, (trigger_value >> 8) & 0xFF)
        self._write_reg(self.REG_TRIGGER_VAL_2, (trigger_value >> 16) & 0xFF)
        self._write_reg(self.REG_TRIGGER_VAL_3, (trigger_value >> 24) & 0xFF)
        
        # Write post-trigger count (16-bit)
        self._write_reg(self.REG_DELAY_COUNT_L, post_trigger & 0xFF)
        self._write_reg(self.REG_DELAY_COUNT_H, (post_trigger >> 8) & 0xFF)
        
        # Write read count (16-bit)
        self._write_reg(self.REG_READ_COUNT_L, samples & 0xFF)
        self._write_reg(self.REG_READ_COUNT_H, (samples >> 8) & 0xFF)
        
        # Write divider (8-bit)
        self._write_reg(self.REG_DIVIDER, divider & 0xFF)
        
        return {
            "trigger_mask": f"0x{trigger_mask:08X}",
            "trigger_value": f"0x{trigger_value:08X}",
            "samples": samples,
            "post_trigger": post_trigger,
            "divider": divider
        }
        
    def arm(self) -> Dict:
        """Arm the logic analyzer"""
        self._write_reg(self.REG_CMD, self.CMD_ARM)
        return {"status": "armed"}
        
    def capture(self, timeout: float = 5.0) -> Optional[List[int]]:
        """Capture data (waits for completion)"""
        start_time = time.time()
        
        # Wait for DONE state
        while time.time() - start_time < timeout:
            status = self.get_status()
            if status['state'] == self.STATE_DONE:
                break
            time.sleep(0.01)
        else:
            return None  # Timeout
            
        # Read samples (4 bytes per 32-bit sample)
        samples = []
        for addr in range(self.REG_DATA_START, self.REG_DATA_START + 0x80, 4):
            b0 = self._read_reg(addr + 0)
            b1 = self._read_reg(addr + 1)
            b2 = self._read_reg(addr + 2)
            b3 = self._read_reg(addr + 3)
            sample = b0 | (b1 << 8) | (b2 << 16) | (b3 << 24)
            samples.append(sample)
            
        return samples
        
    def export_vcd(self, samples: List[int], filename: str = "capture.vcd"):
        """Export samples to VCD format"""
        with open(filename, 'w') as f:
            # Header
            f.write("$date\n")
            f.write(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("$end\n")
            f.write("$version\n")
            f.write("  Papilio Logic Analyzer\n")
            f.write("$end\n")
            f.write("$timescale 1ns $end\n")
            f.write("$scope module logic $end\n")
            
            # Variables
            for i, name in enumerate(self.CHANNEL_NAMES):
                f.write(f"$var wire 1 {chr(33+i)} {name} $end\n")
            f.write("$upscope $end\n")
            f.write("$enddefinitions $end\n")
            
            # Initial values
            f.write("#0\n")
            f.write("$dumpvars\n")
            if samples:
                for i in range(32):
                    bit = (samples[0] >> i) & 1
                    f.write(f"{bit}{chr(33+i)}\n")
            f.write("$end\n")
            
            # Data
            for t, sample in enumerate(samples[1:], 1):
                f.write(f"#{t}\n")
                for i in range(32):
                    bit = (sample >> i) & 1
                    prev_bit = (samples[t-1] >> i) & 1
                    if bit != prev_bit:
                        f.write(f"{bit}{chr(33+i)}\n")
                        
        return {"filename": filename, "samples": len(samples)}
