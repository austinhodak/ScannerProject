#!/usr/bin/env python3
"""
Test script for Scanner Project
Tests basic functionality without requiring hardware
"""

import sys
import os
import json
import tempfile
import logging
from pathlib import Path

# Add scanner module to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from scanner.settings_manager import SettingsManager
from scanner.talkgroup_manager import TalkgroupManager
from scanner.op25_client import OP25Client


def test_settings_manager():
    """Test settings manager functionality"""
    print("Testing Settings Manager...")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        test_settings = {"test_key": "test_value", "volume_level": 50}
        json.dump(test_settings, f)
        settings_file = f.name
    
    try:
        # Test loading existing settings
        settings = SettingsManager(settings_file)
        assert settings.get("test_key") == "test_value"
        assert settings.get("volume_level") == 50
        
        # Test default values
        assert settings.get("nonexistent", "default") == "default"
        
        # Test setting values
        settings.set("new_key", "new_value")
        assert settings.get("new_key") == "new_value"
        
        # Test defaults are loaded
        assert settings.get("brightness") == 75  # Should be from defaults
        
        print("✓ Settings Manager tests passed")
        
    finally:
        os.unlink(settings_file)


def test_talkgroup_manager():
    """Test talkgroup manager functionality"""
    print("Testing Talkgroup Manager...")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.tsv', delete=False) as f:
        f.write("TGID\tDepartment\tDescription\tPriority\n")
        f.write("1\tPolice\tPolice Dispatch\tHigh\n")
        f.write("2\tFire\tFire Dispatch\tHigh\n")
        f.write("100\tPublic Works\tMaintenance\tLow\n")
        talkgroups_file = f.name
    
    try:
        # Test loading talkgroups
        tg_mgr = TalkgroupManager(talkgroups_file)
        
        # Test lookup
        police_info = tg_mgr.lookup(1)
        assert police_info['department'] == 'Police'
        assert police_info['priority'] == 'High'
        
        # Test department lookup
        assert tg_mgr.get_department(1) == 'Police'
        assert tg_mgr.get_department(999) == 'Unknown'
        
        # Test priority
        assert tg_mgr.is_high_priority(1) == True
        assert tg_mgr.is_high_priority(100) == False
        
        # Test adding talkgroup
        assert tg_mgr.add_talkgroup(999, "Test Dept", "Test Description", "Medium")
        assert tg_mgr.get_department(999) == "Test Dept"
        
        print("✓ Talkgroup Manager tests passed")
        
    finally:
        os.unlink(talkgroups_file)


def test_op25_client():
    """Test OP25 client functionality"""
    print("Testing OP25 Client...")
    
    # Test initialization
    client = OP25Client("localhost", 8080)
    assert client.host == "localhost"
    assert client.port == 8080
    
    # Test data parsing with real OP25 format - active transmission
    active_transmission_data = [
        {
            "freq": 460550000,
            "tgid": 119,
            "nac": 25,
            "system": "Erie County",
            "json_type": "change_freq"
        },
        {
            "json_type": "trunk_update",
            "25": {
                "top_line": "NAC 0x19 WACN 0xa441 SYSID 0x19 460.025000/465.025000 tsbks 7728",
                "sysid": 25,
                "wacn": 42049
            },
            "srcaddr": 8190009,  # Non-zero = active transmission
            "grpaddr": 119,
            "encrypted": False,
            "nac": 25
        }
    ]
    
    system, freq, tgid, extra = client.parse(active_transmission_data)
    assert system == "Erie County"
    assert freq == 460.55  # Should be converted to MHz
    assert tgid == 119
    assert extra["srcaddr"] == 8190009
    assert extra["active"] == True
    
    # Test data parsing - no active transmission (srcaddr = 0)
    idle_data = [
        {
            "freq": 460025000,
            "system": "Erie County",
            "json_type": "change_freq"
        },
        {
            "json_type": "trunk_update",
            "25": {
                "top_line": "NAC 0x19 WACN 0xa441 SYSID 0x19 460.025000/465.025000 tsbks 7728",
                "sysid": 25,
                "wacn": 42049,
                "rxchan": 460025000,
                "frequency_data": {
                    "460550000": {
                        "type": "voice",
                        "tgids": [119, None],
                        "last_activity": "5.2"
                    }
                }
            },
            "srcaddr": 0,  # Zero = no active transmission
            "grpaddr": 0,
            "nac": 25
        }
    ]
    
    system, freq, tgid, extra = client.parse(idle_data)
    assert system == "Erie County"
    assert freq == 460.025  # Control channel frequency
    assert tgid == 119  # From recent activity
    assert extra["active"] == False
    
    # Test empty data
    system, freq, tgid, extra = client.parse([])
    assert system == "Unknown"
    assert freq is None
    assert tgid is None
    
    print("✓ OP25 Client tests passed")


def test_configuration_files():
    """Test that configuration files are valid"""
    print("Testing Configuration Files...")
    
    # Test settings.json
    settings_file = Path("settings.json")
    if settings_file.exists():
        with open(settings_file) as f:
            settings_data = json.load(f)
            assert isinstance(settings_data, dict)
            assert "volume_level" in settings_data
            print("✓ settings.json is valid")
    
    # Test talkgroups.tsv
    talkgroups_file = Path("talkgroups.tsv")
    if talkgroups_file.exists():
        tg_mgr = TalkgroupManager(str(talkgroups_file))
        talkgroups = tg_mgr.get_all_talkgroups()
        assert len(talkgroups) > 0
        print(f"✓ talkgroups.tsv loaded {len(talkgroups)} talkgroups")


def main():
    """Run all tests"""
    print("Scanner Project Test Suite")
    print("=" * 40)
    
    # Setup logging for tests
    logging.basicConfig(level=logging.WARNING)
    
    try:
        test_settings_manager()
        test_talkgroup_manager()
        test_op25_client()
        test_configuration_files()
        
        print("\n" + "=" * 40)
        print("✓ All tests passed!")
        return 0
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())