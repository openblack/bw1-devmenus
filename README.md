# Black & White developer key menus, switchable in game

`patch_devmenus.py` writes a copy of `runblack.exe` called `runblack_devmenus.exe` in which the developers'
leftover key menus can be switched on and off while you play. The original file is only read.

```
python patch_devmenus.py path\to\runblack.exe                 # writes runblack_devmenus.exe here
python patch_devmenus.py path\to\runblack.exe -o out\game.exe
```

It only accepts the **decrypted** `runblack.exe` from the unofficial 1.42 patch (SHA-256
`3f58bc02a6c421b4e66ef08716646bf0e1fa55ab292786edb521d7596ed48aba`). The encrypted retail executable is refused.

## Keys

Keys work in the 3D world only (not in the temple or menus).

| Keys | Effect |
|------|--------|
| **Ctrl+Alt+1** | Jeremy's menu on |
| **Ctrl+Alt+2** | Tim's menu on |
| **Ctrl+Alt+3** | George's menu on |
| **Ctrl+Alt+4** | Tom's menu on |
| **Ctrl+Alt+5** | the unnamed menu on |
| the same Ctrl+Alt+number again, or **Ctrl+Alt+0** | menus off |

One menu is on at a time. While it is on, only the keys on its list go to it (and lose their normal job);
H shows its help page. Ctrl+Shift+number camera bookmarks still work.

### Jeremy (Ctrl+Alt+1)

| Key | Label on his help page | What it does |
|-----|------------------------|--------------|
| H | (help) | shows the help page |
| W | "Divers (Help My Current Test)" | **spell cheat on/off**: every miracle available. Saved into save games |
| Z | "Go As Fast As Possible" | **as fast as possible on/off**: a game turn every frame, even while paused |
| R | "Free Move in Slow Motion" | toggles a flag nothing reads |
| C | "Cheat" | prints "Jeremy - Cheat", no effect |
| I, O, M, F | slow down, speed up, night time, footpaths | no effect |
| K | "Switch QuickClick Interface" | nothing |

### Tim (Ctrl+Alt+2)

O ("Force an Out of Sync") does nothing; the code was removed before release.

### George (Ctrl+Alt+3)

| Key | What it does |
|-----|--------------|
| W | shows the internet weather report, or "Internet Weather update system not loaded." |
| Shift+W | asks the long-gone weather service to reload |
| A | fake e-mail notification, "You got mail from bitch. Subject: lemons" |
| C | steps a weather symbol number 0..8 |
| B | shows the notification for that weather symbol |
| 3 | writes the help history to the Windows debug output (DebugView) |
| Alt+S | closes all dialogs and opens the multiplayer "start game" box (dialog test) |
| Shift+S | loading-box test, freezes the game for a second |

### Tom (Ctrl+Alt+4)

| Key | What it does |
|-----|--------------|
| W | no effect (wall-hugging debug view not in the release) |
| **Shift+F** | **deletes and rebuilds every land's `Data\Landscape\*.fot` footpath file**, throwing away the current game. Plain F in the original; the patch adds Shift as a safety catch |

### Unnamed (Ctrl+Alt+5)

| Key | What it does |
|-----|--------------|
| **Shift+A** | **hands your god to the computer** for good (reload a save to undo). Plain A in the original |

## Using it

Put `runblack_devmenus.exe` in a game folder and run it from there. Best use a copy of the whole game folder,
so Tom's Shift+F and cheat-flagged saves can't touch your real install. Single player only: Jeremy's W and Z
desync network games.

To undo: switch Jeremy's W and Z off, then Ctrl+Alt+0. On disk, delete `runblack_devmenus.exe`.

The patched program has not been run yet.

## What is patched

Addresses are for the fixed base 0x400000 (no relocations, no ASLR).

| File offset | Original | New | Why |
|-------------|----------|-----|-----|
| 0x240 | `5d 79 4a 00` | `00 80 4a 00` | `.text` VirtualSize grown to cover the zero padding where the stub lives |
| 0x290 | `00 9e 5f 00` | `00 a0 5f 00` | `.data` VirtualSize grown; the selected menu is kept at 0xFBFE00 |
| 0x23F2C6 (0x63F2C6) | `33 c0 66 a1 1c 16 9a 00` | `e9 95 96 26 00 90 90 90` | key handler jumps to the stub where an unbound in-world key is looked up |
| 0x4A8960 (0x8A8960) | 827 zero bytes | stub, key lists, messages | switches menus and routes listed keys to the selected handler |

Key lists (modifiers needed in brackets):

| Menu | List |
|------|------|
| Jeremy | H, K, C, I, O, M, F, R, W, Z |
| Tim | H, O |
| George | H, W, S (Shift or Alt), A, C, B, 3 |
| Tom | H, W, F (Shift) |
| unnamed | H, A (Shift) |

The handlers, from `PCInput.cpp`, are never called in the release build:

| Address | Handler |
|---------|---------|
| 0x640CB0 | shared developer routine (empty, `ret 8`) |
| 0x640CC0 | Jeremy |
| 0x640FA0 | Tim |
| 0x640FE0, 0x640FF0, 0x641000 | empty |
| 0x641010 | unnamed |
| 0x641080 | George |
| 0x641570 | Tom |

## Development

```
uv sync
uv run ruff format .
uv run pytest
RUNBLACK_EXE=path\to\runblack.exe uv run pytest   # also patch the real 1.42 runblack.exe
```
