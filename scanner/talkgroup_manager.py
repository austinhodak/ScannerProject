# --- talkgroup_manager.py ---
import csv
import os
import logging

class TalkgroupManager:
    def __init__(self, filepath):
        self.filepath = filepath
        self.talkgroups = {}
        self.load()
        
    def load(self):
        """Load talkgroups from TSV file"""
        if not os.path.exists(self.filepath):
            logging.warning(f"Talkgroup file not found: {self.filepath}")
            return
            
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith('#'):
                        continue
                    # If the line has tabs, treat as TSV; otherwise, support space-separated minimal format
                    if '\t' in line:
                        parts = [c.strip() for c in line.split('\t')]
                    else:
                        # Minimal format: first token is TGID, remainder is Name
                        # Split on any whitespace; keep remainder intact
                        parts_all = line.split()
                        if len(parts_all) < 2:
                            continue
                        tgid_str = parts_all[0]
                        name_rest = line[len(tgid_str):].strip()
                        parts = [tgid_str, name_rest]

                    # Skip header-like lines
                    if parts[0].lower() == 'tgid':
                        continue
                    try:
                        tgid = int(parts[0])
                    except Exception:
                        logging.debug(f"Skipping non-numeric TGID row: {parts}")
                        continue

                    # Defaults
                    name = ''
                    department = 'Unknown'
                    description = ''
                    priority = 'Medium'
                    tg_type = ''

                    if len(parts) >= 2:
                        name = parts[1]
                        description = name
                    if len(parts) >= 3:
                        department = parts[2]
                    if len(parts) >= 4:
                        priority = parts[3]
                    if len(parts) >= 5:
                        tg_type = parts[4]

                    self.talkgroups[tgid] = {
                        'department': department,
                        'description': description,
                        'priority': priority,
                        'type': tg_type,
                        'name': name,
                    }
                        
            logging.info(f"Loaded {len(self.talkgroups)} talkgroups")
            
        except Exception as e:
            logging.error(f"Error loading talkgroups: {e}")
            
    def lookup(self, tgid):
        """Get talkgroup information by TGID"""
        if tgid is None:
            return None
            
        try:
            tgid = int(tgid)
            return self.talkgroups.get(tgid)
        except (ValueError, TypeError):
            return None
            
    def get_department(self, tgid):
        """Get department name for a TGID"""
        info = self.lookup(tgid)
        return info['department'] if info else 'Unknown'
        
    def get_description(self, tgid):
        """Get description for a TGID"""
        info = self.lookup(tgid)
        return info['description'] if info else ''
        
    def get_priority(self, tgid):
        """Get priority level for a TGID"""
        info = self.lookup(tgid)
        return info['priority'] if info else 'Medium'
        
    def is_high_priority(self, tgid):
        """Check if TGID is high priority"""
        return self.get_priority(tgid) == 'High'
        
    def get_all_talkgroups(self):
        """Get all talkgroups as a dictionary"""
        return self.talkgroups.copy()
        
    def add_talkgroup(self, tgid, department, description="", priority="Medium"):
        """Add a new talkgroup"""
        try:
            tgid = int(tgid)
            self.talkgroups[tgid] = {
                'department': department,
                'description': description,
                'priority': priority
            }
            self.save()
            return True
        except (ValueError, TypeError):
            return False
            
    def save(self):
        """Save talkgroups back to TSV file"""
        try:
            with open(self.filepath, 'w', encoding='utf-8', newline='') as f:
                writer = csv.writer(f, delimiter='\t')
                writer.writerow(['TGID', 'Name', 'Department', 'Description', 'Priority', 'Type'])
                for tgid, info in sorted(self.talkgroups.items()):
                    writer.writerow([
                        tgid,
                        info.get('name', ''),
                        info.get('department', ''),
                        info.get('description', ''),
                        info.get('priority', ''),
                        info.get('type', ''),
                    ])
                    
        except Exception as e:
            logging.error(f"Error saving talkgroups: {e}")