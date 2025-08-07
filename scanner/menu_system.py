# --- menu_system.py ---
import os
import subprocess
import logging
import time
import psutil
from datetime import datetime

class MenuSystem:
    def __init__(self, display, input_mgr, settings, op25_client=None, talkgroup_manager=None, op25_manager=None):
        self.display = display
        self.input_mgr = input_mgr
        self.settings = settings
        self.op25_client = op25_client
        self.talkgroup_manager = talkgroup_manager
        self.op25_manager = op25_manager

        self.menus = {
            "main": ["Scanner Control", "Audio Settings", "Display Settings", "System Settings", "OP25 Management", "Information", "Exit Menu"],
            "Scanner Control": ["Auto Scan", "Priority Scan", "Scan Delay", "Hold System", "Back"],
            "Audio Settings": ["Volume", "Mute", "Recording", "Audio Device", "Back"],
            "Display Settings": ["Brightness", "Timeout", "Show Debug", "Color Scheme", "Back"],
            "System Settings": ["API Port", "Web Interface", "Reboot System", "Reset Settings", "Back"],
            "OP25 Management": ["Start OP25", "Stop OP25", "Restart OP25", "OP25 Status", "OP25 Config", "Create OP25 Config", "OP25 Logs", "Back"],
            "Information": ["System Status", "OP25 Status", "Network Info", "Disk Usage", "Talkgroups", "Back"]
        }

        # Initialize values from settings
        self.values = {
            "Volume": self.settings.get("volume_level", 75),
            "Mute": self.settings.get("mute", False),
            "Recording": self.settings.get("recording", False),
            "Brightness": self.settings.get("brightness", 75),
            "Timeout": self.settings.get("timeout", 30),
            "Show Debug": self.settings.get("show_debug", False),
            "API Port": self.settings.get("api_port", 8080),
            "Web Interface": self.settings.get("web_interface", True),
            "Auto Scan": self.settings.get("auto_scan", True),
            "Priority Scan": self.settings.get("priority_scan", False),
            "Scan Delay": self.settings.get("scan_delay", 2000),
            "Audio Device": self.settings.get("audio_device", "default"),
            "Color Scheme": "Default",
            "Hold System": False
        }

        self.menu_stack = ["main"]
        self.current_index = 0
        self.last_encoder_value = 0
        self.in_menu = False
        self.last_button_time = 0
        self.button_repeat_delay = 0.3

    def in_menu_mode(self):
        return self.in_menu

    def enter_menu(self):
        """Enter menu mode"""
        self.in_menu = True
        self.menu_stack = ["main"]
        self.current_index = 0
        logging.info("Entered menu mode")

    def exit_menu(self):
        """Exit menu mode and return to scanner display"""
        self.menu_stack = ["main"]
        self.current_index = 0
        self.in_menu = False
        logging.info("Exited menu mode")

    def update(self, buttons):
        """Update menu system based on input"""
        current_time = time.time()
        
        # Handle encoder navigation
        encoder_delta = buttons.get("encoder_delta", 0)
        if encoder_delta != 0:
            if encoder_delta > 0:
                self.current_index = (self.current_index + 1) % len(self.current_menu())
            else:
                self.current_index = (self.current_index - 1) % len(self.current_menu())

        # Handle button presses with debouncing
        if buttons.get("confirm") and current_time - self.last_button_time > self.button_repeat_delay:
            self.last_button_time = current_time
            self._handle_selection()

        elif buttons.get("back") and current_time - self.last_button_time > self.button_repeat_delay:
            self.last_button_time = current_time
            self._handle_back()

        elif buttons.get("push") and current_time - self.last_button_time > self.button_repeat_delay:
            self.last_button_time = current_time
            # Push button can be used as alternate confirm in menu
            self._handle_selection()

        # Render menu
        self._render_menu()
        
    def _handle_selection(self):
        """Handle menu item selection"""
        selected = self.current_menu()[self.current_index]

        if selected == "Back":
            self._handle_back()
        elif selected == "Exit Menu":
            self.exit_menu()
        elif selected in self.menus:
            # Navigate to submenu
            self.menu_stack.append(selected)
            self.current_index = 0
        elif selected in self.values:
            # Adjust setting value
            self._adjust_value(selected)
        else:
            # Execute action
            self._execute_action(selected)
            
    def _handle_back(self):
        """Handle back button press"""
        if len(self.menu_stack) > 1:
            self.menu_stack.pop()
            self.current_index = 0
        else:
            self.exit_menu()

    def _adjust_value(self, setting):
        """Adjust a setting value"""
        current_val = self.values[setting]
        
        # Boolean toggles
        if setting in ["Mute", "Recording", "Show Debug", "Web Interface", "Auto Scan", "Priority Scan", "Hold System"]:
            self.values[setting] = not current_val
            
        # Numeric ranges
        elif setting == "Volume":
            self.values[setting] = (current_val + 5) % 105
        elif setting == "Brightness":
            self.values[setting] = (current_val + 10) % 110
        elif setting == "Timeout":
            self.values[setting] = min(current_val + 5, 300) if current_val < 300 else 5
        elif setting == "Scan Delay":
            delays = [500, 1000, 2000, 5000, 10000]
            try:
                idx = delays.index(current_val)
                self.values[setting] = delays[(idx + 1) % len(delays)]
            except ValueError:
                self.values[setting] = delays[0]
        elif setting == "API Port":
            self.values[setting] = current_val + 1 if current_val < 9999 else 8080
            
        # String selections
        elif setting == "Audio Device":
            devices = ["default", "hw:0,0", "hw:1,0", "pulse"]
            try:
                idx = devices.index(current_val)
                self.values[setting] = devices[(idx + 1) % len(devices)]
            except ValueError:
                self.values[setting] = devices[0]
        elif setting == "Color Scheme":
            schemes = ["Default", "High Contrast", "Night Mode"]
            try:
                idx = schemes.index(current_val)
                self.values[setting] = schemes[(idx + 1) % len(schemes)]
            except ValueError:
                self.values[setting] = schemes[0]
        
        # Save to settings
        setting_key = setting.lower().replace(" ", "_")
        self.settings.set(setting_key, self.values[setting])
        logging.info(f"Setting {setting} changed to {self.values[setting]}")
        
    def _execute_action(self, action):
        """Execute a menu action"""
        try:
            # OP25 Management actions
            if action == "Start OP25":
                self._start_op25()
            elif action == "Stop OP25":
                self._stop_op25()
            elif action == "Restart OP25":
                self._restart_op25()
            elif action == "OP25 Config":
                self._show_op25_config()
            elif action == "OP25 Logs":
                self._show_op25_logs()
            elif action == "Create OP25 Config":
                self._create_op25_config()
            # System actions
            elif action == "Reboot System":
                self._reboot_system()
            elif action == "Reset Settings":
                self._reset_settings()
            elif action == "System Status":
                self._show_system_status()
            elif action == "OP25 Status":
                self._show_op25_status()
            elif action == "Network Info":
                self._show_network_info()
            elif action == "Disk Usage":
                self._show_disk_usage()
            elif action == "Talkgroups":
                self._show_talkgroups()
                
        except Exception as e:
            logging.error(f"Error executing action {action}: {e}")
            self.display.show_message("Error", f"Action failed: {action}")
            
    def _start_op25(self):
        """Start OP25 process"""
        if not self.op25_manager:
            self.display.show_message("Error", "OP25 manager not available")
            time.sleep(2)
            return
            
        self.display.show_message("OP25", "Starting...")
        if self.op25_manager.start():
            self.display.show_message("OP25", "Started successfully")
        else:
            self.display.show_message("OP25", "Start failed")
        time.sleep(2)
        
    def _stop_op25(self):
        """Stop OP25 process"""
        if not self.op25_manager:
            self.display.show_message("Error", "OP25 manager not available")
            time.sleep(2)
            return
            
        self.display.show_message("OP25", "Stopping...")
        if self.op25_manager.stop():
            self.display.show_message("OP25", "Stopped successfully")
        else:
            self.display.show_message("OP25", "Stop failed")
        time.sleep(2)
        
    def _restart_op25(self):
        """Restart OP25 process"""
        if not self.op25_manager:
            self.display.show_message("Error", "OP25 manager not available")
            time.sleep(2)
            return
            
        self.display.show_message("OP25", "Restarting...")
        if self.op25_manager.restart():
            self.display.show_message("OP25", "Restarted successfully")
        else:
            self.display.show_message("OP25", "Restart failed")
        time.sleep(2)
        
    def _reboot_system(self):
        """Reboot the system"""
        self.display.show_message("System", "Rebooting in 5 seconds...")
        time.sleep(5)
        try:
            subprocess.run(["sudo", "reboot"], check=True)
        except subprocess.CalledProcessError:
            self.display.show_message("System", "Reboot failed")
            
    def _reset_settings(self):
        """Reset all settings to defaults"""
        self.display.show_message("Settings", "Resetting to defaults...")
        self.settings.reset_to_defaults()
        # Reload values from settings
        for key in self.values:
            setting_key = key.lower().replace(" ", "_")
            self.values[key] = self.settings.get(setting_key, self.values[key])
        self.display.show_message("Settings", "Reset complete")
        time.sleep(2)
        
    def _show_system_status(self):
        """Show system status information"""
        try:
            cpu_percent = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            uptime = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
            
            status = f"CPU: {cpu_percent:.1f}%\n"
            status += f"RAM: {memory.percent:.1f}%\n"
            status += f"Uptime: {str(uptime).split('.')[0]}"
            
            self.display.show_message("System Status", status)
        except Exception as e:
            self.display.show_message("Error", f"Cannot get status: {e}")
        time.sleep(3)
        
    def _show_op25_status(self):
        """Show OP25 connection and process status"""
        message_lines = []
        
        # Process status
        if self.op25_manager:
            status = self.op25_manager.get_status()
            if status["running"]:
                message_lines.append(f"Process: Running (PID {status['pid']})")
                message_lines.append(f"CPU: {status.get('cpu_percent', 0):.1f}%")
                message_lines.append(f"RAM: {status.get('memory_mb', 0):.1f}MB")
                message_lines.append(f"Restarts: {status['restart_count']}")
            else:
                message_lines.append("Process: Not running")
        else:
            message_lines.append("Process: Manager unavailable")
            
        # Connection status
        if self.op25_client:
            conn_status = self.op25_client.get_connection_status()
            is_connected = self.op25_client.is_connected()
            message_lines.append(f"API: {conn_status}")
            message_lines.append(f"Errors: {self.op25_client.connection_errors}")
        else:
            message_lines.append("API: Client unavailable")
            
        message = "\n".join(message_lines)
        self.display.show_message("OP25 Status", message)
        time.sleep(4)
        
    def _show_op25_config(self):
        """Show OP25 configuration"""
        config_lines = []
        config_lines.append(f"Path: {self.settings.get('op25_path', 'Not set')}")
        config_lines.append(f"Config: {self.settings.get('op25_config', 'Not set')}")
        config_lines.append(f"Web Port: {self.settings.get('op25_web_port', 8080)}")
        config_lines.append(f"Gain: {self.settings.get('op25_gain', 'auto')}")
        config_lines.append(f"Auto Restart: {self.settings.get('op25_auto_restart', True)}")
        
        message = "\n".join(config_lines)
        self.display.show_message("OP25 Config", message)
        time.sleep(4)
        
    def _show_op25_logs(self):
        """Show recent OP25 logs"""
        if not self.op25_manager:
            self.display.show_message("Error", "OP25 manager not available")
            time.sleep(2)
            return
            
        logs = self.op25_manager.get_logs(10)
        if logs:
            # Show last few log lines
            message = "\n".join(logs[-3:]) if len(logs) >= 3 else "\n".join(logs)
            self.display.show_message("OP25 Logs", message)
        else:
            self.display.show_message("OP25 Logs", "No logs available")
        time.sleep(4)
        
    def _create_op25_config(self):
        """Create default OP25 configuration files"""
        if not self.op25_manager:
            self.display.show_message("Error", "OP25 manager not available")
            time.sleep(2)
            return
            
        self.display.show_message("OP25", "Creating config files...")
        if self.op25_manager.create_default_config():
            self.display.show_message("OP25", "Config files created")
        else:
            self.display.show_message("OP25", "Config creation failed")
        time.sleep(2)
        
    def _show_network_info(self):
        """Show network information"""
        try:
            import socket
            hostname = socket.gethostname()
            ip = socket.gethostbyname(hostname)
            
            message = f"Host: {hostname}\nIP: {ip}"
            self.display.show_message("Network Info", message)
        except Exception as e:
            self.display.show_message("Network Error", str(e))
        time.sleep(3)
        
    def _show_disk_usage(self):
        """Show disk usage information"""
        try:
            disk = psutil.disk_usage('/')
            total_gb = disk.total / (1024**3)
            used_gb = disk.used / (1024**3)
            free_gb = disk.free / (1024**3)
            
            message = f"Total: {total_gb:.1f}GB\n"
            message += f"Used: {used_gb:.1f}GB\n"
            message += f"Free: {free_gb:.1f}GB"
            
            self.display.show_message("Disk Usage", message)
        except Exception as e:
            self.display.show_message("Disk Error", str(e))
        time.sleep(3)
        
    def _show_talkgroups(self):
        """Show talkgroup information"""
        if self.talkgroup_manager:
            talkgroups = self.talkgroup_manager.get_all_talkgroups()
            count = len(talkgroups)
            
            message = f"Total TGs: {count}\n"
            if count > 0:
                high_priority = sum(1 for tg in talkgroups.values() if tg.get('priority') == 'High')
                message += f"High Priority: {high_priority}\n"
                message += f"Loaded from file"
            else:
                message += "No talkgroups loaded"
                
            self.display.show_message("Talkgroups", message)
        else:
            self.display.show_message("Talkgroups", "Talkgroup manager not available")
        time.sleep(3)

    def _render_menu(self):
        """Render the current menu on display"""
        menu_items = self.current_menu()
        
        # Use OLED display for menu
        if hasattr(self.display, 'show_menu_on_oled'):
            self.display.show_menu_on_oled(menu_items, self.current_index)
        else:
            # Fallback to basic OLED rendering
            if (hasattr(self.display, 'oled') and 
                self.display.oled_available and 
                self.display.oled is not None):
                self.display.oled.fill(0)
                
                # Show menu title
                title = self.menu_stack[-1]
                self.display.oled.text(title[:21], 0, 0, 1)
                
                # Show menu items (up to 5 items visible)
                start_idx = max(0, self.current_index - 2)
                end_idx = min(len(menu_items), start_idx + 5)
                
                for i, item_idx in enumerate(range(start_idx, end_idx)):
                    item = menu_items[item_idx]
                    prefix = "> " if item_idx == self.current_index else "  "
                    
                    # Add value display for settings
                    if item in self.values:
                        val = self.values[item]
                        if isinstance(val, bool):
                            val_str = "ON" if val else "OFF"
                        else:
                            val_str = str(val)
                        text = f"{prefix}{item}: {val_str}"
                    else:
                        text = f"{prefix}{item}"
                    
                    self.display.oled.text(text[:21], 0, (i + 1) * 10, 1)
                
        self.display.oled.show()

    def current_menu(self):
        """Get the current menu items"""
        return self.menus[self.menu_stack[-1]]