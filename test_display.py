#!/usr/bin/env python3
"""
Simple test script to check if OLED display works without font errors
"""
import board
import busio
import adafruit_ssd1306
import time

def test_oled():
    """Test basic OLED functionality"""
    try:
        print("Initializing OLED display...")
        i2c = busio.I2C(board.SCL, board.SDA)
        oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)
        
        print("OLED initialized successfully!")
        
        # Clear display
        oled.fill(0)
        oled.show()
        print("Display cleared")
        
        # Test basic text
        oled.text("Test message", 0, 0, 1)
        oled.text("Line 2", 0, 10, 1) 
        oled.text("Line 3", 0, 20, 1)
        oled.show()
        print("Text displayed successfully!")
        
        # Wait a bit
        time.sleep(3)
        
        # Clear again
        oled.fill(0)
        oled.show()
        print("Test completed successfully - no font errors!")
        
        return True
        
    except Exception as e:
        print(f"Error during OLED test: {e}")
        return False

if __name__ == "__main__":
    success = test_oled()
    if success:
        print("✓ OLED display test passed - scanner should work!")
    else:
        print("✗ OLED display test failed - may need font file")
