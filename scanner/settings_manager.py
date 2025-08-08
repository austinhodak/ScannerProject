# --- settings_manager.py ---
import json
import os
import logging

class SettingsManager:
    def __init__(self, filepath):
        self.filepath = filepath
        self.settings = {}
        self.defaults = {
            "volume_level": 75,
            "mute": False,
            "recording": False,
            "brightness": 75,
            "timeout": 30,
            "show_debug": False,
            "api_port": 8080,
            "web_interface": True,
            "auto_scan": True,
            "priority_scan": False,
            "scan_delay": 2000,
            "op25_host": "127.0.0.1",
            "op25_port": 8080,
            "display_timeout": 30,
            "backlight_brightness": 75,
            "audio_device": "default",
            "recording_path": "/tmp/recordings",
            "log_level": "INFO",
            "op25_path": "/home/ahodak/op25/op25/gr-op25_repeater/apps",
            "op25_config": "cfg.json",
            "op25_log_level": 1,
            "op25_freq_error": 0,
            "op25_fine_tune": 0.0,
            "op25_gain": "auto",
            "op25_web_port": 8080,
            "op25_web_host": "127.0.0.1",
            "op25_auto_restart": True,
            "op25_auto_start": False,
            "system_name": "SCANNER",
            "display_rotation": 0
        }
        self.load()

    def load(self):
        """Load settings from file, creating defaults if needed"""
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, 'r') as f:
                    loaded_settings = json.load(f)
                    
                # Start with defaults and update with loaded values
                self.settings = self.defaults.copy()
                self.settings.update(loaded_settings)
                
                # Save back to ensure all defaults are present
                if len(loaded_settings) != len(self.settings):
                    self.save()
                    
            except (json.JSONDecodeError, IOError) as e:
                logging.error(f"Error loading settings: {e}")
                self.settings = self.defaults.copy()
                self.save()
        else:
            self.settings = self.defaults.copy()
            self.save()

    def get(self, key, default=None):
        """Get setting value with fallback to default"""
        return self.settings.get(key, self.defaults.get(key, default))

    def set(self, key, value):
        """Set setting value and save immediately"""
        self.settings[key] = value
        self.save()
        
    def update(self, updates):
        """Update multiple settings at once"""
        self.settings.update(updates)
        self.save()

    def save(self):
        """Save settings to file"""
        try:
            # Ensure directory exists (only if filepath contains a directory)
            dir_path = os.path.dirname(self.filepath)
            if dir_path:  # Only create directory if there is a directory path
                os.makedirs(dir_path, exist_ok=True)
            
            with open(self.filepath, 'w') as f:
                json.dump(self.settings, f, indent=4)
        except IOError as e:
            logging.error(f"Error saving settings: {e}")
            
    def reset_to_defaults(self):
        """Reset all settings to defaults"""
        self.settings = self.defaults.copy()
        self.save()
        
    def get_all(self):
        """Get all settings as a dictionary"""
        return self.settings.copy()