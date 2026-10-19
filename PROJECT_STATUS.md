# Registro de Status do Projeto & Valores de Referência

Este arquivo rastreia todas as decisões técnicas, regras de inteligência de prompts, triggers de modelos e valores de referência utilizados no desenvolvimento do **ComfyUI Studio Max**.

---

## 📌 Histórico de Entregas e Funcionalidades

### 1. Sanitização Avançada de Prompts (`PromptReviewer`)
- **Regras de Posição & Membros**:
  - Purgas automáticas de poses conflitantes (`bridge_pose` vs poses bípedes, `male_out_of_frame` com purga de contatos de cabeça flutuante).
  - Remoção de `single_tail` quando a personagem for identificada como `kitsune`, `nine_tails` ou `cerberus`.
  - Injeção obrigatória de `(multiple_tails:1.5), (nine_fox_tails:1.4), fluffy_tails` para Kitsunes.
- **Criaturas Sem Pernas Humanas (Monster Girls)**:
  - **Sereia (`mermaid`)**: Purga posturas bípedes (`standing`, `kneeling`, etc.) e pernas humanas (`long_legs`, `thighs`, etc.). Injeta `(single_fish_tail:1.6), (mermaid_tail:1.5), (no_human_legs:1.6)` e carrega sob demanda `<lora:AMermaidFXM_concept-10:0.8>, mermaidxl`.
  - **Lamiá (`lamia`)**: Injeta corpo serpentino, purga pernas humanas e carrega sob demanda `<lora:ALamiaXL_concept-10:0.8>, lamiaxl`.
  - **Garota Robô / Androide (`robot_girl`, `android_girl`, `cyborg`)**: Carrega sob demanda `<lora:ARobotGirls_Concept-12:0.8>, robotxl`.
  - **Górgon / Medusa (`gorgon_girl`, `medusa`)**: Purga cabelos/penteados humanos normais e injeta serpentes vivas na cabeça `(living_snakes_for_hair:1.5), (snake_heads_hair:1.5)`.
  - **Fantasmas / Espíritos (`ghost_girl`)**: Purga peles opacas e injeta corpo translúcido `(see-through_body:1.5), (translucent_body:1.4)`.
  - **Slimes e Elementais**: Purga cores de cabelo/olhos humanos e injeta texturas líquidas, flamejantes, rochosas ou etéreas puras.

### 2. LoRAs Integrados & Triggers Automáticos
| LoRA | Gatilho Automático (Trigger) | Modo de Carga |
|---|---|---|
| `AMermaidFXM_concept-10` | `mermaidxl` | Sob demanda por espécie (Sereia) - **Fora dos sorteios aleatórios** |
| `ALamiaXL_concept-10` | `lamiaxl` | Sob demanda por espécie (Lamiá) - **Fora dos sorteios aleatórios** |
| `ARobotGirls_Concept-12` | `robotxl` | Sob demanda por espécie (Androide/Robô) - **Fora dos sorteios aleatórios** |
| `paulinaapcxlp` | `paulinaapc` | Registro geral de triggers |
| `jmoxcomic` | `jmox style` | Registro geral de triggers |
| `latrans` | `latrans` | Registro geral de triggers |
| `disney_animation` | `disney animation style` | Registro geral de triggers |
| `WaduStyle-000026` | `wadustyle` | Estilo base |
| `AddMicroDetails_Illustrious_v7` | `addmicrodetails` | Detalhamento |
| `fantasiaStyle_illustrious_byJaneB`| `fantasia style, fantasia` | Estilo fantasia |

### 3. Nova Aba: Refinamento Manual Fino (Inpainting Canvas)
- **Canvas HTML5 Interativo**: Seleção de área por pincel inteligente com ajuste de diâmetro (6px a 120px), desfazer, limpar e inverter.
- **Detecção Automática de PNG**: Lê metadados de qualquer imagem gerada via `/api/studio/read_png_info` preenchendo checkpoint, prompt base, dimensões e LoRAs associados.
- **Linguagem Natural + Tags**: Campo aberto para instruções do usuário com atalhos rápidos (`Remover Roupa`, `Joias`, `Expressão`, `Retoque`).
- **Controle Fino de Denoise**: Escala contínua de 0.20 a 1.00 com expansão de máscara configurável (`grow_mask_by`).

---

### 4. Arquitetura Desacoplada e Alta Reatividade (Porta 8180)
- **Eliminação de Gargalo I/O**:
  - Implementação de cache em memória `_TESTER_IMAGE_META_CACHE` indexado por `(mtime, size)`, reduzindo a latência do endpoint `/api/combo_tester/status` de **8.5 segundos** para **100 ms** (ganho de 85x).
  - Remoção de varreduras de disco a cada poll (`refresh=False` por padrão, com refresh explícito via botão e rota `/api/models/scan`).
- **Sincronização Total WebSocket**:
  - Injeção dinâmica do `client_id` do Studio no payload de lote do Combo Tester, permitindo transmissão instantânea de progresso de amostragem (passos do KSampler) e execução de nós.
- **Estabilização de Presets na Galeria**:
  - `_match_approved_combo_name` ajustado para tolerar LoRAs raciais injetados dinamicamente via checagem de subconjunto (`subset`).
  - Cache local no frontend (`comboNameMemory`) para impedir badges de presets de sumirem ou oscilarem durante gravações no disco.

---

## 📐 Valores de Referência de Desenvolvimento

### Resoluções Recomendadas
- **Formato Celular (9:16)**: `832 x 1472`
- **Formato Wallpaper (16:9)**: `1344 x 768`
- **Formato Quadrado (1:1 / Ícones / Sprites)**: `1024 x 1024` ou `896 x 896`

### Parâmetros de Sampler Padrão
- **Sampler**: `Euler`
- **Scheduler**: `sgm_uniform` ou `normal`
- **Steps**: `20` a `28`
- **CFG**: `4.5` a `6.0` (Illustrious SDXL)

### Portas de Rede
- **8188**: ComfyUI API & Engine
- **8180**: Studio Max Manager (Interface Desacoplada)

