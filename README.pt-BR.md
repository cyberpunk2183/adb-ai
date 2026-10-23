# ADB-AI

**Um controle universal para plugar seus aparelhos Android no seu agente de IA.**

Sua TV, box, celular ou tablet — controlados pelo terminal, ou pelo Claude,
Codex, Cursor e qualquer outro agente que fale MCP. Um pacote Python sem
dependência nenhuma, igual no Windows, Linux, macOS e Termux.

[Instalação](docs/INSTALL.md) · [Tutorial](docs/TUTORIAL.md) · [O que dá pra fazer](docs/RECIPES.md) · [Usar com IA](docs/AGENTS.md) · [Como funciona](docs/HOW-IT-WORKS.md) · [Problemas](docs/TROUBLESHOOTING.md) · [English](README.md)

![adb-ai no terminal: varre a rede, conecta na TV, abre o YouTube e confere se está tocando](docs/img/hero.svg)

> A documentação detalhada está em inglês para alcançar mais gente. Este arquivo
> cobre o essencial em português; os comandos são os mesmos.

## O que você precisa

Duas coisas — e o `adb-ai doctor` confere as duas pra você a qualquer momento:

1. **Python 3.9 ou mais novo**
2. **O binário `adb`** (Android platform-tools) — *não* é um pacote Python, por
   isso o `requirements.txt` não tem nenhuma dependência dentro

| Sistema | Como instalar o adb |
|---|---|
| Windows | `winget install Google.PlatformTools` |
| macOS | `brew install android-platform-tools` |
| Debian/Ubuntu | `sudo apt install adb` |
| Fedora | `sudo dnf install android-tools` |
| Arch | `sudo pacman -S android-tools` |
| Termux (Android) | `pkg install android-tools python` |

## Instalação

```bash
git clone https://github.com/cyberpunk2183/adb-ai
cd adb-ai
./install.sh        # Linux, macOS, Termux — instala o que faltar, perguntando antes
.\install.ps1       # Windows (PowerShell)
```

Use `--check` (`-Check` no Windows) pra só ver o que falta, sem mexer em nada.
Sem instalar também funciona: `python -m adbai ...` roda direto da pasta.

## Ligar a depuração no aparelho

É aqui que todo mundo trava. **Nada conecta antes disso.**

**Android TV / TV box:** Configurações → Preferências do dispositivo → Sobre →
clique em **Versão** sete vezes → volte → **Opções do desenvolvedor** → ative
**Depuração por rede** (ou *Depuração ADB*/*USB*, conforme o aparelho).

**Celular/tablet:** Configurações → Sobre → toque em **Número da versão** sete
vezes → Opções do desenvolvedor → **Depuração sem fio**. No Android 11+ precisa
parear uma vez: `adb pair IP:PORTA` com o código que a tela mostra.

Na primeira conexão **o aparelho mostra um aviso** perguntando se permite este
computador. Marque *Sempre permitir* e aceite — sem isso não conecta.

## Primeiros comandos

```bash
adb-ai doctor                              # está tudo certo?
adb-ai scan                                # acha o aparelho na rede
adb-ai connect 192.168.0.42 --alias tv    # conecta e salva o apelido "tv"

adb-ai open youtube                        # abre app por apelido, pacote ou pedaço do nome
adb-ai youtube "lofi hip hop"              # busca sem brigar com o teclado da tela
adb-ai key down down ok                    # sequência de teclas
adb-ai volume up -n 3
adb-ai state                               # o que está na tela e se está tocando
adb-ai shot tela.png                       # screenshot
adb-ai off                                 # apaga a tela
```

**O IP vai mudar.** É DHCP: a TV que era `.102` ontem pode ser `.115` hoje. Deu
*No route to host*? Roda `adb-ai scan` e conecta de novo — é pra isso que o
`scan` existe.

## Plugar no seu agente

É pra isso que o projeto existe: uma linha, e seu agente controla seus
aparelhos.

**Claude Code**

```bash
claude mcp add adb-ai -- adb-ai mcp
```

**Claude Desktop** — `claude_desktop_config.json`

```json
{ "mcpServers": { "adb-ai": { "command": "adb-ai", "args": ["mcp"] } } }
```

**Codex CLI** — `~/.codex/config.toml`

```toml
[mcp_servers.adb_ai]
command = "adb-ai"
args = ["mcp"]
```

**Cursor** — `~/.cursor/mcp.json`

```json
{ "mcpServers": { "adb-ai": { "command": "adb-ai", "args": ["mcp"] } } }
```

Qualquer outro cliente MCP segue o mesmo formato. Chegam 15 ferramentas: achar
na rede, conectar, teclas, apps, URLs, busca no YouTube, alarme, timer, volume,
liga/desliga, estado e print (que volta como imagem pro modelo olhar).

**Skill do Claude Code:**

```bash
mkdir -p ~/.claude/skills && cp -r skills/adb-ai ~/.claude/skills/
```

Aí é só falar: *"põe o YouTube na TV"*, *"pausa isso aí"*, *"o que tá na tela da
sala?"*.

O `adb_shell` (shell cru) **vem desligado** no MCP — só liga com
`ADBAI_ALLOW_SHELL=1`. Um agente que aperta Play é uma coisa; um agente que
roda qualquer comando num aparelho da sua rede é outra bem diferente.

## Por que não usar o `adb` direto?

- **O DHCP troca o IP dos aparelhos** — o `scan` acha de novo, com sockets
  puros, sem nmap, igual no Windows e no Termux.
- **Tem aparelho que corrompe a própria screenshot** — várias TVs Android
  imprimem lixo do driver antes do PNG; o `shot` sempre corta até o cabeçalho.
- **Nem todo aparelho tem `grep` que funcione** — todo filtro acontece no seu
  computador, em Python, nunca com pipe do lado do aparelho.
- **Nomes de tecla e de pacote são impossíveis de decorar** — `adb-ai key ok` em
  vez de `adb shell input keyevent KEYCODE_DPAD_CENTER`.
- **"Funcionou?"** — `adb-ai state` responde numa chamada só.

## Limites, responsabilidade e aviso legal

Isto é um controle remoto, não um desbloqueio. Serve para aparelhos **seus**,
com depuração ligada por você, na **sua** rede. Não contorna DRM, paywall nem
restrição de conta. E não alcança aparelho que ninguém abriu: a depuração ADB
fica atrás de um menu escondido e de um aviso que alguém precisa aceitar na
tela do próprio aparelho, presencialmente.

Dito isso — **qualquer ferramenta que controla aparelhos pela rede pode ser mal
usada**, e esta não é exceção: o `scan` varre uma faixa de rede, e controlar
muitos aparelhos é esta ferramenta num laço. Os autores não apoiam esse uso e
não se responsabilizam por ele. Leia o **[DISCLAIMER.md](DISCLAIMER.md)** antes
de usar. Em resumo:

- use só em aparelhos que são seus ou que você tem autorização para administrar;
- **ADB por TCP não tem autenticação** depois de autorizado — nunca exponha a
  porta 5555 na internet e desligue a depuração quando terminar;
- vem **sem garantia nenhuma**: você roda, você assume o resultado.

**Apontar isso para um celular é uma decisão bem maior que apontar para uma
TV.** Acesso ADB a um celular é o mesmo alcance que você tem com ele destravado
na mão: qualquer app, qualquer campo de texto, print de qualquer coisa na tela —
inclusive código de 2FA. Leia
[Phones are not TVs](DISCLAIMER.md#phones-are-not-tvs).

Política de segurança e checklist: **[SECURITY.md](SECURITY.md)**.

## Licença

MIT © 2026 cyberpunk2183
