# Publishing to the AUR (first time)

Assumes Arch/CachyOS and that the source is already on GitHub:

`https://github.com/OG-Feromax/any-pad-to-xbox`

## 1. AUR account

1. Register at <https://aur.archlinux.org/register> (when the site is up).
2. Under **My Account**, paste your SSH public key (`~/.ssh/id_ed25519.pub`).
3. Confirm your email.

## 2. Local tools

```bash
sudo pacman -S --needed base-devel git
```

Optional: `namcap` to lint the package.

## 3. AUR package repo

Suggested name: **`any-pad-to-xbox-git`** (tracks GitHub).

```bash
mkdir -p ~/Builds/any-pad-to-xbox-git
cd ~/Builds/any-pad-to-xbox-git
cp ~/Builds/any-pad-to-xbox/packaging/aur/PKGBUILD .
makepkg --printsrcinfo > .SRCINFO
git init
git add PKGBUILD .SRCINFO
git commit -m "Initial import: any-pad-to-xbox-git"
git remote add origin ssh://aur@aur.archlinux.org/any-pad-to-xbox-git.git
git push -u origin master
```

AUR’s default branch is usually `master`.

## 4. Test before relying on it

```bash
cd ~/Builds/any-pad-to-xbox-git
makepkg -si
any-pad-to-xbox
```

Fix the PKGBUILD if needed, regenerate `.SRCINFO`, commit, push.

## 5. After upstream changes

```bash
cd ~/Builds/any-pad-to-xbox-git
makepkg -f
makepkg --printsrcinfo > .SRCINFO
git add PKGBUILD .SRCINFO
git commit -m "Update to latest upstream"
git push
```

## Checklist

- [ ] `license=('MIT')` matches the GitHub `LICENSE`
- [ ] `depends` only official repos (`pyside6`, `python-evdev`, …)
- [ ] Nothing installed under `/home/...`
- [ ] `.SRCINFO` committed and current
- [ ] `namcap` clean enough for upload

Package page (once published):

`https://aur.archlinux.org/packages/any-pad-to-xbox-git`
