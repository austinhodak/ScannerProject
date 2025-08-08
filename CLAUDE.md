# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Scanner Project is a comprehensive radio scanner interface system designed for Raspberry Pi with OP25 integration. It provides a complete hardware control interface for digital radio monitoring with dual display support (TFT and OLED), physical controls, and automated OP25 process management.

## Commands

### Running the Application
```bash
python -m scanner.scanner_main
```

### Testing
```bash
python test_scanner.py
```

### Installing Dependencies
```bash
pip install -r requirements.txt
```

### OP25 Management
The system includes built-in OP25 process management. OP25 can be controlled through the menu system or configured for auto-start in `settings.json`.

## Architecture Overview

### Core Components
- **scanner_main.py**: Main application entry point with event loop, signal handling, and component orchestration
- **settings_manager.py**: Configuration management with defaults and JSON persistence  
- **display_manager.py**: Dual display controller (TFT framebuffer + OLED I2C) with caching and throttling
- **input_manager.py**: GPIO input handling with debouncing for rotary encoder and buttons
- **menu_system.py**: Complete hierarchical menu system for settings and system control
- **op25_client.py**: OP25 HTTP API client with data parsing and connection management
- **op25_manager.py**: OP25 process lifecycle management (start/stop/restart/monitoring)
- **talkgroup_manager.py**: Talkgroup database management with priority handling

### Threading Architecture
- Main thread: UI updates, input processing, volume control
- OP25Client thread: Continuous polling of OP25 API for radio data  
- InputManager thread: GPIO monitoring with event queuing
- All threads are daemon threads for clean shutdown

### Data Flow
1. OP25Client polls HTTP API (`http://localhost:8080`) for radio transmission data
2. Parsed data flows to DisplayManager for visual presentation
3. InputManager processes GPIO events and queues them for main loop
4. MenuSystem intercepts input when active, otherwise main loop handles scanner display
5. SettingsManager provides configuration persistence across all components

### Hardware Integration
- **TFT Display**: 480x320 via framebuffer (`/dev/fb1`) with direct memory mapping
- **OLED Display**: 128x64 SSD1306 via I2C with scrolling text support  
- **GPIO Controls**: Rotary encoder (GPIO 16,20) and buttons (GPIO 19,21,26)
- **Audio**: System volume control via PulseAudio/ALSA integration

### Configuration Files
- **settings.json**: System configuration with OP25 parameters, display settings, and feature flags
- **talkgroups.tsv**: Talkgroup database with department names and priority levels
- **scanner.json**: OP25 configuration file referenced by OP25 process
- **trunk.tsv**: OP25 trunking system definitions

### Key Design Patterns
- Component injection: All managers passed to MenuSystem for coordinated control
- State caching: DisplayManager caches signatures to prevent unnecessary redraws
- Graceful degradation: System works without hardware (falls back to console output)
- Process management: Automatic OP25 restart on failures with configurable parameters
- Error resilience: Connection retries, fallback displays, and comprehensive logging

### Development Notes
- Hardware-specific imports are conditionally loaded (RPi.GPIO, adafruit libraries)
- Platform detection enables development on non-Pi systems
- Logging configured to both file (`/tmp/scanner.log`) and console
- Signal handlers ensure clean shutdown of all components and processes
- Memory management includes periodic garbage collection for long-running operations