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
                reader = csv.DictReader(f, delimiter='\t')
                for row in reader:
                    try:
                        tgid = int(row['TGID'])
                        self.talkgroups[tgid] = {
                            'department': row.get('Department', 'Unknown'),
                            'description': row.get('Description', ''),
                            'priority': row.get('Priority', 'Medium')
                        }
                    except (ValueError, KeyError) as e:
                        logging.warning(f"Invalid talkgroup entry: {row}, error: {e}")
                        
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
                writer.writerow(['TGID', 'Department', 'Description', 'Priority'])
                
                for tgid, info in sorted(self.talkgroups.items()):
                    writer.writerow([
                        tgid,
                        info['department'],
                        info['description'],
                        info['priority']
                    ])
                    
        except Exception as e:
            logging.error(f"Error saving talkgroups: {e}")