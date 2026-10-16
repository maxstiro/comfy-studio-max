# Especificação de Arquitetura Distribuída

Este documento descreve como o **Studio Max** foi projetado para operar em topologia local ou distribuída, permitindo hospedar a interface em um Home Server enquanto a computação gráfica permanece em uma máquina dedicada com GPU AMD.

---

## 🗺️ Topologias Suportadas

### 1. Topologia Local (Monolítica / Inicial)
Tanto o serviço de interface (`studio_service.py`) quanto o motor de inferência (`ComfyUI`) rodam no mesmo computador (Windows com GPU AMD).
- **Studio Service**: `http://localhost:8180`
- **ComfyUI**: `http://127.0.0.1:8188`
- O Studio controla o ComfyUI local via `subprocess` (iniciar/parar) e faz proxy das requisições de geração de imagem.

### 2. Topologia Distribuída (Home Server + Workstation IA)
- **Home Server (Debian / Proxmox / Docker / Raspberry Pi)**:
  - Executa o `studio_service.py` permanentemente.
  - Acessa as pastas de imagens geradas via compartilhamento de rede SMB/NFS (`\\WORKSTATION\output` ou montado em `/mnt/ia_output`).
  - Serve a interface web na rede local (ex: `http://192.168.1.100:8180`) para navegadores e Home Assistant.
  - O Home Assistant consome `/latest_image` diretamente do Home Server, que nunca cai.
- **Workstation IA (Windows com GPU AMD Radeon)**:
  - Executa apenas o ComfyUI na porta `8188`.
  - O Studio Manager envia os prompts via API REST e WebSocket para `http://IP_DA_WORKSTATION:8188`.
  - Suporta Wake-on-LAN (WoL) e automações do Home Assistant para ligar o PC somente durante as sessões de geração.

---

## ⚙️ Variáveis de Configuração do Studio Service

O `studio_service.py` lê as seguintes variáveis de ambiente (ou `studio_config.json`):

| Variável | Padrão Local | Exemplo em Home Server | Descrição |
|---|---|---|---|
| `STUDIO_HOST` | `0.0.0.0` | `0.0.0.0` | Endereço de bind da interface web |
| `STUDIO_PORT` | `8180` | `8180` | Porta HTTP da interface web |
| `COMFYUI_URL` | `http://127.0.0.1:8188` | `http://192.168.1.150:8188` | URL da instância do ComfyUI |
| `COMFYUI_OUTPUT_DIR` | `D:\IA\ComfyUI\output` | `/mnt/ia_storage/output` | Caminho das imagens geradas |
| `COMFYUI_INPUT_DIR` | `D:\IA\ComfyUI\input` | `/mnt/ia_storage/input` | Caminho de uploads |
| `COMFYUI_START_CMD` | `iniciar.bat` | `ssh user@workstation "iniciar.bat"` | Comando para ligar o ComfyUI remotamente |
| `COMFYUI_STOP_CMD` | `parar.bat` | `ssh user@workstation "parar.bat"` | Comando para desligar o ComfyUI |

---

## 🛡️ Prevenção de Falhas de VRAM e TDR na GPU AMD

A GPU AMD sob ROCm/DirectML no Windows exige os seguintes cuidados implementados no sistema:
1. **Purga Periódica de VRAM**:
   - `gc.collect()` e `torch.cuda.empty_cache()` acionados automaticamente ao término de batches para evitar acúmulo de tensores na troca dinâmica de LoRAs.
2. **Flags de Inicialização Otimizadas**:
   - `--use-pytorch-cross-attention`
   - `--disable-pinned-memory`
   - `--disable-async-offload`
   - `--disable-dynamic-vram`
   - `--reserve-vram 2.0`
3. **Resiliência a Desconexão do KSampler**:
   - O Studio Manager detecta timeout ou queda no WebSocket do ComfyUI, preserva o estado da tela do usuário e oferece reinício com 1 clique sem perda de formulário.
