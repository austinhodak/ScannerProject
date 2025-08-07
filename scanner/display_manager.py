# --- display_manager.py ---
from PIL import Image, ImageDraw, ImageFont
import os
from datetime import datetime
import board
import busio
import adafruit_ssd1306
import logging

class DisplayManager:
    def __init__(self, talkgroup_manager=None):
        # TFT settings
        self.width = 480
        self.height = 320
        self.image_path = "/tmp/scanner_screen.jpg"
        self.talkgroup_manager = talkgroup_manager
        
        # Initialize fonts with fallbacks (only for TFT display)
        self.font_small = self._load_font(size=12)
        self.font_med = self._load_font(size=16)
        self.font_large = self._load_font(size=24)
        
        # Color scheme
        self.colors = {
            'background': 'black',
            'text': 'white',
            'header': 'orange',
            'department': 'yellow',
            'status': 'blue',
            'high_priority': 'red',
            'medium_priority': 'orange',
            'low_priority': 'green'
        }

        # Initialize OLED display (simple approach like working code)
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            self.oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)
            self.oled.fill(0)
            self.oled.show()
            self.oled_available = True
            logging.info("OLED display initialized successfully")
        except Exception as e:
            logging.warning(f"OLED display not available: {e}")
            self.oled_available = False
            self.oled = None
            
    def _load_font(self, size=16):
        """Load font with fallbacks"""
        font_paths = [
            f"/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            f"/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            f"/System/Library/Fonts/Arial.ttf",  # macOS
            f"/Windows/Fonts/arial.ttf"  # Windows
        ]
        
        for font_path in font_paths:
            try:
                if os.path.exists(font_path):
                    return ImageFont.truetype(font_path, size)
            except Exception as e:
                logging.debug(f"Could not load font {font_path}: {e}")
                
        # Fallback to default
        try:
            return ImageFont.load_default()
        except:
            return None

    def update(self, system, freq, tgid, extra, settings):
        self.update_tft(system, freq, tgid, extra, settings)
        if self.oled_available:
            self.update_oled(system, freq, tgid, extra)

    def update_tft(self, system, freq, tgid, extra, settings):
        """Update TFT display with current scanner information"""
        try:
            img = Image.new('RGB', (self.width, self.height), color=self.colors['background'])
            draw = ImageDraw.Draw(img)

            # Header with timestamp
            now = datetime.now().strftime("%b%d %H:%M:%S")
            draw.rectangle((0, 0, self.width, 30), fill=self.colors['background'])
            draw.text((self.width - 120, 5), now, fill=self.colors['text'], font=self.font_small)
            
            # Connection status indicator
            status_color = self.colors['high_priority'] if system == "Offline" else self.colors['medium_priority']
            draw.rectangle((10, 5, 20, 25), fill=status_color)

            # System name bar
            draw.rectangle((0, 30, self.width, 70), fill=self.colors['header'])
            system_text = system[:35] if system else "No System"
            draw.text((10, 40), system_text, fill="black", font=self.font_large)

            # Department/Agency bar
            department = "Scanning..."
            dept_color = self.colors['department']
            
            if tgid and self.talkgroup_manager:
                tg_info = self.talkgroup_manager.lookup(tgid)
                if tg_info:
                    department = tg_info['department']
                    description = tg_info['description']
                    if description:
                        department = f"{department} - {description}"
                    
                    # Color code by priority
                    priority = tg_info.get('priority', 'Medium')
                    if priority == 'High':
                        dept_color = self.colors['high_priority']
                    elif priority == 'Medium':
                        dept_color = self.colors['medium_priority']
                    else:
                        dept_color = self.colors['low_priority']
                else:
                    department = f"TGID {tgid} - Unknown"

            draw.rectangle((0, 70, self.width, 110), fill=dept_color)
            dept_text = department[:40] if len(department) > 40 else department
            draw.text((10, 80), dept_text, fill="black", font=self.font_large)

            # Talkgroup and frequency info
            if tgid:
                if extra.get('active'):
                    # Active transmission - show source address
                    srcaddr = extra.get('srcaddr', 0)
                    tag = f"TGID: {tgid} | SRC: {srcaddr}"
                    if extra.get('encrypted'):
                        tag += " [ENC]"
                else:
                    # Recent activity
                    last_activity = extra.get('last_activity')
                    if last_activity:
                        tag = f"TGID: {tgid} (last: {last_activity}s)"
                    else:
                        tag = f"TGID: {tgid}"
            else:
                tag = "Scanning..."
                
            draw.text((10, 120), tag, fill=self.colors['text'], font=self.font_large)

            freq_text = f"Freq: {freq:.4f} MHz" if freq else "Freq: --"
            draw.text((10, 155), freq_text, fill=self.colors['text'], font=self.font_med)

            # System info
            nac = extra.get('nac', '--')
            wacn = extra.get('wacn', '--')
            sysid = extra.get('sysid', '--')
            
            site_info = f"NAC: {nac} | WACN: {wacn} | SYS: {sysid}"
            if extra.get('error'):
                site_info += f" | ERR: {extra.get('error')}"
            draw.text((10, 175), site_info, fill=self.colors['text'], font=self.font_med)
            
            # Additional system info
            if settings.get('show_debug'):
                debug_info = f"Auto: {'ON' if settings.get('auto_scan') else 'OFF'} | "
                debug_info += f"Priority: {'ON' if settings.get('priority_scan') else 'OFF'}"
                draw.text((10, 195), debug_info, fill=self.colors['text'], font=self.font_small)

            # Status bar
            draw.rectangle((0, self.height - 40, self.width, self.height), fill=self.colors['status'])
            volume = settings.get('volume_level', 0)
            mute_status = "MUTE" if settings.get('mute') else f"VOL:{volume}"
            rec_status = "REC" if settings.get('recording') else ""
            status_text = f"{mute_status} | SQL:2"
            if rec_status:
                status_text += f" | {rec_status}"
            draw.text((10, self.height - 30), status_text, fill=self.colors['text'], font=self.font_med)

            # Save and display
            img.save(self.image_path)
            
            # Only try to display on framebuffer if it exists
            if os.path.exists("/dev/fb1"):
                os.system(f"sudo fbi -T 1 -d /dev/fb1 -noverbose -a {self.image_path} > /dev/null 2>&1")
            else:
                logging.debug("Framebuffer /dev/fb1 not available")
                
        except Exception as e:
            logging.error(f"Error updating TFT display: {e}")

    def update_oled(self, system, freq, tgid, extra=None):
        """Update OLED display with basic scanner information"""
        if not self.oled_available or self.oled is None:
            return
            
        if extra is None:
            extra = {}
            
        try:
            self.oled.fill(0)
            
            # System name (truncated)
            system_text = system[:20] if system else "No System"
            self.oled.text(system_text, 0, 0, 1)
            
            if tgid:
                # Get department name if available
                department = "Unknown"
                if self.talkgroup_manager:
                    dept_info = self.talkgroup_manager.get_department(tgid)
                    if dept_info:
                        department = dept_info[:12]  # Truncate for OLED
                
                # Show transmission status
                if extra.get('active'):
                    status_char = "*" if not extra.get('encrypted') else "E"
                    self.oled.text(f"{status_char}TG:{tgid} {department}", 0, 10, 1)
                else:
                    self.oled.text(f"TG:{tgid} {department}", 0, 10, 1)
                
                if freq:
                    self.oled.text(f"{freq:.4f} MHz", 0, 20, 1)
            else:
                self.oled.text("Scanning...", 0, 10, 1)
                
            # Show connection and activity status
            if system != "Offline":
                if extra.get('active'):
                    status = "ACTIVE"
                elif extra.get('last_activity'):
                    status = f"IDLE {extra.get('last_activity')}s"
                else:
                    status = "ONLINE"
            else:
                status = "OFFLINE"
            self.oled.text(status, 0, 30, 1)
            
            self.oled.show()
        except Exception as e:
            logging.error(f"Error updating OLED display: {e}")

    def show_menu_on_oled(self, menu_items, selected_index):
        """Display menu on OLED"""
        if not self.oled_available or self.oled is None:
            return
            
        try:
            self.oled.fill(0)
            
            # Show up to 6 menu items
            start_idx = max(0, selected_index - 2)
            end_idx = min(len(menu_items), start_idx + 6)
            
            for i, item_idx in enumerate(range(start_idx, end_idx)):
                item = menu_items[item_idx]
                prefix = "> " if item_idx == selected_index else "  "
                text = f"{prefix}{item}"[:21]  # Truncate for display
                self.oled.text(text, 0, i * 10, 1)
                
            self.oled.show()
        except Exception as e:
            logging.error(f"Error showing menu on OLED: {e}")

    def clear(self):
        """Clear both displays"""
        try:
            if os.path.exists("/dev/fb1"):
                os.system("sudo fbi -T 1 -d /dev/fb1 -noverbose -a /dev/null > /dev/null 2>&1")
            
            if self.oled_available and self.oled is not None:
                self.oled.fill(0)
                self.oled.show()
        except Exception as e:
            logging.error(f"Error clearing displays: {e}")
            
    def show_message(self, title, message, duration=3):
        """Show a temporary message on both displays"""
        try:
            # TFT message
            img = Image.new('RGB', (self.width, self.height), color=self.colors['background'])
            draw = ImageDraw.Draw(img)
            
            # Center the message
            draw.text((50, 100), title, fill=self.colors['header'], font=self.font_large)
            draw.text((50, 150), message, fill=self.colors['text'], font=self.font_med)
            
            img.save(self.image_path)
            if os.path.exists("/dev/fb1"):
                os.system(f"sudo fbi -T 1 -d /dev/fb1 -noverbose -a {self.image_path} > /dev/null 2>&1")
            
            # OLED message
            if self.oled_available and self.oled is not None:
                self.oled.fill(0)
                self.oled.text(title[:21], 0, 10, 1)
                self.oled.text(message[:21], 0, 30, 1)
                self.oled.show()
                
        except Exception as e:
            logging.error(f"Error showing message: {e}")