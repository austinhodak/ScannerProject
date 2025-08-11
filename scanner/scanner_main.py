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
import gc


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

        # Initialize display with talkgroup manager and rotation setting
        rotation = settings.get("display_rotation", 0)
        display = DisplayManager(talkgroup_manager=talkgroup_mgr, rotation=rotation)

        # Initialize ST7789 display with configured pins
        display.initialize_displays(settings)

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
            try:
                # Stop OP25 client first (sets running=False)
                logging.info("Stopping OP25 client...")
                op25.stop()

                # Give threads a moment to see the stop flag
                time.sleep(0.1)

                # Clean up OP25 manager (processes and threads)
                logging.info("Cleaning up OP25 manager...")
                op25_manager.cleanup()

                # Clean up input manager and GPIO
                logging.info("Cleaning up input manager...")
                input_mgr.cleanup()

                # Clean up display last
                logging.info("Cleaning up display...")
                display.cleanup()
                display.clear()

                logging.info("Cleanup completed successfully")
            except Exception as e:
                logging.error(f"Error during cleanup: {e}")
                # Force cleanup if normal cleanup fails
                try:
                    op25_manager.kill_all_op25_processes()
                except:
                    pass

        signal.signal(signal.SIGINT, lambda s, f: signal_handler(s, f, cleanup))
        signal.signal(signal.SIGTERM, lambda s, f: signal_handler(s, f, cleanup))

        # At startup, sync settings volume_level from current system volume (source of truth)
        try:
            display.set_volume_hint(0)  # clear recent hint
            current_sys_vol = display._get_system_volume_percent(settings.get('volume_level', 0))
            settings.set('volume_level', int(current_sys_vol))
        except Exception:
            pass

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
        volume_mode = False
        volume_mode_last_activity = 0.0
        volume_mode_timeout = 2.5  # seconds after last activity

        while True:
            try:
                # Read input
                buttons = input_mgr.read_buttons()

                # Check for menu entry (hold push button) and volume mode toggle (short press)
                if not menu.in_menu_mode():
                    if buttons.get("push"):
                        if push_start_time is None:
                            push_start_time = time.time()
                        else:
                            held = time.time() - push_start_time
                            if held >= menu_entry_hold_time:
                                logging.info("Menu entry triggered by long push")
                                menu.enter_menu()
                                push_start_time = None
                    else:
                        # Button released: if it was a short press, toggle volume mode
                        if push_start_time is not None:
                            held = time.time() - push_start_time
                            if held < menu_entry_hold_time:
                                volume_mode = not volume_mode
                                volume_mode_last_activity = time.time()
                                display.set_volume_mode(volume_mode)
                                logging.info(f"Volume mode {'enabled' if volume_mode else 'disabled'}")
                            push_start_time = None

                # Handle menu or scanner display
                if menu.in_menu_mode():
                    menu.update(buttons)
                else:
                    # Adjust system volume with encoder on main display
                    enc_delta = buttons.get("encoder_delta", 0)
                    if enc_delta and volume_mode:
                        now = time.time()
                        adj = abs(enc_delta) * volume_step_percent

                        # Always update UI immediately for smooth feedback
                        try:
                            # Keep a local expected volume that we will eventually reconcile with system
                            current_vol = settings.get('volume_level', 0)
                            ui_estimated = max(0, min(100, current_vol + (adj if enc_delta > 0 else -adj)))
                            settings.set('volume_level', ui_estimated)
                            display.set_volume_hint(ui_estimated)
                            display.request_oled_refresh()
                            display.skip_tft_for(0.2)
                        except Exception:
                            pass

                        # Coalesce actual system volume changes (rate-limit to 10/sec)
                        if now - last_volume_adjust_time > 0.05:
                            # Try PulseAudio (set absolute volume to match UI)
                            try:
                                subprocess.run([
                                    "pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{int(ui_estimated)}%"
                                ], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=0.5)
                            except Exception:
                                # Fallback to ALSA
                                try:
                                    # Some ALSA controls require specifying the 'Playback' channel
                                    subprocess.run([
                                        "amixer", "-q", "set", "Master", f"{int(ui_estimated)}%"] ,
                                        check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=0.5)
                                except Exception:
                                    pass
                            # After issuing the actual system change, refresh the OLED but keep hint grace active
                            try:
                                display.request_oled_refresh()
                            except Exception:
                                pass
                            last_volume_adjust_time = now
                            volume_mode_last_activity = now
                    # Auto-timeout volume mode after inactivity
                    if volume_mode and (time.time() - volume_mode_last_activity) > volume_mode_timeout:
                        volume_mode = False
                        display.set_volume_mode(False)
                        logging.info("Volume mode timed out")

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

                # Occasional GC to keep memory tidy during long runs
                if int(time.time()) % 10 == 0:
                    try:
                        gc.collect()
                    except Exception:
                        pass
                # Small delay to prevent excessive CPU usage and I/O pressure
                # Reduced delay to support faster OLED refresh rates (up to 20 Hz)
                time.sleep(0.05)
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
