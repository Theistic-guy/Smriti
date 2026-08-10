# Smriti 2.0

A tray-resident shloka reminder app — rewritten in PySide6.

## Quick start

```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
python main.py
```

Left-click the tray icon (the gold "S" medallion) to open Settings.
Right-click it for the full menu (show now, next, pause, quit).

## What changed in this update

- **CSV format now matches ShlokaManager exactly**: `Reference_Number, Shloka, Translation`
  (no more `speaker`/custom columns). `shlokas.csv` in this package is
  your real 117-shloka file.
- **Popup shows the verse only by default.** Two small icon-only
  buttons sit top-right: an **ⓘ "meaning" toggle** that reveals the
  translation in place (the card smoothly grows to fit it, and the
  auto-hide timer is paused the entire time it's open — a long
  translation will never get cut off mid-read) and a **✕ close**
  button. Neither button can take keyboard focus, so neither can ever
  trigger a system beep.
- **Default order is now shuffle** (matches how you described it
  already behaving) — configurable back to sequential in Settings.
- **Settings → Appearance**: font size default raised from 13 to 20,
  and the popup's default width/height increased slightly for it.
  Both are still freely adjustable (up or down) via spin boxes.
- **Settings → Timing** now has a **"Preview a shloka now"** button
  and a **"Restart random cycle"** button (reshuffles the order and
  immediately shows one) — both meant for quickly seeing the effect
  of appearance changes without waiting for the interval timer.

## What changed from the original Tkinter version

- Runs from the **system tray**, no persistent config window.
- The popup is **frameless, translucent, rounded, with a soft drop
  shadow** and a fade-in/fade-out animation instead of an instant
  appear/disappear.
- Settings panel is a **tabbed dialog** (Timing / Appearance /
  Behaviour / Content / Hotkeys) instead of 4 bare text fields — colors,
  fonts, opacity, corner radius, fade duration, shuffle vs. sequential,
  click-through mode, and more.
- **Scroll wheel** on the popup flips to next/previous shloka; **double
  click** advances; **right click** dismisses — in addition to the
  original drag-to-move and hotkey-dismiss behaviour.
- All settings persist via `QSettings` (Windows Registry / an ini file
  on Linux/Mac) instead of a hand-rolled config file.

## Project layout

```
main.py                    entry point
requirements.txt
shlokas.csv                sample data — same format as before, extended with columns
smriti/
  config.py                QSettings wrapper, single source of truth for every setting
  shloka_source.py         loads shlokas.csv, tracks position, sequential/shuffle
  popup.py                 the floating card: paint, drag, fade, wheel/double-click
  settings_dialog.py       tabbed settings UI
  tray.py                  QSystemTrayIcon + context menu
  global_hotkey.py         optional wrapper around the 'keyboard' package
  app.py                   controller: timers + wiring everything together
```

Nothing hardcodes another module's internals — `popup.py` reads
whatever `config.get(...)` currently holds every time it repaints, so
changes in Settings show up on the very next popup without restarting
anything.

## CSV format

```csv
reference,speaker,sanskrit,translation
SB 7.6.1,Prahlada Maharaja said:,"...verse text...","...translation..."
```

`speaker` and `translation` are optional — leave them blank if you
just want the verse and reference. Point Settings → Content at any
CSV file; it doesn't have to be a sibling file anymore.

## The global dismiss hotkey

Uses the `keyboard` package, which on Windows works out of the box,
but on Linux typically needs the app run as root (or your user added
to the `input` group) because it reads raw input devices. If
`keyboard` fails to register the hotkey, the app keeps running fine —
you can still dismiss the popup by right-clicking it or from the tray
menu. Check `controller.hotkeys.last_error` if you want to debug why
registration failed.

## Packaging as a standalone .exe (Windows)

```bash
pip install pyinstaller
pyinstaller --noconfirm --onefile --windowed --name Smriti ^
    --add-data "shlokas.csv;." ^
    main.py
```

The `--windowed` flag suppresses the console window. The built
`dist\Smriti.exe` will look for `shlokas.csv` next to itself at
runtime if no CSV has been chosen yet in Settings — or ship it via
`--add-data` and set the path once in Settings after first launch to
point at wherever you want your real, growing shloka collection to
live (e.g. inside your Obsidian vault).

## To make it start with Windows

Settings → there's a `startup/launch_with_windows` key already wired
into `config.py`, but actually creating the registry Run-key entry or
Startup-folder shortcut is OS-specific and isn't implemented yet —
flagging this deliberately rather than guessing your preferred
approach (Task Scheduler vs. Run key vs. shortcut in the Startup
folder all behave slightly differently). Happy to wire up whichever
you'd prefer.

## Ideas for next iterations

- Light/dark theme toggle is scaffolded (`appearance/theme`) but not
  yet wired into a second QSS palette — currently only dark is drawn.
- A "favorite this shloka" button, saved to a second CSV.
- Multiple popup styles (compact banner vs. card) selectable in
  Settings.
- A small preview pane inside Settings → Appearance so you see the
  card update live as you tweak colors, instead of needing to trigger
  a real popup.
