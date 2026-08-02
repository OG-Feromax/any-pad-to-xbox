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

---

## Troubleshooting

**Game doesn’t see a controller**  
Confirm **Virtual Xbox on** / **Active**. Unplug and replug after Enable. On Steam, try disabling Steam Input for that game while testing.

**Password again?**  
Expected for Enable / Disable / first Install. Not for clicking buttons on the diagram while mapping.

**Disable the virtual pad**  
Use **Disable** in the app.

**Remove system integration**  
There’s no GUI uninstall yet. Stop any `xboxdrv@…` units, then remove:

- `/usr/local/bin/any-pad-to-xbox-runner`
- `/usr/local/lib/any-pad-to-xbox/`
- `/etc/systemd/system/xboxdrv@.service`
- `/etc/udev/rules.d/99-any-pad-to-xbox.rules` (if present)

Reload systemd/udev after. If you installed from a future AUR package, `sudo pacman -Rns any-pad-to-xbox-git` is cleaner.

---

## Layout

| Path | Role |
|------|------|
| `scripts/any-pad-to-xbox` | Dev launcher (`uv`) |
| `src/any_pad_to_xbox/` | PySide6 UI + core |
| `packaging/xpad_bridge.py` | Physical → Xbox uinput bridge |
| `packaging/xboxdrv_runner.py` | Hotplug runner (systemd) |
| `packaging/aur/` | AUR git package |
| `assets/` | Xbox diagram + hit regions |

```bash
./scripts/any-pad-to-xbox
sudo ./packaging/install-system.sh   # system bits only
```

---

## License

[MIT](LICENSE)
