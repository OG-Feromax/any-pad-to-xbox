# Any Pad to Xbox

**Transforma qualquer controle USB genérico num Xbox 360 virtual no Linux.**

Feito para Arch Linux e derivados (CachyOS, EndeavourOS, Manjaro, etc.).  
Ideal para fliperama, fightstick, placa DragonRise, encoders baratos — qualquer pad que o jogo “não reconhece direito”.

> Em uma frase: você mapeia os botões uma vez na interface, clica **Enable**, e os jogos passam a ver um **controle Xbox 360** de verdade.

---

## O que este programa faz (e o que não faz)

| Faz | Não faz |
|-----|---------|
| Lê o seu pad genérico | Não precisa do `xboxdrv` antigo |
| Cria um **controle Xbox 360 virtual** (via kernel `uinput`) | Não “crackeia” nem altera jogos |
| Guarda o mapeamento e reaplica quando você pluga o pad | Não funciona em Windows/macOS |
| Serve bem para mash de fighting game (cada aperto conta) | Não substitui driver de placa de vídeo, etc. |

**Por que precisa de senha às vezes?**  
Só para instalar/ligar o serviço do sistema (como instalar um programa “de verdade”). O mapeamento dos botões fica na sua pasta de usuário — mapear **não** pede senha.

---

## Instalação — escolha um caminho

### Opção A — Pela AUR (recomendado no Arch / CachyOS)

Se você usa um helper AUR (`yay`, `paru`, …):

```bash
yay -S any-pad-to-xbox-git
```

Depois abra **Any Pad to Xbox** no menu de aplicativos, ou no terminal:

```bash
any-pad-to-xbox
```

> Ainda não está na AUR? Use a **Opção B** abaixo. O pacote `any-pad-to-xbox-git` deste repositório é o que vamos publicar.

---

### Opção B — Clonar e rodar (bem simples)

Você só precisa de internet na primeira vez.

1. Abra o **terminal**.
2. Cole estes comandos (um bloco de cada vez):

```bash
# 1) Baixar o projeto
git clone https://github.com/OG-Feromax/any-pad-to-xbox.git
cd any-pad-to-xbox

# 2) Abrir o programa (instala o gerenciador "uv" sozinho se precisar)
./scripts/any-pad-to-xbox
```

Na **primeira vez** a janela pode pedir para instalar a integração do sistema → clique em **Install (asks for password)** e digite a senha do seu usuário (é o `pkexec` / Polkit do Linux).

Pronto. O programa abre.

<details>
<summary>Se der erro de permissão no controle</summary>

No Arch, entrar no grupo `input` ajuda a ler o pad sem root:

```bash
sudo usermod -aG input "$USER"
```

Depois **saia da sessão e entre de novo** (ou reinicie).
</details>

---

## Como usar (passo a passo de noob)

Imagine três etapas: **Mapear → Testar → Ativar**.

### 1. Plugue o controle

- Conecte o pad USB.
- Ele deve aparecer na lista à esquerda (**Connected controllers**).
- Se não aparecer: clique **Refresh**, troque a porta USB, ou confira o grupo `input` acima.

### 2. Instale a parte do sistema (só uma vez)

- Se a barra de status disser que falta setup → **Install (asks for password)**.
- Isso coloca um “ajudante” no sistema para, quando o pad for plugado, nascer o Xbox virtual automaticamente.

### 3. Mapeie os botões

1. Selecione o seu controle na lista.
2. Clique **Start mapping**.
3. No desenho do Xbox, o botão em destaque fica **âmbar** (laranja).
4. Aperte **no seu pad físico** o botão correspondente.
5. Repita até mapear o que você precisa (A/B/X/Y, ombros, direcionais…).
6. Pode pular o que não existir no seu pad (**Skip**).

O mapeamento é salvo em:

`~/.config/any-pad-to-xbox/profiles.json`

### 4. Ative (Enable)

1. Clique **Enable** (pode pedir senha de novo — é para ligar o serviço).
2. O status deve ir para **Active** e aparecer **Virtual Xbox on**.
3. Agora os jogos devem ver um **Microsoft X-Box 360 pad**.

### 5. Teste

1. Clique **Test**.
2. Aperte botões no pad físico.
3. No desenho, o verde = o que o Xbox virtual está recebendo.  
   Se acende verde, está certo para o jogo.

### Remapear depois

- **Remap** → o app desliga o virtual um instante (pede senha) para conseguir ouvir o pad de novo.
- Mapeie à vontade.
- Clique **Enable** outra vez para aplicar.

---

## Cores no diagrama (pra não se perder)

| Cor | Significado |
|-----|-------------|
| Âmbar | Esperando você apertar (aprendendo) |
| Verde | Sinal do **Xbox virtual** (o que o jogo vê) |
| Azul tracejado | Só aparece em modo diagnóstico avançado |

---

## Problemas comuns

**O jogo não vê o controle**  
1. Confirme **Virtual Xbox on** / badge **Active**.  
2. Em Steam: às vezes ajuda desligar temporariamente a configuração de Steam Input para testar.  
3. Desplugue e plugue o pad depois do Enable.

**Pedi senha demais**  
Normal no primeiro setup e no Enable/Disable. Mapear botões **não** pede senha.

**Meu fliperama / DragonRise / placa ótica**  
Controles de fliperama costumam ser **digitais** (ligado/desligado), mesmo quando o Linux mostra eixos `ABS_X` / `ABS_Y`.  
Mapeie o direcional para o D-pad do Xbox — o app já trata isso. Não precisa “calibrar analógico”.

**Quero desligar o virtual**  
Botão **Disable** no app.

**Desinstalar a integração do sistema (avançado)**  
Não há desinstalador gráfico ainda. Em resumo: pare os serviços `xboxdrv@…`, remova os arquivos em `/usr/local/lib/any-pad-to-xbox`, `/usr/local/bin/any-pad-to-xbox-runner`, a unit em `/etc/systemd/system/xboxdrv@.service` e regras em `/etc/udev/rules.d/99-any-pad-to-xbox.rules` se existirem. Se instalou pela AUR, `sudo pacman -Rns any-pad-to-xbox-git` já remove a maior parte.

---

## Para quem desenvolve / publica

- UI + lógica: `src/any_pad_to_xbox/`
- Bridge mash-safe (stdlib): `packaging/xpad_bridge.py`
- Launcher com `uv`: `scripts/any-pad-to-xbox`
- Pacote AUR (git): `packaging/aur/`
- Guia “nunca publiquei na AUR”: [`docs/AUR.md`](docs/AUR.md)

```bash
./scripts/any-pad-to-xbox          # desenvolvimento
sudo ./packaging/install-system.sh # só a integração systemd/udev/bridge
```

---

## Licença

[MIT](LICENSE) — use, modifique, compartilhe. Sem garantia.
