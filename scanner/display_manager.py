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
from abc import ABC, abstractmethod

# Safe imports for displayio hardware and helpers
try:
    import displayio
    from fourwire import FourWire
    import adafruit_st7789

    # Import the helper for converting PIL images to displayio Bitmaps
    from adafruit_pillow_compat import from_pillow

    ST7789_AVAILABLE = True
except ImportError:
    ST7789_AVAILABLE = False


# =====================================================================================
# 1. VIEWMODEL CLASS (The "Brain")
#    Prepares all data for display, separating logic from drawing.
# =====================================================================================
class DisplayViewModel:
    """
    Prepares and holds the state for all displays.
    This class transforms raw scanner data into display-ready strings and properties.
    """

    def __init__(self, talkgroup_manager):
        self.talkgroup_manager = talkgroup_manager
        self._last_signature = None

        # --- All display-ready properties are initialized here ---
        self.timestamp = ""
        self.system_name = "Initializing..."
        self.status_indicator_color = "gray"
        self.department_text = "Scanning..."
        self.department_color = "yellow"
        self.talkgroup_line = "..."
        self.frequency_line = "..."
        self.system_info_line = "..."
        self.status_bar_text = "..."
        self.signal_quality = 0.0
        self.is_signal_locked = False
        self.is_encrypted = False
        self.is_active_transmission = False
        self.radio_id_text = ""
        self.idle_status_text = "MONITORING"

    def has_changed(self):
        """Checks if display-critical data has changed to prevent needless redraws."""
        current_signature = (
            self.system_name,
            self.department_text,
            self.talkgroup_line,
            self.frequency_line,
            self.system_info_line,
            self.status_bar_text,
            self.is_encrypted,
            self.is_active_transmission,
        )
        if current_signature != self._last_signature:
            self._last_signature = current_signature
            return True
        return False

    def update(self, system, freq, tgid, extra, settings):
        """Updates the view model with the latest raw data from the scanner."""
        self.timestamp = datetime.now().strftime("%b %d %H:%M:%S")
        self.signal_quality = extra.get("signal_quality", 0.0)
        self.is_signal_locked = extra.get("signal_locked", False)
        self.is_encrypted = bool(extra.get("encrypted"))
        srcaddr = extra.get("srcaddr")
        self.is_active_transmission = extra.get("active") and srcaddr is not None
        self.system_name = system[:35] if system else "No System"
        self.status_indicator_color = "red" if system == "Offline" else "orange"
        if tgid:
            if self.is_encrypted:
                self.department_text = "Encrypted"
                self.department_color = "orange"
                self.talkgroup_line = "Encrypted Transmission"
            else:
                tg_info = (
                    self.talkgroup_manager.lookup(tgid)
                    if self.talkgroup_manager
                    else None
                )
                if tg_info:
                    self.department_text = tg_info.get("department", "Unknown Dept.")
                    desc = tg_info.get("description", "")
                    if desc:
                        self.department_text = f"{self.department_text} - {desc}"

                    priority = tg_info.get("priority", "Medium")
                    if priority == "High":
                        self.department_color = "red"
                    elif priority == "Medium":
                        self.department_color = "orange"
                    else:
                        self.department_color = "green"
                else:
                    self.department_text = f"TGID {tgid} - Unknown"
                    self.department_color = "yellow"

                if self.is_active_transmission:
                    self.talkgroup_line = f"TGID: {tgid} | SRC: {srcaddr}"
                    self.radio_id_text = f"RADIO {srcaddr}"
                else:
                    self.talkgroup_line = f"TGID: {tgid}"
        else:
            self.department_text = "Scanning..."
            self.department_color = "yellow"
            self.talkgroup_line = "..."
        self.frequency_line = f"Freq: {freq:.4f} MHz" if freq else "Freq: --"
        nac, wacn, sysid = (
            extra.get("nac", "--"),
            extra.get("wacn", "--"),
            extra.get("sysid", "--"),
        )
        self.system_info_line = f"NAC: {nac} | WACN: {wacn} | SYS: {sysid}"
        volume = settings.get("volume_level", 0)
        mute_status = "MUTE" if settings.get("mute") else f"VOL:{volume}"
        rec_status = "REC" if settings.get("recording") else ""
        self.status_bar_text = f"{mute_status}"
        if rec_status:
            self.status_bar_text += f" | {rec_status}"
        if system != "Offline":
            self.idle_status_text = (
                f"IDLE {extra.get('last_activity')}s"
                if extra.get("last_activity")
                else "MONITORING"
            )
        else:
            self.idle_status_text = "OFFLINE"


