# Any Pad to Xbox

Linux tool that turns a generic USB gamepad into a **virtual Xbox 360 controller**.

Built on Arch (works on CachyOS and other Arch-based distros). Aimed at cheap USB encoders, arcade cabinets, DragonRise boards, fightsticks — anything that shows up as a weird joystick instead of something games actually understand.

You map buttons once in the GUI, hit **Enable**, and games see a normal Xbox 360 pad (`Microsoft X-Box 360 pad` over uinput). No xboxdrv.

The bridge is written for fighting-game mash: every physical edge is forwarded, and a down while already down forces a short up+down pulse so presses don’t get eaten.

---

## Requirements

- Arch Linux or derivative
- Python 3.11+
- Kernel `uinput` (usually already available: `sudo modprobe uinput`)
- Ability to approve admin prompts (`pkexec`) when installing/enabling the system service

---

## Install / run from source

```bash
git clone https://github.com/OG-Feromax/any-pad-to-xbox.git
cd any-pad-to-xbox
./scripts/any-pad-to-xbox
```

The launcher installs [`uv`](https://docs.astral.sh/uv/) if needed, syncs dependencies, and opens the app.

On first launch, if system integration isn’t installed yet, use **Install (asks for password)** in the UI. That copies the bridge, a small runner, and a systemd unit so a mapped pad can come back as Xbox after unplug/replug.

Every entry point that touches `/etc` renders the same script, so an install is either complete or it fails loudly — no path writes a subset of the files any more:

| you want | command |
|---|---|
| normal setup | **Install**, then select a pad and **Enable** |
| re-apply after a `git pull` | `./scripts/any-pad-to-xbox --reapply` (or **Enable** in the GUI) |
| see exactly what root would run | `./scripts/any-pad-to-xbox --print-script` |
| headless, for packagers | `sudo ./packaging/install-system.sh` |

The two rule files that make up the integration are `/etc/udev/rules.d/99-any-pad-to-xbox.rules` (start the bridge for a mapped pad) and `/etc/udev/rules.d/65-any-pad-to-xbox-hide.rules` (keep that pad out of game controller lists).

The status bar compares those installed files with what the app would write, so a `git pull` that changes rule generation shows up as **yellow — N system file(s) are behind this app** instead of sitting invisible behind a green bar. `--reapply` does the same check and refuses to ask for your password (or restart the bridge and blink the pad out of a running game) when there is nothing to write. `Enable` always writes — it restarts your pad by design.

Diagnostics mode is reported as a mode, not as a stale file: while `/etc/any-pad-to-xbox/diag_no_grab` exists the bar says **diagnostics mode is ON — games list the pad twice**, because that is true whether or not the app's environment agrees with it.

### Pad permissions

If the pad doesn’t show up (or can’t be read), add yourself to the `input` group, then log out and back in:

```bash
sudo usermod -aG input "$USER"
```

### AUR

An `any-pad-to-xbox-git` PKGBUILD lives under [`packaging/aur/`](packaging/aur/). It isn’t published on the AUR yet (registration was down when this was prepared). When it’s up:

```bash
yay -S any-pad-to-xbox-git
any-pad-to-xbox
```

The package places the bridge, runner and systemd unit; the udev rules and `/etc/any-pad-to-xbox/profiles.json` depend on which pads *you* map, so open the app, hit **Install** once, then **Enable** on each pad.

See [`docs/AUR.md`](docs/AUR.md) for the maintainer-side publish steps.

---

## Using the app

Flow is: **map → enable → test**.

1. Plug the pad in. It should appear under **Connected controllers**. Hit **Refresh** if it doesn’t.
2. Select it. If the top status says setup is missing, run **Install** once.
3. **Start mapping.** The diagram highlights a control in amber — press the matching control on your physical pad. Repeat. Skip anything you don’t have.
4. **Enable.** This may ask for your password; it starts the bridge / virtual pad. Status should show **Active** and **Virtual Xbox on**.
5. **Test.** Press buttons on the real pad. Green on the diagram is what the virtual Xbox is outputting — that’s what games see.

Mappings are stored in your home directory (no password required to save):

`~/.config/any-pad-to-xbox/profiles.json`

System copy used by the bridge after Enable:

`/etc/any-pad-to-xbox/profiles.json`

### Remapping later

**Remap** temporarily stops the virtual pad (password once) so the app can hear the hardware again. Change what you need, then **Enable** to apply.

### Diagram colors

- **Amber** — waiting for you to press something (learning)
- **Green** — live virtual Xbox output
- **Blue dashed** — direct pad preview (diagnostics only)

---

## Why does it ask for my password?

Saving a mapping does **not** need admin rights.

Password prompts are only for system work: installing the helper, starting/stopping the bridge, applying profiles into `/etc`, writing udev rules. Same idea as installing software with `pkexec`.

---

## Arcade / optical sticks

A lot of cab hardware (optical gates on a stick, DragonRise USB boards, etc.) is still **digital** under the hood — on/off per direction — even when Linux exposes `ABS_X` / `ABS_Y` with only a few values (e.g. 0 / 127 / 255).

Map those axes to the Xbox D-pad. You don’t need analog calibration.

## Mashing: what is guaranteed

Under mash a cheap encoder loses the “up” edge, and a game that polls state then sees one
held button instead of two presses. The bridge recovers that edge: a second down while the
button is already down is emitted as **up + SYN + down** (`xpad_bridge.py:325`). The SYN
between them is mandatory — a `0→1` inside the same report is invisible to state pollers.

Measured behaviour (`tests/test_mash_equivalence.py`):

| situation | result |
|---|---|
| presses with their real ups, any rate | **lossless** — 200 cycles in 1 s all come out |
| ups lost, presses ≥ 13 ms apart | **lossless**, one pulse each |
| ups lost, presses < 12 ms apart | treated as USB bounce and dropped (debounce window) |
| ups lost at 120/s | degrades by halving: ~60 presses/s survive |
| kernel autorepeat (`value == 2`) | ignored, not a press |

The 12 ms window is what makes a held button immune to bounce, so it is a deliberate
limit, not an oversight — and 83 presses/s on one button is beyond anything a hand does.

D-pad directions mapped from an analog axis are **level** state and are never pulsed: many
encoders re-send the same value while a direction is held, and pulsing that would make
every hold look like mash. For tap-dpad use `--dpad-as-button` (the SparkFun profile),
which maps directions to keys and therefore gets edge recovery.

### Where the milliseconds go

```bash
./scripts/mash-check --latency --seconds 15   # press the pad during the window
```

`--latency` compares **kernel timestamps**: the physical event when the kernel received the
USB report, the virtual one when uinput injected the translation. It needs diag mode, and
says so rather than returning "no samples" — while the bridge holds the exclusive grab, no
other reader sees the physical node at all. The number it gives is the kernel + bridge hop
only; expect well under a millisecond. The rest of the chain is not the bridge's:

| stage | typical | how to see it |
|---|---|---|
| USB polling of the pad | 0 to one poll interval (8–16 ms on these encoders) | `sudo lsusb -v -d 0079:0006 \| grep -i bInterval`; also shows as the gap lattice in the diag log |
| kernel input layer → bridge → uinput | < 0.1 ms | `--latency` |
| bridge translating one event | ~0.01 ms, ~0.04 ms worst | PHYS→EMIT delta in `/tmp/any-pad-bridge.*.diag` |
| game sampling input | 0 to one frame (16.7 ms at 60 Hz) | outside the app |

A wired pad pays the USB poll and the frame wait whether or not this bridge is in the path,
so the honest comparison is the middle rows, not the total.

Because the poll interval is the biggest item, it is the one worth measuring — and the one
you can change. `--poll` reads the same diag log and fits the lattice of inter-report gaps
(idle stretches and same-report bursts are both excluded, and the answer names the largest
interval that fits rather than the smallest, since every multiple of 8 is also a multiple of
1):

```bash
./scripts/mash-check --poll --now          # fits the log as it stands
```

To try shortening it, override the driver's interval and re-measure:

```bash
sudo sh -c 'echo 1 > /sys/module/usbhid/parameters/jspoll'
# unplug and replug the pad — usbhid reads the parameter at probe time, not on a live device
./scripts/mash-check --poll --now
```

Replug matters, and so does the hub: behind a transaction translator the device may not
actually reach 1 ms. A shorter interval costs roughly one URB per millisecond on that port.
To keep it across boots, put `options usbhid jspoll=1` in `/etc/modprobe.d/usbhid.conf`.

### Measuring it on your own pad

```bash
./scripts/mash-check --seconds 10     # mash now; counts what the game receives
```

That watches the virtual pad and prints presses per button, presses/s, the fastest gap,
and anything left stuck down. **Both modes wait for you** — nothing is measured by pressing
after a report command finishes.

For the strict side-by-side count you need diag mode, because the bridge normally holds an
exclusive grab on the physical pad and nothing can observe it separately:

```bash
ANY_PAD_DIAG_NO_GRAB=1 ./scripts/any-pad-to-xbox   # 1. start the app in diag mode
# 2. select the pad, click Enable                  (asks for your password)
./scripts/mash-check --diag --seconds 10           # 3. mash during the countdown
# 4. Enable again without the variable to go back
```

`--diag` reads `/tmp/any-pad-bridge.<event>.diag` and counts **only what arrived during its
own countdown** — presses from before you ran it belong to an earlier test, and the report
says which scope it used (`--now` deliberately means "the whole session"). One file per
mapped pad, since two bridges writing the same path would truncate each other. It joins the
two sides on code numbers (a physical `BTN_THUMB` is a virtual `BTN_A`) and scopes itself to
the profile of the pad that wrote the log; mixing in other pads' buttons invents losses that
never happened. A button mapped to `lt`/`rt` leaves the bridge as an axis ramp and is counted
as such. Axis-mapped directions are declared out of scope rather than skipped silently.

---

## Troubleshooting

**Game doesn’t see a controller**
Confirm **Virtual Xbox on** / **Active**. Unplug and replug after Enable. On Steam, try disabling Steam Input for that game while testing.

**Game sees a second controller that never responds**
The bridge grabs the physical pad, so it emits nothing — but grabbing does not stop *enumeration*, and SDL / RetroArch list every device tagged `ID_INPUT_JOYSTICK`. The install writes `65-any-pad-to-xbox-hide.rules` to clear that tag on mapped pads. Confirm it took:

```bash
udevadm info -q property /dev/input/event20 | grep ID_INPUT
```

A mapped physical pad should show `ID_INPUT=1` with **no** `ID_INPUT_JOYSTICK` line; the virtual Xbox pad keeps its tag. If the tag is still there, **Enable** again (the rules on disk may predate your last pull).

Two things this does **not** hide, and why:

- **Tools that scan device nodes instead of asking udev** — `jstest-gtk`, `antimicrox`, RetroArch's **joydev** input driver. The kernel still creates a `js` node for the grabbed pad, and those tools open `/dev/input/js*` by directory listing, so the pad appears. It is inert (the bridge holds the events). Use the **udev** input driver in RetroArch; don't trust `jstest-gtk` as a check for this feature.
- **`/dev/input/by-id/…-joystick` symlinks** on the physical pad. udev applies rules in lexical order, and the system's own `60-persistent-input.rules` creates that symlink from `ID_INPUT_JOYSTICK` *before* our `65-*` file clears the tag — so the symlink is made on every plug, replug included. It's a name, not an enumeration signal; games that filter by the property never see it.

One pad, one grabber — and **the first one wins**. Tested on a live node: a second
`EVIOCGRAB` fails with `EBUSY`, it does not take over. The bridge retries for 1.5 s and then
gives up, so if something else grabbed the pad first (antimicrox, another remapper) the
bridge dies and the pad never becomes an Xbox controller:

```bash
systemctl status "xboxdrv@event20.service"        # failed?
grep -i "busy\|error" /var/log/any-pad-to-xbox.log | tail
fuser -v /dev/input/event20                        # who else has it open
```

Fix by closing the other remapper, not by replugging.

**Pad stopped working and you edited `profiles.json` by hand**
The bridge refuses an unusable mapping instead of half-mapping the pad, and names every
bad entry:

```bash
grep -i "cannot be bridged" /var/log/any-pad-to-xbox.log
```

Expect something like `profile 'DragonRise Fliperama' cannot be bridged: evdev_keymap
'BTN_FAKEO' is not a known input code name`. It fails before the device is opened, so the
pad is never left grabbed-and-dead. Either fix the name or map it again in the app.

**Password again?**
Expected for Enable / Disable / first Install. Not for clicking buttons on the diagram while mapping.

**Reading the pad while it stays mapped (diagnostics)**
The bridge grabs the pad exclusively, so the live preview can’t see it. Run with `ANY_PAD_DIAG_NO_GRAB=1` and click **Enable** to have both read it:

```bash
ANY_PAD_DIAG_NO_GRAB=1 ./scripts/any-pad-to-xbox
```

That writes `/etc/any-pad-to-xbox/diag_no_grab`, which makes games see the physical pad again — debugging only. **It is a mode, not a test run: it stays on across reboots of the app and the machine until you turn it off**, because the hotplug runner reads that file on every plug. Enable once more without the variable (or run `--reapply` without it) to go back.

**Disable the virtual pad**  
Use **Disable** in the app.

**Remove system integration**  
There’s no GUI uninstall yet. Stop any `xboxdrv@…` units, then remove:

- `/usr/local/bin/any-pad-to-xbox-runner`
- `/usr/local/lib/any-pad-to-xbox/`
- `/etc/systemd/system/xboxdrv@.service`
- `/etc/udev/rules.d/99-any-pad-to-xbox.rules` (if present)
- `/etc/udev/rules.d/65-any-pad-to-xbox-hide.rules` (if present; hides mapped physical pads from games)

Reload systemd/udev after. If you installed from a future AUR package, `sudo pacman -Rns any-pad-to-xbox-git` is cleaner.

---

## Layout

| Path | Role |
|------|------|
| `scripts/any-pad-to-xbox` | Dev launcher (`uv`) |
| `src/any_pad_to_xbox/` | PySide6 UI + core |
| `src/any_pad_to_xbox/core/udev.py` | udev rule text (bridge + hide) |
| `src/any_pad_to_xbox/core/installer.py` | renders the one root install script |
| `packaging/xpad_bridge.py` | Physical → Xbox uinput bridge |
| `packaging/xboxdrv_runner.py` | Hotplug runner (systemd) |
| `packaging/aur/` | AUR git package |
| `assets/` | Xbox diagram + hit regions |
| `tests/` | pure-logic tests: no root, no pad, no Qt — run by `.github/workflows/tests.yml` |

```bash
./scripts/any-pad-to-xbox            # the app
uv run pytest                        # tests
./scripts/mash-check --seconds 10    # measure press fidelity on your pad
./scripts/any-pad-to-xbox --print-script   # the root script, without running it
sudo ./packaging/install-system.sh   # system bits only
```

`packaging/xpad_bridge.py` and `packaging/xboxdrv_runner.py` run under `/usr/bin/python3`, **outside** the venv — they must stay stdlib-only, and `tests/test_packaging_invariants.py` enforces it. Same reason `core/installer.py` imports nothing from PySide6: `install-system.sh` renders as root before any `uv sync` has happened.

---

## License

[MIT](LICENSE)
