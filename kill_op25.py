#!/usr/bin/env python3
"""
Emergency script to kill all OP25 processes
Run this if you have too many rx.py processes running
"""
import psutil
import logging

logging.basicConfig(level=logging.INFO)

def find_all_op25_processes():
    """Find ALL OP25 processes"""
    processes = []
    try:
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            if proc.info['name'] and ('multi_rx.py' in proc.info['name'] or 'rx.py' in proc.info['name']):
                processes.append(proc)
            elif proc.info['cmdline']:
                cmdline = ' '.join(proc.info['cmdline'])
                if ('multi_rx.py' in cmdline or 'rx.py' in cmdline or 
                    ('python' in cmdline and ('multi_rx.py' in cmdline or 'rx.py' in cmdline))):
                    processes.append(proc)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return processes

def kill_all_op25():
    """Kill all OP25 processes"""
    all_procs = find_all_op25_processes()
    killed_count = 0
    
    if not all_procs:
        print("No OP25 processes found")
        return 0
    
    print(f"Found {len(all_procs)} OP25 processes to kill:")
    for proc in all_procs:
        try:
            print(f"  PID {proc.pid}: {' '.join(proc.cmdline())}")
        except:
            print(f"  PID {proc.pid}: <unknown command>")
    
    confirm = input("\nKill all these processes? (y/N): ")
    if confirm.lower() != 'y':
        print("Cancelled")
        return 0
    
    print("\nKilling processes...")
    for proc in all_procs:
        try:
            proc.kill()
            proc.wait(timeout=5)
            print(f"✓ Killed PID {proc.pid}")
            killed_count += 1
        except Exception as e:
            print(f"✗ Failed to kill PID {proc.pid}: {e}")
    
    print(f"\nKilled {killed_count} OP25 processes")
    return killed_count

if __name__ == "__main__":
    kill_all_op25()
