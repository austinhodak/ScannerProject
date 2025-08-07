# --- op25_client.py ---
import requests
import time
import logging
from datetime import datetime, timedelta

class OP25Client:
    def __init__(self, host="127.0.0.1", port=8080, system_name=None):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.system_name = system_name or "SCANNER"  # Default fallback
        self.latest_data = (self.system_name, None, None, {})
        self.last_update = None
        self.connection_errors = 0
        self.max_errors = 5
        self.running = True
        
        # Data validation
        self.last_valid_data = None
        self.data_timeout = timedelta(seconds=30)

    def run(self):
        """Main loop for OP25 client"""
        logging.info(f"Starting OP25 client connection to {self.base_url}")
        
        while self.running:
            try:
                # Try to get data from OP25
                payload = [{"command": "update", "arg1": 0, "arg2": 0}]
                response = requests.post(
                    self.base_url, 
                    json=payload, 
                    timeout=5,
                    headers={'Content-Type': 'application/json'}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    parsed_data = self.parse(data)
                    
                    if parsed_data is not None:
                        # We got valid data - update our state
                        self.latest_data = parsed_data
                        self.last_update = datetime.now()
                        self.last_valid_data = parsed_data
                        self.connection_errors = 0
                    else:
                        # Empty/invalid response - maintain current state
                        # Only fall back to "No Activity" if we haven't had valid data for a while
                        if (not self.last_valid_data or not self.last_update or 
                            datetime.now() - self.last_update > self.data_timeout):
                            self.latest_data = (self.system_name, None, None, {"status": "no_activity"})
                else:
                    raise requests.RequestException(f"HTTP {response.status_code}")
                    
            except requests.exceptions.Timeout:
                logging.warning("OP25 connection timeout")
                self._handle_connection_error("Timeout")
                
            except requests.exceptions.ConnectionError:
                logging.warning(f"Cannot connect to OP25 at {self.base_url}")
                self._handle_connection_error("Connection Error")
                
            except requests.exceptions.RequestException as e:
                logging.error(f"OP25 request error: {e}")
                self._handle_connection_error("Request Error")
                
            except Exception as e:
                logging.error(f"Unexpected error in OP25 client: {e}")
                self._handle_connection_error("Unknown Error")

            time.sleep(0.5)
            
    def _handle_connection_error(self, error_type):
        """Handle connection errors with backoff"""
        self.connection_errors += 1
        
        if self.connection_errors >= self.max_errors:
            self.latest_data = ("Offline", None, None, {"error": error_type})
        else:
            self.latest_data = (f"Connecting... ({error_type})", None, None, {"error": error_type})
            
        # Exponential backoff for repeated errors
        if self.connection_errors > 3:
            time.sleep(min(5, self.connection_errors))

    def get_latest(self):
        """Get the latest scanner data"""
        return self.latest_data
        
    def stop(self):
        """Stop the OP25 client"""
        self.running = False
        
    def is_connected(self):
        """Check if connected to OP25"""
        return self.connection_errors < self.max_errors and self.latest_data[0] not in ["Offline", "Unknown"]
        
    def get_connection_status(self):
        """Get detailed connection status"""
        if self.connection_errors == 0:
            return "Connected"
        elif self.connection_errors < self.max_errors:
            return f"Unstable ({self.connection_errors} errors)"
        else:
            return "Disconnected"

    def parse(self, data):
        """Parse OP25 JSON data into scanner format (supports both rx.py and multi_rx.py formats)"""
        if not data or not isinstance(data, list):
            logging.debug("Invalid or empty data received from OP25")
            return None
        
        # Check if data array is empty - if so, maintain current state
        if len(data) == 0:
            logging.debug("Empty data array received from OP25 - maintaining current state")
            return None

        system = self.system_name  # Use configured system name
        freq = None
        tgid = None
        extra = {}
        
        # Track if we have an active transmission
        active_transmission = False
        srcaddr = 0

        try:
            # Look for channel updates (multi_rx.py format) and transmission info
            for item in data:
                if not isinstance(item, dict):
                    continue
                    
                json_type = item.get("json_type")
                
                # NEW: Handle multi_rx.py channel_update format
                if json_type == "channel_update":
                    # Look through channel data
                    for ch_id, ch_data in item.items():
                        if ch_id in ["json_type", "channels"]:
                            continue
                        if not isinstance(ch_data, dict):
                            continue
                            
                        # Extract transmission info
                        ch_freq = ch_data.get("freq")
                        if ch_freq:
                            freq = ch_freq / 1e6  # Convert Hz to MHz
                        
                        tgid = ch_data.get("tgid")
                        srcaddr = ch_data.get("srcaddr", 0)
                        ch_system = ch_data.get("system")
                        if ch_system:
                            system = ch_system
                        
                        # Check if this is an active transmission
                        if srcaddr and srcaddr > 0 and tgid and tgid > 0:
                            active_transmission = True
                            logging.debug(f"Active transmission: TGID={tgid}, SRC={srcaddr}")
                            
                        extra.update({
                            "srcaddr": srcaddr,
                            "tgid": tgid,
                            "encrypted": ch_data.get("encrypted", 0),
                            "emergency": ch_data.get("emergency", 0),
                            "active": active_transmission,
                            "channel_name": ch_data.get("name", f"Channel {ch_id}"),
                            "tag": ch_data.get("tag", ""),
                            "srctag": ch_data.get("srctag", ""),
                            "mode": ch_data.get("mode"),
                            "signal_quality": ch_data.get("signal_quality", 0),
                            "signal_locked": ch_data.get("signal_locked", 0),
                            "error": ch_data.get("error", 0)
                        })
                
                # Check for active transmission via trunk_update (both old and new formats)
                elif json_type == "trunk_update":
                    # Check for old rx.py format (srcaddr/grpaddr at top level)
                    old_srcaddr = item.get("srcaddr", 0)
                    old_grpaddr = item.get("grpaddr", 0)
                    encrypted = item.get("encrypted", False)
                    nac = item.get("nac", 0)
                    
                    # Active transmission if srcaddr is not 0 (old format)
                    if old_srcaddr != 0:
                        active_transmission = True
                        tgid = old_grpaddr
                        srcaddr = old_srcaddr
                        extra.update({
                            "srcaddr": old_srcaddr,
                            "encrypted": encrypted,
                            "nac": nac,
                            "active": True
                        })
                        logging.debug(f"Active transmission (old format): TGID={tgid}, SRC={srcaddr}")
                
                # Get frequency info from change_freq (old rx.py format)
                elif json_type == "change_freq":
                    current_freq = item.get("freq")
                    if current_freq:
                        freq = current_freq / 1e6  # Convert Hz to MHz
                        old_system = item.get("system", "Unknown")
                        if old_system != "Unknown":
                            system = old_system
                        extra.update({
                            "nac": item.get("nac", 0),
                            "wacn": item.get("wacn", 0),
                            "sysid": item.get("sysid", 0),
                            "sigtype": item.get("sigtype", "Unknown"),
                            "error": item.get("error", 0)
                        })
            
            # If we have an active transmission, we're done
            if active_transmission and freq and tgid:
                extra["timestamp"] = datetime.now().isoformat()
                logging.debug(f"Active: System={system}, Freq={freq:.4f}, TGID={tgid}, SRC={srcaddr}")
                return system, freq, tgid, extra
            
            # Otherwise, look for system info in trunk_update
            for item in data:
                if not isinstance(item, dict):
                    continue
                    
                json_type = item.get("json_type")
                
                if json_type == "trunk_update":
                    # Parse system information
                    for sys_id, sys_data in item.items():
                        if sys_id in ["json_type", "srcaddr", "grpaddr", "encrypted", "nac"]:
                            continue
                        if not isinstance(sys_data, dict):
                            continue
                            
                        # Extract system name (multi_rx.py format has it directly)
                        sys_system = sys_data.get("system")
                        if sys_system:
                            system = sys_system
                        else:
                            # Fallback to configured system name
                            system = self.system_name
                            
                        # Get current control channel frequency
                        rxchan = sys_data.get("rxchan")
                        if rxchan and not freq:  # Only if we don't have freq from channel_update
                            freq = rxchan / 1e6
                            
                        extra.update({
                            "sysid": sys_data.get("sysid", sys_id),
                            "wacn": sys_data.get("wacn", 0),
                            "nac": sys_data.get("nac", 0),
                            "rxchan": sys_data.get("rxchan", 0),
                            "txchan": sys_data.get("txchan", 0),
                            "rfid": sys_data.get("rfid", 0),
                            "stid": sys_data.get("stid", 0),
                            "active": active_transmission
                        })
                        
                        # Look for recent activity in frequency_data
                        freq_data = sys_data.get("frequency_data", {})
                        most_recent_freq = None
                        most_recent_time = float('inf')
                        
                        for freq_str, details in freq_data.items():
                            if not isinstance(details, dict):
                                continue
                                
                            # Check for active talkgroups
                            tgids = details.get("tgids", [])
                            active_tgids = [tg for tg in tgids if tg is not None]
                            
                            # Check last activity time
                            last_activity = details.get("last_activity", "999.9").strip()
                            try:
                                activity_time = float(last_activity)
                                if activity_time < most_recent_time:
                                    most_recent_time = activity_time
                                    most_recent_freq = freq_str
                                    if active_tgids:
                                        tgid = active_tgids[0]
                            except (ValueError, TypeError):
                                pass
                        
                        # If we found recent activity, use that frequency
                        if most_recent_freq and most_recent_time < 30:  # Within 30 seconds
                            freq = float(most_recent_freq) / 1e6
                            extra["last_activity"] = most_recent_time
                            extra["activity_freq"] = freq
                            
                        break  # Use first valid system
                        
            # Set defaults if nothing found
            if not system or system == "Unknown":
                system = extra.get("sysid", "No System")
                # Always use consistent system name instead of dynamic values
                if isinstance(system, int) or not system or system.startswith("System "):
                    system = self.system_name
                    
            extra["timestamp"] = datetime.now().isoformat()
            
            freq_str = f"{freq:.4f}" if freq else "None"
            logging.debug(f"Parsed: System={system}, Freq={freq_str}, TGID={tgid}, Active={active_transmission}")
            return system, freq, tgid, extra
                    
        except Exception as e:
            logging.error(f"Error parsing OP25 data: {e}")
            import traceback
            logging.debug(traceback.format_exc())
            # Return None on parse error to maintain current state
            return None
            
        return system, freq, tgid, extra
        
    def send_command(self, command, arg1=0, arg2=0):
        """Send a command to OP25"""
        try:
            payload = [{"command": command, "arg1": arg1, "arg2": arg2}]
            response = requests.post(
                self.base_url,
                json=payload,
                timeout=5,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                logging.error(f"Command failed: HTTP {response.status_code}")
                return None
                
        except Exception as e:
            logging.error(f"Error sending command to OP25: {e}")
            return None