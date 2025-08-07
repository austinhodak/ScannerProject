# --- op25_client.py ---
import requests
import time
import logging
from datetime import datetime, timedelta

class OP25Client:
    def __init__(self, host="127.0.0.1", port=8080):
        self.host = host
        self.port = port
        self.base_url = f"http://{host}:{port}"
        self.latest_data = ("Unknown", None, None, {})
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
                    
                    if parsed_data and parsed_data[0] != "Unknown":
                        self.latest_data = parsed_data
                        self.last_update = datetime.now()
                        self.last_valid_data = parsed_data
                        self.connection_errors = 0
                    else:
                        # Use last valid data if recent
                        if (self.last_valid_data and self.last_update and 
                            datetime.now() - self.last_update < self.data_timeout):
                            self.latest_data = self.last_valid_data
                        else:
                            self.latest_data = ("No Activity", None, None, {})
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
        """Parse OP25 JSON data into scanner format"""
        if not data or not isinstance(data, list):
            logging.debug("Invalid or empty data received from OP25")
            return ("Unknown", None, None, {})

        system = "Unknown"
        freq = None
        tgid = None
        extra = {}
        
        # Track if we have an active transmission
        active_transmission = False
        srcaddr = 0

        try:
            # Look for active transmission info first
            for item in data:
                if not isinstance(item, dict):
                    continue
                    
                json_type = item.get("json_type")
                
                # Check for active transmission via trunk_update
                if json_type == "trunk_update":
                    srcaddr = item.get("srcaddr", 0)
                    grpaddr = item.get("grpaddr", 0)
                    encrypted = item.get("encrypted", False)
                    nac = item.get("nac", 0)
                    
                    # Active transmission if srcaddr is not 0
                    if srcaddr != 0:
                        active_transmission = True
                        tgid = grpaddr
                        extra.update({
                            "srcaddr": srcaddr,
                            "encrypted": encrypted,
                            "nac": nac,
                            "active": True
                        })
                        logging.debug(f"Active transmission: TGID={tgid}, SRC={srcaddr}")
                
                # Get frequency info from change_freq
                elif json_type == "change_freq":
                    current_freq = item.get("freq")
                    if current_freq:
                        freq = current_freq / 1e6  # Convert Hz to MHz
                        system = item.get("system", "Unknown")
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
                            
                        # Extract system name from top_line
                        top_line = sys_data.get("top_line", "")
                        if top_line and "NAC" in top_line:
                            # Parse system name from top_line format
                            # "NAC 0x19 WACN 0xa441 SYSID 0x19 460.025000/465.025000 tsbks 7728"
                            system = f"System {sys_data.get('sysid', sys_id)}"
                            
                        # Get current control channel frequency
                        rxchan = sys_data.get("rxchan")
                        if rxchan and not freq:  # Only if we don't have freq from change_freq
                            freq = rxchan / 1e6
                            
                        extra.update({
                            "sysid": sys_data.get("sysid", sys_id),
                            "wacn": sys_data.get("wacn", 0),
                            "rxchan": sys_data.get("rxchan", 0),
                            "txchan": sys_data.get("txchan", 0),
                            "tsbks": sys_data.get("tsbks", 0),
                            "active": False
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
                if isinstance(system, int):
                    system = f"System {system}"
                    
            extra["timestamp"] = datetime.now().isoformat()
            
            freq_str = f"{freq:.4f}" if freq else "None"
            logging.debug(f"Parsed: System={system}, Freq={freq_str}, TGID={tgid}, Active={active_transmission}")
            return system, freq, tgid, extra
                    
        except Exception as e:
            logging.error(f"Error parsing OP25 data: {e}")
            import traceback
            logging.debug(traceback.format_exc())
            
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