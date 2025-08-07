# --- op25_manager.py ---
import subprocess
import psutil
import time
import logging
import signal
import os
import queue
import select
from pathlib import Path
from threading import Thread, Event, Lock


class OP25Manager:
    def __init__(self, settings):
        self.settings = settings
        self.process = None
        self.monitoring_thread = None
        self.stop_event = Event()
        self._start_lock = Lock()
        self.restart_count = 0
        self.max_restarts = 5
        self.last_restart_time = 0
        self.restart_cooldown = 30  # 30 seconds between restarts
        
        # OP25 configuration
        self.op25_path = self.settings.get("op25_path", "/home/ahodak/op25/op25/gr-op25_repeater/apps")
        self.config_file = self.settings.get("op25_config", "scanner.json")
        self.log_level = self.settings.get("op25_log_level", 1)
        self.freq_error = self.settings.get("op25_freq_error", 0)
        self.fine_tune = self.settings.get("op25_fine_tune", 0.0)
        self.gain = self.settings.get("op25_gain", "auto")
        self.args = self.settings.get("op25_args", [])
        
        # Web interface settings
        self.web_port = self.settings.get("op25_web_port", 8080)
        self.web_host = self.settings.get("op25_web_host", "127.0.0.1")
        
        # Terminal log display only (no disk writes)
        self.log_thread = None
        self.show_logs_in_terminal = True  # default ON per user request
        
    def is_running(self):
        """Check if OP25 process is running"""
        # Prefer our managed process handle if available
        if self.process and self.process.poll() is None:
            return True
        # Fallback: search processes
        return self._find_op25_process() is not None
        
    def _find_op25_process(self):
        """Find existing OP25 process by name"""
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                if proc.info['name'] and ('multi_rx.py' in proc.info['name'] or 'rx.py' in proc.info['name']):
                    return proc
                if proc.info['cmdline']:
                    cmdline = ' '.join(proc.info['cmdline'])
                    if 'multi_rx.py' in cmdline or 'rx.py' in cmdline or 'op25' in cmdline.lower():
                        return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return None
        
    def _find_all_op25_processes(self):
        """Find ALL existing OP25 processes by name"""
        processes = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    # Only consider processes that look like our multi_rx execution
                    if proc.info['cmdline']:
                        cmdline = ' '.join(proc.info['cmdline'])
                        if 'multi_rx.py' in cmdline:
                            processes.append(proc)
                        # Legacy support: rx.py
                        elif 'rx.py' in cmdline:
                            processes.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        return processes
    
    def _log_monitor_thread(self):
        """Monitor OP25 process logs and display in terminal (stdout only)"""
        if not self.process:
            return
            
        try:
            # Monitor both stdout and stderr
            while self.process and self.process.poll() is None:
                # Use select to check if data is available (Unix/Linux only)
                if hasattr(select, 'select'):
                    ready, _, _ = select.select([self.process.stdout], [], [], 0.1)
                    for stream in ready:
                        line = stream.readline()
                        if not line:
                            continue
                        # Print raw line to terminal only
                        if self.show_logs_in_terminal:
                            print(line.rstrip())
                else:
                    # Fallback: blocking readline with small sleep to reduce CPU
                    line = self.process.stdout.readline()
                    if line and self.show_logs_in_terminal:
                        print(line.rstrip())
                    time.sleep(0.05)
                    
        except Exception as e:
            logging.debug(f"Log monitor thread error: {e}")
    
    def get_recent_logs(self, count=50):
        """Terminal-only mode: no in-memory buffering, return empty list"""
        return []
    
    def set_terminal_logging(self, enabled):
        """Enable or disable terminal log display"""
        self.show_logs_in_terminal = enabled
        if enabled:
            print("\033[92m[Scanner] Multi_rx terminal logging enabled\033[0m")
        else:
            print("\033[93m[Scanner] Multi_rx terminal logging disabled\033[0m")
        
    def get_status(self):
        """Get detailed status of OP25 process"""
        proc = self._find_op25_process()
        if proc:
            try:
                return {
                    "running": True,
                    "pid": proc.pid,
                    "cpu_percent": proc.cpu_percent(),
                    "memory_mb": proc.memory_info().rss / 1024 / 1024,
                    "status": proc.status(),
                    "create_time": proc.create_time(),
                    "restart_count": self.restart_count
                }
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        
        return {
            "running": False,
            "pid": None,
            "restart_count": self.restart_count
        }
        
    def start(self, config_file=None):
        """Start OP25 process"""
        # Prevent concurrent starts
        with self._start_lock:
            if self.is_running():
                logging.info("OP25 is already running")
                return True
            
        try:
            config_file = config_file or self.config_file
            
            # Validate/resolve configuration file
            if config_file and not Path(config_file).exists():
                # Try relative to op25_path
                candidate = Path(self.op25_path) / config_file
                if not candidate.exists():
                    logging.error(f"Config file not found: {config_file}")
                    return False
                config_file = str(candidate)

            # Build command line arguments
            cmd = self._build_command(config_file)
            
            logging.info(f"Starting OP25 with command: {' '.join(cmd)}")
            
            # Set working directory to OP25 apps directory
            cwd = self.op25_path if os.path.exists(self.op25_path) else None
            
            # Start process with proper environment
            env = os.environ.copy()
            env['PYTHONPATH'] = self.op25_path + ':' + env.get('PYTHONPATH', '')
            
            # Inherit parent's stdout/stderr so multi_rx logs print directly to terminal
            # No pipes, no background reader threads – lowest overhead, avoids freezes
            self.process = subprocess.Popen(
                cmd,
                cwd=cwd,
                env=env,
                preexec_fn=os.setsid  # Create new process group
            )
            
            # Wait a moment to see if process starts successfully
            time.sleep(2)
            
            if self.process and self.process.poll() is None:
                logging.info(f"OP25 started successfully with PID {self.process.pid}")
                # Write PID file
                try:
                    self.pid_file.write_text(str(self.process.pid))
                except Exception as e:
                    logging.debug(f"Could not write pid file: {e}")
                self._start_monitoring()
                return True
            else:
                output = b""
                try:
                    output = self.process.stdout.read() or b""
                except Exception:
                    pass
                logging.error(f"OP25 failed to start. Output: {output.decode(errors='ignore')}")
                return False
                
        except Exception as e:
            logging.error(f"Error starting OP25: {e}")
            return False
            
    def _build_command(self, config_file):
        """Build OP25 command line for multi_rx.py"""
        cmd = ["python3", "multi_rx.py"]
        
        # multi_rx.py uses a simpler command format: multi_rx.py -c cfg.json
        # Add configuration file
        config_path = Path(config_file)
        if config_path.exists():
            cmd.extend(["-c", str(config_path)])
        elif (Path(self.op25_path) / config_file).exists():
            cmd.extend(["-c", str(Path(self.op25_path) / config_file)])
        else:
            # Default to cfg.json if no specific config file found
            cmd.extend(["-c", "cfg.json"])
            logging.info(f"Using default config file: cfg.json")
            
        return cmd
        
    def stop(self, force=False):
        """Stop OP25 process"""
        stopped = False
        
        # Stop our managed process
        if self.process and self.process.poll() is None:
            try:
                if force:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                else:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    
                # Wait for graceful shutdown
                try:
                    self.process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                    self.process.wait()
                    
                logging.info("OP25 process stopped")
                stopped = True
                
            except Exception as e:
                logging.error(f"Error stopping OP25 process: {e}")
                
        # Stop ALL other OP25 processes except our managed one
        all_procs = self._find_all_op25_processes()
        if all_procs:
            logging.info(f"Found {len(all_procs)} OP25 processes to stop")
            for proc in all_procs:
                if self.process and proc.pid == self.process.pid:
                    continue
                try:
                    if force:
                        proc.kill()
                    else:
                        proc.terminate()
                        
                    proc.wait(timeout=10)
                    logging.info(f"Stopped OP25 process PID {proc.pid}")
                    stopped = True
                    
                except (psutil.TimeoutExpired, psutil.NoSuchProcess):
                    if not force:
                        try:
                            proc.kill()
                            proc.wait(timeout=5)
                            logging.info(f"Force-killed OP25 process PID {proc.pid}")
                            stopped = True
                        except:
                            pass
                except Exception as e:
                    logging.error(f"Error stopping OP25 process {proc.pid}: {e}")
                
        # Stop monitoring
        if self.monitoring_thread:
            self.stop_event.set()
            self.monitoring_thread.join(timeout=5)
            self.monitoring_thread = None
        # Join log thread if running
        if self.log_thread:
            try:
                self.log_thread.join(timeout=2)
            except Exception:
                pass
            self.log_thread = None

        # Close pipes to unblock any readers
        try:
            if self.process and self.process.stdout:
                self.process.stdout.close()
        except Exception:
            pass
            
        self.process = None

        # Remove PID file
        try:
            if self.pid_file.exists():
                self.pid_file.unlink()
        except Exception:
            pass
        return stopped
        
    def restart(self):
        """Restart OP25 process"""
        current_time = time.time()
        
        # Check restart cooldown
        # Exponential backoff up to 5 minutes
        dynamic_cooldown = min(300, max(self.restart_cooldown, 2 ** self.restart_count))
        if current_time - self.last_restart_time < dynamic_cooldown:
            logging.warning("OP25 restart on cooldown")
            return False
            
        # Check restart limit
        if self.restart_count >= self.max_restarts:
            logging.error("OP25 restart limit exceeded")
            return False
            
        logging.info("Restarting OP25...")
        
        # Stop current process
        self.stop()
        time.sleep(2)
        
        # Start new process
        if self.start():
            self.restart_count += 1
            self.last_restart_time = current_time
            logging.info(f"OP25 restarted successfully (restart #{self.restart_count})")
            return True
        else:
            logging.error("Failed to restart OP25")
            return False
            
    def _start_monitoring(self):
        """Start monitoring threads"""
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            return
            
        self.stop_event.clear()
        
        # Start process health monitoring thread
        self.monitoring_thread = Thread(target=self._monitor_process, daemon=True)
        self.monitoring_thread.start()
        
        # When inheriting stdout/stderr, there's no need for a log thread
        print("\033[92m[Scanner] Multi_rx logs printing directly to terminal\033[0m")
        
    def _monitor_process(self):
        """Monitor OP25 process health"""
        logging.info("Started OP25 process monitoring")
        
        while not self.stop_event.wait(10):  # Check every 10 seconds
            try:
                if not self.is_running():
                    logging.warning("OP25 process died unexpectedly")
                    
                    # Attempt automatic restart
                    if self.settings.get("op25_auto_restart", True):
                        if self.restart():
                            logging.info("OP25 automatically restarted")
                        else:
                            logging.error("Failed to automatically restart OP25")
                            break
                    else:
                        break
                        
            except Exception as e:
                logging.error(f"Error in OP25 monitoring: {e}")
                
        logging.info("OP25 monitoring stopped")
        
    def get_logs(self, lines=50):
        """Get recent OP25 logs"""
        # Prefer the in-memory queue, which the log thread fills
        return self.get_recent_logs(lines)
        
    def create_default_config(self):
        """Create default OP25 configuration files"""
        try:
            # Create trunk.tsv
            trunk_content = [
                '"Sysname"\t"Control Channel List"\t"Offset"\t"NAC"\t"Modulation"\t"TGID Tags File"\t"Whitelist"\t"Blacklist"\t"Center Frequency"',
                '"Local System"\t"460.025"\t"0"\t"659"\t"cqpsk"\t"talkgroups.tsv"\t""\t""\t""'
            ]
            
            trunk_path = Path("trunk.tsv")
            with open(trunk_path, 'w') as f:
                f.write('\n'.join(trunk_content))
            logging.info(f"Created default trunk.tsv: {trunk_path}")
            
            # Create basic scanner.json if it doesn't exist
            config_path = Path(self.config_file)
            if not config_path.exists():
                config = {
                    "channels": {
                        "control_channel": {
                            "frequency": 460025000,
                            "bandwidth": 12500,
                            "center_frequency": 460000000
                        }
                    },
                    "trunking": {
                        "system_name": "Local System", 
                        "nac": 659,
                        "sysid": 659,
                        "wacn": 48193
                    },
                    "audio": {
                        "sample_rate": 8000,
                        "output_device": "default"
                    },
                    "logging": {
                        "level": 1,
                        "file": "/tmp/op25.log"
                    }
                }
                
                import json
                with open(config_path, 'w') as f:
                    json.dump(config, f, indent=4)
                logging.info(f"Created default scanner.json: {config_path}")
            
            return True
            
        except Exception as e:
            logging.error(f"Error creating OP25 config files: {e}")
            return False
            
    def cleanup(self):
        """Clean up resources"""
        self.stop()
        
    def kill_all_op25_processes(self):
        """Emergency method to kill ALL OP25 processes on the system"""
        all_procs = self._find_all_op25_processes()
        killed_count = 0
        
        if all_procs:
            logging.warning(f"Found {len(all_procs)} OP25 processes to kill")
            for proc in all_procs:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                    logging.info(f"Killed OP25 process PID {proc.pid}")
                    killed_count += 1
                except Exception as e:
                    logging.error(f"Failed to kill OP25 process {proc.pid}: {e}")
        
        logging.info(f"Killed {killed_count} OP25 processes")
        return killed_count
        
    def __del__(self):
        """Destructor"""
        try:
            self.cleanup()
        except:
            pass