# =====================================================================================
# 2. BASE AND DRIVER CLASSES (The "Hands")
# =====================================================================================
class BaseDisplay(ABC):
    """Abstract base class for all display types."""

    def __init__(self):
        self._last_update_time = 0.0
        self.is_available = False

    @abstractmethod
    def update(self, view_model: DisplayViewModel, force_redraw=False):
        pass

    @abstractmethod
    def clear(self):
        pass

    @abstractmethod
    def show_message(self, title, message, duration=3):
        pass

    def _should_update(self, interval):
        now = time.time()
        if (now - self._last_update_time) >= interval:
            self._last_update_time = now
            return True
        return False


class TFTDisplay(BaseDisplay):
    """Driver for the ST7789 TFT display using PIL for robust drawing."""

    def __init__(self, rotation=0):
        super().__init__()
        if not ST7789_AVAILABLE:
            logging.debug("ST7789 libraries not found, TFT will be unavailable.")
            return
        self.width, self.height = (320, 240) if rotation in [0, 180] else (240, 320)
        self.rotation = rotation
        self.display = None
        self.font_small = self._load_font(12)
        self.font_med = self._load_font(16)
        self.font_large = self._load_font(24)
        self.colors = {
            "background": "black",
            "text": "white",
            "header": "orange",
            "status": "blue",
        }

    def initialize_hardware(self, settings):
        """Initializes the physical display hardware. Called by DisplayManager."""
        if not ST7789_AVAILABLE:
            return
        try:
            displayio.release_displays()
            spi = board.SPI()
            s = settings or {}
            cs_pin = getattr(board, s.get("st7789_cs_pin", "D5"))
            dc_pin = getattr(board, s.get("st7789_dc_pin", "D25"))
            rst_pin = getattr(board, s.get("st7789_rst_pin", "D27"))
            display_bus = FourWire(
                spi, command=dc_pin, chip_select=cs_pin, reset=rst_pin
            )
            self.display = adafruit_st7789.ST7789(
                display_bus, width=320, height=240, rotation=self.rotation
            )
            self.is_available = True
            logging.info(
                f"ST7789 display initialized successfully (Rotation: {self.rotation})"
            )
        except Exception as e:
            logging.error(f"Failed to initialize ST7789 display: {e}")
            self.is_available = False

    def _display_pil_image(self, img: Image.Image):
        """Helper to convert a PIL image and show it on a displayio screen."""
        # The modern displayio way: convert PIL image to a displayio.Bitmap,
        # put it in a Group, and set it as the root_group.
        group = displayio.Group()
        bitmap = from_pillow(img.convert("RGB"))
        tile_grid = displayio.TileGrid(bitmap, pixel_shader=bitmap.pixel_shader)
        group.append(tile_grid)
        self.display.root_group = group

    def update(self, view_model: DisplayViewModel, force_redraw=False):
        if not self.is_available or (not self._should_update(0.5) and not force_redraw):
            return

        try:
            img = Image.new(
                "RGB", (self.width, self.height), color=self.colors["background"]
            )
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, self.width, 30), fill=self.colors["header"])
            draw.text((5, 5), "SCANNER", fill="black", font=self.font_med)
            draw.text(
                (self.width - 130, 5),
                view_model.timestamp,
                fill="black",
                font=self.font_med,
            )
            draw.rectangle(
                (0, 30, self.width, 70), fill=view_model.status_indicator_color
            )
            draw.text(
                (10, 35), view_model.system_name, fill="black", font=self.font_large
            )
            draw.rectangle((0, 70, self.width, 110), fill=view_model.department_color)
            draw.text(
                (10, 75), view_model.department_text, fill="black", font=self.font_large
            )
            draw.text(
                (10, 120),
                view_model.talkgroup_line,
                fill=self.colors["text"],
                font=self.font_large,
            )
            draw.text(
                (10, 155),
                view_model.frequency_line,
                fill=self.colors["text"],
                font=self.font_med,
            )
            draw.text(
                (10, 175),
                view_model.system_info_line,
                fill=self.colors["text"],
                font=self.font_med,
            )
            draw.rectangle(
                (0, self.height - 30, self.width, self.height),
                fill=self.colors["status"],
            )
            draw.text(
                (10, self.height - 25),
                view_model.status_bar_text,
                fill="white",
                font=self.font_med,
            )

            # FIX: Use the correct displayio method to show the image
            self._display_pil_image(img)
        except Exception as e:
            logging.error(f"Error updating TFT display: {e}")

    def show_message(self, title, message, duration=3):
        if not self.is_available:
            return
        img = Image.new("RGB", (self.width, self.height), color="black")
        draw = ImageDraw.Draw(img)
        title_bbox = draw.textbbox((0, 0), title, font=self.font_large)
        msg_bbox = draw.textbbox((0, 0), message, font=self.font_med)
        draw.text(
            ((self.width - title_bbox[2]) / 2, self.height / 2 - 30),
            title,
            font=self.font_large,
            fill="orange",
        )
        draw.text(
            ((self.width - msg_bbox[2]) / 2, self.height / 2),
            message,
            font=self.font_med,
            fill="white",
        )

        # FIX: Use the correct displayio method to show the image
        self._display_pil_image(img)

    def clear(self):
        if not self.is_available:
            return
        # A black screen is just a black PIL image.
        black_img = Image.new("RGB", (self.width, self.height), color="black")
        self._display_pil_image(black_img)

    def _load_font(self, size):
        paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
        for path in paths:
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
        return ImageFont.load_default()


