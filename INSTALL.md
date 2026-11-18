# GhostHand install checklist (per machine / per agent)

Project location: wherever you cloned/copied this repo to (no absolute-path
dependency; copy the whole folder to the target machine and it works).

## A. Python package (once per agent runtime)

```bash
pip install -e /path/to/ghosthand
```

- After install, `from ghosthand import GhostDriver` works in any agent
- Editable mode: code changes take effect immediately, no reinstall needed
- Dependencies: Python 3.10+, playwright (`pip install playwright`; browser
  drivers ship with playwright, no separate chromium needed — attach mode
  reuses your existing browser by default)

## B. Browser extension (once per browser, shared by all agents)

The `extension/` folder is an MV3 extension that works on Edge / Chrome /
Brave / Arc and other Chromium browsers.

**Option 1: load unpacked (recommended, changes take effect immediately)**
1. Type `edge://extensions` in the address bar (`chrome://extensions` on Chrome)
2. Enable "Developer mode" (top left)
3. Click "Load unpacked" → select `/path/to/ghosthand/extension`
4. The ghost-hand icon in the toolbar means success

**Option 2: zip (when sending to others)**
- Zip the `extension/` folder, unzip on the target machine, load as above

## C. Usage per agent (two modes, pick one)

| Mode | Command | For |
|---|---|---|
| Shared browser (attach) | `GhostDriver().attach(new_tab=True)` | Serial agent tasks; the browser must be started with `--remote-debugging-port=9222` first |
| Isolated instance (launch) | `GhostDriver().launch(user_data_dir)` | Concurrent agents, one instance per agent, physically isolated |

**Note**: do not let multiple agents attach to the same 9222 port at once
(CDP clients fight over focus).

## D. Self-test (mandatory after install on a new machine)

```bash
python -m ghosthand selftest
```

10/10 = human trajectory / long-press / trusted / stealth all ready.

## E. Minimal checklist for another computer

Copy the whole `ghosthand/` folder over, then:
1. Install Python 3.10+
2. `pip install -e /path/to/ghosthand` (or the corresponding path on that machine)
3. Install the extension per B
4. Run the self-test per D