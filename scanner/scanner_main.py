# --- scanner_main.py ---
from scanner.settings_manager import SettingsManager
from scanner.op25_client import OP25Client
from scanner.op25_manager import OP25Manager
from scanner.display_manager import DisplayManager
from scanner.input_manager import InputManager
from scanner.menu_system import MenuSystem
from scanner.talkgroup_manager import TalkgroupManager
import time
import threading
import logging
import signal
import sys
import subprocess


def setup_logging(settings):
    """Setup logging configuration"""
    log_level = settings.get("log_level", "INFO")
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('/tmp/scanner.log'),
            logging.StreamHandler()
        ]
    )
    
    # Reduce noise from some modules
    logging.getLogger('requests').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


def signal_handler(sig, frame, cleanup_func):
    """Handle shutdown signals gracefully"""
    logging.info(f"Received signal {sig}, shutting down gracefully...")
    cleanup_func()
    sys.exit(0)


def main():
    """Main scanner application"""
    print("Starting Scanner System...")
    
    try:
        # Initialize components
        settings = SettingsManager("settings.json")
        setup_logging(settings)
        
        logging.info("Scanner system starting up...")
        
        # Load talkgroup data
        talkgroup_mgr = TalkgroupManager("talkgroups.tsv")
        
        # Initialize OP25 manager
        op25_manager = OP25Manager(settings)
        
        # Initialize OP25 client with settings
        op25_host = settings.get("op25_host", "127.0.0.1")
        op25_port = settings.get("op25_port", 8080)
        system_name = settings.get("system_name", "SCANNER")
        prefer_op25 = settings.get("prefer_op25_system_name", False)
        op25 = OP25Client(host=op25_host, port=op25_port, system_name=system_name, prefer_op25_name=prefer_op25)
        
        # Initialize display with talkgroup manager
        display = DisplayManager(talkgroup_manager=talkgroup_mgr)
        
        # Initialize input manager
        input_mgr = InputManager()
        
        # Initialize menu system with all dependencies
        menu = MenuSystem(
            display=display, 
            input_mgr=input_mgr, 
            settings=settings,
            op25_client=op25,
            talkgroup_manager=talkgroup_mgr,
            op25_manager=op25_manager
        )
        
        # Setup signal handlers for graceful shutdown
        def cleanup():
            logging.info("Cleaning up...")
            op25.stop()
            op25_manager.cleanup()
            input_mgr.cleanup()
            display.clear()
            
        signal.signal(signal.SIGINT, lambda s, f: signal_handler(s, f, cleanup))
        signal.signal(signal.SIGTERM, lambda s, f: signal_handler(s, f, cleanup))
        
        # Start background threads
        logging.info("Starting background threads...")
        op25_thread = threading.Thread(target=op25.run, daemon=True, name="OP25Client")
        input_thread = threading.Thread(target=input_mgr.run, daemon=True, name="InputManager")
        
        op25_thread.start()
        input_thread.start()
        
        logging.info("Scanner system ready")
        display.show_message("Scanner", "System Ready")
        
        # Auto-start OP25 if configured
        if settings.get("op25_auto_start", False):
            logging.info("Auto-starting OP25...")
            display.show_message("OP25", "Auto-starting...")
            if op25_manager.start():
                logging.info("OP25 auto-started successfully")
                display.show_message("OP25", "Started")
            else:
                logging.warning("OP25 auto-start failed")
                display.show_message("OP25", "Auto-start failed")
            time.sleep(2)
        else:
            time.sleep(2)
        
        # Main application loop
        last_menu_check = 0
        menu_entry_hold_time = 1.0  # Hold push button for 1 second to enter menu
        push_start_time = None
        last_volume_adjust_time = 0.0
        volume_step_percent = 3  # percent per encoder detent
        
        while True:
            try:
                # Read input
                buttons = input_mgr.read_buttons()
                
                # Check for menu entry (hold push button)
                if not menu.in_menu_mode():
                    if buttons.get("push"):
                        if push_start_time is None:
                            push_start_time = time.time()
                        elif time.time() - push_start_time >= menu_entry_hold_time:
                            logging.info("Menu entry triggered by long push")
                            menu.enter_menu()
                            push_start_time = None
                    else:
                        push_start_time = None
                
                # Handle menu or scanner display
                if menu.in_menu_mode():
                    menu.update(buttons)
                else:
                    # Adjust system volume with encoder on main display
                    enc_delta = buttons.get("encoder_delta", 0)
                    if enc_delta:
                        now = time.time()
                        # Combine steps into one system call (rate-limit to 10/sec)
                        if now - last_volume_adjust_time > 0.05:
                            adj = abs(enc_delta) * volume_step_percent
                            sign = '+' if enc_delta > 0 else '-'
                            # Try PulseAudio
                            try:
                                subprocess.run([
                                    "pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{sign}{adj}%"
                                ], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=0.5)
                            except Exception:
                                # Fallback to ALSA
                                try:
                                    # amixer expects e.g. 3%+ or 3%- on some versions
                                    subprocess.run([
                                        "amixer", "-q", "set", "Master", f"{adj}%{sign}"
                                    ], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=0.5)
                                except Exception:
                                    pass
                            last_volume_adjust_time = now
                    
                    # Update scanner display
                    system, freq, tgid, extra = op25.get_latest()
                    display.update(system, freq, tgid, extra, settings)
                    
                    # Check for back button to enter menu (alternative method)
                    if buttons.get("back"):
                        current_time = time.time()
                        if current_time - last_menu_check > 0.5:  # Debounce
                            logging.info("Menu entry triggered by back button")
                            menu.enter_menu()
                            last_menu_check = current_time
                
                # Small delay to prevent excessive CPU usage
                time.sleep(0.1)
                
            except Exception as e:
                logging.error(f"Error in main loop: {e}")
                display.show_message("Error", "System error occurred")
                time.sleep(1)
    
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        print(f"Fatal error: {e}")
    finally:
        cleanup()
        logging.info("Scanner system shutdown complete")
        print("Scanner system shutdown complete")


if __name__ == "__main__":
    main()