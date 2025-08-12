# --- display_manager.py ---
from PIL import Image, ImageDraw, ImageFont
import os
from datetime import datetime
import time
import subprocess
import re
import logging

# Hardware-specific libraries are optional in dev environments
try:
    import board  # type: ignore
    import busio  # type: ignore
    import adafruit_ssd1306  # type: ignore
except Exception:
    board = None  # type: ignore
    busio = None  # type: ignore
    adafruit_ssd1306 = None  # type: ignore

try:
    import displayio
    from fourwire import FourWire
    import adafruit_st7789
    from adafruit_display_text import label
    import terminalio
    ST7789_AVAILABLE = True
except ImportError:
    try:
        import displayio
        from displayio import FourWire
        import adafruit_st7789
        from adafruit_display_text import label
        import terminalio
        ST7789_AVAILABLE = True
    except ImportError:
        ST7789_AVAILABLE = False

# Try Raspberry Pi-friendly RGB display driver for direct PIL image support
try:
    from adafruit_rgb_display import st7789 as rgb_st7789
    import digitalio

    RGB_ST7789_AVAILABLE = True
except Exception:
    RGB_ST7789_AVAILABLE = False

class DisplayManager:
    def __init__(self, talkgroup_manager=None, rotation=0):
        # ST7789 TFT settings
        self._panel_native_width = 240  # native portrait width
        self._panel_native_height = 320  # native portrait height
        self.image_path = "/tmp/scanner_screen.jpg"
        self.talkgroup_manager = talkgroup_manager
        self._last_tft_signature = None
        self.rotation = (
            rotation if rotation in [0, 90, 180, 270] else 180
        )  # Rotation angle
        # Compute current logical width/height based on rotation
        if self.rotation in (0, 180):
            self.width = self._panel_native_width
            self.height = self._panel_native_height
        else:
            self.width = self._panel_native_height
            self.height = self._panel_native_width

        # Initialize fonts with fallbacks (only for TFT display / PIL rendering)
        # Defaults used until apply_font_settings() is called with user settings
        self.font_small = self._load_font(size=12)
        self.font_med = self._load_font(size=16)
        self.font_large = self._load_font(size=24)
        # Optional style-specific fonts
        self._font_regular_small = self.font_small
        self._font_regular_med = self.font_med
        self._font_regular_large = self.font_large
        self._font_bold_small = self.font_small
        self._font_bold_med = self.font_med
        self._font_bold_large = self.font_large
        self._font_condensed_tgid = self.font_large
        # Pixel-small font for crisp UI elements (time/vol)
        try:
            self._font_pixel_small = ImageFont.load_default()
        except Exception:
            self._font_pixel_small = self.font_small
        # Font registry/cache to allow explicit font selection by name
        self._font_cache = {}
        self._font_search_dirs = [
            "/usr/share/fonts/truetype/dejavu",
            "/usr/share/fonts/truetype/liberation",
            "/usr/share/fonts/truetype",
            "/usr/share/fonts",
        ]
        try:
            self._scan_available_fonts()
        except Exception:
            self._font_index = {}
            self._font_available_names = []

        # Initialize scrolling state for OLED
        self.scroll_offset = 0
        self.scroll_direction = 1
        self.last_scroll_time = 0
        self.scroll_delay = 0.5  # Seconds between scroll updates (will be overridden by settings)
        self.current_scroll_text = ""

        # OLED refresh rate control
        self._last_oled_update = 0.0
        self._oled_min_interval = 0.05  # default 20 Hz (1/20 = 0.05)
        self._oled_error_count = 0
        self._oled_disabled_until = 0.0
        # Volume cache (reduce shell calls)
        self._vol_cache = 0
        self._vol_last_time = 0.0
        self._vol_poll_interval = 1.0  # seconds between actual system volume polls
        self._vol_hint_grace = 0.6     # seconds to trust UI hint before polling system
        self._last_user_volume_change_time = 0.0
        # ST7789 TFT throttling/settings
        self._last_tft_push = 0.0
        self._tft_min_interval = (
            0.2  # default seconds between ST7789 updates (reduce flicker)
        )
        # Skip TFT during rapid user interactions
        self._skip_tft_until = 0.0
        # Volume adjustment mode (UI hint)
        self._volume_mode_active = False

        # Initialize ST7789 display
        self.st7789_available = False
        self.st7789_display = None
        # RGB driver (Pi) display
        self.rgb_display_available = False
        self.rgb_display = None
        # ST7789 initialization will be done later via init_st7789() when settings are available

        # Pre-create display elements for better performance
        self._st7789_splash = None
        self._st7789_text_labels = {}
        self._st7789_bars = {}

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
            # Allow higher I2C frequency for faster OLED refresh (default 400kHz)
            i2c_frequency_hz = 400_000
            try:
                # If SettingsManager is used to pass settings, we may not have it here; keep default
                # Caller can later adjust via a setter if needed
                pass
            except Exception:
                pass
            try:
                i2c = busio.I2C(board.SCL, board.SDA, frequency=i2c_frequency_hz)
            except TypeError:
                # Older libraries may not support frequency kwarg
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

        # Ensure OLED state attributes exist even if init failed
        if not hasattr(self, "oled_available"):
            self.oled_available = False
        if not hasattr(self, "oled"):
            self.oled = None

    def _reinit_oled(self) -> bool:
        """Attempt to re-initialize the OLED after an I/O error with backoff."""
        try:
            # Avoid hammering the bus if we're in backoff
            now = time.time()
            if now < getattr(self, "_oled_disabled_until", 0.0):
                return False

            # Try to recreate I2C and the display object
            try:
                i2c = busio.I2C(board.SCL, board.SDA, frequency=400_000)
            except TypeError:
                i2c = busio.I2C(board.SCL, board.SDA)
            oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)
            oled.fill(0)
            oled.show()
            self.oled = oled
            self.oled_available = True
            # Reset error/backoff
            self._oled_error_count = 0
            self._oled_disabled_until = 0.0
            logging.info("OLED reinitialized successfully after error")
            return True
        except Exception as e:
            # Schedule next retry with exponential backoff
            try:
                self._oled_error_count = int(getattr(self, "_oled_error_count", 0)) + 1
                backoff = min(60.0, float(2 ** min(self._oled_error_count, 6)))
            except Exception:
                backoff = 5.0
            self._oled_disabled_until = time.time() + backoff
            self.oled_available = False
            self.oled = None
            logging.warning(f"OLED reinit failed, will retry in {backoff:.1f}s: {e}")
            return False

    def init_st7789(self, settings):
        """Initialize ST7789 display.
        Preference order can be controlled with settings['tft_driver'] in {'rgb','displayio'} (default 'displayio').
        """
        preferred_driver = (
            str(settings.get("tft_driver", "displayio")).lower() if settings else "displayio"
        )

        # Try RGB driver first if requested
        if preferred_driver == "rgb" and RGB_ST7789_AVAILABLE:
            try:
                try:
                    displayio.release_displays()
                except Exception:
                    pass
                spi = board.SPI()
                cs_pin_name = settings.get("st7789_cs_pin", "D5")
                dc_pin_name = settings.get("st7789_dc_pin", "D25")
                rst_pin_name = settings.get("st7789_rst_pin", "D27")
                tft_cs = digitalio.DigitalInOut(getattr(board, cs_pin_name, board.D5))
                tft_dc = digitalio.DigitalInOut(getattr(board, dc_pin_name, board.D25))
                tft_rst = digitalio.DigitalInOut(getattr(board, rst_pin_name, board.D27))
                baudrate = int(settings.get("st7789_baudrate", 48_000_000))
                rotation = int(settings.get("tft_rotation", 180))
                if rotation in (0, 180):
                    self.width = self._panel_native_width
                    self.height = self._panel_native_height
                else:
                    self.width = self._panel_native_height
                    self.height = self._panel_native_width
                self.rotation = rotation
                self.rgb_display = rgb_st7789.ST7789(
                    spi,
                    cs=tft_cs,
                    dc=tft_dc,
                    rst=tft_rst,
                    baudrate=baudrate,
                    width=self.width,
                    height=self.height,
                    x_offset=0,
                    y_offset=0,
                    rotation=rotation,
                )
                self.rgb_display_available = True
                self.st7789_available = True
                logging.info(
                    f"RGB ST7789 initialized ({self.width}x{self.height}) CS:{cs_pin_name} DC:{dc_pin_name} RST:{rst_pin_name} baud:{baudrate} rot:{rotation}"
                )
                return
            except Exception as e:
                logging.warning(f"RGB ST7789 init failed, falling back to displayio: {e}")
                self.rgb_display_available = False
                self.rgb_display = None

        # Fallback: displayio driver
        if ST7789_AVAILABLE:
            try:
                displayio.release_displays()
                spi = board.SPI()
                try:
                    if spi.try_lock():
                        spi.configure(baudrate=24_000_000)
                finally:
                    try:
                        spi.unlock()
                    except Exception:
                        pass
                cs_pin_name = settings.get("st7789_cs_pin", "D5") if settings else "D5"
                dc_pin_name = settings.get("st7789_dc_pin", "D25") if settings else "D25"
                rst_pin_name = settings.get("st7789_rst_pin", "D27") if settings else "D27"
                tft_cs = getattr(board, cs_pin_name, board.D5)
                tft_dc = getattr(board, dc_pin_name, board.D25)
                tft_rst = getattr(board, rst_pin_name, board.D27)
                display_bus = FourWire(
                    spi, command=tft_dc, chip_select=tft_cs, reset=tft_rst
                )
                rotation = int(settings.get("tft_rotation", 180)) if settings else 180
                if rotation in (0, 180):
                    self.width = self._panel_native_width
                    self.height = self._panel_native_height
                else:
                    self.width = self._panel_native_height
                    self.height = self._panel_native_width
                self.rotation = rotation
                self.st7789_display = adafruit_st7789.ST7789(
                    display_bus,
                    width=self.width,
                    height=self.height,
                    rotation=rotation,
                    rowstart=0,
                    colstart=0,
                )
                self.st7789_available = True
                logging.info(
                    f"displayio ST7789 initialized ({self.width}x{self.height}) CS:{cs_pin_name} DC:{dc_pin_name} RST:{rst_pin_name}"
                )
            except Exception as e:
                logging.warning(f"displayio ST7789 init failed: {e}")
                self.st7789_available = False
                self.st7789_display = None
        else:
            logging.warning("No suitable ST7789 driver available")

    # Legacy _init_fast_display removed (unused)

    # Legacy _format_signal_bars removed (unused)

    def _get_system_volume_percent(self, fallback: int = 0) -> int:
        """Return current system output volume percent using PulseAudio or ALSA.
        Caches for ~1s to avoid frequent shell calls.
        """
        now = time.time()
        # During recent user volume interaction, trust UI hint to avoid flicker/mismatch
        if now - getattr(self, "_last_user_volume_change_time", 0.0) < float(getattr(self, "_vol_hint_grace", 0.6)):
            return self._vol_cache
        # Honor configured poll interval to make on-screen volume feel more responsive
        if now - self._vol_last_time < float(getattr(self, "_vol_poll_interval", 1.0)):
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
        """Return current system volume percentage; fallback to settings volume_level.
        Uses recent UI hint for a short grace window to avoid flicker.
        """
        fallback = 0
        try:
            if settings is not None:
                fallback = int(settings.get('volume_level', 0))
        except Exception:
            fallback = 0
        return self._get_system_volume_percent(fallback)

    def set_volume_hint(self, volume_percent: int):
        """Provide a recent volume value to avoid slow system queries.
        This immediately updates the cached value and timestamp.
        """
        try:
            vol = max(0, min(100, int(volume_percent)))
            self._vol_cache = vol
            self._vol_last_time = time.time()
            self._last_user_volume_change_time = self._vol_last_time
        except Exception:
            pass

    def request_oled_refresh(self):
        """Allow next OLED update to proceed immediately (bypass throttle once)."""
        try:
            self._last_oled_update = 0.0
        except Exception:
            pass

    def _format_oled_header(self, extra, settings) -> str:
        """Header text for OLED left side: just volume (e.g., 'V55')."""
        vol_num = self._get_volume_percent(settings)
        return f"V{vol_num}"

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
        """Draw OLED header: time on far left, volume next, signal bar on far right."""
        # Left-most: current time HH:MM
        try:
            time_text = datetime.now().strftime("%H:%M")
        except Exception:
            time_text = "--:--"
        # Draw time normally (not inverted)
        try:
            self.oled.text(time_text[:5], 0, 0, 1)
        except Exception:
            pass
        time_px = min(len(time_text), 5) * 6

        # Volume text immediately to the right of time, with a space
        vol_text = self._format_oled_header(extra, settings)
        vol_x = time_px + 6  # 1-char spacer
        try:
            vol_px = min(len(vol_text), 6) * 6
            if self._volume_mode_active:
                # Invert only the volume region
                if hasattr(self.oled, 'fill_rect'):
                    self.oled.fill_rect(vol_x, 0, max(18, vol_px + 2), 10, 1)
                else:
                    for dx in range(max(18, vol_px + 2)):
                        for dy in range(10):
                            self.oled.pixel(vol_x + dx, dy, 1)
                if hasattr(self.oled, 'text'):
                    self.oled.text(vol_text[:6], vol_x, 0, 0)
            else:
                self.oled.text(vol_text[:6], vol_x, 0, 1)
        except Exception:
            # Fallback plain draw
            try:
                self.oled.text(vol_text[:6], vol_x, 0, 1)
            except Exception:
                pass
        left_px_end = vol_x + min(len(vol_text), 20) * 6

        # Right: Signal rectangle fill (progress bar)
        # Determine signal quality in [0,1]
        try:
            quality = float(extra.get('signal_quality', 0.0))
        except Exception:
            quality = 0.0
        if quality < 0.0:
            quality = 0.0
        elif quality > 1.0:
            quality = 1.0

        bar_w = 40  # total width of bar
        bar_h = 8   # height of bar
        margin_right = 2
        x_bar = max(0, 128 - bar_w - margin_right)
        y_bar = 0
        self._draw_progress_bar(x_bar, y_bar, bar_w, bar_h, quality)

        # Optional: lock icon just to the left of bar if there's room
        if extra.get('signal_locked'):
            x_lock = x_bar - 10
            if x_lock > left_px_end + 2:
                self._draw_oled_header_lock_safe(x_lock)

    def _draw_oled_header_lock_safe(self, x_lock: int):
        """Helper to draw lock icon safely without raising exceptions."""
        try:
            self._draw_lock_icon(x_lock, 0)
        except Exception:
            pass

    def _draw_progress_bar(self, x: int, y: int, w: int, h: int, frac: float):
        """Draw an outline rectangle and fill horizontally to fraction [0,1]."""
        try:
            # Outline
            if hasattr(self.oled, 'rect'):
                self.oled.rect(x, y, w, h, 1)
            # Inner fill
            inner_w = max(0, min(w - 2, int((w - 2) * frac)))
            if inner_w <= 0 or h <= 2:
                return
            if hasattr(self.oled, 'fill_rect'):
                self.oled.fill_rect(x + 1, y + 1, inner_w, h - 2, 1)
            else:
                # Fallback: fill manually with pixels
                for dx in range(inner_w):
                    for dy in range(h - 2):
                        self.oled.pixel(x + 1 + dx, y + 1 + dy, 1)
        except Exception:
            # Ignore drawing errors on systems without OLED
            pass

    def _init_st7789_layout(self):
        """Initialize the ST7789 display layout once for better performance."""
        if not self.st7789_available or self.st7789_display is None:
            return False

        try:
            import displayio
            from adafruit_display_text import label
            import terminalio

            # Create main group once (no backgrounds; text only)
            self._st7789_splash = displayio.Group()

            # Create text labels (reuse these, just update text)
            # Top row: TIME VOL [LOCK] SIGNAL BAR
            self._st7789_text_labels["time"] = label.Label(
                terminalio.FONT, text="--:--:--", color=0xFFFFFF, x=6, y=5
            )
            self._st7789_splash.append(self._st7789_text_labels['time'])

            self._st7789_text_labels["vol"] = label.Label(
                terminalio.FONT, text="V00", color=0xFFFFFF, x=70, y=5
            )
            self._st7789_splash.append(self._st7789_text_labels["vol"])

            # Signal strength rectangle (like OLED): outline + horizontal fill
            self._sig_w, self._sig_h = 40, 10
            self._sig_x, self._sig_y = self.width - self._sig_w - 6, 6
            self._sig_bitmap = displayio.Bitmap(self._sig_w, self._sig_h, 2)
            self._sig_palette = displayio.Palette(2)
            # index 0 transparent, index 1 white
            try:
                self._sig_palette.make_transparent(0)
            except Exception:
                pass
            self._sig_palette[0] = 0x000000
            self._sig_palette[1] = 0xFFFFFF
            # Draw outline (1px border)
            for x in range(self._sig_w):
                self._sig_bitmap[x, 0] = 1
                self._sig_bitmap[x, self._sig_h - 1] = 1
            for y in range(self._sig_h):
                self._sig_bitmap[0, y] = 1
                self._sig_bitmap[self._sig_w - 1, y] = 1
            self._sig_tile = displayio.TileGrid(
                self._sig_bitmap, pixel_shader=self._sig_palette, x=self._sig_x, y=self._sig_y
            )
            self._st7789_splash.append(self._sig_tile)

            # Lock indicator as bitmap (larger) with transparent background
            lock_w, lock_h = 12, 12
            self._lock_bitmap = displayio.Bitmap(lock_w, lock_h, 2)
            self._lock_palette = displayio.Palette(2)
            # index 0 transparent, 1 white
            self._lock_palette[0] = 0x000000
            self._lock_palette[1] = 0xFFFFFF
            try:
                self._lock_palette.make_transparent(0)
            except Exception:
                pass
            # Draw lock: outer rectangle and shackle
            # Body border
            for x in range(2, 10):
                self._lock_bitmap[x, 5] = 1
                self._lock_bitmap[x, 10] = 1
            for y in range(6, 10):
                self._lock_bitmap[2, y] = 1
                self._lock_bitmap[9, y] = 1
            # Keyhole
            self._lock_bitmap[6, 8] = 1
            # Shackle
            for x in range(3, 9):
                self._lock_bitmap[x, 4] = 1
            self._lock_bitmap[3, 3] = 1
            self._lock_bitmap[8, 3] = 1
            self._lock_bitmap[4, 2] = 1
            self._lock_bitmap[7, 2] = 1
            self._st7789_lock = displayio.TileGrid(
                self._lock_bitmap, pixel_shader=self._lock_palette, x=-20, y=5
            )
            self._st7789_splash.append(self._st7789_lock)

            # Move talkgroup up directly below header
            self._st7789_text_labels["tgid"] = label.Label(
                terminalio.FONT, text="TGID Info", color=0xFFFFFF, x=10, y=45
            )
            self._st7789_splash.append(self._st7789_text_labels["tgid"])

            # Move system and dept labels down
            self._st7789_text_labels["system"] = label.Label(
                terminalio.FONT, text="System", color=0xFFFFFF, x=10, y=70
            )
            self._st7789_splash.append(self._st7789_text_labels['system'])

            self._st7789_text_labels["dept"] = label.Label(
                terminalio.FONT, text="Department", color=0xFFFFFF, x=10, y=100
            )
            self._st7789_splash.append(self._st7789_text_labels['dept'])

            self._st7789_text_labels["freq"] = label.Label(
                terminalio.FONT, text="Frequency", color=0xFFFFFF, x=10, y=140
            )
            self._st7789_splash.append(self._st7789_text_labels['freq'])

            self._st7789_text_labels["info"] = label.Label(
                terminalio.FONT, text="System Info", color=0xFFFFFF, x=10, y=160
            )
            self._st7789_splash.append(self._st7789_text_labels['info'])

            self._st7789_text_labels['status_text'] = label.Label(terminalio.FONT, text="Status", color=0xFFFFFF, x=10, y=self.height-15)
            self._st7789_splash.append(self._st7789_text_labels['status_text'])

            # Set the display group
            self.st7789_display.root_group = self._st7789_splash

            return True

        except Exception as e:
            logging.error(f"Error initializing ST7789 layout: {e}")
            return False

    def _update_st7789_display(self, system, freq, tgid, extra, settings):
        """Update the ST7789 display by just changing text content (much faster)."""
        if not self.st7789_available or self.st7789_display is None:
            return False

        # Initialize layout if not done yet
        if self._st7789_splash is None:
            if not self._init_st7789_layout():
                return False

        try:
            from datetime import datetime

            # Update text labels only (very fast)
            # Top row updates: TIME VOL LOCK SIGNAL BARS
            self._st7789_text_labels['time'].text = datetime.now().strftime("%H:%M:%S")
            # Volume (Vxx)
            try:
                vol_num = int(self._get_volume_percent(settings))
            except Exception:
                vol_num = 0
            self._st7789_text_labels["vol"].text = f"VOL: {vol_num:02d}"
            # Signal bar fill and lock icon
            quality = 0.0
            try:
                quality = float(extra.get("signal_quality", 0.0))
            except Exception:
                pass
            # Fill the signal rectangle like OLED
            # Clear interior
            for x in range(1, self._sig_w - 1):
                for y in range(1, self._sig_h - 1):
                    self._sig_bitmap[x, y] = 0
            inner_w = max(0, min(self._sig_w - 2, int((self._sig_w - 2) * max(0.0, min(1.0, quality)))))
            if inner_w > 0 and self._sig_h > 2:
                for x in range(1, 1 + inner_w):
                    for y in range(1, self._sig_h - 1):
                        self._sig_bitmap[x, y] = 1
            # Lock icon visible only when locked; position just before bars
            if extra.get("signal_locked"):
                self._st7789_lock.x = self._sig_x - 18
            else:
                # move off-screen
                self._st7789_lock.x = -20

            system_text = system[:25] if system else "No System"
            self._st7789_text_labels['system'].text = system_text

            # Department info
            department = "Scanning..."
            encrypted = bool(extra.get('encrypted'))

            if tgid and self.talkgroup_manager and not encrypted:
                tg_info = self.talkgroup_manager.lookup(tgid)
                if tg_info:
                    department = tg_info['department']
                    description = tg_info['description']
                    if description:
                        # Avoid leading "Unknown - " when department is missing or Unknown
                        if (
                            not department
                            or str(department).strip().lower() == "unknown"
                        ):
                            department = f"{description}"
                        else:
                            department = f"{department} - {description}"
                else:
                    department = f"TGID {tgid} - Unknown"
            elif encrypted:
                department = "Encrypted"

            self._st7789_text_labels['dept'].text = department[:30]

            # Talkgroup info; if no active transmission, show Scanning...
            if tgid:
                if bool(extra.get("active")):
                    if encrypted:
                        tag = "Encrypted"
                    else:
                        srcaddr = extra.get("srcaddr", 0)
                        tag = f"TGID: {tgid} | SRC: {srcaddr}"
                else:
                    tag = "Scanning..."
            else:
                tag = "Scanning..."

            self._st7789_text_labels['tgid'].text = tag[:35]

            # Frequency
            freq_text = f"Freq: {freq:.4f} MHz" if freq else "Freq: --"
            self._st7789_text_labels['freq'].text = freq_text

            # System info
            nac = extra.get('nac', '--')
            wacn = extra.get('wacn', '--') 
            sysid = extra.get('sysid', '--')
            site_info = f"NAC:{nac} WACN:{wacn} SYS:{sysid}"
            self._st7789_text_labels['info'].text = site_info[:35]

            # Status
            volume = settings.get('volume_level', 0)
            mute_status = "MUTE" if settings.get('mute') else f"VOL:{volume}"
            rec_status = "REC" if settings.get('recording') else ""
            status_text = f"{mute_status} | SQL:2"
            if rec_status:
                status_text += f" | {rec_status}"
            self._st7789_text_labels['status_text'].text = status_text[:30]

            return True

        except Exception as e:
            logging.error(f"Error updating ST7789 display: {e}")
            return False

    def _update_fast_displayio(self, system, freq, tgid, extra, settings):
        """Legacy fast displayio update removed (unused)."""
        return False

    def _draw_lock_icon_pil(
        self, draw: ImageDraw.ImageDraw, x: int, y: int, color=(255, 255, 255)
    ) -> None:
        """Draw a small lock icon similar to the displayio bitmap at (x,y)."""
        try:
            # Body border (12x12 area)
            for dx in range(2, 10):
                draw.point((x + dx, y + 5), fill=color)
                draw.point((x + dx, y + 10), fill=color)
            for dy in range(6, 10):
                draw.point((x + 2, y + dy), fill=color)
                draw.point((x + 9, y + dy), fill=color)
            # Keyhole
            draw.point((x + 6, y + 8), fill=color)
            # Shackle
            for dx in range(3, 9):
                draw.point((x + dx, y + 4), fill=color)
            draw.point((x + 3, y + 3), fill=color)
            draw.point((x + 8, y + 3), fill=color)
            draw.point((x + 4, y + 2), fill=color)
            draw.point((x + 7, y + 2), fill=color)
        except Exception:
            pass

    def _render_rgb_layout_like_displayio(
        self, system, freq, tgid, extra, settings
    ) -> Image.Image:
        """Render a PIL image that matches the displayio layout (white text on black, same positions)."""
        img = Image.new("RGB", (self.width, self.height), color=(0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Top row content
        try:
            time_str = datetime.now().strftime("%H:%M:%S")
        except Exception:
            time_str = "--:--:--"
        try:
            vol_num = int(self._get_volume_percent(settings))
        except Exception:
            vol_num = 0
        vol_text = f"VOL: {vol_num:02d}"

        # Signal/lock
        try:
            quality = float(extra.get("signal_quality", 0.0))
        except Exception:
            quality = 0.0
        quality = max(0.0, min(1.0, quality))
        locked = bool(extra.get("signal_locked"))

        # Below header: texts similar to displayio
        system_text = system[:25] if system else "No System"
        department = "Scanning..."
        encrypted = bool(extra.get("encrypted"))
        if tgid and self.talkgroup_manager and not encrypted:
            tg_info = self.talkgroup_manager.lookup(tgid)
            if tg_info:
                department = tg_info["department"]
                description = tg_info["description"]
                if description:
                    # Avoid leading "Unknown - " when department is missing or Unknown
                    if not department or str(department).strip().lower() == "unknown":
                        department = f"{description}"
                    else:
                        department = f"{department} - {description}"
            else:
                department = f"TGID {tgid} - Unknown"
        elif encrypted:
            department = "Encrypted"
        dept_text = department[:30]

        if tgid:
            if bool(extra.get("active")):
                if encrypted:
                    tag = "Encrypted"
                else:
                    srcaddr = extra.get("srcaddr", 0)
                    tag = f"TGID: {tgid} | SRC: {srcaddr}"
            else:
                tag = "Scanning..."
        else:
            tag = "Scanning..."
        tag = tag[:35]

        freq_text = f"Freq: {freq:.4f} MHz" if freq else "Freq: --"
        nac = extra.get("nac", "--")
        wacn = extra.get("wacn", "--")
        sysid = extra.get("sysid", "--")
        info_text = f"NAC:{nac} WACN:{wacn} SYS:{sysid}"[:35]

        volume = settings.get("volume_level", 0) if settings else 0
        mute_status = "MUTE" if (settings and settings.get("mute")) else f"VOL:{volume}"
        rec_status = "REC" if (settings and settings.get("recording")) else ""
        status_text = f"{mute_status} | SQL:2"
        if rec_status:
            status_text += f" | {rec_status}"

        white = (255, 255, 255)
        # Positions copied from displayio label setup
        draw.text(
            (6, 5),
            time_str,
            fill=white,
            font=(
                self._font_pixel_small or self._font_regular_small or self.font_small
            ),
        )
        draw.text(
            (70, 5),
            vol_text,
            fill=white,
            font=(
                self._font_pixel_small or self._font_regular_small or self.font_small
            ),
        )

        # Signal rectangle (outline + horizontal fill)
        sig_w, sig_h = 40, 10
        sig_x, sig_y = self.width - sig_w - 6, 6
        draw.rectangle(
            (sig_x, sig_y, sig_x + sig_w - 1, sig_y + sig_h - 1), outline=white
        )
        inner_w = max(0, min(sig_w - 2, int((sig_w - 2) * quality)))
        if inner_w > 0 and sig_h > 2:
            draw.rectangle(
                (sig_x + 1, sig_y + 1, sig_x + inner_w, sig_y + sig_h - 2), fill=white
            )

        if locked:
            self._draw_lock_icon_pil(draw, sig_x - 18, 5, color=white)

        # Content texts
        # Talkgroup: use medium font to avoid oversized appearance
        draw.text(
            (10, 30), tag, fill=white, font=self.font("DejaVuSansCondensed-Bold.ttf", 16)
        )
        draw.text(
            (10, 50),
            system_text,
            fill=white,
            font=(self._font_regular_med or self.font_med),
        )
        draw.text(
            (10, 70),
            dept_text,
            fill=white,
            font=(self._font_regular_med or self.font_med),
        )
        draw.text(
            (10, 90),
            freq_text,
            fill=white,
            font=(self._font_regular_med or self.font_med),
        )
        draw.text(
            (10, self.height - 10),
            info_text,
            fill=white,
            font=(self._font_pixel_small or self.font_med),
        )
        # draw.text(
        #     (10, self.height - 15),
        #     status_text[:30],
        #     fill=white,
        #     font=(self._font_regular_med or self.font_med),
        # )

        return img

    def set_rotation(self, angle):
        """Set display rotation angle (0, 90, 180, or 270 degrees)"""
        if angle in [0, 90, 180, 270]:
            self.rotation = angle
            # Update logical dimensions to match rotation
            if self.rotation in (0, 180):
                self.width = self._panel_native_width
                self.height = self._panel_native_height
            else:
                self.width = self._panel_native_height
                self.height = self._panel_native_width
            logging.info(f"Display rotation set to {angle} degrees")
        else:
            logging.warning(f"Invalid rotation angle {angle}, must be 0, 90, 180, or 270")

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

    def _load_font_from_candidates(self, candidates, size):
        """Try to load a truetype font from a list of candidate paths."""
        for path in candidates:
            try:
                if path and os.path.exists(path):
                    return ImageFont.truetype(path, size)
            except Exception as e:
                logging.debug(f"Could not load font {path}: {e}")
        # As last resort use default
        try:
            return ImageFont.load_default()
        except Exception:
            return None

    def _resolve_font_path(self, name: str) -> str | None:
        """Resolve a font name to a full path. Accepts names with or without .ttf.
        Searches common system font directories (focus on DejaVu on Raspberry Pi).
        Case-insensitive match is attempted if exact case fails.
        """
        if not name:
            return None
        # Absolute path provided
        if os.path.isabs(name) and os.path.exists(name):
            return name
        # Use scanned index if available
        try:
            if hasattr(self, "_font_index"):
                key = name if name.lower().endswith(".ttf") else f"{name}.ttf"
                cand = self._font_index.get(key.lower())
                if cand and os.path.exists(cand):
                    return cand
        except Exception:
            pass
        # Build candidate filenames (with and without extension)
        base_with_ext = name if name.lower().endswith(".ttf") else f"{name}.ttf"
        # Try direct joins
        for dir_path in self._font_search_dirs:
            try:
                path = os.path.join(dir_path, base_with_ext)
                if os.path.exists(path):
                    return path
            except Exception:
                pass
        # Case-insensitive search within directories
        for dir_path in self._font_search_dirs:
            try:
                entries = os.listdir(dir_path)
                target_lower = base_with_ext.lower()
                for entry in entries:
                    try:
                        if entry.lower() == target_lower:
                            return os.path.join(dir_path, entry)
                    except Exception:
                        pass
            except Exception:
                pass
        return None

    def _scan_available_fonts(self):
        index = {}
        names = []
        for dir_path in self._font_search_dirs:
            try:
                for entry in os.listdir(dir_path):
                    try:
                        if entry.lower().endswith(".ttf"):
                            full = os.path.join(dir_path, entry)
                            index[entry.lower()] = full
                            names.append(os.path.splitext(entry)[0])
                    except Exception:
                        pass
            except Exception:
                pass
        self._font_index = index
        self._font_available_names = sorted(set(names))

    def available_fonts(self):
        try:
            return list(self._font_available_names)
        except Exception:
            return []

    def get_font_by_name(self, name: str, size: int):
        """Return a truetype font by its filename or short name (e.g., 'DejaVuSans.ttf' or 'DejaVuSans-Bold').
        Results are cached per (name,size). Falls back to default on failure.
        """
        try:
            key = (str(name).strip().lower(), int(size))
        except Exception:
            key = (str(name).strip().lower(), 16)
        try:
            if key in self._font_cache:
                return self._font_cache[key]
            path = self._resolve_font_path(name)
            if path and os.path.exists(path):
                font = ImageFont.truetype(path, size)
            else:
                font = ImageFont.load_default()
            self._font_cache[key] = font
            return font
        except Exception as e:
            logging.debug(f"get_font_by_name failed for {name}@{size}: {e}")
            try:
                return ImageFont.load_default()
            except Exception:
                return self.font_med

    def font(self, name: str | None, size: int | None, default=None):
        """Convenience: get a cached font by name and size, with a default fallback.
        Usage example at any draw.text call:
            font=self.font("DejaVuSansCondensed-Bold", 18)
        You can also pass the full filename with .ttf.
        """
        try:
            if not name:
                return default or self.font_med
            return self.get_font_by_name(name, int(size) if size else 16) or default or self.font_med
        except Exception:
            return default or self.font_med

    def apply_font_settings(self, settings):
        """Load and cache regular, bold, and condensed fonts based on settings.
        Expected settings keys (optional):
          - tft_font_regular, tft_font_bold, tft_font_condensed (absolute .ttf paths)
          - tft_font_small_size, tft_font_medium_size, tft_font_large_size, tft_font_tgid_size
        """
        try:
            # Sizes with sane defaults
            size_small = (
                int(settings.get("tft_font_small_size", 12)) if settings else 12
            )
            size_med = int(settings.get("tft_font_medium_size", 16)) if settings else 16
            size_large = (
                int(settings.get("tft_font_large_size", 24)) if settings else 24
            )
            size_tgid = int(settings.get("tft_font_tgid_size", 16)) if settings else 16

            # Optional explicit paths
            user_regular = (
                (settings.get("tft_font_regular") or "").strip() if settings else ""
            )
            user_bold = (
                (settings.get("tft_font_bold") or "").strip() if settings else ""
            )
            user_cond = (
                (settings.get("tft_font_condensed") or "").strip() if settings else ""
            )

            # Default candidates per style (cross-platform best-effort)
            regular_candidates = [
                user_regular,
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
                "/System/Library/Fonts/Arial.ttf",
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/Library/Fonts/Arial.ttf",
                "/Windows/Fonts/arial.ttf",
            ]
            bold_candidates = [
                user_bold,
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                "/System/Library/Fonts/Arial Bold.ttf",
                "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf",
                "/Windows/Fonts/arialbd.ttf",
            ]
            condensed_candidates = [
                user_cond,
                "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSansNarrow-Regular.ttf",
                "/System/Library/Fonts/Supplemental/Arial Narrow.ttf",
                "/Library/Fonts/Arial Narrow.ttf",
                "/Windows/Fonts/arialn.ttf",
            ]

            # Load fonts
            self._font_regular_small = self._load_font_from_candidates(
                regular_candidates, size_small
            )
            self._font_regular_med = self._load_font_from_candidates(
                regular_candidates, size_med
            )
            self._font_regular_large = self._load_font_from_candidates(
                regular_candidates, size_large
            )

            self._font_bold_small = self._load_font_from_candidates(
                bold_candidates, size_small
            )
            self._font_bold_med = self._load_font_from_candidates(
                bold_candidates, size_med
            )
            self._font_bold_large = self._load_font_from_candidates(
                bold_candidates, size_large
            )

            self._font_condensed_tgid = self._load_font_from_candidates(
                condensed_candidates, size_tgid
            )

            # Maintain backward-compatible attributes
            self.font_small = self._font_regular_small or self.font_small
            self.font_med = self._font_regular_med or self.font_med
            self.font_large = self._font_regular_large or self.font_large
        except Exception as e:
            logging.debug(f"apply_font_settings failed: {e}")

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
        # Update OLED first for better perceived responsiveness
        if self.oled_available:
            self.update_oled(system, freq, tgid, extra, settings)
        # Optionally skip TFT updates during rapid user interactions
        if time.time() >= self._skip_tft_until:
            self.update_tft(system, freq, tgid, extra, settings)

    def update_tft(self, system, freq, tgid, extra, settings):
        """Update TFT display with current scanner information"""
        try:
            # Settings to control TFT activity
            tft_enabled = settings.get('tft_enable', True)
            if not tft_enabled:
                return
            update_interval = float(settings.get('tft_update_interval', self._tft_min_interval))

            # Precompute all text content for signature/caching (exclude time)
            system_text = system[:35] if system else "No System"

            # Department/Agency bar
            department = "Scanning..."
            dept_color = self.colors['department']
            encrypted = bool(extra.get('encrypted'))

            if tgid and self.talkgroup_manager and not encrypted:
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
            elif encrypted:
                department = "Encrypted"
                dept_color = self.colors['medium_priority']

            dept_text = department[:40] if len(department) > 40 else department

            # Talkgroup and frequency info
            if tgid:
                if encrypted:
                    tag = "Encrypted"
                elif extra.get('active'):
                    # Active transmission - show source address
                    srcaddr = extra.get('srcaddr', 0)
                    tag = f"TGID: {tgid} | SRC: {srcaddr}"
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

            # Build a signature of visible content (exclude timestamp so time alone won't trigger)
            signature = (system_text, dept_text, tag, freq_text, site_info, status_text)
            now_ts = time.time()
            if signature == self._last_tft_signature and (now_ts - self._last_tft_push) < update_interval:
                # No relevant changes and not time for a scheduled refresh
                return
            self._last_tft_signature = signature

            # Proceed to draw only when content changed
            # If RGB path is active, render a PIL image that mirrors the displayio layout
            img = None
            if (
                getattr(self, "rgb_display_available", False)
                and self.rgb_display is not None
            ):
                img = self._render_rgb_layout_like_displayio(
                    system, freq, tgid, extra, settings
                )

            # Note: ST7789 rotation is handled in display initialization
            # PIL rotation is not needed as ST7789 driver handles this

            # Push to TFT display
            pushed = False
            if self.st7789_available and (now_ts - self._last_tft_push) >= update_interval:
                if (
                    getattr(self, "rgb_display_available", False)
                    and self.rgb_display is not None
                ):
                    # Pi-friendly RGB driver: push PIL image matching the displayio layout
                    try:
                        if img is not None:
                            try:
                                self.rgb_display.image(img)
                            except Exception:
                                self.rgb_display.display(img)
                            pushed = True
                        else:
                            pushed = False
                    except Exception as e:
                        logging.debug(f"RGB ST7789 display push failed: {e}")
                        pushed = False
                else:
                    # displayio driver path
                    pushed = self._update_st7789_display(
                        system, freq, tgid, extra, settings
                    )
                if pushed:
                    self._last_tft_push = now_ts
                else:
                    # Fallback to saving image file for debugging
                    img.save(self.image_path)
            else:
                # No ST7789 display; save image file for debugging/development
                img.save(self.image_path)

            # If a lot of updates fail, temporarily slow down TFT to reduce bus contention
            try:
                self._tft_error_count = int(getattr(self, "_tft_error_count", 0))
                if not pushed:
                    self._tft_error_count += 1
                else:
                    self._tft_error_count = 0
                if self._tft_error_count >= 5:
                    self._skip_tft_until = time.time() + 1.0
                    self._tft_error_count = 0
            except Exception:
                pass

        except Exception as e:
            logging.error(f"Error updating TFT display: {e}")

    def update_oled(self, system, freq, tgid, extra=None, settings=None):
        """Update OLED display with transmission information"""
        if not self.oled_available or self.oled is None:
            # Try lazy reinit if previously failed and backoff elapsed
            self._reinit_oled()
        if not self.oled_available or self.oled is None:
            return

        if extra is None:
            extra = {}

        # Check OLED refresh rate throttling
        now = time.time()
        if settings:
            oled_refresh_rate = settings.get('oled_refresh_rate', 20)
            oled_interval = 1.0 / max(1, oled_refresh_rate)  # Prevent division by zero

            # Update scroll speed from settings
            self.scroll_delay = settings.get('oled_scroll_speed', 0.2)
            # Update volume poll interval to make volume number react faster when user turns encoder
            try:
                self._vol_poll_interval = float(settings.get('volume_poll_interval', 0.2))
            except Exception:
                self._vol_poll_interval = 0.2
            # Update grace period during which UI hint overrides system value
            try:
                self._vol_hint_grace = float(settings.get('volume_hint_grace', 0.6))
            except Exception:
                self._vol_hint_grace = 0.6
        else:
            oled_interval = self._oled_min_interval

        # Throttle OLED updates based on refresh rate setting
        if now - self._last_oled_update < oled_interval:
            return

        self._last_oled_update = now

        try:
            self.oled.fill(0)

            # Check if there's an active transmission with a radio ID
            srcaddr = extra.get('srcaddr')
            active_transmission = extra.get('active') and srcaddr is not None
            encrypted = bool(extra.get('encrypted'))

            if active_transmission and tgid:
                # ACTIVE TRANSMISSION - Show 3-line format

                # Line 1: Custom header
                # Draw composed header: SID/VOL + lock icon + bars
                self._draw_oled_header(extra, settings)

                # Line 2: TALKGROUP (get full description with scrolling)
                if encrypted:
                    talkgroup_text = "ENCRYPTED"
                else:
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
                if not encrypted:
                    radio_text = f"RADIO {srcaddr}"
                    self.oled.text(radio_text, 0, 20, 1)

                # Lines 4-6: Reserved for future dual SDR setup
                # (Currently empty but available)

            else:
                # NO ACTIVE TRANSMISSION - Show scanning status

                # Line 1: Custom header
                # Draw composed header: SID/VOL + lock icon + bars
                self._draw_oled_header(extra, settings)

                # Line 2: Scanning status
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
            # On success, reset error count
            self._oled_error_count = 0
        except Exception as e:
            logging.error(f"Error updating OLED display: {e}")
            # Attempt recovery on I/O errors
            self._reinit_oled()

    def show_menu_on_oled(self, menu_items, selected_index):
        """Display menu on OLED"""
        if not self.oled_available or self.oled is None:
            # Try lazy reinit if previously failed and backoff elapsed
            self._reinit_oled()
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
            self._oled_error_count = 0
        except Exception as e:
            logging.error(f"Error showing menu on OLED: {e}")
            self._reinit_oled()

    def clear(self):
        """Clear both displays"""
        try:
            # Clear ST7789 display
            if self.st7789_available:
                try:
                    black_image = Image.new('RGB', (self.width, self.height), color=(0, 0, 0))
                    if (
                        getattr(self, "rgb_display_available", False)
                        and self.rgb_display is not None
                    ):
                        try:
                            try:
                                self.rgb_display.image(black_image)
                            except Exception:
                                self.rgb_display.display(black_image)
                        except Exception:
                            pass
                    elif self.st7789_display is not None:
                        self.st7789_display.display(black_image)
                except Exception as e:
                    logging.debug(f"Error clearing ST7789 display: {e}")

            # Clear OLED display
            if self.oled_available and self.oled is not None:
                self.oled.fill(0)
                self.oled.show()
        except Exception as e:
            logging.error(f"Error clearing displays: {e}")

    def cleanup(self):
        """Clean up display resources"""
        try:
            # Clean up ST7789 display
            if self.st7789_available:
                try:
                    # Clear display if RGB driver present
                    if (
                        getattr(self, "rgb_display_available", False)
                        and self.rgb_display is not None
                    ):
                        try:
                            black_image = Image.new(
                                "RGB", (self.width, self.height), color=(0, 0, 0)
                            )
                            try:
                                self.rgb_display.image(black_image)
                            except Exception:
                                self.rgb_display.display(black_image)
                        except Exception:
                            pass
                    self.st7789_display = None
                    self.st7789_available = False
                    logging.info("ST7789 display cleaned up successfully")
                except Exception as e:
                    logging.debug(f"Error cleaning up ST7789 display: {e}")

        except Exception as e:
            logging.error(f"Error in DisplayManager cleanup: {e}")

    def skip_tft_for(self, seconds: float):
        """Temporarily skip TFT updates to keep UI responsive."""
        try:
            self._skip_tft_until = max(self._skip_tft_until, time.time() + max(0.0, float(seconds)))
        except Exception:
            pass

    def show_message(self, title, message, duration=3):
        """Show a temporary message on both displays"""
        # Note: duration parameter reserved for future use
        try:
            # ST7789 message
            if self.st7789_available:
                try:
                    # Create message image
                    img = Image.new('RGB', (self.width, self.height), color=(0, 0, 0))
                    draw = ImageDraw.Draw(img)

                    # Title (centered, orange)
                    title_bbox = draw.textbbox(
                        (0, 0), title, font=(self._font_bold_large or self.font_large)
                    )
                    title_width = title_bbox[2] - title_bbox[0]
                    title_x = (self.width - title_width) // 2
                    draw.text(
                        (title_x, 100),
                        title,
                        fill=(255, 165, 0),
                        font=(self._font_bold_large or self.font_large),
                    )

                    # Message (centered, white)
                    msg_bbox = draw.textbbox(
                        (0, 0), message, font=(self._font_regular_med or self.font_med)
                    )
                    msg_width = msg_bbox[2] - msg_bbox[0]
                    msg_x = (self.width - msg_width) // 2
                    draw.text(
                        (msg_x, 140),
                        message,
                        fill=(255, 255, 255),
                        font=(self._font_regular_med or self.font_med),
                    )

                    # Display the message on RGB driver if available; otherwise attempt displayio or save
                    if (
                        getattr(self, "rgb_display_available", False)
                        and self.rgb_display is not None
                    ):
                        try:
                            try:
                                self.rgb_display.image(img)
                            except Exception:
                                self.rgb_display.display(img)
                        except Exception:
                            pass
                    elif self.st7789_display is not None:
                        try:
                            self.st7789_display.display(img)
                        except Exception:
                            pass
                    else:
                        img.save(self.image_path)

                except Exception as e:
                    logging.debug(f"Error preparing ST7789 message: {e}")

            # OLED message
            if self.oled_available and self.oled is not None:
                self.oled.fill(0)
                self.oled.text(title[:21], 0, 10, 1)
                self.oled.text(message[:21], 0, 30, 1)
                self.oled.show()

        except Exception as e:
            logging.error(f"Error showing message: {e}")

    def set_volume_mode(self, active: bool):
        """Enable/disable temporary volume adjustment mode (affects OLED header rendering)."""
        try:
            self._volume_mode_active = bool(active)
            self.request_oled_refresh()
        except Exception:
            pass
