# --- display_manager.py ---
from PIL import Image, ImageDraw, ImageFont
import os
from datetime import datetime
import time
import subprocess
import re
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
        self._last_tft_signature = None
        
        # Initialize fonts with fallbacks (only for TFT display)
        self.font_small = self._load_font(size=12)
        self.font_med = self._load_font(size=16)
        self.font_large = self._load_font(size=24)
        
        # Initialize scrolling state for OLED
        self.scroll_offset = 0
        self.scroll_direction = 1
        self.last_scroll_time = 0
        self.scroll_delay = 0.5  # Seconds between scroll updates
        self.current_scroll_text = ""
        # Volume cache (reduce shell calls)
        self._vol_cache = 0
        self._vol_last_time = 0.0
        # TFT push throttling
        self._last_tft_push = 0.0
        self._tft_min_interval = 1.0  # seconds between framebuffer pushes
        self._framebuffer_available = os.path.exists("/dev/fb1")
        
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
    
    def _format_signal_bars(self, extra) -> str:
        """Return signal bars like |||| using signal_quality in range [0, 1]."""
        quality = extra.get('signal_quality', None)
        if quality is None:
            bars = 0
        else:
            try:
                q = float(quality)
            except Exception:
                q = 0.0
            # Clamp to [0,1]
            if q < 0.0:
                q = 0.0
            elif q > 1.0:
                q = 1.0
            # Map to 0..4 bars with simple thresholds
            if q >= 0.80:
                bars = 4
            elif q >= 0.60:
                bars = 3
            elif q >= 0.40:
                bars = 2
            elif q >= 0.20:
                bars = 1
            else:
                bars = 0
        return ("|" * bars).ljust(4, " ")

    def _get_system_volume_percent(self, fallback: int = 0) -> int:
        """Return current system output volume percent using PulseAudio or ALSA.
        Caches for ~1s to avoid frequent shell calls.
        """
        now = time.time()
        if now - self._vol_last_time < 1.0:
            return self._vol_cache
        vol = fallback
        # Try PulseAudio (pactl)
        try:
            out = subprocess.check_output(
                ["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=0.4,
            )
            m = re.search(r"(\d{1,3})%", out)
            if m:
                vol = int(m.group(1))
        except Exception:
            # Try ALSA (amixer)
            try:
                out = subprocess.check_output(
                    ["amixer", "get", "Master"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=0.4,
                )
                m = re.search(r"\[(\d{1,3})%\]", out)
                if m:
                    vol = int(m.group(1))
            except Exception:
                pass
        vol = max(0, min(100, int(vol)))
        self._vol_cache = vol
        self._vol_last_time = now
        return vol

    def _get_volume_percent(self, settings) -> int:
        """Return current system volume percentage; fallback to settings volume_level."""
        fallback = 0
        try:
            if settings is not None:
                fallback = int(settings.get('volume_level', 0))
        except Exception:
            fallback = 0
        return self._get_system_volume_percent(fallback)

    def _format_oled_header(self, extra, settings) -> str:
        """Header: SIDxx Vnn L |||| (no brackets, <= 20 chars)"""
        sysid = extra.get('sysid')
        sid = f"SID {sysid}" if sysid is not None else "SID --"
        vol_num = self._get_volume_percent(settings)
        vol = f"V{vol_num}"
        lock = "L " if extra.get('signal_locked') else "  "
        sig = self._format_signal_bars(extra)
        header = f"{sid} {vol} {lock}{sig}"
        return header[:20]

    def _draw_lock_icon(self, x: int, y: int):
        """Draw a tiny 6x8 padlock icon at (x,y) on the OLED (mono)."""
        try:
            # Body
            # outer rect 6x5 starting at y+3
            if hasattr(self.oled, 'rect'):
                self.oled.rect(x, y + 3, 6, 5, 1)
                # keyhole
                self.oled.pixel(x + 3, y + 5, 1)
            else:
                # fallback with pixels
                for dx in range(6):
                    self.oled.pixel(x + dx, y + 3, 1)
                    self.oled.pixel(x + dx, y + 7, 1)
                for dy in range(3, 8):
                    self.oled.pixel(x, y + dy, 1)
                    self.oled.pixel(x + 5, y + dy, 1)
                self.oled.pixel(x + 3, y + 5, 1)
            # Shackle (u-shape)
            self.oled.pixel(x + 1, y + 2, 1)
            self.oled.pixel(x + 4, y + 2, 1)
            self.oled.pixel(x + 1, y + 1, 1)
            self.oled.pixel(x + 4, y + 1, 1)
            for dx in range(2, 4):
                self.oled.pixel(x + dx, y + 0, 1)
        except Exception:
            # If drawing fails, ignore
            pass

    def _draw_oled_header(self, extra, settings):
        """Draw header components with a true icon for lock and text bars."""
        # Left segment: SID + volume
        sysid = extra.get('sysid')
        sid = f"SID {sysid}" if sysid is not None else "SID --"
        vol_num = self._get_volume_percent(settings)
        left = f"{sid} V{vol_num} "
        # Draw left text
        self.oled.text(left[:20], 0, 0, 1)
        x = min(len(left), 20) * 6  # approximate 6px per char
        # Lock/icon and bars
        if extra.get('signal_locked') and x <= 120 - 8:
            self._draw_lock_icon(x, 0)
            x += 8
        bars = self._format_signal_bars(extra)
        if x < 120:
            self.oled.text(bars[: max(0, (120 - x) // 6)], x, 0, 1)
            
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
    
    def _get_scrolling_text(self, text, max_width=20):
        """Get scrolling text if text is longer than max_width"""
        import time
        
        if len(text) <= max_width:
            return text
            
        # Check if enough time has passed for next scroll step
        current_time = time.time()
        if current_time - self.last_scroll_time < self.scroll_delay:
            # Return current position
            if hasattr(self, 'current_scroll_text') and self.current_scroll_text:
                return self.current_scroll_text[:max_width]
            else:
                return text[:max_width]
        
        # Update scroll position
        self.last_scroll_time = current_time
        
        # Add padding to create smooth scrolling
        padded_text = text + "   "  # 3 spaces padding
        text_len = len(padded_text)
        
        # Calculate scroll position
        if text_len <= max_width:
            scrolled_text = padded_text
        else:
            # Scroll back and forth
            max_offset = text_len - max_width
            
            if self.scroll_direction == 1:  # Scrolling right
                self.scroll_offset += 1
                if self.scroll_offset >= max_offset:
                    self.scroll_direction = -1  # Start scrolling back
                    # Pause at the end for readability
                    self.scroll_delay = 1.0
                else:
                    self.scroll_delay = 0.5
            else:  # Scrolling left
                self.scroll_offset -= 1
                if self.scroll_offset <= 0:
                    self.scroll_direction = 1  # Start scrolling forward
                    # Pause at the beginning for readability
                    self.scroll_delay = 1.0
                else:
                    self.scroll_delay = 0.5
            
            scrolled_text = padded_text[self.scroll_offset:self.scroll_offset + max_width]
        
        self.current_scroll_text = scrolled_text
        return scrolled_text

    def update(self, system, freq, tgid, extra, settings):
        self.update_tft(system, freq, tgid, extra, settings)
        if self.oled_available:
            self.update_oled(system, freq, tgid, extra, settings)

    def update_tft(self, system, freq, tgid, extra, settings):
        """Update TFT display with current scanner information"""
        try:
            # Precompute all text content for signature/caching
            now = datetime.now().strftime("%b%d %H:%M:%S")
            system_text = system[:35] if system else "No System"

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

            dept_text = department[:40] if len(department) > 40 else department

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
                
            freq_text = f"Freq: {freq:.4f} MHz" if freq else "Freq: --"

            # System info
            nac = extra.get('nac', '--')
            wacn = extra.get('wacn', '--')
            sysid = extra.get('sysid', '--')
            
            site_info = f"NAC: {nac} | WACN: {wacn} | SYS: {sysid}"
            if extra.get('error'):
                site_info += f" | ERR: {extra.get('error')}"
            
            # Additional system info
            if settings.get('show_debug'):
                debug_info = f"Auto: {'ON' if settings.get('auto_scan') else 'OFF'} | "
                debug_info += f"Priority: {'ON' if settings.get('priority_scan') else 'OFF'}"

            # Status bar
            volume = settings.get('volume_level', 0)
            mute_status = "MUTE" if settings.get('mute') else f"VOL:{volume}"
            rec_status = "REC" if settings.get('recording') else ""
            status_text = f"{mute_status} | SQL:2"
            if rec_status:
                status_text += f" | {rec_status}"

            # Build a signature of visible content
            signature = (now, system_text, dept_text, tag, freq_text, site_info, status_text)
            if signature == self._last_tft_signature:
                # No visual changes; skip costly redraw/push
                return
            self._last_tft_signature = signature

            # Proceed to draw only when content changed
            img = Image.new('RGB', (self.width, self.height), color=self.colors['background'])
            draw = ImageDraw.Draw(img)

            # Header with timestamp
            draw.rectangle((0, 0, self.width, 30), fill=self.colors['background'])
            draw.text((self.width - 120, 5), now, fill=self.colors['text'], font=self.font_small)
            # Connection status indicator
            status_color = self.colors['high_priority'] if system == "Offline" else self.colors['medium_priority']
            draw.rectangle((10, 5, 20, 25), fill=status_color)
            # System name bar
            draw.rectangle((0, 30, self.width, 70), fill=self.colors['header'])
            draw.text((10, 40), system_text, fill="black", font=self.font_large)
            # Department/Agency bar
            draw.rectangle((0, 70, self.width, 110), fill=dept_color)
            draw.text((10, 80), dept_text, fill="black", font=self.font_large)
            # Talkgroup/Freq
            draw.text((10, 120), tag, fill=self.colors['text'], font=self.font_large)
            draw.text((10, 155), freq_text, fill=self.colors['text'], font=self.font_med)
            # System info
            draw.text((10, 175), site_info, fill=self.colors['text'], font=self.font_med)
            # Debug info
            if settings.get('show_debug'):
                draw.text((10, 195), debug_info, fill=self.colors['text'], font=self.font_small)
            # Status bar
            draw.rectangle((0, self.height - 40, self.width, self.height), fill=self.colors['status'])
            draw.text((10, self.height - 30), status_text, fill=self.colors['text'], font=self.font_med)

            # Save
            img.save(self.image_path)
            
            # Throttled framebuffer update to avoid spawning many fbi processes
            if self._framebuffer_available:
                now = time.time()
                if now - self._last_tft_push >= self._tft_min_interval:
                    self._last_tft_push = now
                    os.system(f"sudo fbi -T 1 -d /dev/fb1 -noverbose -a {self.image_path} > /dev/null 2>&1")
            else:
                logging.debug("Framebuffer /dev/fb1 not available")
                
        except Exception as e:
            logging.error(f"Error updating TFT display: {e}")

    def update_oled(self, system, freq, tgid, extra=None, settings=None):
        """Update OLED display with transmission information"""
        if not self.oled_available or self.oled is None:
            return
            
        if extra is None:
            extra = {}
            
        try:
            self.oled.fill(0)
            
            # Check if there's an active transmission with a radio ID
            srcaddr = extra.get('srcaddr')
            active_transmission = extra.get('active') and srcaddr is not None
            
            if active_transmission and tgid:
                # ACTIVE TRANSMISSION - Show 3-line format
                
                # Line 1: Custom header
                # Draw composed header: SID/VOL + lock icon + bars
                self._draw_oled_header(extra, settings)
                
                # Line 2: TALKGROUP (get full description with scrolling)
                talkgroup_text = f"TG {tgid}"
                if self.talkgroup_manager:
                    tg_info = self.talkgroup_manager.lookup(tgid)
                    if tg_info:
                        label = tg_info.get('name') or tg_info.get('description')
                        if label:
                            talkgroup_text = self._get_scrolling_text(label, 20)
                        elif tg_info.get('department'):
                            dept_text = f"{tg_info['department']} {tgid}"
                            talkgroup_text = self._get_scrolling_text(dept_text, 20)
                        
                self.oled.text(talkgroup_text, 0, 10, 1)
                
                # Line 3: RADIO ID
                radio_text = f"RADIO {srcaddr}"
                self.oled.text(radio_text, 0, 20, 1)
                
                # Lines 4-6: Reserved for future dual SDR setup
                # (Currently empty but available)
                
            else:
                # NO ACTIVE TRANSMISSION - Show scanning status
                
                # Line 1: Custom header
                # Draw composed header: SID/VOL + lock icon + bars
                self._draw_oled_header(extra, settings)
                
                # Line 2: Scanning status with scrolling
                if tgid:
                    if self.talkgroup_manager:
                        tg_info = self.talkgroup_manager.lookup(tgid)
                        if tg_info:
                            last_tg = tg_info.get('name') or tg_info.get('description') or f"TG {tgid}"
                        else:
                            last_tg = f"TG {tgid}"
                    else:
                        last_tg = f"TG {tgid}"
                    
                    # Add "LAST: " prefix and use scrolling
                    last_text = f"LAST: {last_tg}"
                    scrolled_last = self._get_scrolling_text(last_text, 20)
                    self.oled.text(scrolled_last, 0, 10, 1)
                else:
                    self.oled.text("SCANNING...", 0, 10, 1)
                
                # Line 3: Connection status
                if system != "Offline":
                    if extra.get('last_activity'):
                        status = f"IDLE {extra.get('last_activity')}s"
                    else:
                        status = "MONITORING"
                else:
                    status = "OFFLINE"
                self.oled.text(status, 0, 20, 1)
            
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