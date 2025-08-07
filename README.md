# Scanner Project

A comprehensive radio scanner interface system designed for Raspberry Pi with OP25 integration.

## Features

- **Real-time Scanner Display**: Shows active radio transmissions with system info, frequencies, and talkgroup data
- **Dual Display Support**: Both TFT (480x320) and OLED (128x64) displays
- **Physical Controls**: Rotary encoder and buttons for hardware-based navigation
- **Complete Menu System**: Settings management through hierarchical menus
- **OP25 Integration**: Connects to OP25 digital radio software for trunk radio monitoring
- **OP25 Process Management**: Start, stop, restart, and monitor OP25 automatically
- **Talkgroup Management**: Department/agency name lookup and priority color coding
- **Robust Error Handling**: Graceful fallbacks and comprehensive logging
- **Process Monitoring**: Automatic restart of failed processes with health monitoring

## Hardware Requirements

- **Raspberry Pi** (3B+ or newer recommended)
- **TFT Display** (480x320) connected via framebuffer (`/dev/fb1`)
- **OLED Display** (128x64) via I2C (SSD1306)
- **Physical Controls**: 
  - 3 buttons (GPIO 19, 21, 26)
  - Rotary encoder (GPIO 16, 20)
- **OP25 Software** running locally on port 8080

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd ScannerProject
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Configure your talkgroups in `talkgroups.tsv`
4. Adjust settings in `settings.json` if needed
5. Ensure OP25 is running and accessible

## Usage

### Starting the Scanner

```bash
python -m scanner.scanner_main
```

### Menu Navigation

- **Hold Push Button (1 sec)**: Enter menu system
- **Back Button**: Alternative menu entry or go back
- **Rotary Encoder**: Navigate menu items
- **Confirm Button**: Select menu item or adjust setting

### Menu Structure

- **Scanner Control**: Auto scan, priority scan, scan delay settings
- **Audio Settings**: Volume, mute, recording controls
- **Display Settings**: Brightness, timeout, debug display
- **System Settings**: API configuration, system restart options
- **OP25 Management**: Start/stop/restart OP25, view status, configuration, and logs
- **Information**: System status, OP25 status, network info

## Configuration Files

### settings.json
Contains all system settings including:
- Audio levels and recording settings
- Display brightness and timeout
- OP25 connection parameters
- OP25 process management settings
- Scan behavior settings

### scanner.json
OP25 configuration file containing:
- Channel and frequency settings
- Trunking system parameters
- Audio output configuration
- Logging preferences

### trunk.tsv
OP25 trunk system configuration file:
- System definitions with control channels
- NAC, modulation, and frequency settings
- Links to talkgroup files
- Compatible with OP25 rx.py -T option

### talkgroups.tsv
Tab-separated file containing:
- TGID (Talkgroup ID)
- Department name
- Description
- Priority level (High/Medium/Low)

## Logging

Logs are written to `/tmp/scanner.log` and console. Log level can be configured in settings.json.

## Development

The project follows a modular design:

- `scanner_main.py`: Main application loop and initialization
- `settings_manager.py`: Configuration management
- `talkgroup_manager.py`: Talkgroup data handling
- `op25_client.py`: OP25 API communication
- `op25_manager.py`: OP25 process management and monitoring
- `display_manager.py`: TFT and OLED display control
- `input_manager.py`: GPIO input handling with debouncing
- `menu_system.py`: Complete menu system implementation

## Troubleshooting

### Display Issues
- Check framebuffer permissions: `ls -l /dev/fb1`
- Verify I2C is enabled: `sudo raspi-config`
- Check display connections

### GPIO Issues
- Ensure user is in gpio group: `sudo usermod -a -G gpio $USER`
- Check pin assignments match your hardware

### OP25 Issues
- **Process Management**: Use menu system to start/stop/restart OP25
- **Configuration**: Check `scanner.json` for OP25 settings
- **Path Issues**: Verify `op25_path` in settings.json points to OP25 installation
- **Permissions**: Ensure user can execute OP25 rx.py script
- **Dependencies**: Check OP25 prerequisites (GNU Radio, etc.)

### OP25 Configuration
The system includes default configurations:
- `scanner.json`: Basic OP25 configuration
- `trunk.tsv`: Sample talkgroup definitions
- Settings can be adjusted through the menu system

## License

[Add your license information here]