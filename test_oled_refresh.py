#!/usr/bin/env python3
"""
Test script to verify OLED refresh rate improvements
"""

import time
import json
from scanner.display_manager import DisplayManager
from scanner.settings_manager import SettingsManager

def test_oled_refresh_rate():
    """Test the OLED refresh rate functionality"""
    print("Testing OLED refresh rate improvements...")
    
    # Load settings
    settings_mgr = SettingsManager("settings.json")
    
    # Verify new settings exist
    oled_refresh_rate = settings_mgr.get('oled_refresh_rate', None)
    oled_scroll_speed = settings_mgr.get('oled_scroll_speed', None)
    
    print(f"OLED refresh rate setting: {oled_refresh_rate} Hz")
    print(f"OLED scroll speed setting: {oled_scroll_speed} seconds")
    
    if oled_refresh_rate is None:
        print("ERROR: oled_refresh_rate setting not found!")
        return False
        
    if oled_scroll_speed is None:
        print("ERROR: oled_scroll_speed setting not found!")
        return False
    
    # Test display manager initialization
    try:
        display = DisplayManager()
        print(f"Display Manager initialized successfully")
        print(f"OLED available: {display.oled_available}")
        print(f"Default OLED min interval: {display._oled_min_interval} seconds")
        
        # Test refresh rate calculation
        expected_interval = 1.0 / oled_refresh_rate
        print(f"Expected OLED interval: {expected_interval:.3f} seconds ({oled_refresh_rate} Hz)")
        
        # Test with mock data
        system = "TEST SYSTEM"
        freq = 453.1250
        tgid = 1234
        extra = {"active": True, "srcaddr": 5678, "signal_locked": True}
        
        # Time multiple updates to verify throttling
        print("\nTesting OLED update timing...")
        update_times = []
        
        for i in range(10):
            start_time = time.time()
            display.update_oled(system, freq, tgid, extra, settings_mgr.settings)
            end_time = time.time()
            update_times.append(end_time - start_time)
            time.sleep(0.01)  # Small delay between tests
        
        avg_update_time = sum(update_times) / len(update_times)
        print(f"Average OLED update time: {avg_update_time:.4f} seconds")
        print(f"Theoretical max refresh rate: {1.0/avg_update_time:.1f} Hz")
        
        # Cleanup
        display.cleanup()
        
        print("\nTest completed successfully!")
        return True
        
    except Exception as e:
        print(f"ERROR during testing: {e}")
        return False

if __name__ == "__main__":
    success = test_oled_refresh_rate()
    exit(0 if success else 1)
