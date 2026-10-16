# ComfyUI Studio & HA Endpoint (Studio Max)

Ambiente integrado de geração de imagens com **ComfyUI**, interface Web desacoplada (**Studio Max**), nó sanitizador de prompts (**PromptReviewer**) e integração com automações no **Home Assistant**.

---

## 🏛️ Arquitetura do Sistema

O sistema é construído de forma modular e híbrida, suportando execução local ou distribuída (servidor web em Home Server / Proxmox e geração pesada de IA em máquina dedicada com GPU AMD ROCm/DirectML).

```
┌────────────────────────────────────────────────────────┐
│  Home Assistant / Web Browser (Desktop & Mobile)       │
└──────────────────────────┬─────────────────────────────┘
                           │ HTTP / WebSocket
                           ▼
┌────────────────────────────────────────────────────────┐
│  Studio Manager Service (Porta 8180 - Sempre Ativo)     │
│  - Servidor web leve (~30 MB RAM, 0% GPU)              │
│  - Navegação de Galerias, Zoom, Favoritos e Presets     │
│  - Compatibilidade com Home Assistant (/latest_image)   │
│  - Gerenciador de Ciclo de Vida do ComfyUI (Start/Stop)│
│  - Editor e Armazenamento de Opções Customizadas       │
└──────────────────────────┬─────────────────────────────┘
                           │ Proxy / Enfileiramento
                           ▼
┌────────────────────────────────────────────────────────┐
│  ComfyUI Server (Porta 8188 - On-Demand na GPU)        │
│  - Modelos SDXL / Illustrious                          │
│  - Nós de Teste de Combinação e Refinamento Fino       │
│  - PromptReviewer (Sanitização e LoRAs dinâmicos)      │
│  - VAEEncodeForInpaint & RemBG                         │
└────────────────────────────────────────────────────────┘
```

---

## 🚀 Como Iniciar

### 1. Iniciar o Studio Desacoplado (Serviço Leve)
Para ter acesso permanente à galeria, presets e controle do servidor:
```powershell
python studio_service.py
```
Acesse: [http://localhost:8180/studio](http://localhost:8180/studio)

### 2. Iniciar o ComfyUI (Motor de IA)
Pode ser iniciado diretamente com 1 clique através do Studio Web (botão de controle no cabeçalho) ou pelo script:
```powershell
.\iniciar.bat
```

---

## 📡 Integração com o Home Assistant

O sistema provê endpoints específicos consumidos por cards do Home Assistant:
- `GET /latest_image`: Retorna o arquivo binário da imagem mais recente gerada no sistema (com headers anti-cache).
- `GET /latest_image_info`: Retorna metadados em JSON da última imagem (nome, tamanho, data).
- `POST /api/server/restart`: Solicita o reinício do processo do ComfyUI.
- `POST /api/server/shutdown`: Solicita o encerramento do ComfyUI para liberar a GPU.

> Ambos os endpoints `/latest_image` e `/latest_image_info` estão disponíveis tanto na porta do ComfyUI (`8188`) quanto na porta do Studio Service (`8180`), garantindo que o card do Home Assistant nunca fique inacessível mesmo com o ComfyUI em repouso.

---

## 📁 Estrutura de Diretórios

```
D:\IA\ComfyUI\custom_nodes\comfyui-ha-endpoint\
├── __init__.py           # Nós customizados (PromptReviewer, HA endpoints, trava de processo)
├── studio_backend.py     # Rotas da API interna do Studio integradas ao ComfyUI
├── studio_service.py     # Serviço web desacoplado e servidor distribuído (Porta 8180)
├── studio.html           # Interface web completa com abas de geração e ferramentas
├── studio_options.json   # Base de dados de opções customizadas editáveis pelo usuário
├── README.md             # Este guia geral
├── ARCHITECTURE.md       # Documentação da arquitetura distribuída e configurações
└── PROJECT_STATUS.md     # Rastreamento de progresso, regras de IA e valores de referência
```
