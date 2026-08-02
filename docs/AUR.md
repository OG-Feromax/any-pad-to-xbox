# Publicar na AUR (primeira vez)

Este guia assume Arch/CachyOS e que o código já está no GitHub:

`https://github.com/OG-Feromax/any-pad-to-xbox`

## 1. Conta na AUR

1. Crie conta em <https://aur.archlinux.org/register>.
2. Em **My Account**, cole a chave pública SSH (`~/.ssh/id_ed25519.pub`).
3. Confirme o e-mail.

## 2. Ferramentas locais

```bash
sudo pacman -S --needed base-devel git
```

Opcional, para gerar `.SRCINFO` automaticamente:

```bash
sudo pacman -S --needed pacman-contrib   # fornece makepkg
# ou: yay -S namcap   # valida o PKGBUILD
```

## 3. Clone o repositório AUR (pacote vazio no começo)

Nome sugerido: **`any-pad-to-xbox-git`** (sempre puxa o GitHub).

```bash
cd ~/Builds
git clone ssh://aur@aur.archlinux.org/any-pad-to-xbox-git.git
cd any-pad-to-xbox-git
```

Se o clone falhar com “não existe”, na primeira vez você cria a pasta local e faz push — a AUR cria o repo no primeiro push com SSH da conta AUR.

```bash
mkdir -p ~/Builds/any-pad-to-xbox-git
cd ~/Builds/any-pad-to-xbox-git
cp ~/Builds/any-pad-to-xbox/packaging/aur/PKGBUILD .
# gere .SRCINFO (obrigatório na AUR)
makepkg --printsrcinfo > .SRCINFO
git init
git add PKGBUILD .SRCINFO
git commit -m "Initial import: any-pad-to-xbox-git"
git remote add origin ssh://aur@aur.archlinux.org/any-pad-to-xbox-git.git
git push -u origin master
```

> A branch padrão da AUR costuma ser `master` (não `main`).

## 4. Testar o pacote antes de publicar

```bash
cd ~/Builds/any-pad-to-xbox-git
makepkg -si
any-pad-to-xbox
```

Se algo quebrar, corrija o `PKGBUILD`, rode de novo `makepkg --printsrcinfo > .SRCINFO`, commit e push.

## 5. Atualizar depois de mudar o GitHub

```bash
cd ~/Builds/any-pad-to-xbox-git
# pkgver sobe sozinho no prepare() do PKGBUILD -git
makepkg -f
makepkg --printsrcinfo > .SRCINFO
git add PKGBUILD .SRCINFO
git commit -m "Update to latest upstream"
git push
```

## 6. Checklist rápido (revisores da AUR ligam para isso)

- [ ] `license=('MIT')` batendo com o `LICENSE` do GitHub  
- [ ] `depends` só com pacotes oficiais (`pyside6`, `python-evdev`, …)  
- [ ] Não instalar em `/home/seu-usuario`  
- [ ] `.SRCINFO` commitado e atualizado  
- [ ] `namcap PKGBUILD` e `namcap *.pkg.tar.zst` sem erros graves  

## 7. Depois do push

Em alguns minutos o pacote aparece em:

`https://aur.archlinux.org/packages/any-pad-to-xbox-git`

Usuários instalam com:

```bash
yay -S any-pad-to-xbox-git
```
