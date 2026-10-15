# ComfyUI AI Studio & Home Assistant Endpoint

Suíte integrada de ferramentas profissionais para **ComfyUI**, fornecendo interface gráfica de controle, gerador de testes de combinações de LoRAs, pipelines de pós-processamento e automações para Home Assistant.

---

## 🚀 Funcionalidades Principais

1. **Testador de Combinações & LoRAs**:
   - Sorteio e teste aleatório ou controlado de modelos e até 5 LoRAs simultâneos.
   - Suporte a proporções **9:16 (Celular)**, **16:9 (Wallpaper)** e **1:1 (Quadrado)**.
   - Alternância entre **Modo Seguro (SFW)** e **Modo NSFW** com injeção automática de negativos anatômicos.
   - Galeria em tempo real com acumulação de rodadas e sistema de salvar/aprovar presets.

2. **Refinamento & Upscaling 2-Pass**:
   - Upscale Lanczos / Hi-Res Fix com DPMPP_2M e Face/Hand Detailers dedicados.

3. **Cartoonizador Inteligente**:
   - Conversão de fotos para anime/cartoon com detecção automática facial via InsightFace.
   - Auto-calibração e aprendizado de pesos ideais por feedback do usuário.

4. **FaceSwap Profissional (ReActor & FaceDetailer)**:
   - Troca facial em lote com CodeFormer e textura realista.

5. **Gerador de Ícones e Pixel Art (Prompt Builder Interativo)**:
   - Presets modulares expostos em JSON (`presets/pixelart_presets.json`) para itens, monstros, cenários e heróis.
   - Controle total de raça, gênero, vestimentas, poses e atividades (SFW e NSFW).
   - Suporte a remoção de fundo e estilização retro RPG sprite (Dungeon Squad).

6. **PromptReviewer Inteligente**:
   - Resolução de conflitos de poses e roupas.
   - Sanitização de anatomia para criaturas com parte inferior não humana (centauras, sereias, lamias, aracnes, scyllas, slime girls) com genitália e cor adaptadas por espécie.
   - Injeção oficial de transparência (`see-through_body`, `translucent_body`) para fantasmas e espíritos.
   - Tratamento de cor homogênea e translúcida para slime girls (sem peruca ou olhos humanos destoantes).

---

## 📦 Instalação Portátil

### 1. Clonar o Repositório
No diretório `custom_nodes` da sua instalação do ComfyUI:

```bash
cd ComfyUI/custom_nodes
git clone <URL_DO_REPOSITORIO> comfyui-ha-endpoint
cd comfyui-ha-endpoint
```

### 2. Instalar Dependências
Com o ambiente virtual do ComfyUI ativado:

```bash
pip install -r requirements.txt
```
Ou execute o script de instalação automática:
```bash
python install.py
```

### 3. Acessar a Interface
Inicie o ComfyUI normalmente e abra o navegador em:
```
http://localhost:8188/studio.html
```
*(ou substitua `localhost` pelo IP da máquina na rede local)*

---

## ⚙️ Customização de Presets
As listas de opções de Pixel Art e personagens estão desacopladas do código e residem em:
- `presets/pixelart_presets.json`

Você pode editar diretamente este arquivo ou adicionar novas categorias e opções; elas serão carregadas automaticamente na interface.

---

## 🏠 Integração com Home Assistant
O nó expõe endpoints HTTP otimizados para webviews e painéis do Home Assistant:
- `GET /latest_image`: Retorna o arquivo da última imagem gerada (com headers no-cache).
- `GET /latest_image_info`: Informações em JSON sobre a última geração.
- `GET /ha_view`: Página HTML responsiva e auto-atualizável para cards de Iframe.