class OLEDDisplay(BaseDisplay):
    """Driver for the SSD1306 I2C OLED display."""

    def __init__(self):
        super().__init__()
        try:
            i2c = busio.I2C(board.SCL, board.SDA)
            self.display = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c)
            self.is_available = True
            self.clear()
            logging.info("OLED display initialized successfully.")
        except Exception as e:
            logging.warning(f"OLED display not available: {e}")
            self.is_available = False

    def update(self, view_model: DisplayViewModel, force_redraw=False):
        if not self.is_available or (not self._should_update(0.1) and not force_redraw):
            return
        try:
            self.display.fill(0)
            self.display.text(datetime.now().strftime("%H:%M:%S"), 0, 0, 1)
            self._draw_progress_bar(88, 0, 40, 8, view_model.signal_quality)
            if view_model.is_active_transmission:
                tg_text = view_model.department_text[:21]
                self.display.text(tg_text, 0, 12, 1)
                self.display.text(view_model.radio_id_text[:21], 0, 24, 1)
            else:
                self.display.text("Scanning...", 0, 12, 1)
                self.display.text(view_model.idle_status_text[:21], 0, 24, 1)
            self.display.text(view_model.status_bar_text[:21], 0, 54, 1)
            self.display.show()
        except Exception as e:
            logging.error(f"Error updating OLED display: {e}")

    def show_message(self, title, message, duration=3):
        if not self.is_available:
            return
        self.display.fill(0)
        self.display.text(title[:21], 0, 10, 1)
        self.display.text(message[:21], 0, 30, 1)
        self.display.show()

    def clear(self):
        if not self.is_available:
            return
        self.display.fill(0)
        self.display.show()

    def _draw_progress_bar(self, x, y, w, h, frac):
        self.display.rect(x, y, w, h, 1)
        fill_w = max(0, min(w - 2, int((w - 2) * frac)))
        if fill_w > 0:
            self.display.fill_rect(x + 1, y + 1, fill_w, h - 2, 1)


# =====================================================================================
# 3. MAIN MANAGER CLASS (The "Orchestrator")
# =====================================================================================
class DisplayManager:
    """
    Manages all display devices by orchestrating the ViewModel and Display Drivers.
    """

    def __init__(self, talkgroup_manager=None, rotation=0):
        self.view_model = DisplayViewModel(talkgroup_manager)
        self.displays = []
        tft = TFTDisplay(rotation=rotation)
        self.displays.append(tft)
        oled = OLEDDisplay()
        self.displays.append(oled)

    def initialize_displays(self, settings):
        """Initializes hardware for all managed displays that require it."""
        logging.info("Initializing display hardware...")
        for display in self.displays:
            if hasattr(display, "initialize_hardware"):
                try:
                    display.initialize_hardware(settings)
                except Exception as e:
                    logging.error(f"Error initializing {type(display).__name__}: {e}")
        if not any(d.is_available for d in self.displays):
            logging.warning(
                "No displays were initialized. DisplayManager will be inactive."
            )

    def update(self, system, freq, tgid, extra, settings):
        self.view_model.update(system, freq, tgid, extra, settings)
        force_update = extra.get("force_redraw", False)
        if not self.view_model.has_changed() and not force_update:
            return
        for display in self.displays:
            if display.is_available:
                try:
                    display.update(self.view_model, force_redraw=force_update)
                except Exception as e:
                    logging.error(
                        f"Failed to update display {type(display).__name__}: {e}"
                    )

    def clear(self):
        for display in self.displays:
            if display.is_available:
                display.clear()

    def show_message(self, title, message, duration=3):
        for display in self.displays:
            if display.is_available:
                display.show_message(title, message, duration)
        if duration > 0:
            time.sleep(duration)

    def cleanup(self):
        logging.info("Cleaning up displays.")
        self.clear()
