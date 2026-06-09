# MojiTap

A lightweight desktop emoji picker built with **PyQt6** for Linux, with a global hotkey, system tray integration, configurable output modes, recent emoji history, and a skin-tone toggle directly in the picker UI.

## Features

- Global hotkey to open the picker
- System tray app with quick access menu
- Insert emojis by:
  - typing into the active window
  - copying to clipboard
  - or both
- Recent emoji history
- Searchable emoji catalog
- Skin-tone selector inside the picker
- Optional launch-on-login support
- Linux-focused behavior tuned for **KDE Plasma 6**

## Requirements

### Runtime requirements

- **Linux** desktop environment
- **Python 3.10+**
- `python3-venv`
- A working **system tray / status notifier**
- **XWayland** available when using Wayland

### Recommended Linux packages

The app works best on KDE Plasma 6 / Wayland when these tools are installed:

- `xdotool` — used for paste/type automation
- `wl-clipboard` — provides `wl-copy` for clipboard integration on Wayland

On Arch / CachyOS, install them with:

```bash
sudo pacman -S python python-virtualenv xdotool wl-clipboard
```

On Debian / Ubuntu:

```bash
sudo apt install python3 python3-venv xdotool wl-clipboard
```

## Python dependencies

Installed automatically from `requirements.txt`:

- `PyQt6`
- `emoji`
- `pynput`
- `pyperclip`
- `requests`
- `Pillow`

## Project layout

```text
MojiTap/
├── README.MD
├── requirements.txt
├── run.sh
├── build-linux.sh
└── src/
    ├── main.py
    ├── picker_window.py
    ├── settings_window.py
    ├── output_manager.py
    ├── hotkey_manager.py
    ├── startup_manager.py
    ├── emoji_data.py
    ├── emoji_image_loader.py
    └── config.py
```

## Quick start

From the project root:

```bash
./run.sh
```

To open the picker immediately on launch:

```bash
./run.sh --show
```

What `run.sh` does:

1. Creates a local virtual environment in `.venv` if needed
2. Installs Python dependencies from `requirements.txt`
3. Forces `QT_QPA_PLATFORM=xcb` on Linux for more reliable Plasma / Wayland behavior
4. Starts the tray application

## Usage

### Opening the picker

Use the configured global shortcut:

- Default: `Ctrl + Alt + E`

You can also:

- left-click the tray icon to open the picker
- right-click the tray icon for the tray menu

### Skin tones

The skin tone selector lives in the **main picker UI**, on the right side of the category bar.

Selecting a tone will:

- update tone-capable emojis shown in the picker
- update tone-capable category icons where applicable
- insert the selected skin-tone version when you click an emoji

### Output modes

Configure output behavior from **Settings → General**:

- **Type into active window**
- **Copy to clipboard**
- **Both**

## Linux / KDE Plasma notes

This project is currently tuned for **KDE Plasma 6**.

Important behavior notes:

- On Linux, the app defaults to `QT_QPA_PLATFORM=xcb`
- This means the app runs through **XWayland** even in a Wayland session
- That setup has proven more reliable for:
  - opening on the correct monitor
  - dismissing correctly
  - pasting into the active window

### Clipboard and typing behavior

- On Wayland, clipboard output prefers `wl-copy`
- Paste automation uses `xdotool key ctrl+v`
- If direct typing fails, clipboard output acts as the fallback path

## Configuration and data files

### Config file

Stored at:

```text
~/.config/mojitap/config.json
```

### Cache

Used for downloaded emoji packs and Unicode metadata:

```text
~/.cache/mojitap/
```

### Recent emoji state

Stored in the app config and updated automatically.

### Autostart entry

When enabled from Settings, Linux autostart is written to:

```text
~/.config/autostart/mojitap.desktop
```

## Building a single-file Linux executable

A build helper script is included:

```bash
./build-linux.sh
```

The build script:

1. Creates a dedicated build virtual environment in `.venv-build`
2. Installs project requirements
3. Installs `PyInstaller`
4. Builds a **single-file** Linux executable
5. Generates a `.desktop` launcher in `dist/`
6. Optionally asks whether to add the app to your applications menu
7. Writes the final binary to:

```text
dist/MojiTap
```

If you answer **yes** to the build script prompt, it also installs:

- a launcher into `~/.local/share/applications/`
- an icon into `~/.local/share/icons/hicolor/512x512/apps/`

That makes the app show up in your desktop environment's applications menu without requiring `sudo`.

### Build prerequisites

Make sure these are available before building:

- `python3`
- `python3-venv`
- `pip`
- a standard Linux userspace capable of running PyInstaller

On Arch / CachyOS, a typical setup is:

```bash
sudo pacman -S python python-virtualenv base-devel
```

## Running the built executable

After building:

```bash
./dist/MojiTap
```

The bundled executable keeps the same Linux behavior as the source launcher and defaults to `QT_QPA_PLATFORM=xcb` unless you override it explicitly.

## Troubleshooting

### The app opens but does not paste into another app

Check that these tools are installed:

- `xdotool`
- `wl-copy` (from `wl-clipboard`)

### The tray icon does not appear

Make sure your desktop environment supports a system tray / status notifier.

### The picker opens on the wrong monitor

This project is tuned for Plasma/KWin behavior. If you are using another desktop environment or compositor, window placement may differ.

### The global hotkey does not work

The Linux hotkey listener uses `pynput`. Desktop/session restrictions can interfere with global shortcuts depending on the environment.

## Development notes

Useful commands:

```bash
./run.sh
./run.sh --show
./build-linux.sh
```

## License

No license file is currently included in this repository. Add one if you plan to distribute the project publicly.
