# --- input_manager.py ---
import RPi.GPIO as GPIO
import time
import logging
from gpiozero import RotaryEncoder

class InputManager:
    def __init__(self):
        # GPIO pin assignments
        self.PUSH = 26      # Push button (menu entry)
        self.CONFIRM = 19   # Confirm/Select button
        self.BACK = 21      # Back/Cancel button
        
        # Button state tracking for debouncing
        self.button_states = {}
        self.last_button_time = {}
        self.debounce_time = 0.2  # 200ms debounce
        
        # Initialize GPIO
        try:
            GPIO.setmode(GPIO.BCM)
            for pin in [self.PUSH, self.CONFIRM, self.BACK]:
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
                self.button_states[pin] = False
                self.last_button_time[pin] = 0
                
            # Initialize rotary encoder
            self.encoder = RotaryEncoder(a=16, b=20, max_steps=0)
            self.last_encoder_value = 0
            
            self.gpio_available = True
            logging.info("GPIO initialized successfully")
            
        except Exception as e:
            logging.warning(f"GPIO not available: {e}")
            self.gpio_available = False
            
        self.running = True

    def run(self):
        """Background thread for input processing"""
        while self.running:
            if self.gpio_available:
                # Could add interrupt-based input handling here
                pass
            time.sleep(0.05)

    def read_buttons(self):
        """Read current button states with debouncing"""
        if not self.gpio_available:
            # Return mock input for testing without GPIO
            return {
                "push": False,
                "confirm": False,
                "back": False,
                "encoder": 0,
                "encoder_delta": 0
            }
            
        current_time = time.time()
        buttons = {}
        
        # Read button states with debouncing
        for pin, name in [(self.PUSH, "push"), (self.CONFIRM, "confirm"), (self.BACK, "back")]:
            current_state = not GPIO.input(pin)  # Invert because of pull-up
            
            # Check if button state changed and debounce time has passed
            if (current_state != self.button_states[pin] and 
                current_time - self.last_button_time[pin] > self.debounce_time):
                
                self.button_states[pin] = current_state
                self.last_button_time[pin] = current_time
                buttons[name] = current_state and current_state  # Only trigger on press
            else:
                buttons[name] = False
                
        # Read encoder with delta calculation
        current_encoder = self.encoder.steps
        encoder_delta = current_encoder - self.last_encoder_value
        self.last_encoder_value = current_encoder
        
        buttons["encoder"] = current_encoder
        buttons["encoder_delta"] = encoder_delta
        
        return buttons
        
    def wait_for_button_release(self, button_name):
        """Wait for a specific button to be released"""
        if not self.gpio_available:
            return
            
        pin_map = {"push": self.PUSH, "confirm": self.CONFIRM, "back": self.BACK}
        pin = pin_map.get(button_name)
        
        if pin:
            while not GPIO.input(pin):  # Wait while button is pressed
                time.sleep(0.05)
                
    def reset_encoder(self):
        """Reset encoder position to zero"""
        if self.gpio_available:
            self.encoder.steps = 0
            self.last_encoder_value = 0

    def cleanup(self):
        """Clean up GPIO resources"""
        self.running = False
        if self.gpio_available:
            try:
                # Close encoder first to prevent issues
                if hasattr(self, 'encoder') and self.encoder:
                    try:
                        self.encoder.close()
                        logging.info("Rotary encoder closed")
                    except Exception as e:
                        logging.warning(f"Error closing encoder: {e}")
                
                # Clean up GPIO
                GPIO.cleanup()
                logging.info("GPIO cleaned up")
            except Exception as e:
                logging.error(f"Error cleaning up GPIO: {e}")
            finally:
                self.gpio_available = False
                
    def get_input_status(self):
        """Get status of input system"""
        return {
            "gpio_available": self.gpio_available,
            "running": self.running,
            "encoder_position": self.encoder.steps if self.gpio_available else 0
        }