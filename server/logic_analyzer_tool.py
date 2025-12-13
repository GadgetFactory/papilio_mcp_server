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
    
    # Current memory depth (updated with Block RAM)
    MEMORY_DEPTH = 2048  # Updated from 1024 with Block RAM implementation
    
    # Register offsets (SUMP-compatible)
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
    
    # Channel names for the 32 monitored signals (updated for current probe configuration)
    CHANNEL_NAMES = [
        # Bits [7:0] - Debug signals
        "audio_left", "rst", "clk_27mhz", "esp_miso", "esp_mosi", "esp_clk", "esp_cs_n", "rgb_led",
        # Bits [15:8] - Wishbone address bus [7:0]
        "wb_adr[0]", "wb_adr[1]", "wb_adr[2]", "wb_adr[3]", 
        "wb_adr[4]", "wb_adr[5]", "wb_adr[6]", "wb_adr[7]",
        # Bits [23:16] - Wishbone control signals
        "la_selected", "ym2149_selected", "sid_selected", "rgb_led_selected",
        "wb_ack_i", "wb_we_o", "wb_stb_o", "wb_cyc_o",
        # Bits [31:24] - Wishbone data bus [7:0]
        "wb_dat[0]", "wb_dat[1]", "wb_dat[2]", "wb_dat[3]",
        "wb_dat[4]", "wb_dat[5]", "wb_dat[6]", "wb_dat[7]",
    ]
    
    def __init__(self, controller):
        """Initialize with a PapilioController instance"""
        self.ctrl = controller
        self.configured_samples = 128  # Default sample count
        
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
            "depth": self.MEMORY_DEPTH,
            "sample_rate_mhz": 27.0,
            "capture_duration_us": (self.MEMORY_DEPTH / 27.0)
        }
        
    def configure(self, trigger_mask: int = 0, trigger_value: int = 0,
                  samples: int = 1024, post_trigger: int = 512, divider: int = 0) -> Dict:
        """Configure trigger and capture parameters"""
        # Store configured sample count
        self.configured_samples = samples
        
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
        
    def capture(self, timeout: float = 5.0, num_samples: Optional[int] = None) -> Optional[List[int]]:
        """
        Capture data (waits for completion)
        
        Args:
            timeout: Timeout in seconds
            num_samples: Number of samples to read (default: MEMORY_DEPTH)
            
        Returns 32-bit samples where each sample contains:
            [31:24] = wb_dat_o[7:0]
            [23:16] = control signals (wb_cyc, wb_stb, wb_we, wb_ack, selections)
            [15:8]  = wb_adr_o[7:0]
            [7:0]   = debug signals (rgb_led, spi, clk, rst, audio)
        """
        start_time = time.time()
        
        # Wait for DONE state (bit 2 = TRIGGERED)
        while time.time() - start_time < timeout:
            status_byte = self._read_reg(self.REG_STATUS)
            if status_byte & 0x04:  # TRIGGERED bit
                break
            time.sleep(0.01)
        else:
            return None  # Timeout
        
        # Read 32-bit samples (4 bytes per sample)
        # Sample memory is byte-addressable: each 32-bit sample occupies 4 consecutive bytes
        samples = []
        max_samples = num_samples if num_samples else getattr(self, 'configured_samples', 128)
        
        for i in range(max_samples):
            # Calculate base address for this sample
            sample_offset = i * 4
            byte0 = self._read_reg(self.REG_DATA_START + sample_offset + 0)  # [7:0]
            byte1 = self._read_reg(self.REG_DATA_START + sample_offset + 1)  # [15:8]
            byte2 = self._read_reg(self.REG_DATA_START + sample_offset + 2)  # [23:16]
            byte3 = self._read_reg(self.REG_DATA_START + sample_offset + 3)  # [31:24]
            
            # Combine into 32-bit sample
            sample_32bit = (byte3 << 24) | (byte2 << 16) | (byte1 << 8) | byte0
            samples.append(sample_32bit)
            
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
    def decode_wb_data_samples(self, samples: List[int]) -> List[Dict]:
        """
        Decode samples as Wishbone data bus values (wb_dat_o[7:0]).
        Since the LA only outputs [31:24] where wb_dat_o is mapped,
        each sample byte represents the Wishbone data bus value.
        
        Returns list of decoded sample dictionaries with wb_dat_o value.
        """
        decoded = []
        for i, byte_val in enumerate(samples):
            decoded.append({
                "sample_num": i,
                "wb_dat_o": byte_val,
                "hex": f"0x{byte_val:02X}"
            })
        return decoded
    
    def find_trigger_in_samples(self, samples: List[int], trigger_value: int) -> Optional[int]:
        """Find the sample index where the trigger value appears."""
        for i, val in enumerate(samples):
            if val == trigger_value:
                return i
        return None
    
    def analyze_wb_transactions(self, samples: List[int], 
                                trigger_value: Optional[int] = None,
                                context_before: int = 10,
                                context_after: int = 20) -> Dict:
        """
        Analyze Wishbone data captures around a trigger point.
        
        Args:
            samples: List of captured byte samples (wb_dat_o values)
            trigger_value: The trigger value to find (None = analyze all)
            context_before: Samples to include before trigger
            context_after: Samples to include after trigger
            
        Returns:
            Dict with trigger index, context window, and statistics
        """
        trigger_idx = None
        if trigger_value is not None:
            trigger_idx = self.find_trigger_in_samples(samples, trigger_value)
        
        # Extract context window
        if trigger_idx is not None:
            start = max(0, trigger_idx - context_before)
            end = min(len(samples), trigger_idx + context_after + 1)
            window = samples[start:end]
            window_start = start
        else:
            window = samples[:min(50, len(samples))]
            window_start = 0
        
        # Calculate statistics
        unique_values = set(samples)
        value_counts = {}
        for val in samples:
            value_counts[val] = value_counts.get(val, 0) + 1
        
        return {
            "total_samples": len(samples),
            "trigger_index": trigger_idx,
            "trigger_found": trigger_idx is not None,
            "window_samples": self.decode_wb_data_samples(window),
            "window_start_index": window_start,
            "unique_values_count": len(unique_values),
            "most_common": sorted(value_counts.items(), key=lambda x: x[1], reverse=True)[:5],
            "capture_duration_us": len(samples) / 27.0
        }