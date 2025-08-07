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
                reader = csv.reader(f, delimiter='\t')
                headers = next(reader, None)
                # Flexible format detection:
                # - Minimal: TGID \t Name
                # - Extended: TGID \t Department \t Description \t Priority \t Type
                has_header = False
                if headers and any(h.upper() in ("TGID", "NAME", "DEPARTMENT") for h in headers):
                    has_header = True
                else:
                    # If first row looks numeric TGID, treat it as data
                    if headers is not None:
                        try:
                            int(headers[0])
                        except Exception:
                            has_header = True
                        else:
                            # push back the first line as data
                            f.seek(0)
                            reader = csv.reader(f, delimiter='\t')

                for row in reader:
                    if not row or len(row) == 0:
                        continue
                    try:
                        tgid = int(row[0])
                    except Exception as e:
                        logging.warning(f"Invalid TGID row: {row}")
                        continue

                    # Defaults
                    name = ''
                    department = 'Unknown'
                    description = ''
                    priority = 'Medium'
                    tg_type = ''

                    if has_header and headers:
                        # Map by header names if present
                        # Re-read as DictReader for this line for safety
                        # Simpler: build a dict manually
                        row_dict = {headers[i]: row[i] for i in range(min(len(headers), len(row)))}
                        name = row_dict.get('Name') or row_dict.get('Description') or ''
                        department = row_dict.get('Department', department)
                        description = row_dict.get('Description', name)
                        priority = row_dict.get('Priority', priority)
                        tg_type = row_dict.get('Type', tg_type)
                    else:
                        # Positional minimal format
                        if len(row) >= 2:
                            name = row[1]
                            description = name
                        if len(row) >= 3:
                            department = row[2]
                        if len(row) >= 4:
                            priority = row[3]
                        if len(row) >= 5:
                            tg_type = row[4]

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