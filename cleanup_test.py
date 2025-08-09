#!/usr/bin/env python3
"""
Test script to verify cleanup sequence works properly
"""

import time
import signal
import sys
import threading
from scanner.input_manager import InputManager
from scanner.op25_manager import OP25Manager
from scanner.display_manager import DisplayManager
from scanner.settings_manager import SettingsManager

def test_cleanup():
    """Test the cleanup sequence in isolation"""
    print("Testing cleanup sequence...")
    
    # Initialize components
    settings = SettingsManager("settings.json")
    input_mgr = InputManager()
    op25_manager = OP25Manager(settings)
    display = DisplayManager()
    
    print("Components initialized")
    
    # Test cleanup with timeout
    def cleanup_with_timeout():
        print("Starting cleanup sequence...")
        start_time = time.time()
        
        try:
            print("1. Stopping OP25 manager...")
            op25_manager.cleanup()
            print(f"   OP25 manager cleanup completed in {time.time() - start_time:.2f}s")
            
            print("2. Cleaning up input manager...")
            step_time = time.time()
            input_mgr.cleanup()
            print(f"   Input manager cleanup completed in {time.time() - step_time:.2f}s")
            
            print("3. Cleaning up display...")
            step_time = time.time()
            display.cleanup()
            display.clear()
            print(f"   Display cleanup completed in {time.time() - step_time:.2f}s")
            
            total_time = time.time() - start_time
            print(f"Total cleanup time: {total_time:.2f}s")
            return True
            
        except Exception as e:
            print(f"ERROR during cleanup: {e}")
            return False
    
    # Run cleanup with a timeout to detect hangs
    cleanup_thread = threading.Thread(target=cleanup_with_timeout)
    cleanup_thread.daemon = True
    cleanup_thread.start()
    
    # Wait up to 30 seconds for cleanup
    cleanup_thread.join(timeout=30)
    
    if cleanup_thread.is_alive():
        print("ERROR: Cleanup is hanging! Thread did not complete within 30 seconds.")
        print("This indicates a potential issue with one of the cleanup methods.")
        return False
    else:
        print("Cleanup completed successfully!")
        return True

def signal_handler(sig, frame):
    print("\nInterrupt received, testing cleanup...")
    success = test_cleanup()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    # Set up signal handler
    signal.signal(signal.SIGINT, signal_handler)
    
    print("Cleanup test ready. Press Ctrl+C to test cleanup sequence.")
    print("Alternatively, the test will run automatically in 5 seconds...")
    
    try:
        time.sleep(5)
        print("\nRunning automatic cleanup test...")
        success = test_cleanup()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        pass  # Will be handled by signal handler
