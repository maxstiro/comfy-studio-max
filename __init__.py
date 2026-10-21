"""
Extensão de Endpoint para Home Assistant
Disponibiliza rotas HTTP para exibir a última imagem gerada, visualizador ao vivo via iframe e informações de status.
Rotas:
  GET /latest_image       -> Retorna o arquivo da última imagem gerada (com no-cache)
  GET /latest_image_info  -> Retorna JSON com nome, timestamp e caminho da última imagem
  GET /ha_view            -> Página HTML responsiva e auto-atualizável para cards de Iframe no Home Assistant
"""
import server
from aiohttp import web
import pathlib, msvcrt, sys, os, json, random, datetime, re, copy, aiohttp, asyncio, subprocess

# --- IDENTIFICAÇÃO DINÂMICA DA RAIZ DO COMFYUI ---
COMFY_ROOT = pathlib.Path(__file__).resolve().parents[2]
if not (COMFY_ROOT / "main.py").exists() and pathlib.Path(r"D:\IA\ComfyUI").exists():
    COMFY_ROOT = pathlib.Path(r"D:\IA\ComfyUI")

# --- TRAVA DE INSTÂNCIA ÚNICA (PREVINE EXECUÇÃO DUPLICADA) ---
if os.environ.get("COMFY_NO_LOCK") != "1":
    LOCK_PATH = COMFY_ROOT / "user" / "comfy.lock"

    def _is_pid_running_comfy(pid_str):
        try:
            pid = int(pid_str)
            if pid == os.getpid():
                return False
            import psutil
            p = psutil.Process(pid)
            return p.is_running() and ("python" in p.name().lower())
        except Exception:
            return False

    is_already_running = False
    if LOCK_PATH.exists():
        try:
            content = LOCK_PATH.read_text(encoding="utf-8", errors="ignore").strip()
            if "PID:" in content:
                recorded_pid = content.split("PID:")[-1].strip()
                if _is_pid_running_comfy(recorded_pid):
                    is_already_running = True
        except Exception:
            pass

    if is_already_running:
        print("\n" + "=" * 70)
        print("[BLOQUEIO] JA EXISTE UMA INSTANCIA DO COMFYUI EM EXECUCAO!")
        print("Abortando esta segunda execucao para evitar conflito de portas e GPU.")
        print("=" * 70 + "\n")
        sys.exit(0)
    else:
        try:
            LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
            LOCK_PATH.write_text(f"PID: {os.getpid()}\n", encoding="utf-8")
        except Exception:
            pass

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

OUTPUT_DIR = COMFY_ROOT / "output"

@server.PromptServer.instance.routes.get("/latest_image")
async def get_latest_image(request):
    try:
        if not OUTPUT_DIR.exists():
            return web.Response(status=404, text="Output directory not found")
        
        valid_exts = {".png", ".webp", ".jpg", ".jpeg"}
        images = [f for f in OUTPUT_DIR.rglob("*") if f.is_file() and f.suffix.lower() in valid_exts]
        if not images:
            return web.Response(status=404, text="No images found yet")
            
        latest_file = max(images, key=lambda f: f.stat().st_mtime)
        
        response = web.FileResponse(latest_file)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    except Exception as e:
        return web.Response(status=500, text=f"Error retrieving latest image: {e}")

@server.PromptServer.instance.routes.get("/latest_image_info")
async def get_latest_image_info(request):
    try:
        if not OUTPUT_DIR.exists():
            return web.json_response({"error": "Output directory not found"}, status=404)
        
        valid_exts = {".png", ".webp", ".jpg", ".jpeg"}
        images = [f for f in OUTPUT_DIR.rglob("*") if f.is_file() and f.suffix.lower() in valid_exts]
        if not images:
            return web.json_response({"has_image": False, "filename": None})
            
        latest_file = max(images, key=lambda f: f.stat().st_mtime)
        stat = latest_file.stat()
        rel_path = latest_file.relative_to(OUTPUT_DIR).as_posix()
        return web.json_response({
            "has_image": True,
            "filename": latest_file.name,
            "relative_path": rel_path,
            "size_bytes": stat.st_size,
            "timestamp": stat.st_mtime
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/server/restart")
@server.PromptServer.instance.routes.get("/api/server/restart")
async def api_server_restart(request):
    try:
        import subprocess, asyncio
        async def do_restart():
            await asyncio.sleep(0.5)
            restart_bat = COMFY_ROOT / "reiniciar.bat"
            subprocess.Popen(["cmd.exe", "/c", str(restart_bat)], cwd=str(COMFY_ROOT), creationflags=subprocess.CREATE_NO_WINDOW)
        asyncio.create_task(do_restart())
        return web.json_response({"success": True, "message": "Reiniciando servidor ComfyUI..."})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/server/shutdown")
@server.PromptServer.instance.routes.get("/api/server/shutdown")
async def api_server_shutdown(request):
    try:
        import subprocess, asyncio
        async def do_shutdown():
            await asyncio.sleep(0.5)
            stop_bat = COMFY_ROOT / "parar.bat"
            subprocess.Popen(["cmd.exe", "/c", str(stop_bat)], cwd=str(COMFY_ROOT), creationflags=subprocess.CREATE_NO_WINDOW)
        asyncio.create_task(do_shutdown())
        return web.json_response({"success": True, "message": "Desligando servidor ComfyUI..."})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.get("/ha_view")
async def get_ha_view(request):
    html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ComfyUI Live View</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #0e0e10;
      color: #efeff1;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      height: 100vh;
      width: 100vw;
    }
    #container {
      position: relative;
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      background: #000;
      overflow: hidden;
    }
    #img {
      max-width: 100%;
      max-height: 100%;
      object-fit: contain;
      transition: opacity 0.3s ease-in-out;
      opacity: 1;
    }
    #img.loading {
      opacity: 0.5;
    }
    #badge {
      position: absolute;
      bottom: 8px;
      right: 8px;
      background: rgba(0, 0, 0, 0.65);
      backdrop-filter: blur(4px);
      padding: 3px 8px;
      border-radius: 6px;
      font-size: 11px;
      color: #999;
      pointer-events: none;
    }
    #dot {
      display: inline-block;
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #00e676;
      margin-right: 5px;
      box-shadow: 0 0 6px #00e676;
    }

    /* Gatilho discreto para touch / visibilidade no cantinho sem obstruir o preview */
    #btn-menu-trigger {
      position: absolute;
      top: 10px;
      right: 10px;
      z-index: 25;
      background: rgba(15, 20, 32, 0.45);
      backdrop-filter: blur(8px);
      border: 1px solid rgba(255, 255, 255, 0.12);
      color: rgba(255, 255, 255, 0.7);
      padding: 5px 10px;
      border-radius: 20px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 6px;
      transition: all 0.25s ease;
      opacity: 0.35;
      box-shadow: 0 2px 8px rgba(0,0,0,0.3);
    }
    #btn-menu-trigger:hover, #container:hover #btn-menu-trigger {
      opacity: 0.85;
      background: rgba(15, 20, 32, 0.8);
      color: #fff;
    }
    #container:hover #btn-menu-trigger {
      opacity: 0;
      pointer-events: none;
    }

    /* Barra Superior com Auto-Hide / Retrátil (Totalmente desobstruída em repouso) */
    #top-actions {
      position: absolute;
      top: 10px;
      left: 10px;
      right: 10px;
      display: flex;
      justify-content: flex-end;
      align-items: center;
      gap: 6px;
      z-index: 30;
      opacity: 0;
      transform: translateY(-10px);
      transition: opacity 0.25s cubic-bezier(0.16, 1, 0.3, 1), transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
      pointer-events: none;
    }

    /* Revela ao passar o mouse pelo preview ou quando ativado por toque */
    #container:hover #top-actions,
    #top-actions.active {
      opacity: 1;
      transform: translateY(0);
      pointer-events: all;
    }

    .shortcuts-wrapper {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      background: rgba(11, 15, 25, 0.88);
      backdrop-filter: blur(14px);
      padding: 6px 10px;
      border-radius: 12px;
      border: 1px solid rgba(255, 255, 255, 0.12);
      box-shadow: 0 8px 32px rgba(0, 0, 0, 0.6);
    }

    .btn-top {
      display: inline-flex;
      align-items: center;
      gap: 5px;
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid rgba(255, 255, 255, 0.09);
      color: #e2e8f0;
      text-decoration: none;
      padding: 6px 11px;
      border-radius: 8px;
      font-size: 11.5px;
      font-weight: 600;
      transition: all 0.15s ease;
      white-space: nowrap;
    }
    .btn-top:hover {
      background: rgba(255, 255, 255, 0.14);
      border-color: rgba(255, 255, 255, 0.25);
      color: #ffffff;
      transform: translateY(-1px);
      box-shadow: 0 4px 12px rgba(0, 0, 0, 0.35);
    }

    #btn-tester:hover { background: #4f46e5; border-color: #6366f1; }
    #btn-refine:hover { background: #0284c7; border-color: #38bdf8; }
    #btn-cartoon:hover { background: #db2777; border-color: #f472b6; }
    #btn-faceswap:hover { background: #7c3aed; border-color: #a78bfa; }
    #btn-pixelart:hover { background: #059669; border-color: #34d399; }
    #btn-open:hover { background: #2563eb; border-color: #60a5fa; }

    .btn-top svg {
      width: 13px;
      height: 13px;
      fill: none;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
    }
  </style>
</head>
<body>
  <div id="container" onclick="toggleMenuTouch()">
    <div id="btn-menu-trigger">⚡ Atalhos</div>

    <div id="top-actions" onclick="event.stopPropagation()">
      <div class="shortcuts-wrapper">
        <a id="btn-tester" class="btn-top" href="/studio#tab-tester" target="_blank" rel="noopener noreferrer" title="Testador de Combinações e Presets de LoRAs">
          🧪 Testador
        </a>
        <a id="btn-create" class="btn-top" href="/studio#tab-create" target="_blank" rel="noopener noreferrer" title="Criação Planejada de Imagens">
          🎨 Criar
        </a>
        <a id="btn-saved" class="btn-top" href="/studio#tab-saved" target="_blank" rel="noopener noreferrer" title="Galeria de Imagens Guardadas">
          ⭐ Guardadas
        </a>
        <a id="btn-refine" class="btn-top" href="/studio#tab-refine" target="_blank" rel="noopener noreferrer" title="Tratamento e Refinamento com Upscale e Detecção de LoRAs">
          ✨ Refinar
        </a>
        <a id="btn-cartoon" class="btn-top" href="/studio#tab-cartoon" target="_blank" rel="noopener noreferrer" title="Cartoonização / Estilização Anime (3-5 variações)">
          🎨 Cartoon
        </a>
        <a id="btn-faceswap" class="btn-top" href="/studio#tab-faceswap" target="_blank" rel="noopener noreferrer" title="FaceSwap de Rosto Fonte para Alvos Múltiplos">
          🎭 FaceSwap
        </a>
        <a id="btn-pixelart" class="btn-top" href="/studio#tab-pixelart" target="_blank" rel="noopener noreferrer" title="Gerador de Pixel Art e Ícones com Prompt Builder">
          👾 Pixel Art
        </a>
        <a id="btn-open" class="btn-top" href="http://localhost:8188" target="_blank" rel="noopener noreferrer" title="Interface nativa do ComfyUI (porta 8188)">
          ⚙️ ComfyUI
        </a>
        <button id="btn-restart" class="btn-top" onclick="triggerServerAction('restart')" title="Reiniciar ComfyUI" style="cursor:pointer; background:rgba(234,179,8,0.12); border-color:rgba(234,179,8,0.3); color:#fbbf24;">
          🔄 Reiniciar
        </button>
        <button id="btn-shutdown" class="btn-top" onclick="triggerServerAction('shutdown')" title="Desligar ComfyUI" style="cursor:pointer; background:rgba(239,68,68,0.12); border-color:rgba(239,68,68,0.3); color:#f87171;">
          🛑 Desligar
        </button>
      </div>
    </div>

    <!-- Modal Custom de Confirmação -->
    <div id="ha-confirm-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.85); backdrop-filter:blur(8px); z-index:999999; align-items:center; justify-content:center; padding:20px;">
      <div style="background:#0f172a; border:1px solid rgba(255,255,255,0.15); border-radius:14px; max-width:400px; width:100%; padding:22px; box-shadow:0 20px 40px rgba(0,0,0,0.8); text-align:center;">
        <div id="ha-confirm-icon" style="font-size:2rem; margin-bottom:8px;">⚠️</div>
        <h3 id="ha-confirm-title" style="margin:0 0 10px 0; font-size:1.15rem; color:#f87171;">Confirmar Ação</h3>
        <p id="ha-confirm-msg" style="margin:0 0 18px 0; font-size:0.9rem; color:#cbd5e1; line-height:1.4;"></p>
        <div style="display:flex; justify-content:center; gap:10px;">
          <button id="ha-confirm-cancel" style="background:#334155; color:#fff; border:none; border-radius:8px; padding:7px 16px; cursor:pointer; font-weight:500;">Cancelar</button>
          <button id="ha-confirm-ok" style="background:#ef4444; color:#fff; border:none; border-radius:8px; padding:7px 16px; cursor:pointer; font-weight:600;">Confirmar</button>
        </div>
      </div>
    </div>

    <img id="img" src="/latest_image" alt="ComfyUI Latest Output" />
    <div id="badge"><span id="dot"></span><span id="info">Conectado</span></div>
  </div>

  <script>
    let currentTimestamp = 0;
    const imgEl = document.getElementById('img');
    const infoEl = document.getElementById('info');
    const dotEl = document.getElementById('dot');
    const topActions = document.getElementById('top-actions');
    let touchTimer = null;

    function toggleMenuTouch() {
      topActions.classList.toggle('active');
      if (topActions.classList.contains('active')) {
        clearTimeout(touchTimer);
        touchTimer = setTimeout(() => { topActions.classList.remove('active'); }, 5000);
      }
    }

    // Ajusta dinamicamente a porta e host baseados no host atual (localhost, IP de rede ou Home Assistant)
    const host = window.location.hostname || 'localhost';
    const port = (window.location.port && window.location.port !== '') ? window.location.port : '8188';
    const proto = window.location.protocol || 'http:';
    const baseUrl = (host !== 'localhost' && host !== '127.0.0.1') ? `${proto}//${host}:${port}` : `http://localhost:${port}`;

    document.getElementById('btn-open').href = `${baseUrl}`;
    document.getElementById('btn-tester').href = `${baseUrl}/studio#tab-tester`;
    document.getElementById('btn-create').href = `${baseUrl}/studio#tab-create`;
    document.getElementById('btn-saved').href = `${baseUrl}/studio#tab-saved`;
    document.getElementById('btn-refine').href = `${baseUrl}/studio#tab-refine`;
    document.getElementById('btn-cartoon').href = `${baseUrl}/studio#tab-cartoon`;
    document.getElementById('btn-faceswap').href = `${baseUrl}/studio#tab-faceswap`;
    document.getElementById('btn-pixelart').href = `${baseUrl}/studio#tab-pixelart`;

    function haConfirmDialog(title, message, isDanger = true) {
      return new Promise((resolve) => {
        const modal = document.getElementById('ha-confirm-modal');
        if (!modal) {
          resolve(window.confirm(message));
          return;
        }
        document.getElementById('ha-confirm-title').textContent = title;
        document.getElementById('ha-confirm-msg').textContent = message;
        const okBtn = document.getElementById('ha-confirm-ok');
        const cancelBtn = document.getElementById('ha-confirm-cancel');
        okBtn.style.background = isDanger ? '#ef4444' : '#2563eb';
        modal.style.display = 'flex';
        function finish(val) {
          modal.style.display = 'none';
          document.removeEventListener('keydown', onKey);
          resolve(val);
        }
        function onKey(e) {
          if (e.key === 'Escape') finish(false);
          else if (e.key === 'Enter') finish(true);
        }
        okBtn.onclick = () => finish(true);
        cancelBtn.onclick = () => finish(false);
        modal.onclick = (e) => { if (e.target === modal) finish(false); };
        document.addEventListener('keydown', onKey);
        okBtn.focus();
      });
    }

    async function triggerServerAction(action) {
      const isRestart = action === 'restart';
      const label = isRestart ? 'reiniciar' : 'desligar';
      const ok = await haConfirmDialog(
        `${isRestart ? 'Reiniciar' : 'Desligar'} Servidor`,
        `Deseja realmente ${label} o servidor ComfyUI?`,
        !isRestart
      );
      if (!ok) return;
      dotEl.style.background = '#eab308';
      dotEl.style.boxShadow = '0 0 6px #eab308';
      infoEl.textContent = isRestart ? 'Reiniciando...' : 'Desligando...';
      try {
        await fetch(`${baseUrl}/api/server/${action}`, { method: 'POST' });
        if (isRestart) {
          setTimeout(() => { location.reload(); }, 12000);
        } else {
          dotEl.style.background = '#ef4444';
          dotEl.style.boxShadow = '0 0 6px #ef4444';
          infoEl.textContent = 'Desligado';
        }
      } catch (e) {
        console.error(e);
      }
    }

    async function checkLatest() {
      try {
        const res = await fetch('/latest_image_info?t=' + Date.now());
        if (!res.ok) throw new Error('Offline');
        const data = await res.json();
        
        dotEl.style.background = '#00e676';
        dotEl.style.boxShadow = '0 0 6px #00e676';
        
        if (data.has_image && data.timestamp !== currentTimestamp) {
          if (currentTimestamp !== 0) {
            // Nova imagem detectada! Recarregar
            const tempImg = new Image();
            tempImg.src = '/latest_image?t=' + data.timestamp;
            tempImg.onload = () => {
              imgEl.src = tempImg.src;
              currentTimestamp = data.timestamp;
              infoEl.textContent = data.filename || 'Atualizado';
            };
          } else {
            currentTimestamp = data.timestamp;
            infoEl.textContent = data.filename || 'Pronto';
          }
        }
      } catch (err) {
        dotEl.style.background = '#ff5252';
        dotEl.style.boxShadow = '0 0 6px #ff5252';
        infoEl.textContent = 'Desconectado';
      }
    }

    // Polling super leve a cada 2 segundos
    setInterval(checkLatest, 2000);
    checkLatest();
  </script>
</body>
</html>
"""
    response = web.Response(text=html, content_type="text/html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# --- NÓ CUSTOMIZADO: FILTRAGEM INTELIGENTE DE TAGS PARA DETAILERS ---
def _match_tag(tag, keywords):
    import re
    # Normaliza underscores para espacos para permitir correspondência de fronteira de palavra \b
    tag_norm = ' ' + tag.lower().replace('_', ' ') + ' '
    for kw in keywords:
        pattern = r'\b' + re.escape(kw) + r'\b'
        if re.search(pattern, tag_norm):
            return True
    return False

ORAL_KEYWORDS = [
    'blowjob', 'deepthroat', 'oral', 'fellatio', 'sucking', 'sucking penis', 'licking penis',
    'penis', 'large penis', 'cock', 'shaft', 'glans', 'cum', 'cum on face', 'facial', 'bukkake',
    'mouth full of cum', 'cum in mouth', 'cum dripping', 'cum dripping from mouth', 'semen',
    'saliva', 'drool', 'drooling', 'open mouth', 'parted lips', 'gagging', 'tears', 'male out of frame',
    'female focus', '1boy', 'after oral', 'sucking cock'
]

FACE_KEYWORDS = [
    # Raca, anatomia fisica e pele
    'elf', 'dark elf', 'succubus', 'demon', 'vampire', 'angel', 'cat girl', 'catgirl', 'wolf girl', 'wolfgirl', 
    'fox girl', 'foxgirl', 'kitsune', 'bunny girl', 'android', 'goblin', 'orc', 'monster girl', 'human girl', 
    'centaur', 'centaur girl', 'mermaid', 'siren', 'elemental', 'water elemental', 'fire elemental', 
    'earth elemental', 'rock elemental', 'air elemental', 'wind elemental', 'ghost', 'ghost girl', 'phantom', 
    'poltergeist', 'skeleton', 'skeleton girl', 'undead', 'arachne', 'minotaur', 'gorgon', 'medusa', 'lamia', 
    'harpy', 'slime girl', 'dragon girl', 'gargoyle', 'moth girl', 'dryad', 'plant girl', 'cerberus', 'mummy',
    'kemonomimi', 'horn', 'horns', 'ear', 'ears', 'fang', 'fangs', 'tusk', 'tusks', 'halo', 'skin', 'dark skin', 
    'pale skin', 'green skin', 'tanned skin', 'translucent skin', 'spectral', 'liquid body', 'flames', 'scales', 
    'chitin', 'skull face', 'glowing eye sockets', 'freckles', 'beauty mark', 'mole', 'robot joints',
    # Cabelo (cores, estilos e acessorios)
    'hair', 'bangs', 'ponytail', 'twintail', 'twintails', 'braid', 'braids', 'bun', 'buns', 'space buns', 'updo', 
    'bob', 'bob cut', 'ahoge', 'curl', 'curls', 'curly', 'wavy', 'straight', 'dreadlocks', 'drill', 'drills', 
    'pixie', 'undercut', 'hairclip', 'hairband', 'ribbon', 'blonde', 'brunette', 'auburn', 'silver hair', 
    'white hair', 'black hair', 'brown hair', 'red hair', 'blue hair', 'green hair', 'pink hair', 'purple hair',
    # Olhos e pupilas
    'eye', 'eyes', 'pupil', 'pupils', 'heterochromia', 'sclera', 'iris', 'eyelash', 'eyelashes', 'eyebrow', 
    'eyebrows', 'eyeshadow', 'eyeliner',
    # Expressao facial, olhar, emocao e boca
    'blush', 'flushed', 'flushed cheeks', 'smile', 'smiling', 'gentle smile', 'smirk', 'playful smirk', 
    'grinning', 'laughing', 'open mouth', 'closed mouth', 'parted lips', 'biting lip', 'biting lower lip', 
    'pouting', 'tongue', 'tongue out', 'teeth', 'drool', 'drooling', 'saliva', 'lip', 'lips', 'breathless', 
    'panting', 'moan', 'moaning', 'ahegao', 'pleasure', 'pleasured', 'pleasured expression', 'ecstatic', 
    'ecstatic face', 'love-struck', 'winking', 'wink', 'gaze', 'stare', 'looking', 'glance', 'tear', 'tears', 
    'teary eyes', 'crying', 'cheerful', 'playful', 'seductive', 'cute', 'naughty', 'horny', 'embarrassed', 
    'shy', 'nervous', 'smug', 'angry', 'screaming', 'yandere', 'tsundere', 'dazed', 'hypnotized', 'expression', 
    'bedroom eyes', 'submissive gaze', 'looking up', 'looking down', 'looking away', 'looking at viewer', 
    'averted gaze', 'look', 'face'
] + ORAL_KEYWORDS

EYES_KEYWORDS = [
    # Cores, heterocromia e formato dos olhos
    'eye', 'eyes', 'pupil', 'pupils', 'heterochromia', 'sclera', 'iris', 'eyelash', 'eyelashes', 'eyebrow', 
    'eyebrows', 'eyeshadow', 'eyeliner', 'slit pupils', 'heart-shaped pupils', 'star-shaped pupils', 
    'dilated pupils', 'constricted pupils', 'glowing eyes', 'sparkling eyes', 'clear eyes', 'gradient eyes',
    # Olhar, direcao e expressao ocular
    'gaze', 'stare', 'looking', 'glance', 'eye contact', 'looking at viewer', 'looking up', 'looking down', 
    'looking away', 'averted gaze', 'side glance', 'winking', 'wink', 'squint', 'narrowed eyes', 'wide eyed', 
    'bedroom eyes', 'half-closed', 'alluring gaze', 'submissive gaze', 'rolled eyes', 'cross-eyed', 'tear', 
    'tears', 'teary', 'crying', 'sparkling', 'love-struck', 'dilated', 'constricted', 'ecstatic', 'alluring', 
    'submissive', 'bedroom', 'blush', 'flushed', 'cheerful', 'playful', 'seductive', 'ahegao', 'moaning', 
    'breathless', 'pleasured expression', 'smile',
    # Contexto de pele para manter consistencia ao redor da orbita
    'dark skin', 'pale skin', 'green skin', 'tanned skin', 'android skin', 'freckles'
]

HANDS_KEYWORDS = [
    'hand', 'hands', 'finger', 'fingers', 'palm', 'palms', 'nail', 'nails', 'claw', 'claws', 'fist', 
    'glove', 'gloves', 'gloved', 'holding', 'touching', 'grasping', 'caressing', 'grabbing', 'gesturing', 
    'peace sign', 'v sign', 'pointing', 'interlocked fingers'
]

class PromptTagFilter:
    """
    Filtra o prompt positivo original herdando fielmente características de personagem (raça, pele, cabelo, olhos),
    expressões completas e contexto anatômico (incluindo oral/facial) para cada Detailer (Rosto, Olhos, Mãos).
    Retorna o CONDITIONING já encodado pelo CLIP e o texto filtrado.
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "clip": ("CLIP",),
                "full_prompt": ("STRING", {"multiline": True, "forceInput": True}),
                "target_mode": (["face", "eyes", "hands"], {"default": "face"}),
                "base_tags": ("STRING", {"multiline": True, "default": ""}),
            }
        }

    RETURN_TYPES = ("CONDITIONING", "STRING")
    RETURN_NAMES = ("conditioning", "filtered_prompt")
    FUNCTION = "filter_prompt"
    CATEGORY = "conditioning"

    def filter_prompt(self, clip, full_prompt, target_mode, base_tags):
        import re
        # Remove tags lora e quebras
        clean_p = re.sub(r'<lora:[^>]+>', '', full_prompt)
        clean_p = re.sub(r'\bBREAK\b', '', clean_p)

        if target_mode == "eyes":
            keywords = EYES_KEYWORDS
        elif target_mode == "face":
            keywords = FACE_KEYWORDS
        elif target_mode == "hands":
            keywords = HANDS_KEYWORDS
        else:
            keywords = []

        extracted = []
        tags = [t.strip() for t in clean_p.split(',') if t.strip()]
        for t in tags:
            if _match_tag(t, keywords):
                if t not in extracted:
                    extracted.append(t)

        # Proteção de Cenas Orais:
        # Se for modo face e houver cena de oral / sêmen facial, removemos 'smooth clean skin'
        # para que o inpainter do FaceDetailer não apague o sêmen, saliva ou feche a boca.
        is_oral = False
        if target_mode == "face":
            is_oral = any(_match_tag(t, ORAL_KEYWORDS) for t in tags)

        results = []
        if base_tags.strip():
            b_list = [x.strip() for x in base_tags.split(',') if x.strip()]
            if is_oral:
                b_list = [b for b in b_list if 'clean skin' not in b.lower() and 'smooth' not in b.lower()]
            for b in b_list:
                if b not in results:
                    results.append(b)

        for e in extracted:
            if e not in results:
                results.append(e)

        # Se for cena de oral e não tiver menção a boca aberta, reforça open_mouth, parted_lips
        if is_oral and not any(_match_tag(r, ['open mouth', 'parted lips', 'deepthroat', 'blowjob']) for r in results):
            results.append('open_mouth, parted_lips')

        output_str = ', '.join(results)
        
        # Encodar CONDITIONING via CLIP
        tokens = clip.tokenize(output_str)
        cond = clip.encode_from_tokens_scheduled(tokens)
        return (cond, output_str)


# --- TABELA DE TRIGGERS DOS LORAS (ILLUSTRIOUS & ANIMA) ---
LORA_TRIGGER_REGISTRY = {
    # Illustrious
    '0nz9kmeemsggxkv1km7g1svne0': 'FantasyForge',
    'fantasyforge': 'FantasyForge',
    '748cmsdxl': '748cmstyle',
    'addmicrodetails_illustrious_v7': 'addmicrodetails',
    'addmicrodetails': 'addmicrodetails',
    'anime_in_real': 'ani2rel',
    'ani2rel': 'ani2rel',
    'between pages illustrious': 'PagesDaal',
    'between_pages_illustrious': 'PagesDaal',
    'chxrrygxg_v1-illustrious-ty_lee': 'chxrrygxg',
    'chxrrygxg': 'chxrrygxg',
    'ck-shadow-circuit-il-000012': 'in the style of cksc',
    'cksc': 'in the style of cksc',
    'comics_gff_style-000008': 'comiks, fgg',
    'comiks': 'comiks, fgg',
    'd5jr09s54zp67m9me2m1b7bq80': 'T-kay',
    't-kay': 'T-kay',
    'disney_animation_v5-v7': 'DISNEY_ANIMATION',
    'disney_animation': 'DISNEY_ANIMATION',
    'disney': 'DISNEY_ANIMATION',
    '3d_stylized_style_v2': '3d stylized, 3d style',
    '3d_stylized': '3d stylized, 3d style',
    'afkarenaillustrious': 'afk arena, afk style',
    'afkarena': 'afk arena, afk style',
    'afkarenallustrious': 'afk arena, afk style',
    'afkjourneyillustrious': 'afk journey, afk style',
    'smooth_booster_v5': 'smooth booster',
    'smooth_booster': 'smooth booster',
    'illustriousxlv01_stabilizer_v1.198': '',
    'illustriousxlv01_stabilizer': '',
    'dungeon_squad_illustriousv5': 'dungeon squad style, pixel art, retro rpg sprite',
    'dungeon_squad': 'dungeon squad style, pixel art, retro rpg sprite',
    'fantasiastyle_illustrious_byjaneb': 'fantasia style, fantasia',
    'fantasiastyle': 'fantasia style, fantasia',
    'flatline_v2_-_illus_x_niji': 'flatline, flat vector illustration',
    'flatline': 'flatline, flat vector illustration',
    'g0thicill3': 'g0thic, neon',
    'g0thic': 'g0thic, neon',
    'haiz_ai_illu': 'haiz_ai',
    'haiz_ai': 'haiz_ai',
    'hyperrealistic_illustrious': 'hyperrealistic, photorealistic',
    'ickpotixl_v1': 'ickpot style',
    'illmythd4rkl1nes': 'D4rkL1nes',
    'd4rkl1nes': 'D4rkL1nes',
    'incoth': 'incoth',
    'jab_illustrious_v1.5': 'jabstyle',
    'jabstyle': 'jabstyle',
    'jj_v2_illu': 'jj',
    'latrans_-_art_style-000013': 'latrans artstyle',
    'moriimee_gothic_realistic': 'gothic, realistic',
    'moriimee': 'gothic, realistic',
    'mysticalplantpenetratorillust': 'mystical plant, tentacles',
    'new_cartoon_midjourney': 'carto4on',
    'carto4on': 'carto4on',
    'nv_kawaiitech_wm_il_sh': 'nv-kawaiitech',
    'oil(0ilstyle)': '0ilstyle',
    '0ilstyle': '0ilstyle',
    'rabbithole_illu_edition': 'r4bbith0le-illu',
    'r4bbith0le': 'r4bbith0le-illu',
    'rapscallion_illustrious': 'rapscallionstyle',
    'rapscallionstyle': 'rapscallionstyle',
    'retro_scifi_artstyle_illustriousxl-000021': 'retro_artstyle, retro',
    'retrocom1': 'retro, science fiction',
    's1 dramatic lighting illustrious_v2': 's1_dram',
    's1_dram': 's1_dram',
    'sarafaber-artstyle': 'sf4b3r-style',
    'secretofkells-artstyle': 'k3lls-style, toon (style)',
    'sketch_6-000012': 'greyscale, sketch',
    'sts_age_slider_illustrious_v1': 'age slider, mature',
    'sunstoneillustrious': 'sunstone, sunstone style',
    'the_look_illustrious': 'lookdaal',
    'wadustyle-000026': 'wadustyle',
    'wadustyle': 'wadustyle',
    'zynthra_illustrious': 'zynthra, zynthra style',
    'zy_illustrious_realism_enhancer_v1': 'realism enhancer, realistic',

    # Novas Adicoes AMOLED & Dinamica
    'glowing_in_dark_contrast_style': 'glowing_in_dark_contrast_style, neon, glowing',
    'glowing_in_dark': 'glowing_in_dark_contrast_style, neon, glowing',
    'model': 'glowing_in_dark_contrast_style, neon, glowing',
    'ptd': 'p3rf3ctd, high contrast, dramatic, glowing',
    'p3rf3ctd': 'p3rf3ctd, high contrast, dramatic, glowing',
    'flatline_v2_-_illus_x_niji': 'flatline, flat vector illustration',
    'flatline': 'flatline, flat vector illustration',
    'ck-shadow-circuit-il-000012': 'in the style of cksc',
    'cksc': 'in the style of cksc',
    'g0thicill3(g0thic neon)': 'g0thic, neon',
    'g0thic': 'g0thic, neon',
    'illmythd4rkl1nes(d4rkl1nes)': 'd4rkl1nes',
    'd4rkl1nes': 'd4rkl1nes',
    'posingdynamicsill': 'posingdynamicsdaal',
    'posingdynamics': 'posingdynamicsdaal',

    # Monster Girls LoRAs (Carregamento sob demanda contextual - Raciais)
    'alamiaxl_concept-10': 'lamiaxl',
    'alamiaxl_concept': 'lamiaxl',
    'alamiaxl': 'lamiaxl',
    'amermaidfxm_concept-10': 'mermaidxl',
    'amermaidfxm_concept': 'mermaidxl',
    'amermaidfxm': 'mermaidxl',
    'arobotgirls_concept-12': 'robotxl',
    'arobotgirls_concept': 'robotxl',
    'arobotgirls': 'robotxl',
    'gorgonlora-il-000014': 'snake hair, snake_hair, gorgon',
    'gorgonlora-il': 'snake hair, snake_hair, gorgon',
    'gorgonlora': 'snake hair, snake_hair, gorgon',
    'ghost-sfwnsfw-il.v1.0-000013': 'ghost, translucent body, see-through body',
    'ghost-sfwnsfw-il': 'ghost, translucent body, see-through body',
    'ghost-sfwnsfw': 'ghost, translucent body, see-through body',
    'ghost_sex': 'ghost sex, translucent body',
    'draenei-il-000014': 'dra-v1.0, dra-v1.0-f, draenei',
    'draenei-il': 'dra-v1.0, dra-v1.0-f, draenei',
    'draenei': 'dra-v1.0, dra-v1.0-f, draenei',
    'fsev1.0-000011': 'fsev1.0, fairy, fairy wings',
    'fsev1.0': 'fsev1.0, fairy, fairy wings',
    'fairy': 'fsev1.0, fairy, fairy wings',
    'orc-e33_s1155': 'orc, orc_girl, green_skin, tusks',
    'orc-e33': 'orc, orc_girl, green_skin, tusks',
    'orc': 'orc, orc_girl, green_skin, tusks',
    'flesh_unit_5.1': 'flesh_unit',
    'flesh_unit': 'flesh_unit',
    'gazelle_race-e66_s1122': 'gazelle_race, gazelle horns',
    'gazelle_race': 'gazelle_race, gazelle horns',
    'pand4w4_w4kfu_il': 'pand4w4_w4kfu, panda ears, two tone body',
    'pand4w4_w4kfu': 'pand4w4_w4kfu, panda ears, two tone body',
    'pandawa': 'pand4w4_w4kfu, panda ears, two tone body',
    'serpent-e40_s1360': 'serpent, snake scales',
    'serpent': 'serpent, snake scales',
    'navi_race_avatar_jc_illustrious_leaf1': "na'vi, blue skin, pointy ears, yellow eyes",
    'navi_race': "na'vi, blue skin, pointy ears, yellow eyes",
    'saber-toothed': 'saber-tooth, saber-toothed, smilodon tail, countershading',
    'saber_toothed': 'saber-tooth, saber-toothed, smilodon tail, countershading',
    'paulinaapcxlp_style-08': 'paulinaapcxlp',
    'paulinaapcxlp': 'paulinaapcxlp',
    'jmoxcomix_style-12': 'jmoxcomic',
    'jmoxcomic': 'jmoxcomic',
    'latrans_-_art_style-000013': 'latrans',
    'latrans': 'latrans',
    'disney_animation_v5-v7': 'disney animation style',

    # Novos LoRAs de Estilo Illustrious (Para sorteio no Combo Tester e identificação geral)
    'bluefley_style_-_illustration': 'by bluefley',
    'bluefley': 'by bluefley',
    'cartoon_saloon_style': 'csstyle',
    'csstyle': 'csstyle',
    'creative-angle_v2_naixl': 'creative angle',
    'creative-angle': 'creative angle',
    'cutesexyrobutts': 'cutesexyrobutts',
    'detr1mentall_v01': 'detr1mental',
    'detr1mental': 'detr1mental',
    'disgea_characters': 'disgaea_style',
    'disgea': 'disgaea_style',
    'explore_the_world_v3.0-000005': 'exploreworld',
    'explore_the_world': 'exploreworld',
    'fantasy_art_style': 'fantasy_art',
    'fantasy_art': 'fantasy_art',
    'flat_inking': 'flat_inking_style',
    'flat_inking_style': 'flat_inking_style',
    'gem': 'by gem',
    'heylittlekhana_style': 'hlk_style',
    'hlk_style': 'hlk_style',
    'jonyeld_style': 'by jonyeld',
    'jonyeld': 'by jonyeld',
    'mobile_game_collection_-_mad_tale_style': 'madtalestyle',
    'mad_tale': 'madtalestyle',
    'muse_style': 'muse_style',
    'n1coduran_pixel_art_style': 'by n1co, pixel art',
    'n1coduran': 'by n1co, pixel art',
    'raw-color-illustrious': 'raw color',
    'raw-color': 'raw color',
    'rule_of_thirds_2': 'rule of thirds',
    'rule_of_thirds': 'rule of thirds',
    'thronebreakeril-000014': 'tbcv1',
    'thronebreakeril': 'tbcv1',
    'thronebreaker': 'tbcv1',
    'tbcv1': 'tbcv1',
    'vempire': 'vempire',

    # Anima
    'between-pages-anima-base-800': 'PagesDaal',
    'pearly_dark_fantasy': 'pearlydafa, dark fantasy',
    'pearly_drawn_fantasy_style': 'pearlydraf',
    'pearly_fishine': 'pearlyfisst',
    'pearly_fizintine_style': 'pearlyfiz',
    'pearly_mona': 'pearlymost, digital art',
    'pearly_onyx_vanima': 'pearlyonyst',
    'pearly_petiflow2': 'pearlypetif, flat color',
    'pearly_sunstone': 'pearlysunst',
    'pearly_vice_and_violence_style': 'pearlyvivi',
    'sarafaber-anima': 'sf4b3r-style',

    # LoRAs NSFW Específicos sob demanda contextual (NUNCA sortear aleatoriamente)
    '1-freaky_dicksv3': 'fdicks, veiny_penis',
    'freaky_dicks': 'fdicks, veiny_penis',
    '2-masturbation with dildo (illustrious) v1': 'dildomasturbation, sex_toy, dildo',
    'masturbation with dildo': 'dildomasturbation, sex_toy, dildo',
    '3-spreadanusill': 'spreadanusill, spread_anus',
    'spreadanusill': 'spreadanusill, spread_anus',
    '4-buttplugs': 'buttplug, anal_object_insertion',
    'buttplugs': 'buttplug, anal_object_insertion',
    '6-heldbygiantv2illlllllll_epoch_11': 'HeldByGiantV2ILLLLLLLLL',
    '6-heldbygiant': 'HeldByGiantV2ILLLLLLLLL',
    'heldbygiant': 'HeldByGiantV2ILLLLLLLLL',
    '7-il_lesbian_anal_strap-on': 'lestraabed, strap-on, yuri, 2girls',
    'il_lesbian_anal_strap-on': 'lestraabed, strap-on, yuri, 2girls',
    'strap-on': 'lestraabed, strap-on, yuri, 2girls',
    'il_between_pencils_and_semi-realism_style': 'stbedap, semi-realistic, pencil sketch, traditional media',
    'between_pencils': 'stbedap, semi-realistic, pencil sketch, traditional media',
    'stbedap': 'stbedap, semi-realistic, pencil sketch, traditional media',
    '8-masterfist_il': 'Masterfist_IL, inpussy, inass, realistic',
    'masterfist_il': 'Masterfist_IL, inpussy, inass, realistic',
    'masterfist': 'Masterfist_IL, inpussy, inass, realistic'
}

def insert_contextual(tags: list, new_tag: str, anchor_keywords: list, fallback_to_end=True, place='after') -> list:
    """
    Insere 'new_tag' na lista 'tags' imediatamente adjacente (antes ou depois) à tag mais
    relevante que contenha uma das 'anchor_keywords'. Evita duplicatas e mantém coerência posicional.
    Utiliza regex de fronteira para evitar que substrings curtas (ex: 'male') casem indevidamente com 'female' ou 'muscular_female'.
    """
    if not new_tag:
        return tags
    new_tag_clean = new_tag.strip()
    if not new_tag_clean:
        return tags

    # Evita duplicação se a tag exata já existir
    new_lower = new_tag_clean.lower()
    if any(new_lower == t.lower().strip() for t in tags):
        return tags

    import re
    best_idx = -1
    for i, t in enumerate(tags):
        tl = t.lower()
        matched = False
        for ak in anchor_keywords:
            ak_low = ak.lower().strip()
            if not ak_low:
                continue
            pattern = r'(?<![a-zA-Z0-9_])' + re.escape(ak_low) + r'(?![a-zA-Z0-9_])'
            if re.search(pattern, tl):
                best_idx = i
                matched = True
                break
        if matched:
            break

    if best_idx != -1:
        insert_pos = (best_idx + 1) if place == 'after' else best_idx
        return tags[:insert_pos] + [new_tag_clean] + tags[insert_pos:]

    if fallback_to_end:
        return tags + [new_tag_clean]
    return tags

def find_lora_trigger(lora_name: str):
    if not lora_name:
        return None
    raw = lora_name.replace('\\', '/').split('/')[-1]
    clean = raw.lower().replace('.safetensors', '').strip()
    if clean in LORA_TRIGGER_REGISTRY:
        return LORA_TRIGGER_REGISTRY[clean]
    for k, v in LORA_TRIGGER_REGISTRY.items():
        if k in clean or clean in k:
            return v
    import re
    match = re.search(r'\(([^)]+)\)', raw)
    if match:
        extracted = match.group(1).strip()
        if extracted:
            return extracted
    return None

def _try_hook_rgthree():
    """Hook transparente no RgthreePowerLoraLoader para capturar LoRAs ativados no switch visual."""
    try:
        import sys
        for mod_name, mod in list(sys.modules.items()):
            if 'power_lora_loader' in mod_name and hasattr(mod, 'RgthreePowerLoraLoader'):
                cls = mod.RgthreePowerLoraLoader
                if getattr(cls, '_trigger_patched', False):
                    return
                orig_load_loras = cls.load_loras
                def hooked_load_loras(self, model=None, clip=None, **kwargs):
                    applied = getattr(model, '_applied_loras', []) if model else []
                    applied = list(applied)
                    for key, value in kwargs.items():
                        if key.upper().startswith('LORA_') and isinstance(value, dict) and value.get('on'):
                            lora_val = value.get('lora')
                            if lora_val and lora_val not in applied:
                                applied.append(lora_val)
                    res = orig_load_loras(self, model=model, clip=clip, **kwargs)
                    if isinstance(res, tuple) and len(res) >= 1 and res[0] is not None:
                        res[0]._applied_loras = applied
                    return res
                cls.load_loras = hooked_load_loras
                cls._trigger_patched = True
                return
    except Exception:
        pass

# Ativação antecipada do hook caso rgthree já esteja nos módulos carregados
_try_hook_rgthree()


# --- NÓ CUSTOMIZADO: PROMPT REVIEWER & RESOLVEDOR DE CONFLITOS ---
class PromptReviewer:
    """
    Avalia e resolve conflitos lógicos no prompt pós-sorteio de wildcards:
    - Poses conflitantes (ex: standing vs lying_on_back)
    - Roupas vs Atividade sexual / Nudez (ex: jeans fechado com penetracao -> calca aberta/abaixada; saia -> saia levantada)
    - Proteção de cenas de oral (impede que boca fechada ou pele limpa estraguem a cena)
    - Auto-injeção de triggers de LoRA ao ativá-lo (via tag <lora:...> ou Power Lora Loader)
    - Olhos/Olhar conflitantes (ex: closed_eyes com looking_at_viewer)
    - Deduplicação inteligente de tags repetidas
    Retorna o prompt polido e um log descritivo das correções aplicadas.
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "forceInput": True}),
                "resolve_clothing": ("BOOLEAN", {"default": True}),
                "resolve_pose": ("BOOLEAN", {"default": True}),
                "resolve_gaze": ("BOOLEAN", {"default": True}),
                "resolve_oral": ("BOOLEAN", {"default": True}),
                "auto_lora_triggers": ("BOOLEAN", {"default": True}),
                "deduplicate": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "opt_model": ("MODEL",),
                "opt_lora_triggers": ("STRING", {"default": "", "multiline": True}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("reviewed_prompt", "review_log")
    FUNCTION = "review_prompt"
    CATEGORY = "conditioning/text"

    def review_prompt(self, prompt, resolve_clothing=True, resolve_pose=True, resolve_gaze=True, 
                      resolve_oral=True, auto_lora_triggers=True, deduplicate=True, opt_model=None, opt_lora_triggers=""):
        import re, hashlib
        _try_hook_rgthree()

        logs = []
        prompt_hash_val = int(hashlib.md5(prompt.lower().encode('utf-8')).hexdigest()[:6], 16)
        raw_tags = [t.strip() for t in prompt.split(',') if t.strip()]
        
        # 0. Sanitização Defensiva de Tags Problemáticas Globais
        # (A) arched_spine -> arched_back (evita renderização de ossos/espinha visíveis em roupas translúcidas)
        # (B) bedroom_eyes -> heavy_lids, seductive_eyes (evita que o modelo force cenário de quarto/cama)
        sanitized_raw = []
        for t in raw_tags:
            ct = t
            if 'arched_spine' in ct.lower():
                ct = re.sub(r'\barched_spine\b', 'arched_back', ct, flags=re.IGNORECASE)
                logs.append('[Spine Converted] Substituído "arched_spine" por "arched_back" para evitar ossos/espinha visíveis.')
            if 'bedroom_eyes' in ct.lower():
                ct = re.sub(r'\bbedroom_eyes\b', 'heavy_lids, seductive_eyes', ct, flags=re.IGNORECASE)
                logs.append('[Bedroom Cleansed] Substituído "bedroom_eyes" por "heavy_lids, seductive_eyes" para não forçar cenário de quarto.')
            if 'glowing_edges' in ct.lower():
                ct = re.sub(r'\bglowing_edges\b', 'subtle_rim_light', ct, flags=re.IGNORECASE)
                logs.append('[Highlight Cleanse] Substituído "glowing_edges" por "subtle_rim_light" para evitar runas/cristais de neon excessivos.')
            if 'colorful_fish_tail' in ct.lower():
                ct = re.sub(r'\bcolorful_fish_tail\b', 'single_tail, mermaid_tail, single_fish_tail', ct, flags=re.IGNORECASE)
                logs.append('[Tail Cleanse] Substituído "colorful_fish_tail" por cauda única para evitar peixes avulsos e duas caudas.')
            if 'backlit_silhouette' in ct.lower():
                ct = re.sub(r'\bbacklit_silhouette\b', 'dramatic_backlighting, subtle_rim_light', ct, flags=re.IGNORECASE)
                logs.append('[Silhouette Softened] Substituído "backlit_silhouette" por iluminação dramática.')
            elif 'silhouette' in ct.lower():
                ct = re.sub(r'\b(dark\s+|black\s+|nude\s+|body\s+)?silhouette\b', 'dramatic_rim_light, subtle_backlighting', ct, flags=re.IGNORECASE)
                logs.append('[Silhouette Softened] Suavizado termo "silhouette" para iluminação de destaque.')
            # Normalizacao de tags Danbooru comuns com espacos simples para formato de underscore
            danbooru_space_fixes = [
                (r'\b([a-zA-Z0-9_-]+)\s+hair\b', r'\1_hair'),
                (r'\b([a-zA-Z0-9_-]+)\s+eyes\b', r'\1_eyes'),
                (r'\brule\s+of\s+thirds\b', 'rule_of_thirds'),
                (r'\bcinematic\s+angle\b', 'cinematic_angle'),
                (r"\b(worm's\s+eye\s+view|worm's\s+eye\s+perspective)\b", "worm's-eye_view"),
                (r'\blooking\s+up\b', 'looking_up'),
                (r'\blooking\s+down\b', 'looking_down'),
                (r'\bbest\s+quality\b', 'best_quality'),
                (r'\btop\s+quality\b', 'top_quality'),
                (r'\bvery\s+aesthetic\b', 'very_aesthetic'),
                (r'\bhighly\s+aesthetic\b', 'highly_aesthetic'),
                (r'\bstunning\s+illustration\b', 'stunning_illustration'),
                (r'\bdetailed\s+artwork\b', 'detailed_artwork'),
                (r'\b(simple|white|black|grey|gray)\s+background\b', r'\1_background'),
                (r'\bsee\s+through\s+body\b', 'see-through_body'),
                (r'\btranslucent\s+body\b', 'translucent_body'),
                (r'\btwo\s+legs\b', 'two_legs'),
                (r'\bmultiple\s+legs\b', 'multiple_legs'),
                (r'\bmissile\s+pod\b', 'missile_pod'),
                (r'\bholding\s+railgun\b', 'holding_railgun'),
                (r'\bholding\s+cannon\b', 'holding_cannon'),
                (r'\bholding\s+gatling\s+gun\b', 'holding_gatling_gun'),
                (r'\bglowing\s+eyes\b', 'glowing_eyes'),
                (r'\bvaginal\s+object\s+insertion\b', 'vaginal_object_insertion'),
                (r'\bbare\s+breasts\b', 'bare_breasts'),
                (r'\bbare\s+pussy\b', 'bare_pussy'),
                (r'\bbare\s+anus\b', 'bare_anus'),
                (r'\bparted\s+lips\b', 'parted_lips'),
                (r'\bopen\s+mouth\b', 'open_mouth'),
                (r'\bclosed\s+eyes\b', 'closed_eyes'),
                (r'\blying\s+on\s+back\b', 'lying_on_back'),
                (r'\blying\s+on\s+stomach\b', 'lying_on_stomach'),
                (r'\blegs\s+spread\b', 'legs_spread'),
                (r'\b(arched|arching)\s+back\b', 'arched_back'),
            ]
            if not ct.startswith('<') and not ct.startswith('('):
                for pat, rep in danbooru_space_fixes:
                    ct = re.sub(pat, rep, ct, flags=re.IGNORECASE)
            sanitized_raw.append(ct)
        raw_tags = sanitized_raw

        # 1. Deduplicacao preservando ordem
        if deduplicate:
            seen = set()
            tags = []
            for t in raw_tags:
                clean_t = t.lower()
                if clean_t not in seen:
                    seen.add(clean_t)
                    tags.append(t)
            if len(tags) < len(raw_tags):
                logs.append(f'[Deduplication] Removidas {len(raw_tags) - len(tags)} tags duplicadas.')
        else:
            tags = raw_tags.copy()

        full_text_lower = ' '.join(tags).lower()

        # 2. Resolução de conflitos de Pose
        if resolve_pose:
            lying_signals = {'lying_on_back', 'lying_on_stomach', 'on_back', 'on_stomach', 'legs_spread_in_m-shape', 'reclining', 'spread_eagled', 'side_lying', 'missionary'}
            all_fours_signals = {'on_all_fours', 'all_fours', 'chest_to_mattress', 'doggy', 'doggy_style', 'bent_over'}
            kneeling_signals = {'kneeling', 'on_knees', 'thighs_spread', 'straddling', 'cowgirl'}
            sitting_signals = {'sitting', 'sitting_cross-legged', 'squatting', 'seiza', 'sitting_on_chair', 'sitting_on_bed', 'lounging'}
            standing_signals = {'standing', 'weight_on_one_leg', 'hip_cocked', 'hands_behind_back', 'hands_on_hips', 'confident_stance', 'standing_looking_back', 'leaning_against_wall', 'one_leg_lifted', 'walking', 'running'}

            has_lying = any(s in full_text_lower for s in lying_signals)
            has_all_fours = any(s in full_text_lower for s in all_fours_signals)
            has_kneeling = any(s in full_text_lower for s in kneeling_signals)
            has_sitting = any(s in full_text_lower for s in sitting_signals)
            has_standing = any(s in full_text_lower for s in standing_signals)

            if has_lying and (has_standing or has_sitting or has_all_fours):
                tags_to_drop = standing_signals | sitting_signals | (all_fours_signals - lying_signals)
                dropped = [t for t in tags if any(sig in t.lower() for sig in tags_to_drop) and not any(ls in t.lower() for ls in lying_signals)]
                if dropped:
                    tags = [t for t in tags if t not in dropped]
                    logs.append(f'[Pose Conflict] Priorizado DEITADA (lying); removidas posturas conflitantes: {dropped}')
            elif has_all_fours and (has_standing or has_lying or has_sitting):
                tags_to_drop = standing_signals | sitting_signals | lying_signals
                dropped = [t for t in tags if any(sig in t.lower() for sig in tags_to_drop) and not any(sig in t.lower() for sig in all_fours_signals)]
                if dropped:
                    tags = [t for t in tags if t not in dropped]
                    logs.append(f'[Pose Conflict] Priorizado QUATRO APOIOS (all_fours); removidas posturas conflitantes: {dropped}')
            elif has_kneeling and (has_standing or has_lying):
                tags_to_drop = standing_signals | lying_signals
                dropped = [t for t in tags if any(sig in t.lower() for sig in tags_to_drop) and not any(sig in t.lower() for sig in kneeling_signals)]
                if dropped:
                    tags = [t for t in tags if t not in dropped]
                    logs.append(f'[Pose Conflict] Priorizado DE JOELHOS (kneeling); removidas posturas conflitantes: {dropped}')
            elif has_sitting and has_standing:
                dropped = [t for t in tags if any(sig in t.lower() for sig in standing_signals)]
                if dropped:
                    tags = [t for t in tags if t not in dropped]
                    logs.append(f'[Pose Conflict] Priorizado SENTADA (sitting); removido: {dropped}')

        # 3. Resolução de Conflitos Roupa vs Atividade / Nudez
        if resolve_clothing:
            full_text_lower = ' '.join(tags).lower()
            
            # Detecta se a personagem foi declarada explicitamente SEM calcinha ou completamente nua
            has_no_panties = any(sig in full_text_lower for sig in {'bottomless', 'no_panties', 'completely_nude', 'completely_naked', 'naked', 'nude'})
            is_totally_naked = any(sig in full_text_lower for sig in {'completely_nude', 'completely_naked', 'naked', 'nude'})
            is_topless = is_totally_naked or any(sig in full_text_lower for sig in {'topless', 'bare_breasts', 'exposed_breasts'})
            is_nsfw_scene = any(sig in full_text_lower for sig in ['nsfw', 'pussy', 'bare_breasts', 'masturbation', 'fingering', 'penetration', 'sex']) or has_no_panties or is_topless

            # Tags de manipulação de calcinha que ficam inúteis se a personagem NÃO ESTIVER de calcinha
            panties_actions_aside = {
                'panties_aside', 'pulling_panties_aside', 'pulling_panties_to_the_side', 
                'bloomers_pulled_aside', 'underwear_aside'
            }
            panties_actions_down = {
                'pulling_panties_down', 'pulling_down_panties', 'slowly_lowering_panties', 
                'lowering_panties', 'taking_off_panties', 'removing_panties', 'adjusting_panties', 
                'panties_down', 'panties_around_one_ankle', 'panties_around_ankles'
            }

            other_bad_partials = {
                'shorts_pulled_down', 'pulled_down_jeans', 'pulled_down_pants', 'unbuttoned_fly', 
                'one_breast_exposed', 'slipping_towel', 'slipping_down', 'one_strap_slipping_down'
            }

            new_tags = []
            for t in tags:
                tl = t.lower()

                # Eliminar toalhas soltas em cenas íntimas / NSFW
                if is_nsfw_scene and any(tw in tl for tw in ['towel', 'bath_towel', 'slipping_towel', 'wrapped_in_towel']):
                    logs.append(f'[Towel Conflict] Removida toalha "{t}" em cena NSFW para evitar pedacos de pano deslocados.')
                    continue

                # SOMENTE quando a personagem está explicitamente sem calcinha (bottomless, no_panties, completely_nude):
                # ações de manipular calcinha ficam inúteis e entram em conflito lógico com a ausência da peça
                if has_no_panties:
                    if any(pa in tl for pa in panties_actions_aside):
                        cleaned_t = t
                        for pa in panties_actions_aside:
                            cleaned_t = re.sub(rf'\b{pa}\b', 'parting_own_thighs, teasing', cleaned_t, flags=re.IGNORECASE)
                        cleaned_t = re.sub(r',\s*,', ',', cleaned_t).strip(' ,')
                        logs.append(f'[Panties Action Converted] Substituida acao inútil "{t}" por "parting_own_thighs, teasing" pois a personagem esta sem calcinha.')
                        t = cleaned_t
                        tl = t.lower()

                    if any(pd in tl for pd in panties_actions_down):
                        cleaned_t = t
                        for pd in panties_actions_down:
                            cleaned_t = re.sub(rf'\b{pd}\b', 'caressing_own_thighs, teasing', cleaned_t, flags=re.IGNORECASE)
                        cleaned_t = re.sub(r',\s*,', ',', cleaned_t).strip(' ,')
                        logs.append(f'[Panties Action Converted] Substituida acao inútil "{t}" por "caressing_own_thighs, teasing" pois a personagem esta sem calcinha.')
                        t = cleaned_t
                        tl = t.lower()

                    # Se a tag for uma calcinha física e personagem é bottomless / no_panties / completely_nude:
                    # remove a calcinha para manter consistência com a ausência declarada de roupa íntima
                    if any(p_kw in tl for p_kw in ['panties', 'underwear', 'bloomers']) and 'no_panties' not in tl:
                        if not any(keep in tl for keep in ['pulling', 'striptease', 'touching', 'caressing', 'parting']):
                            logs.append(f'[Clothing Conflict] Removida calcinha "{t}" conflitante com estado sem calcinha/bottomless.')
                            continue

                # Se personagem está topless / sem sutiã, resolver ações de sutiã
                if is_topless:
                    if any(ba in tl for ba in ['unhooking_bra', 'bra_half_unhooked', 'pulling_down_bra', 'pulling_bra_aside']):
                        cleaned_t = t
                        for ba in ['unhooking_bra', 'bra_half_unhooked', 'pulling_down_bra', 'pulling_bra_aside']:
                            cleaned_t = re.sub(rf'\b{ba}\b', 'cupping_breast', cleaned_t, flags=re.IGNORECASE)
                        cleaned_t = re.sub(r',\s*,', ',', cleaned_t).strip(' ,')
                        logs.append(f'[Bra Action Converted] Substituida acao de sutia "{t}" por "cupping_breast" pois personagem esta topless/nude.')
                        t = cleaned_t
                        tl = t.lower()
                    if is_totally_naked and any(b_kw in tl for b_kw in ['bra', 'sheer_bra', 'lace_bra']):
                        logs.append(f'[Clothing Conflict] Removido sutia "{t}" pois personagem esta completely_nude.')
                        continue

                # Eliminar outras tags de roupas puxadas pela metade
                if any(bp in tl for bp in other_bad_partials):
                    cleaned_t = t
                    for bp in other_bad_partials:
                        cleaned_t = re.sub(rf'\b{bp}\b', '', cleaned_t, flags=re.IGNORECASE)
                    cleaned_t = re.sub(r',\s*,', ',', cleaned_t).strip(' ,')
                    if not cleaned_t:
                        logs.append(f'[Partial Clothing Removed] Removida tag instavel "{t}".')
                        continue
                    t = cleaned_t
                    tl = t.lower()

                # Nudez total: remove qualquer peça casual restante
                if is_totally_naked:
                    if any(c in tl for c in ['jeans', 'pants', 'trousers', 'shorts', 'skirt', 'dress', 'shirt', 'sweater', 'hoodie', 'jacket', 't-shirt', 'tank_top', 'blouse', 'coat', 'pajamas', 'yukata', 'casual_clothes', 'towel', 'lingerie', 'underwear', 'panties', 'bra']):
                        logs.append(f'[Clothing Conflict] Removida roupa "{t}" por presenca de nudez total (completely_naked).')
                        continue

                new_tags.append(t)
            tags = new_tags

        # 3.1 Sanitização de Auréolas / Halos Indesejados
        is_angel = any(a in full_text_lower for a in ['angel', 'angel_girl', 'wings', 'feathered_wings'])
        if not is_angel:
            dropped_halo = [t for t in tags if any(h in t.lower() for h in ['golden_halo', 'glowing_halo', 'halo'])]
            if dropped_halo:
                tags = [t for t in tags if t not in dropped_halo]
                # Se tinha halo como iluminacao, garante luz dourada sem adereco de cabeca
                tags.append('golden_rim_lighting')
                logs.append(f'[Halo Accessory Removed] Removido halo/aureola {dropped_halo} pois personagem nao e anjo.')


        # 4. Proteção de Cenas de Oral e Conflitos de Boca/Expressão
        if resolve_oral:
            full_text_lower = ' '.join(tags).lower()
            oral_signals = {'blowjob', 'deepthroat', 'oral', 'fellatio', 'sucking_penis', 'licking_penis', 
                            'mouth_full_of_cum', 'cum_dripping_from_mouth', 'sucking_cock', 'cunnilingus'}
            if any(sig in full_text_lower for sig in oral_signals):
                mouth_conflicts = {'closed_mouth', 'biting_lip', 'biting_lower_lip', 'biting_knuckle', 
                                   'lip_bite', 'playful_tongue_bite', 'clenched_teeth', 'pout'}
                new_tags = []
                purged_mouth = []
                for t in tags:
                    tl = t.lower()
                    if any(mc in tl for mc in mouth_conflicts):
                        purged_mouth.append(t)
                    else:
                        new_tags.append(t)
                if purged_mouth:
                    new_tags.append('open_mouth, parted_lips')
                    tags = new_tags
                    logs.append(f'[Oral Conflict Resolved] Removida expressao bucal conflitante {purged_mouth} e garantida boca aberta/parted_lips para viabilizar ato oral.')

            kiss_signals = {'kissing', 'french_kiss', 'deep_kiss'}
            if any(sig in full_text_lower for sig in kiss_signals):
                kiss_conflicts = {'biting_lip', 'biting_lower_lip', 'biting_knuckle', 'pout', 'closed_mouth'}
                new_tags = []
                purged_kiss = []
                for t in tags:
                    tl = t.lower()
                    if any(kc in tl for kc in kiss_conflicts):
                        purged_kiss.append(t)
                    else:
                        new_tags.append(t)
                if purged_kiss:
                    new_tags.append('parted_lips, kissing')
                    tags = new_tags
                    logs.append(f'[Kissing Conflict Resolved] Removido {purged_kiss} por conflito anatomico com beijo.')

            # Purgar caustics fora da agua
            if 'underwater' not in full_text_lower and 'submerged' not in full_text_lower and 'pool' not in full_text_lower:
                tags = [t for t in tags if 'underwater_caustics' not in t.lower()]

        # 5. Resolução de Olhos e Olhar
        if resolve_gaze:
            full_text_lower = ' '.join(tags).lower()
            has_closed = 'closed_eyes' in full_text_lower
            open_signals = {'looking_at_viewer', 'eye_contact', 'bedroom_eyes', 'winking', 'wink', 'staring', 'looking_up', 'looking_away', 'averted_gaze', 'wide_eyed', 'submissive_gaze'}
            has_open_intent = any(sig in full_text_lower for sig in open_signals)

            if has_closed and has_open_intent:
                tags = [t for t in tags if 'closed_eyes' not in t.lower()]
                logs.append('[Gaze Conflict] Removido \"closed_eyes\" devido a presenca de tags ativas de olhar/expressao ocular.')

        # 6. Auto-Injeção de Triggers de LoRA ao Ativá-lo
        if auto_lora_triggers:
            # Lista de tags limpas (sem os termos <lora:...>)
            clean_text = re.sub(r'<lora:[^>]+>', '', ' '.join(tags))
            clean_tags_lower = [t.strip().lower() for t in clean_text.split(',') if t.strip()]

            # (A) Detectar LoRAs explicitamente passados via opt_lora_triggers (ex: Combo Tester)
            if opt_lora_triggers:
                for direct_trig in [dt.strip() for dt in opt_lora_triggers.split(',') if dt.strip()]:
                    if not any(direct_trig.lower() == ct or direct_trig.lower() in ct for ct in clean_tags_lower):
                        tags.append(direct_trig)
                        clean_tags_lower.append(direct_trig.lower())
                        logs.append(f'[LoRA Trigger Direct Injected] Injetado trigger "{direct_trig}" de opt_lora_triggers.')

            # (B) Detectar LoRAs chamados no texto <lora:nome:peso>
            lora_text_calls = re.findall(r'<lora:([^:>]+)(?::[^>]+)?>', ' '.join(tags))
            for lc in lora_text_calls:
                trig = find_lora_trigger(lc)
                if trig and not any(trig.lower() == ct or trig.lower() in ct for ct in clean_tags_lower):
                    tags.append(trig)
                    clean_tags_lower.append(trig.lower())
                    logs.append(f'[LoRA Trigger Auto-Injected] Injetado trigger "{trig}" para o LoRA "{lc}".')

            # (C) Detectar LoRAs ativados no Power Lora Loader (via opt_model)
            if opt_model is not None:
                active_loras = getattr(opt_model, '_applied_loras', [])
                for al in active_loras:
                    trig = find_lora_trigger(al)
                    if trig and not any(trig.lower() == ct or trig.lower() in ct for ct in clean_tags_lower):
                        tags.append(trig)
                        clean_tags_lower.append(trig.lower())
                        logs.append(f'[LoRA Trigger Auto-Injected (PowerLoader)] Injetado trigger "{trig}" para LoRA ativo "{al}".')
        # 7. Otimizacao de Estilo AMOLED (Predominantemente Preto + Linhas Neon + Destaques Minimos)
        full_text_lower = ' '.join(tags).lower()
        amoled_triggers = {
            'pitch_black_background', 'pure black background', 'absolute darkness', 
            'mostly black image', 'pitch-black body', 'pitch-black figure', 
            'estilo_amoled', 'pitch black', 'true black'
        }
        is_amoled = any(trig in full_text_lower for trig in amoled_triggers)
        if is_amoled:
            # (A) Remover termo 'silhouette' para evitar artefatos e elementos/figuras estranhas indesejadas
            sil_purged = []
            no_sil_tags = []
            for t in tags:
                if 'silhouette' in t.lower():
                    # Substitui 'silhouette' por 'dark figure' ou descarta termos genericos
                    sub = re.sub(r'\b(dark\s+|nude\s+|body\s+)?silhouette\b', 'dark figure', t, flags=re.IGNORECASE).strip()
                    sub = re.sub(r'\s+', ' ', sub).strip(', ')
                    if sub and sub.lower() not in ['dark figure']:
                        no_sil_tags.append(sub)
                    elif sub.lower() == 'dark figure':
                        if not any('dark figure' in st.lower() for st in no_sil_tags):
                            no_sil_tags.append('dark figure')
                    sil_purged.append(t)
                else:
                    no_sil_tags.append(t)
            if sil_purged:
                tags = no_sil_tags
                logs.append(f'[AMOLED Sanitize] Removido termo "silhouette" ({len(sil_purged)} ocorrencias) para evitar elementos indesejados.')

            # (B) Remover iluminacao ambiente e cenarios que quebram o fundo preto absoluto
            ambient_conflicts = [
                'sunlight', 'daylight', 'bright lighting', 'ambient lighting', 'well-lit',
                'white background', 'grey background', 'gray background', 'complex background',
                'room', 'bedroom', 'living room', 'scenery', 'indoors', 'outdoors',
                'street', 'park', 'beach', 'classroom', 'office', 'soft lighting',
                'morning light', 'golden hour', 'direct sunlight', 'lens flare'
            ]
            purged = []
            cleaned_tags = []
            for t in tags:
                tl = t.lower().strip()
                if any(ac == tl or f' {ac} ' in f' {tl} ' or tl.startswith(f'{ac} ') or tl.endswith(f' {ac}') for ac in ambient_conflicts):
                    purged.append(t)
                else:
                    cleaned_tags.append(t)
            if purged:
                tags = cleaned_tags
                logs.append(f'[AMOLED Conflict] Removida iluminacao/cenario conflitante: {purged}')

            # (C) Garantir presenca de flatline para traco vetorial de alto contraste
            if not any('flatline' in t.lower() for t in tags):
                tags.append('flatline, flat vector illustration')
                logs.append('[AMOLED Boost] Injetado "flatline, flat vector illustration" para tracos limpos e vetorizados.')

            # (D) Auto-injetar os dois LoRAs de AMOLED se nao estiverem ja no loader/prompt
            # LoRA 1: Glowing In Dark Contrast Style (0.75)
            # LoRA 2: PTD Style: Contrast & Glow (0.70)
            target_loras = [
                ('Glowing_In_Dark_Contrast_Style', 0.75, 'glowing_in_dark_contrast_style, neon, glowing'),
                ('ptd', 0.70, 'p3rf3ctd, high contrast, dramatic'),
            ]
            for l_name, l_weight, l_trig in target_loras:
                is_in_text = any(l_name.lower() in t.lower() for t in tags)
                is_in_active = False
                if opt_model is not None:
                    applied = getattr(opt_model, '_applied_loras', [])
                    is_in_active = any(l_name.lower() in str(a).lower() for a in applied)
                if not is_in_text and not is_in_active:
                    tags.append(f'<lora:illustrious\\{l_name}:{l_weight}>')
                    for trig_tag in [s.strip() for s in l_trig.split(',') if s.strip()]:
                        if not any(trig_tag.lower() == t.lower() for t in tags):
                            tags.append(trig_tag)
                    logs.append(f'[AMOLED Auto-LoRA] Ativado automaticamente LoRA "{l_name}" (peso {l_weight}) com triggers oficiais.')

            # (E) Reorganizar para posicionar Qualidade e AMOLED Core no inicio (Chunk 1)
            amoled_keywords = [
                'black', 'dark', 'shadow', 'neon', 'glowing', 'rim light',
                'rim lighting', 'contour', 'highlight', 'chiaroscuro', 'bioluminescent',
                'contrast', 'minimal', 'edge lighting', 'void', 'flatline', 'vector'
            ]
            quality_tokens = []
            amoled_tokens = []
            other_tokens = []
            for t in tags:
                tl = t.lower()
                if any(q in tl for q in ['masterpiece', 'best quality', 'absurdres', 'ultra-detailed', 'high quality', 'top quality', 'stunning illustration']):
                    quality_tokens.append(t)
                elif any(kw in tl for kw in amoled_keywords):
                    amoled_tokens.append(t)
                else:
                    other_tokens.append(t)

            tags = quality_tokens + amoled_tokens + other_tokens
            logs.append('[AMOLED Priority] Estilo AMOLED reorganizado com prioridade maxima (Chunk 1).')

        # 8. Deteccao e Ajuste de Camera em Wallpapers Landscape (16:9)
        # Em imagens horizontais/wallpapers, personagens nao devem ficar colados na camera
        full_text_lower = ' '.join(tags).lower()
        is_landscape_wall = any(w in full_text_lower for w in [
            'horizontal_composition', 'landscape_composition', 'scenery_focused', 
            'camera_wall', 'panoramic_view', 'scenic_background'
        ])
        if is_landscape_wall:
            close_up_signals = {'close-up', 'extreme_close-up', 'tight_portrait', 'focus_on_face', 'focus_on_eyes_and_lips', 'macro_detail'}
            new_tags = []
            replaced_cameras = []
            has_inserted_wide = False
            for t in tags:
                tl = t.lower()
                if any(cs in tl for cs in close_up_signals):
                    replaced_cameras.append(t)
                    if not has_inserted_wide:
                        new_tags.append('wide_environmental_portrait, cinematic, rule_of_thirds')
                        has_inserted_wide = True
                else:
                    new_tags.append(t)
            if replaced_cameras:
                tags = new_tags
                logs.append(f'[Wallpaper Framing Fixed] Substituido enquadramento fechado {replaced_cameras} por plano ambiental aberto para valorizar o cenario de wallpaper.')

        # 9. Harmonizacao de Duplas Femininas (2girls substituindo 1girl no slot principal, SEM multiple_girls)
        full_text_lower = ' '.join(tags).lower()
        has_2girls = any(k in full_text_lower for k in ['2girls', 'two_girls', 'multiple_girls'])
        if has_2girls:
            # Identificar a posicao original do sujeito (onde 1girl ou solo estavam posicionados)
            target_idx = None
            for idx, t in enumerate(tags):
                tl = t.lower().strip()
                if tl in {'1girl', 'solo', '(1girl)', '(solo)'}:
                    target_idx = idx
                    break

            # Se 1girl nao foi encontrado como tag isolada, posicionar logo apos as tags de qualidade
            if target_idx is None:
                for idx, t in enumerate(tags):
                    tl = t.lower().strip()
                    if any(c in tl for c in ['masterpiece', 'best quality', 'ultra-detailed', 'absurdres', 'highly aesthetic']):
                        target_idx = idx + 1
                if target_idx is None:
                    target_idx = 0

            # Limpar 1girl/solo e retirar 2girls/multiple_girls de tags compostas posteriores
            cleaned_tags = []
            for t in tags:
                tl = t.lower().strip()
                if tl in {'1girl', 'solo', '(1girl)', '(solo)', 'multiple_girls', '(multiple_girls)'}:
                    continue
                if tl in {'2girls', 'two_girls', '2girls, multiple_girls'}:
                    continue
                if '2girls' in tl or 'multiple_girls' in tl or 'two_girls' in tl:
                    parts = [p.strip() for p in t.split(',') if p.strip()]
                    kept_parts = [p for p in parts if p.lower().strip() not in {'2girls', 'multiple_girls', 'two_girls'}]
                    if kept_parts:
                        cleaned_tags.append(', '.join(kept_parts))
                else:
                    cleaned_tags.append(t)

            # Inserir puramente '2girls' (NUNCA usar multiple_girls para não gerar 3 ou mais garotas)
            final_pos = min(target_idx, len(cleaned_tags))
            cleaned_tags.insert(final_pos, '2girls')
            tags = cleaned_tags
            logs.append(f'[2girls Harmonization] Tag "2girls" inserida no início (slot {final_pos}), sem "multiple_girls" para evitar excesso de personagens.')
        # 10. Protecao e Firmeza Anatomica em Camas / Colchoes (Anti-Afundamento de Membros)
        full_text_lower = ' '.join(tags).lower()
        bed_signals = {'bed', 'mattress', 'satin_sheets', 'sheets', 'futon', 'on_bed', 'kneeling_on_bed', 'sitting_on_edge_of_bed'}
        if any(bs in full_text_lower for bs in bed_signals):
            new_tags = []
            bed_fixes = []
            for t in tags:
                tl = t.lower().strip()
                if 'chest_to_mattress' in tl:
                    new_tags.append('propped_up_on_elbows, arched_back')
                    bed_fixes.append('chest_to_mattress -> propped_up_on_elbows')
                elif 'kneeling_on_bed' in tl:
                    new_tags.append('kneeling_on_bed, firm_mattress, visible_knees')
                    bed_fixes.append('reforcado visible_knees')
                else:
                    new_tags.append(t)
            tags = new_tags
            if not any('firm_mattress' in t.lower() for t in tags):
                tags.append('firm_mattress, limbs_on_top_of_bed, clear_anatomy')
                logs.append('[Bed Protection] Injetado "firm_mattress, limbs_on_top_of_bed" para impedir que membros afundem no colchao.')
            if bed_fixes:
                logs.append(f'[Bed Protection Fixes] {", ".join(bed_fixes)}')

        # 11. Sanitização de Fruta Pera e Bloqueio de pear_shaped
        cleaned_tags = []
        for t in tags:
            tl = t.lower()
            if 'pear_shaped' in tl or 'pear-shaped' in tl:
                cleaned_tags.append('(wide_hips:1.3), (thick_thighs:1.3), narrow_waist, round_butt, curvy_lower_body')
                logs.append('[Body Sanitized] Substituido "pear_shaped" por tags precisas de curvas para impedir geracao de peras.')
            elif 'pearly' in tl:
                cleaned_tags.append(t.replace('pearly', 'thick'))
            elif tl.strip() in {'pear', 'pears'}:
                logs.append('[Fruit Removed] Removida tag "pear" para evitar aparecimento de fruta.')
            else:
                cleaned_tags.append(t)
        tags = cleaned_tags

        # 12. Sanitização de Câmeras e Velas Indesejadas
        cleaned_tags = []
        for t in tags:
            tl = t.lower()
            # Substituir referências a câmera física por looking_at_viewer
            if any(cam in tl for cam in ['holding vintage camera', 'taking photo with camera', 'polaroid camera', 'camera resting on floor', 'reaching toward lens']):
                logs.append(f'[Camera Removed] Removida referencia a objeto camera "{t}".')
                cleaned_tags.append('looking_at_viewer')
            elif 'towards camera' in tl or 'to camera' in tl or 'facing camera' in tl or 'into camera' in tl:
                cleaned_tags.append('looking_at_viewer')
            # Substituir velas físicas por iluminação âmbar suave
            elif any(cnd in tl for cnd in ['lighting_scented_candle', 'candlelight', 'candlelit', 'candles', 'burning candle']):
                logs.append(f'[Candle Removed] Substituida vela fisica "{t}" por iluminacao ambar aconchegante.')
                cleaned_tags.append('warm_amber_glow, dim_ambient_lighting')
            else:
                cleaned_tags.append(t)
        tags = cleaned_tags

        # 13. Anatomia e Genitália de Criaturas sem Pernas Humanas (Centaura, Sereia, Lamia, Aracne, Scylla, Slime)
        full_text_lower = ' '.join(tags).lower()
        non_human_creatures = {
            'centaur': ('corpo equino de 4 patas', '(equine_slit:1.4), (matching_equine_skin:1.3), horse_tail_raised'),
            'centaur_girl': ('corpo equino de 4 patas', '(equine_slit:1.4), (matching_equine_skin:1.3), horse_tail_raised'),
            'mermaid': ('cauda de peixe aquatica', '(aquatic_slit:1.4), (matching_scales_color:1.3), fish_slit'),
            'lamia': ('cauda serpentina', '(snake_slit:1.4), (matching_scales_color:1.3), reptilian_slit'),
                        'scylla': ('tentaculos aquaticos', '(tentacle_slit:1.4), (matching_tentacles_color:1.3), tentacles_parted'),
            'scylla_girl': ('tentaculos aquaticos', '(tentacle_slit:1.4), (matching_tentacles_color:1.3), tentacles_parted'),
            'slime_girl': ('corpo de slime translucido', '(translucent_slit:1.4), (liquid_pussy:1.3), matching_slime_color, gelatinous_slit')
        }
        detected_creatures = [k for k in non_human_creatures if k in full_text_lower]
        if detected_creatures:
            c_name = detected_creatures[0]
            c_desc, c_genital = non_human_creatures[c_name]
            
            # Purgar poses e membros que forçam pernas humanas (inclusive long_legs, trembling_legs, coxas)
            leg_conflicts = {
                'crossed_legs', 'one_leg_lifted', 'bare_legs', 'thighs_spread', 
                'kicking_feet', 'legs_apart', 'leg_dangling', 'bare_feet', 
                'walking_away', 'tiptoe', 'runner_stance', 'pigeon-toed',
                'legs_spread', 'kneeling_on_bed', 'w-sitting', 'sitting_cross-legged',
                'human_legs', 'human_feet', 'human_knees', 'feet', 'toes',
                'long_legs', 'trembling_legs', 'straight_legs', 'shapely_legs',
                'toned_legs', 'smooth_legs', 'm-shaped_legs', 'legs_in_the_air',
                'parting_own_thighs', 'caressing_own_thighs', 'thighs', 'toned_thighs',
                'plump_thighs', 'thick_thighs', 'slender_thighs', 'knees', 'shins', 'ankles'
            }
            new_tags = []
            purged_legs = []
            for t in tags:
                tl = t.lower()
                if any(lc in tl for lc in leg_conflicts):
                    purged_legs.append(t)
                else:
                    new_tags.append(t)
            tags = new_tags
            if purged_legs:
                logs.append(f'[Monster Anatomy Enforced] Removidas referencias a pernas humanas {purged_legs} para {c_name}.')

            # Para criaturas com cauda aquática ou serpentina (mermaid, lamia, scylla):
            # remover posturas bípedes (standing, kneeling, upright) e penetrações humanas que forçam pernas bípedes
            if c_name in ['mermaid', 'lamia', 'scylla', 'scylla_girl']:
                bipedal_poses = {'standing', 'kneeling', 'walking', 'running', 'tiptoe', 'runner_stance', 'weight_on_one_leg', 'one_leg_lifted', 'confident_stance', 'crawling_forward', 'upright'}
                bipedal_purged = [t for t in tags if any(bp == t.lower().strip() or f' {bp} ' in f' {t.lower()} ' for bp in bipedal_poses)]
                if bipedal_purged:
                    tags = [t for t in tags if t not in bipedal_purged]
                    logs.append(f'[Tail Purity] Removidas posturas bípedes {bipedal_purged} para {c_name}.')
                
                # Purgar termos de penetração e sexo bípede que obrigam a IA a sintetizar pernas humanas abertas
                penetration_conflicts = {
                    'vaginal_penetration', 'penetration', 'insertion', 'deep_pounding', 'large_penis', 
                    'belly_bulge', 'creampie', 'fingers_on_thighs', 'fingers_spreading_pussy', 
                    'paired_legs_up_m-frame', 'spooning_sex', 'side_penetration'
                }
                purged_pen = [t for t in tags if any(pc in t.lower() for pc in penetration_conflicts)]
                if purged_pen:
                    tags = [t for t in tags if t not in purged_pen]
                    tags.append('(tail_intertwined:1.3), (tail_embrace:1.3), (aquatic_mating:1.3), intimate_embrace, fondling_breasts')
                    logs.append(f'[Tail Anatomy Protection] Substituída penetração bípede {purged_pen} por abraço/acasalamento sensual com cauda para não dividir a cauda em pernas humanas.')

                if c_name == 'mermaid':
                    if not any('single_fish_tail' in t.lower() for t in tags):
                        tags = insert_contextual(tags, '(resting_on_tail:1.3), (curved_tail:1.3), (single_fish_tail:1.6), (mermaid_tail:1.5), (single_tail:1.6)', ['mermaid', '1girl'], place='after')
                        logs.append('[Mermaid Tail Enforced] Injetada cauda única de peixe curva e anatômica (single_tail) adjacente à raça.')
                    if not any('amermaidfxm' in t.lower() for t in tags):
                        tags = insert_contextual(tags, '<lora:illustrious\\monster_girls\\AMermaidFXM_concept-10:0.8>, mermaidxl', ['mermaid', 'single_fish_tail'], place='after')
                        logs.append('[Monster LoRA Loaded] LoRA AMermaidFXM_concept-10 acoplado adjacente à sereia.')
                elif c_name == 'lamia':
                    if not any('alamiaxl' in t.lower() for t in tags):
                        tags = insert_contextual(tags, '<lora:illustrious\\monster_girls\\ALamiaXL_concept-10:0.8>, lamiaxl', ['lamia', '1girl'], place='after')
                        logs.append('[Monster LoRA Loaded] LoRA ALamiaXL_concept-10 acoplado adjacente à lamia.')
                    if not any('single_snake_tail' in t.lower() for t in tags):
                        tags = insert_contextual(tags, '(single_snake_tail:1.35), (single_tail:1.3), continuous_serpentine_lower_body', ['lamiaxl', 'lamia', 'snake_lower_body'], place='after')
                        logs.append('[Lamia Cleanse] Cauda única garantida no positivo ((single_snake_tail:1.35)).')

            # Garantir tags positivas de reforço anatômico sem pernas humanas
            if not any('no_human_legs' in t.lower() for t in tags):
                tags = insert_contextual(tags, '(no_human_legs:1.6), (no_legs:1.5), (no_feet:1.5)', [c_name, 'single_fish_tail', 'curved_tail'], place='after')
                logs.append(f'[Monster Anatomy Enforced] Injetado "(no_human_legs:1.6), (no_legs:1.5)" adjacente a {c_name} ({c_desc}).')

            # Adaptação Genital e de Cor para Criaturas Não-Humanas
            genital_signals = {'pussy', 'bare_pussy', 'exposed_pussy', 'vaginal', 'fingering', 'cunnilingus', 'insertion', 'dildo', 'masturbation', 'crotchless'}
            has_genital_intent = any(any(gs in t.lower() for gs in genital_signals) for t in tags)
            if has_genital_intent:
                cleaned_genital_tags = []
                replaced_genitals = []
                for t in tags:
                    tl = t.lower()
                    if any(gs in tl for gs in ['bare_pussy', 'pussy', 'exposed_pussy']):
                        replaced_genitals.append(t)
                        cleaned_genital_tags.append(c_genital)
                    else:
                        cleaned_genital_tags.append(t)
                tags = cleaned_genital_tags
                if replaced_genitals:
                    logs.append(f'[Monster Genital Adapted] Genitalia adaptada para anatomia de {c_name}: {c_genital}.')
                elif not any(c_genital in t for t in tags):
                    tags = insert_contextual(tags, c_genital, ['bare_pussy', 'pussy', 'exposed_pussy', 'insertion', c_name], place='after')
                    logs.append(f'[Monster Genital Enforced] Injetada genitalia de especie/cor ({c_genital}) para {c_name}.')

        # 14. Slimes e Elementais: Supressão de Cores Humanas e Consistência Elemental
        elemental_types = {
            'air_elemental_girl': ('ar/vento', 'swirling_breeze_hair, (translucent_white_hair:1.4), (glowing_white_eyes:1.4), (misty_body:1.4), ethereal'),
            'water_elemental_girl': ('agua/liquido', '(liquid_hair:1.4), (translucent_cyan_hair:1.4), (glowing_cyan_eyes:1.4), (liquid_body:1.4), aquatic_glow'),
            'fire_elemental_girl': ('fogo/chamas', '(flame_hair:1.4), (blazing_fire_hair:1.4), (glowing_amber_eyes:1.4), (fire_elemental_body:1.4), fiery_aura'),
            'earth_elemental_girl': ('terra/cristais', '(crystalline_hair:1.4), (stone_textured_skin:1.3), (glowing_gold_eyes:1.4), rocky_accents')
        }
        is_elemental = any(k in full_text_lower for k in elemental_types)
        is_slime = 'slime_girl' in full_text_lower or 'slime_body' in full_text_lower
        if is_slime or is_elemental:
            human_hair_colors = {'blonde_hair', 'brown_hair', 'black_hair', 'red_hair', 'silver_hair', 'white_hair', 'pink_hair', 'blue_hair', 'green_hair', 'purple_hair', 'orange_hair', 'yellow_hair', 'grey_hair', 'gray_hair'}
            human_eye_colors = {'blue_eyes', 'green_eyes', 'brown_eyes', 'red_eyes', 'amber_eyes', 'hazel_eyes', 'purple_eyes', 'yellow_eyes', 'gold_eyes', 'golden_eyes', 'grey_eyes', 'gray_eyes'}
            purged_colors = []
            new_tags = []
            for t in tags:
                tl = t.lower().strip()
                if any(hc in tl for hc in human_hair_colors) or any(ec in tl for ec in human_eye_colors):
                    purged_colors.append(t)
                else:
                    new_tags.append(t)
            tags = new_tags
            if purged_colors:
                logs.append(f'[Elemental Cleanse] Removidas definicoes humanas de cabelo/olhos {purged_colors} para consistencia elemental.')
            if is_slime and not any('translucent_hair' in t.lower() for t in tags):
                tags = insert_contextual(tags, '(slime_hair:1.4), (translucent_hair:1.4), (translucent_eyes:1.3), matching_slime_color', ['slime_girl', '1girl'], place='after')
            for el_k, (el_desc, el_injected) in elemental_types.items():
                if el_k in full_text_lower:
                    tags = insert_contextual(tags, el_injected, [el_k, '1girl'], place='after')
                    logs.append(f'[Elemental Trait Enforced] Injetadas caracteristicas puras de {el_desc} adjacente à personagem.')
                    break

        # 14.1 Medusa / Gorgon: Cabelo Canonico de Serpentes Vivas e LoRA Gorgon
        if any(k in full_text_lower for k in ['gorgon_girl', 'gorgon', 'medusa', 'living_snakes_hair', 'snake_hair']):
            human_hairstyles = {
                'french_braid', 'twin_braids', 'braid', 'braids', 'single_braid', 'side_braid',
                'ponytail', 'high_ponytail', 'side_ponytail', 'twin_ponytails', 'pigtails', 'twintails',
                'twin_drills', 'drill_hair', 'bob_cut', 'pixie_cut', 'double_bun', 'space_buns',
                'half_updo', 'half_up_half_down', 'hair_bun', 'chignon', 'topknot', 'bangs',
                'parted_bangs', 'blunt_bangs', 'asymmetrical_hair', 'slicked_back', 'straight_hair',
                'wavy_hair', 'curly_hair', 'loose_hair', 'short_hair', 'long_hair', 'very_long_hair'
            }
            human_hair_colors = {
                'blonde_hair', 'brown_hair', 'black_hair', 'red_hair', 'silver_hair', 'white_hair',
                'pink_hair', 'blue_hair', 'purple_hair', 'orange_hair', 'yellow_hair', 'grey_hair', 'gray_hair'
            }
            purged_medusa_hair = []
            new_tags = []
            for t in tags:
                tl = t.lower().strip()
                if any(hs == tl or f' {hs} ' in f' {tl} ' for hs in human_hairstyles) or any(hc == tl or f' {hc} ' in f' {tl} ' for hc in human_hair_colors):
                    purged_medusa_hair.append(t)
                else:
                    new_tags.append(t)
            tags = new_tags
            if purged_medusa_hair:
                logs.append(f'[Medusa Hair Enforced] Removidos estilos/cores de cabelo humano {purged_medusa_hair} para manter serpentes vivas na cabeca.')
            if not any('living_snakes_for_hair' in t.lower() for t in tags):
                tags = insert_contextual(tags, '(living_snakes_for_hair:1.5), (writhing_snakes:1.4), (snake_heads_hair:1.5), (medusa_hair:1.4), serpentine_hair', ['medusa', 'gorgon_girl', 'gorgon', '1girl'], place='after')
                logs.append('[Medusa Hair Enforced] Injetado "living_snakes_for_hair, writhing_snakes, snake_heads_hair" adjacente a Medusa.')
            if not any('gorgonlora' in t.lower() for t in tags):
                tags = insert_contextual(tags, '<lora:illustrious\\monster_girls\\Gorgonlora-IL-000014:0.85>, snake hair, snake_hair, gorgon', ['medusa', 'gorgon_girl', 'gorgon', '1girl'], place='after')
                logs.append('[Monster LoRA Loaded] LoRA Gorgonlora-IL-000014 acoplado adjacente à Gorgon/Medusa.')

        # 14.2 Kitsune & Cerberus: Garantia e Preservacao de Multiplas Caudas (multiple_tails)
        if any(k in full_text_lower for k in ['kitsune', 'nine-tailed_fox', 'nine_tails', 'cerberus_girl', 'multiple_tails']):
            tags = [t for t in tags if not any(st == t.lower().strip() or f'({st}:' in t.lower() for st in ['single_tail', 'one_tail', 'single_fish_tail'])]
            if 'kitsune' in full_text_lower and not any('multiple_tails' in t.lower() for t in tags):
                tags = insert_contextual(tags, '(multiple_tails:1.5), (nine_fox_tails:1.4), fluffy_tails', ['kitsune', 'fox_tail', 'nine_tails', '1girl'], place='after')
                logs.append('[Kitsune Multi-Tails Enforced] Injetado "(multiple_tails:1.5), (nine_fox_tails:1.4), fluffy_tails" adjacente à Kitsune.')

        # 14.3 Robot / Android Girl: LoRA Especialista de Juntas Mecanicas
        if any(k in full_text_lower for k in ['robot_girl', 'android_girl', 'cyborg', 'synthetic_skin', 'mechanical_joints']):
            if not any('arobotgirls' in t.lower() for t in tags):
                tags = insert_contextual(tags, '<lora:illustrious\\monster_girls\\ARobotGirls_Concept-12:0.8>, robotxl', ['robot_girl', 'android_girl', 'cyborg', '1girl'], place='after')
                logs.append('[Monster LoRA Loaded] LoRA ARobotGirls_Concept-12 acoplado adjacente à garota robo.')

        # 14.4 Draenei: Chifres, Cauda, Pele Azul e Pernas Digitígradas/Cascos
        if any(k in full_text_lower for k in ['draenei', 'draenei_girl', 'eredar', 'dra-v1.0']):
            if not any('no_human_ears' in t.lower() for t in tags):
                tags = insert_contextual(tags, 'no_human_ears', ['draenei', 'pointy_ears', '1girl'], place='after')
            if not any('draenei-il' in t.lower() for t in tags):
                tags = insert_contextual(tags, '<lora:illustrious\\monster_girls\\Draenei-IL-000014:0.85>, dra-v1.0, dra-v1.0-f, draenei, horns, blue_skin', ['draenei', 'draenei_girl', '1girl'], place='after')
                logs.append('[Monster LoRA Loaded] LoRA Draenei-IL-000014 acoplado adjacente à Draenei.')

        # 14.5 Fairy / Pixie: Asas de Fada Etéreas e Purga de Asas Demoníacas/Penas
        if any(k in full_text_lower for k in ['fairy_girl', 'fairy', 'pixie', 'fsev1.0']):
            conflicting_wings = {'black_bat_wings', 'bat_wings', 'demon_wings', 'feathered_wings', 'angel_wings'}
            purged_wings = []
            new_tags = []
            for t in tags:
                tl = t.lower().strip()
                if any(cw in tl for cw in conflicting_wings):
                    purged_wings.append(t)
                else:
                    new_tags.append(t)
            if purged_wings:
                tags = new_tags
                logs.append(f'[Fairy Wings Cleanse] Removidas asas conflitantes {purged_wings} para garantir asas puras de fada.')
            if not any('fsev1.0' in t.lower() or 'fairy' in t.lower() and '<lora:' in t.lower() for t in tags):
                tags = insert_contextual(tags, '<lora:illustrious\\monster_girls\\FSEV1.0-000011:0.85>, fsev1.0, fairy, fairy wings, wings', ['fairy_girl', 'fairy', 'pixie', '1girl'], place='after')
                logs.append('[Monster LoRA Loaded] LoRA FSEV1.0-000011 acoplado adjacente à Fada.')

        # 15. Fantasmas, Poltergeists e Espíritos: Transparência Real e LoRAs Especialistas (SFW / NSFW)
        # ESTRITAMENTE para quando a personagem FOR de fato da raça fantasma (evita contaminar bunny_girl, elf, etc.)
        ghost_races = {'ghost_girl', 'ghost', 'poltergeist', 'phantom', 'spectral_body', 'banshee', 'ethereal_spirit'}
        is_ghost_race = any(re.search(r'\b' + re.escape(gr) + r'\b', full_text_lower) for gr in ghost_races)
        if is_ghost_race:
            opaque_skin_tags = {'pale skin', 'porcelain skin', 'tanned skin', 'dark skin', 'solid skin'}
            purged_skin = []
            new_tags = []
            for t in tags:
                tl = t.lower()
                if any(os_tag in tl for os_tag in opaque_skin_tags):
                    purged_skin.append(t)
                else:
                    new_tags.append(t)
            tags = new_tags
            if purged_skin:
                logs.append(f'[Ghost Body Cleanse] Removidas tags de pele opaca {purged_skin} para garantir transparencia.')
            if not any('see-through_body' in t.lower() for t in tags):
                tags = insert_contextual(tags, '(see-through_body:1.5), (translucent_body:1.4), (semi-transparent_skin:1.3), ethereal', ['ghost_girl', 'ghost', 'phantom', 'banshee', '1girl'], place='after')
                logs.append('[Ghost Transparency] Injetado "see-through_body, translucent_body, semi-transparent_skin" adjacente ao fantasma.')

            # Injeção dinâmica de LoRA de Ghost (SFW/Geral vs NSFW Ghost Sex)
            is_sexual = any(s in full_text_lower for s in [
                'sex', 'fucking', 'penetration', 'dildo', 'insertion', 'vaginal', 'anal',
                'blowjob', 'fellatio', 'cunnilingus', 'fingering', 'masturbation', 'paizuri',
                'creampie', 'cum', 'ghost sex', 'ghost_sex'
            ])
            if is_sexual:
                if not any('ghost_sex' in t.lower() or 'ghost-sfwnsfw' in t.lower() for t in tags):
                    tags = insert_contextual(tags, '<lora:illustrious\\monster_girls\\Ghost_sex:0.85>, ghost sex, translucent body', ['ghost_girl', 'ghost', 'phantom', 'banshee', '1girl'], place='after')
                    logs.append('[Monster LoRA Loaded] LoRA Ghost_sex acoplado dinamicamente para cena de fantasma NSFW.')
            else:
                if not any('ghost-sfwnsfw' in t.lower() or 'ghost_sex' in t.lower() for t in tags):
                    tags = insert_contextual(tags, '<lora:illustrious\\monster_girls\\Ghost-SFWNSFW-IL.V1.0-000013:0.85>, ghost, translucent body, see-through body', ['ghost_girl', 'ghost', 'phantom', 'banshee', '1girl'], place='after')
                    logs.append('[Monster LoRA Loaded] LoRA Ghost-SFWNSFW-IL acoplado dinamicamente para personagem fantasma.')
        else:
            # Se NÃO for raça fantasma, expurga qualquer menção acidental a ghost sex ou corpo translúcido
            rogue_ghost = [t for t in tags if any(k in t.lower() for k in ['ghost_sex', 'ghost sex', 'fucking_a_ghost', 'spectral_penetration', 'ghost-sfwnsfw'])]
            if rogue_ghost:
                tags = [t for t in tags if t not in rogue_ghost]
                logs.append(f'[Ghost Purge] Removidos termos de fantasma {rogue_ghost} pois a personagem não é de raça fantasma.')

        # 15.1 Orc Girl: LoRA Especialista Orc (50% de ativação sorteada) e Desobrigação de Dreadlocks
        if any(k in full_text_lower for k in ['orc_girl', 'orc', 'female_orc', 'orc_woman']):
            should_activate_orc_lora = (prompt_hash_val % 100 < 50)
            if should_activate_orc_lora:
                if not any('orc-e33' in t.lower() or ('orc' in t.lower() and '<lora:' in t.lower()) for t in tags):
                    tags = insert_contextual(tags, '<lora:illustrious\\monster_girls\\Orc-e33_s1155:0.85>, orc, orc_girl, green_skin, tusks', ['orc_girl', 'orc', '1girl'], place='after')
                    logs.append('[Monster LoRA Loaded] LoRA Orc-e33_s1155 acoplado adjacente à Orc (50% de chance sorteada).')
            else:
                logs.append('[Orc Base Style] LoRA Orc-e33_s1155 dispensado nesta geração (50% de chance: estilo Orc nativo do checkpoint).')

            # Desobrigação de dreadlocks: não forçar dreadlocks na Orc para permitir variedade de penteados
            if any('dreadlock' in t.lower() for t in tags):
                tags = [t for t in tags if not any(d in t.lower() for d in ['dreadlocks', 'dreadlock'])]
                logs.append('[Orc Hair Diversity] Removido "dreadlocks" obrigatório para permitir diversidade de penteados na Orc.')

        # 15.2 Flesh Unit: Unidade Assimilada Biomecânica (Raça Própria)
        if any(k in full_text_lower for k in ['flesh_unit', 'flesh unit', 'assimilated_unit', 'biomechanical_girl']):
            if not any('flesh_unit' in t.lower() and '<lora:' in t.lower() for t in tags):
                is_nsfw_scene = any(s in full_text_lower for s in ['nsfw', 'nude', 'naked', 'sex', 'penetration', 'dildo'])
                flesh_triggers = 'flesh_unit, biomechanical, cybernetic_body, synthetic_skin' if is_nsfw_scene else 'flesh_unit, biomechanical, cybernetic_implants'
                tags = insert_contextual(tags, f'<lora:illustrious\\monster_girls\\flesh_unit_5.1:0.85>, {flesh_triggers}', ['flesh_unit', 'assimilated_unit', '1girl'], place='after')
                logs.append(f'[Monster LoRA Loaded] LoRA flesh_unit_5.1 acoplado para Flesh Unit (modo {"NSFW" if is_nsfw_scene else "SFW"}).')

        # 15.3 Gazelle Race: Chifres e Traços de Gazela
        if any(k in full_text_lower for k in ['gazelle_girl', 'gazelle_race', 'gazelle']):
            if not any('gazelle' in t.lower() and '<lora:' in t.lower() for t in tags):
                tags = insert_contextual(tags, '<lora:illustrious\\monster_girls\\Gazelle_Race-e66_s1122:0.85>, gazelle_race, gazelle horns', ['gazelle_girl', 'gazelle_race', 'gazelle', '1girl'], place='after')
                logs.append('[Monster LoRA Loaded] LoRA Gazelle_Race-e66_s1122 acoplado adjacente à Gazela.')

        # 15.4 Pandawa: Menina Panda (Wakfu/Fantasy)
        if any(k in full_text_lower for k in ['pandawa', 'pand4w4', 'pand4w4_w4kfu', 'panda_girl']):
            if not any('pand4w4' in t.lower() and '<lora:' in t.lower() for t in tags):
                tags = insert_contextual(tags, '<lora:illustrious\\monster_girls\\pand4w4_w4kfu_IL:0.85>, pand4w4_w4kfu, giant panda, animal ears, two tone body', ['pandawa', 'panda_girl', '1girl'], place='after')
                logs.append('[Monster LoRA Loaded] LoRA pand4w4_w4kfu_IL acoplado adjacente à Pandawa.')

        # 15.5 Serpent Race: Escamas e Traços de Serpente
        if any(k in full_text_lower for k in ['serpent_girl', 'serpent_race', 'serpent']) and not any('lamiaxl' in t.lower() for t in tags):
            if not any('serpent' in t.lower() and '<lora:' in t.lower() for t in tags):
                tags = insert_contextual(tags, '<lora:illustrious\\monster_girls\\Serpent-e40_s1360:0.85>, serpent, snake scales', ['serpent_girl', 'serpent_race', 'serpent', '1girl'], place='after')
                logs.append('[Monster LoRA Loaded] LoRA Serpent-e40_s1360 acoplado adjacente à Serpente.')

        # 15.6 Na'vi: Avatar / Orelhas Pontudas, Pele Azul e Olhos Amarelos
        if any(k in full_text_lower for k in ["na'vi", 'navi_girl', 'navi_race', 'avatar_race']):
            if not any('navi' in t.lower() and '<lora:' in t.lower() for t in tags):
                tags = insert_contextual(tags, "<lora:illustrious\\monster_girls\\NaVi_Race_Avatar_JC_illustrious_Leaf1:0.85>, na'vi, blue skin, pointy ears, yellow eyes", ["na'vi", 'navi_girl', '1girl'], place='after')
                logs.append("[Monster LoRA Loaded] LoRA NaVi_Race_Avatar_JC_illustrious_Leaf1 acoplado adjacente à Na'vi.")

        # 15.7 Saber-toothed: Smilodon / Dente-de-Sabre
        if any(k in full_text_lower for k in ['saber_toothed', 'saber-toothed', 'saber-tooth', 'smilodon']):
            if not any('saber-tooth' in t.lower() and '<lora:' in t.lower() for t in tags):
                tags = insert_contextual(tags, '<lora:illustrious\\monster_girls\\Saber-toothed:0.85>, saber-tooth, saber-toothed, smilodon tail, countershading', ['saber-toothed', 'saber-tooth', 'smilodon', '1girl'], place='after')
                logs.append('[Monster LoRA Loaded] LoRA Saber-toothed acoplado adjacente à Tigresa Dente-de-Sabre.')

        # 15.8 Bee Girl: Menina Abelha / Inseto Alado
        if any(k in full_text_lower for k in ['bee_girl', 'honey_bee', 'bee_wings']):
            if not any('no_human_ears' in t.lower() for t in tags):
                tags = insert_contextual(tags, 'no_human_ears', ['bee_girl', 'insect_antennae', '1girl'], place='after')
            if not any('translucent_wings' in t.lower() or 'bee_wings' in t.lower() for t in tags):
                tags = insert_contextual(tags, '(bee_wings:1.25), (insect_antennae:1.2), translucent_wings', ['bee_girl', '1girl'], place='after')
            logs.append('[Monster Trait Enforced] Injetadas asas de abelha e antenas anatômicas para Bee Girl.')

        # 16. Moderação de Expressões Faciais Excessivas (love-struck é preservado e permitido!)
        drool_heart_tags = {'drooling', 'drool_bead', 'swirling_pupils', 'heart_shaped_pupils'}
        cleaned_tags = []
        for t in tags:
            tl = t.lower()
            if any(dh in tl for dh in drool_heart_tags):
                logs.append(f'[Expression Sanitized] Removido efeito exagerado "{t}" (baba/pupilas em coracao).')
                cleaned_tags.append('parted_lips')
            else:
                cleaned_tags.append(t)
        tags = cleaned_tags

        # 17. Prevenção de Cabeças Flutuantes / Rostos Fantasmas quando Parceiro está Fora de Quadro (male_out_of_frame)
        if 'male_out_of_frame' in full_text_lower or 'faceless_male' in full_text_lower:
            head_contact_actions = {
                'tender_whispering', 'whispering_in_ear', 'whispering', 'intense_gaze',
                'eye_contact_with_partner', 'kissing', 'french_kiss', 'deep_kiss',
                'forehead_touch', 'mouth_to_mouth', 'looking_into_each_others_eyes'
            }
            new_tags = []
            purged_contacts = []
            for t in tags:
                tl = t.lower().strip()
                if any(hca in tl for hca in head_contact_actions):
                    purged_contacts.append(t)
                else:
                    new_tags.append(t)
            if purged_contacts:
                tags = insert_contextual(new_tags, 'head_tilted_back, pleasure_face, heavy_breathing, blush', ['male_out_of_frame', 'faceless_male'], place='after')
                logs.append(f'[Out-of-Frame Cleanse] Removidas acoes de contato facial {purged_contacts} pois o parceiro esta fora de quadro (male_out_of_frame), evitando cabecas flutuantes deformadas.')

        # 18. LoRAs NSFW Especializados sob Demanda Contextual (NUNCA sorteados aleatoriamente)
        import random, hashlib
        full_text_lower = ' '.join(tags).lower()
        # Hash determinístico do prompt para consistência estrita entre o gerador e o leitor de metadados da galeria
        prompt_hash_val = int(hashlib.md5(full_text_lower.encode('utf-8')).hexdigest()[:6], 16)

        # LoRA 1: Freaky Dicks (50% de chance quando 1boy|1other aparecer no prompt, ou 100% quando pênis/ato explícito for promptado)
        boy_other_match = re.search(r'\b(1boy|1other|male_out_of_frame|faceless_male|large_penis|penis|dick|fdicks)\b', full_text_lower)
        if boy_other_match:
            is_explicit_penis = any(re.search(r'\b' + re.escape(p) + r'\b', full_text_lower) for p in [
                'penis', 'large_penis', 'dick', 'cock', 'glans', 'erection', 'fdicks', 'veiny_penis',
                'vaginal_penetration', 'anal_penetration', 'deep_penetration', 'blowjob', 'fellatio', 'creampie'
            ])
            should_activate_fdicks = is_explicit_penis or (prompt_hash_val % 100 < 50)
            if should_activate_fdicks:
                if not any('1-freaky_dicks' in t.lower() for t in tags):
                    # Seleção inteligente de trigger de variação treinado (por criatura/raça ou rotação criativa completa)
                    if any(w in full_text_lower for w in ['tentacle', 'squid', 'octopus', 'kraken', 'eldritch', 'slime']):
                        chosen_trig = 'fdicks, tentacle_penis, huge_penis'
                    elif any(w in full_text_lower for w in ['horse', 'centaur', 'stallion', 'equine', 'unicorn', 'donkey']):
                        chosen_trig = 'fdicks, horse_penis, huge_penis, equine_knot'
                    elif any(w in full_text_lower for w in ['dog', 'wolf', 'canine', 'werewolf', 'fox', 'anubis', 'gnoll', 'kobold', 'hound']):
                        chosen_trig = 'fdicks, canine_penis, knotted, huge_penis'
                    elif any(w in full_text_lower for w in ['dragon', 'lizard', 'reptile', 'demon', 'devil', 'gargoyle', 'succubus', 'incubus']):
                        chosen_trig = 'fdicks, spiked_penis, veiny_penis, huge_penis'
                    elif any(w in full_text_lower for w in ['orc', 'goblin', 'troll', 'ogre', 'monster', 'beast']):
                        chosen_trig = 'fdicks, bumped_penis, huge_penis, veiny_penis'
                    elif any(w in full_text_lower for w in ['alien', 'xenomorph', 'cosmic', 'extraterrestrial']):
                        chosen_trig = 'fdicks, alien_penis, shiny_skin'
                    elif any(w in full_text_lower for w in ['insect', 'bug', 'arachne', 'spider', 'mantis', 'chitin']):
                        chosen_trig = 'fdicks, segmented_penis, realistic'
                    elif any(w in full_text_lower for w in ['robot', 'android', 'cyborg', 'mech', 'automaton']):
                        chosen_trig = 'fdicks, robot_penis, shiny_skin'
                    else:
                        # Rotação rica em todas as variações oficiais treinadas do LoRA para parceiros 1boy|1Other
                        all_freaky_variations = [
                            'fdicks, canine_penis, knotted, huge_penis',
                            'fdicks, horse_penis, huge_penis, equine_knot',
                            'fdicks, tentacle_penis, huge_penis',
                            'fdicks, spiked_penis, veiny_penis',
                            'fdicks, bumped_penis, huge_penis',
                            'fdicks, alien_penis, shiny_skin, erection',
                            'fdicks, segmented_penis, realistic',
                            'fdicks, veiny_penis, huge_penis, realistic',
                            'fdicks, knotted, huge_penis, erection',
                            'fdicks, robot_penis, shiny_skin'
                        ]
                        chosen_trig = all_freaky_variations[prompt_hash_val % len(all_freaky_variations)]

                    lora_tag = '<lora:illustrious\\nsfw\\1-Freaky_dicksv3.safetensors:0.8>'
                    penis_anchors = ['large_penis', 'penis', '1boy|1other', '1boy', '1other', 'male_out_of_frame', 'faceless_male', 'partner', 'vaginal_penetration', 'anal_penetration', 'blowjob']
                    tags = insert_contextual(tags, lora_tag, penis_anchors, place='after')
                    tags = insert_contextual(tags, chosen_trig, [lora_tag, 'large_penis', 'penis', '1boy|1other'], place='after')
                    logs.append(f'[NSFW LoRA 1 Injected] Freaky_dicksv3 acoplado contextualmente ao lado do pênis/masculino com trigger de variação "{chosen_trig}".')

        # LoRA 2: Masturbation with Dildo (atividades nsfw com objetos ou sex_toys)
        dildo_match = any(d in full_text_lower for d in ['dildo', 'sex_toy', 'sex toy', 'object_insertion', 'object insertion', 'vaginal object insertion', 'using_dildo', 'holding_dildo'])
        if dildo_match:
            if not any('2-masturbation with dildo' in t.lower() for t in tags):
                lora_tag = '<lora:illustrious\\nsfw\\2-Masturbation with dildo (illustrious) v1.safetensors:0.8>'
                dildo_trig = 'dildomasturbation, sex toy, dildo, vaginal object insertion'
                tags = insert_contextual(tags, lora_tag, ['using_dildo', 'holding_dildo', 'dildo', 'sex_toy', 'sex toy', 'insertion', 'masturbation'], place='after')
                tags = insert_contextual(tags, dildo_trig, [lora_tag, 'dildo', 'sex_toy'], place='after')
                logs.append('[NSFW LoRA 2 Injected] Masturbation with Dildo acoplado contextualmente ao lado do objeto/sex_toy.')

        # LoRA 3: Spread Anus (apresentação ou exibição do ânus)
        anus_match = any(a in full_text_lower for a in ['anus', 'spread_anus', 'spread anus', 'showing_anus', 'presenting_anus', 'ass_presentation', 'exposed_anus', 'anal_view'])
        if anus_match:
            if not any('3-spreadanusill' in t.lower() for t in tags):
                lora_tag = '<lora:illustrious\\nsfw\\3-spreadanusill.safetensors:0.8>'
                anus_trig = 'spreadanusill, spread anus, anus'
                tags = insert_contextual(tags, lora_tag, ['spread_anus', 'showing_anus', 'presenting_anus', 'ass_presentation', 'anus', 'ass'], place='after')
                tags = insert_contextual(tags, anus_trig, [lora_tag, 'anus', 'ass'], place='after')
                logs.append('[NSFW LoRA 3 Injected] SpreadAnusIll acoplado contextualmente ao lado da apresentação do ânus.')

        # LoRA 4: Butt Plugs (quando plugs forem promptados)
        plug_match = any(p in full_text_lower for p in [
            'buttplug', 'butt_plug', 'butt plug', 'anal_plug', 'tail_plug', 
            'butt_blug', 'blug', 'plug', 'jewel_butt_plug', 'anal_beads'
        ])
        if plug_match:
            if not any('4-buttplugs' in t.lower() for t in tags):
                lora_tag = '<lora:illustrious\\nsfw\\4-buttplugs.safetensors:0.8>'
                plug_trig = 'buttplug, anal object insertion, sex toy'
                if 'jewel' in full_text_lower:
                    plug_trig = 'buttplug, jewel butt plug, anal object insertion, sex toy'
                tags = insert_contextual(tags, lora_tag, ['buttplug', 'butt_plug', 'anal_plug', 'tail_plug', 'butt_blug', 'plug'], place='after')
                tags = insert_contextual(tags, plug_trig, [lora_tag, 'buttplug', 'plug'], place='after')
                logs.append('[NSFW LoRA 4 Injected] ButtPlugs acoplado contextualmente ao lado da menção de plug.')


        # LoRA 6: HeldByGiant (segurada na mão de gigante / diferença extrema de tamanho)
        # Compatível com qualquer raça (humana, elfa, orc, etc.) quando em cena de gigante.
        # Raças pequenas (fairy, goblin_girl, bee_girl, pixie) possuem probabilidade de ativação ampliada.
        # Garantia posicional estrita: sempre deve conter penetração (vaginal ou anal) e postura corporal compatível (legs_spread, legs_apart, doggy_style, from_behind, all_fours).
        is_small_race = any(r in full_text_lower for r in ['fairy', 'goblin_girl', 'bee_girl', 'pixie', 'tiny_girl', 'fairy_girl'])
        has_partner = any(p in full_text_lower for p in ['1boy', '1other', '1boy|1other', 'giant_male', 'male_focus', 'partner'])
        giant_match = any(g in full_text_lower for g in [
            'heldbygiant', 'held_by_giant', 'held_in_giant_hand', 'in_giant_hand',
            'held_in_hand', 'picked_up_by_giant', 'giant_hand', 'giant_fingers',
            'held_in_single_giant_hand', 'held_between_fingers'
        ]) or ('giant' in full_text_lower and 'size_difference' in full_text_lower)

        # Frequência ampliada para raças pequenas em interações com parceiro
        if not giant_match and has_partner:
            threshold = 35 if is_small_race else 10
            if 'size_difference' in full_text_lower or (prompt_hash_val % 100 < threshold):
                giant_match = True
                tags = insert_contextual(tags, 'giant_male, towering_male, size_difference, held_by_giant, suspended_in_air', ['1boy|1other', '1boy', 'female_focus', '1girl'], place='after')
                full_text_lower = ' '.join(tags).lower()
                logs.append(f'[NSFW LoRA 6 Triggered] HeldByGiant ativado contextualmente (chance: {threshold}%).')

        if giant_match:
            # Garantia posicional e anatômica estrita de penetração
            has_penetration = any(p in full_text_lower for p in ['vaginal_penetration', 'anal_penetration', 'double_penetration', 'penetration'])
            if not has_penetration:
                chosen_penetration = 'anal_penetration' if (prompt_hash_val % 3 == 0) else 'vaginal_penetration'
                tags = insert_contextual(tags, chosen_penetration, ['held_by_giant', 'size_difference', 'giant_male', 'female_focus', '1girl'], place='after')
                full_text_lower = ' '.join(tags).lower()
                logs.append(f'[NSFW LoRA 6 Guarantee] Penetração garantida contextualmente: "{chosen_penetration}".')

            # Garantia de postura anatômica compatível
            has_position = any(pos in full_text_lower for pos in [
                'legs_spread', 'spread_legs', 'legs_apart', 'doggy_style', 'from_behind', 'all_fours', 'lifted_from_behind'
            ])
            if not has_position:
                chosen_pos = 'legs_apart, from_behind, doggy_style' if (prompt_hash_val % 2 == 0) else 'legs_spread'
                tags = insert_contextual(tags, chosen_pos, ['vaginal_penetration', 'anal_penetration', 'held_by_giant', 'size_difference'], place='after')
                full_text_lower = ' '.join(tags).lower()
                logs.append(f'[NSFW LoRA 6 Guarantee] Postura anatômica garantida contextualmente: "{chosen_pos}".')

            # Injeção contextual do LoRA e Trigger oficial
            if not any('6-heldbygiant' in t.lower() for t in tags):
                lora_tag = '<lora:illustrious\\nsfw\\6-HeldByGiantV2ILLLLLLLLL_epoch_11.safetensors:0.8>'
                giant_trig = 'HeldByGiantV2ILLLLLLLLL'
                tags = insert_contextual(tags, lora_tag, ['held_by_giant', 'size_difference', 'giant_male', '1boy|1other', '1girl', 'female_focus'], place='after')
                tags = insert_contextual(tags, giant_trig, [lora_tag, 'held_by_giant', 'size_difference'], place='after')
                logs.append('[NSFW LoRA 6 Injected] HeldByGiantV2ILLLLLLLLL acoplado contextualmente.')

        # LoRA 7: Lesbian Anal Strap-on (strap-on / pegging)
        strapon_match = any(st in full_text_lower for st in [
            'strap-on', 'strapon', 'pegging', 'lestraabed', 'strap_on'
        ])
        if strapon_match:
            if not any('7-il_lesbian' in t.lower() or ('strap-on' in t.lower() and '<lora:' in t.lower()) for t in tags):
                lora_tag = '<lora:illustrious\\nsfw\\7-IL_Lesbian_anal_strap-on.safetensors:0.8>'
                tags = insert_contextual(tags, lora_tag, ['strap-on', 'strapon', 'pegging', 'lestraabed', '2girls', '1girl'], place='after')
                if not any('lestraabed' in t.lower() for t in tags):
                    tags = insert_contextual(tags, 'lestraabed, strap-on', [lora_tag, 'strap-on', 'strapon'], place='after')
                logs.append('[NSFW LoRA 7 Injected] 7-IL_Lesbian_anal_strap-on acoplado contextualmente.')

        # LoRA 8: Masterfist (fisting vaginal / anal)
        fisting_match = any(ft in full_text_lower for ft in [
            'fisting', 'vaginal_fisting', 'anal_fisting', 'masterfist', 'inpussy', 'inass'
        ])
        if fisting_match:
            if not any('8-masterfist' in t.lower() or ('masterfist' in t.lower() and '<lora:' in t.lower()) for t in tags):
                lora_tag = '<lora:illustrious\\nsfw\\8-Masterfist_IL.safetensors:0.8>'
                tags = insert_contextual(tags, lora_tag, ['fisting', 'vaginal_fisting', 'anal_fisting', '1girl', 'female_focus'], place='after')
                fist_trig = 'Masterfist_IL, inass, realistic' if 'anal' in full_text_lower else 'Masterfist_IL, inpussy, realistic'
                if not any('masterfist' in t.lower() for t in tags):
                    tags = insert_contextual(tags, fist_trig, [lora_tag, 'fisting'], place='after')
                logs.append('[NSFW LoRA 8 Injected] Masterfist_IL acoplado contextualmente para fisting.')

        # 19. Equilíbrio Dinâmico de Pesos e Anti-Burn / Anti-Supersaturação
        # Multiplicadores excessivos (> 1.20) no SDXL / Illustrious degradam e estressam o espaço latente,
        # causando aberrações cromáticas (pele verde-neon, tentáculos em rosa-choque, sombras esmagadas).
        # Normaliza dinamicamente multiplicadores para a faixa segura (1.10 - 1.20) sem descaracterizar a cena.
        def _balance_weight(match):
            tag_name = match.group(1).strip()
            try:
                weight_val = float(match.group(2))
            except ValueError:
                return match.group(0)

            # Tags de cor/textura corporal (pele, membros, asas, olhos, tentaculos)
            chromatic_tags = ['skin', 'body', 'tentacle', 'slime', 'stone', 'fire', 'scales', 'chitin', 'hair', 'eyes', 'ears', 'horns']
            if any(ct in tag_name.lower() for ct in chromatic_tags):
                max_allowed = 1.15
            else:
                max_allowed = 1.20

            if weight_val > max_allowed:
                logs.append(f'[Weight Balanced] Ajustado peso de ({tag_name}:{weight_val}) para ({tag_name}:{max_allowed:.2f}) para preservar harmonia cromatica.')
                return f'({tag_name}:{max_allowed:.2f})'
            return match.group(0)

        balanced_tags = []
        for t in tags:
            # Achata parênteses duplos com pesos ((tag:peso)) -> (tag:peso) para evitar multiplicação quadrática
            t_flat = re.sub(r'\(\(([^:()]+):([0-9.]+)\)\)', r'(\1:\2)', t)
            bt = re.sub(r'\(([^:()]+):([0-9.]+)\)', _balance_weight, t_flat)
            balanced_tags.append(bt)
        tags = balanced_tags

        # 20. Resoluções Finais de Conflito de Pose e Expansões de Efeito
        # (A) Conflito de straddling em solo: se for solo, substitui straddling por squatting/kneeling
        is_solo_scene = any(t.lower() == 'solo' for t in tags) and not any(p in ' '.join(tags).lower() for p in ['1boy', '1other', '2girls', 'partner', 'giant_male'])
        if is_solo_scene:
            tags = [re.sub(r'\bstraddling\b', 'squatting, legs_apart', t, flags=re.IGNORECASE) for t in tags]

        # (B) Conflito de contrapposto / hip_cocked com poses no chão ou de costas
        has_ground_or_back_pose = any(p in ' '.join(tags).lower() for p in ['from_behind', 'lying_on_stomach', 'all_fours', 'doggy_pose', 'curled_up'])
        if has_ground_or_back_pose:
            tags = [t for t in tags if t.lower() not in ['contrapposto', 'hip_cocked', 'leaning_forward']]

        # (C) Potencialização de lots_of_cum para efeito real de sêmen abundante e espesso no Illustrious
        new_cum_tags = []
        for t in tags:
            if 'lots_of_cum' in t.lower() and 'thick_cum' not in t.lower():
                new_cum_tags.append('((lots_of_cum, thick_cum, copious_cum, excessive_cum, cum_dripping:1.3)), (covered_in_cum:1.2), white_cum')
            else:
                new_cum_tags.append(t)
        tags = new_cum_tags

        cur_prompt_lower = ' '.join(tags).lower()

        # (C.1) Garantia de Fisting de Mao Unica (impede double fisting nao solicitado)
        has_fisting = any(f in cur_prompt_lower for f in ['fisting', 'vaginal_fisting', 'anal_fisting', 'hand_insertion', 'masterfist'])
        has_double = any(df in cur_prompt_lower for df in ['double_fisting', 'two_hands_fisting', 'two_hands_insertion', 'two_fists', 'both_hands_insertion'])
        if has_fisting and not has_double:
            if not any('single_hand_fisting' in t.lower() for t in tags):
                tags = insert_contextual(tags, '(single_hand_fisting:1.25), (one_hand_insertion:1.25)', ['vaginal_fisting', 'anal_fisting', 'fisting', 'inpussy', 'inass', 'masterfist'], place='after')
                logs.append('[Fisting Enforcement] Fisting de mao unica garantido no positivo ((single_hand_fisting:1.25)).')

        # (C.2) Reforco de Corpo Espectral para Garota Fantasma (impede humana normal com mascote)
        is_ghost_race = any(g in cur_prompt_lower for g in ['ghost_girl', 'poltergeist', 'phantom_girl', 'spectral_body'])
        if is_ghost_race:
            if not any('translucent_skin' in t.lower() for t in tags):
                tags = insert_contextual(tags, '(translucent_skin:1.3), (spectral_body:1.3), (see-through_body:1.3), glowing_spectral_skin', ['ghost_girl', 'poltergeist_girl', 'phantom_girl', '1girl'], place='after')
                logs.append('[Ghost Enhancement] Corpo espectral/translucido reforcado na garota.')

        # (D) Contraste de parceiro para 1boy|1Other (100% male_out_of_frame, foco total na garota, sem elfos)
        cur_prompt_lower = ' '.join(tags).lower()
        if any(p in cur_prompt_lower for p in ['1boy', '1other', '1boy|1other', 'male_focus']) and not any(r in cur_prompt_lower for r in ['orc_male', 'dark_skin_male', 'demon_male', 'beastman_male', 'pale_skin_male', 'faceless_male', 'tanned_skin_male', 'wolfman_male']):
            partner_contrasts = [
                'male_out_of_frame, faceless_male, orc_male, green_skin, muscular_hands, claws, broad_hands, rough_skin',
                'male_out_of_frame, faceless_male, dark_skin_male, large_hands, muscular_hands, strong_grip, veins',
                'male_out_of_frame, faceless_male, tanned_skin_male, rough_hands, strong_grip, veins, muscular_forearms',
                'male_out_of_frame, faceless_male, demon_male, dark_red_skin, sharp_claws, clawed_hands',
                'male_out_of_frame, faceless_male, pale_skin_male, vascular_arms, firm_hands, strong_grip',
                'male_out_of_frame, faceless_male, beastman_male, furry_arms, animal_claws, strong_hands',
                'male_out_of_frame, faceless_male, dark_silhouette, shadowy_hands, strong_grip',
                'male_out_of_frame, faceless_male, orc_male, dark_green_skin, muscular_forearms, large_hands'
            ]
            chosen_partner = partner_contrasts[prompt_hash_val % len(partner_contrasts)]
            tags = insert_contextual(tags, chosen_partner, ['1boy|1other', '1boy', '1other', 'female_focus'], place='after')
            logs.append(f'[Partner Contrast] Parceiro out_of_frame qualificado com contraste: "{chosen_partner.split(",")[2].strip()}".')

        # (E) Passada final rigorosa de normalização Danbooru (garante underscores em tags de pênis, LoRA e corpo)
        final_danbooru_fixes = [
            (r'\b([a-zA-Z0-9_-]+)\s+penis\b', r'\1_penis'),
            (r'\b([a-zA-Z0-9_-]+)\s+hair\b', r'\1_hair'),
            (r'\b([a-zA-Z0-9_-]+)\s+eyes\b', r'\1_eyes'),
            (r'\bspread\s+anus\b', 'spread_anus'),
            (r'\bsex\s+toy\b', 'sex_toy'),
            (r'\banal\s+object\s+insertion\b', 'anal_object_insertion'),
            (r'\bequine\s+knot\b', 'equine_knot'),
            (r'\bshiny\s+skin\b', 'shiny_skin'),
            (r'\brule\s+of\s+thirds\b', 'rule_of_thirds'),
            (r'\bbest\s+quality\b', 'best_quality'),
            (r'\btop\s+quality\b', 'top_quality'),
            (r'\bvery\s+aesthetic\b', 'very_aesthetic'),
            (r'\bhighly\s+aesthetic\b', 'highly_aesthetic'),
            (r'\bstunning\s+illustration\b', 'stunning_illustration'),
            (r'\bdetailed\s+artwork\b', 'detailed_artwork'),
            (r'\bsee\s+through\s+body\b', 'see-through_body'),
            (r'\btranslucent\s+body\b', 'translucent_body'),
            (r'\btwo\s+legs\b', 'two_legs'),
            (r'\bmultiple\s+legs\b', 'multiple_legs'),
            (r'\bmissile\s+pod\b', 'missile_pod'),
            (r'\bholding\s+railgun\b', 'holding_railgun'),
            (r'\bholding\s+cannon\b', 'holding_cannon'),
            (r'\bholding\s+gatling\s+gun\b', 'holding_gatling_gun'),
            (r'\bglowing\s+eyes\b', 'glowing_eyes'),
            (r'\bvaginal\s+object\s+insertion\b', 'vaginal_object_insertion'),
            (r'\bbare\s+breasts\b', 'bare_breasts'),
            (r'\bbare\s+pussy\b', 'bare_pussy'),
            (r'\bbare\s+anus\b', 'bare_anus'),
            (r'\bparted\s+lips\b', 'parted_lips'),
            (r'\bopen\s+mouth\b', 'open_mouth'),
            (r'\bclosed\s+eyes\b', 'closed_eyes'),
            (r'\blying\s+on\s+back\b', 'lying_on_back'),
            (r'\blying\s+on\s+stomach\b', 'lying_on_stomach'),
            (r'\blegs\s+spread\b', 'legs_spread'),
            (r'\b(arched|arching)\s+back\b', 'arched_back'),
        ]
        cleansed_tags = []
        for t in tags:
            clean_t = t
            if not clean_t.startswith('<') and not clean_t.startswith('('):
                for pat, rep in final_danbooru_fixes:
                    clean_t = re.sub(pat, rep, clean_t, flags=re.IGNORECASE)
            cleansed_tags.append(clean_t)
        tags = cleansed_tags

        reviewed_prompt = ', '.join(tags)
        log_summary = '\n'.join(logs) if logs else '[OK] Nenhum conflito detectado no prompt.'
        try:
            import gc, torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        return (reviewed_prompt, log_summary)


# --- NÓ CUSTOMIZADO: CARREGADOR INDIVIDUAL DE LORA COM TRIGGER ---
class LoraWithTrigger:
    """
    Carregador de LoRA individual que disponibiliza o trigger oficial automaticamente na saída de texto.
    """
    @classmethod
    def INPUT_TYPES(s):
        import folder_paths
        lora_list = folder_paths.get_filename_list("loras")
        return {
            "required": {
                "model": ("MODEL",),
                "clip": ("CLIP",),
                "lora_name": (lora_list,),
                "strength_model": ("FLOAT", {"default": 0.8, "min": -10.0, "max": 10.0, "step": 0.05}),
                "strength_clip": ("FLOAT", {"default": 0.8, "min": -10.0, "max": 10.0, "step": 0.05}),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP", "STRING", "STRING")
    RETURN_NAMES = ("MODEL", "CLIP", "trigger_word", "lora_tag")
    FUNCTION = "load_lora_with_trigger"
    CATEGORY = "loaders/lora"

    def load_lora_with_trigger(self, model, clip, lora_name, strength_model, strength_clip):
        from nodes import LoraLoader
        trigger = find_lora_trigger(lora_name) or ""
        lora_tag = f"<lora:{lora_name}:{strength_model}>"
        if strength_model == 0 and strength_clip == 0:
            return (model, clip, trigger, lora_tag)

        m_out, c_out = LoraLoader().load_lora(model, clip, lora_name, strength_model, strength_clip)
        return (m_out, c_out, trigger, lora_tag)


# --- NÓ CUSTOMIZADO: ESCALA PROPORCIONAL INTELIGENTE PARA SDXL ---
class ImageScaleProportionalSDXL:
    """
    Redimensiona proporcionalmente a imagem mantendo rigorosamente
    o aspect ratio original (sem achatar nem esticar) e garantindo que largura e altura
    sejam múltiplos de 64 (para compatibilidade perfeita com tensores VAE/Latent SDXL).
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "target_longer_side": ("INT", {"default": 1024, "min": 256, "max": 4096, "step": 64}),
                "upscale_method": (["lanczos", "bicubic", "bilinear", "nearest-exact", "area"], {"default": "lanczos"}),
            }
        }

    RETURN_TYPES = ("IMAGE", "INT", "INT")
    RETURN_NAMES = ("IMAGE", "width", "height")
    FUNCTION = "scale_proportional"
    CATEGORY = "image/transform"

    def scale_proportional(self, image, target_longer_side, upscale_method):
        from nodes import ImageScale
        # image shape: [B, H, W, C]
        _, orig_h, orig_w, _ = image.shape
        
        if orig_w >= orig_h:
            scale = target_longer_side / orig_w
            new_w = target_longer_side
            new_h = round((orig_h * scale) / 64) * 64
        else:
            scale = target_longer_side / orig_h
            new_h = target_longer_side
            new_w = round((orig_w * scale) / 64) * 64
            
        new_w = max(64, int(new_w))
        new_h = max(64, int(new_h))
        
        scaled_img, = ImageScale().upscale(image, upscale_method, new_w, new_h, "disabled")
        return (scaled_img, new_w, new_h)


# --- NÓ CUSTOMIZADO: AMOLED TRUE BLACK LEVELER (OLED CRUSH) ---
class AMOLEDBlackLeveler:
    """
    Nó de Pós-Processamento AMOLED / True Black:
    Esmaga (crush) tons escuros e ruído residual do VAE que estão próximos do preto para preto puro RGB(0, 0, 0),
    garantindo contraste infinito e desligamento real de pixels em telas OLED/AMOLED,
    enquanto preserva intactos e vibrantes os traços coloridos e destaques neon.
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "enabled": ("BOOLEAN", {"default": True}),
                "threshold": ("FLOAT", {"default": 0.08, "min": 0.0, "max": 0.40, "step": 0.01}),
                "feather": ("FLOAT", {"default": 0.03, "min": 0.0, "max": 0.15, "step": 0.01}),
                "boost_neon": ("FLOAT", {"default": 1.10, "min": 1.0, "max": 1.50, "step": 0.05}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "level_blacks"
    CATEGORY = "image/postprocessing"

    def level_blacks(self, image, enabled=True, threshold=0.08, feather=0.03, boost_neon=1.10):
        try:
            if not enabled:
                return (image,)
                
            import torch
            # image: [B, H, W, C]
            lum = 0.2126 * image[..., 0] + 0.7152 * image[..., 1] + 0.0722 * image[..., 2]
            lum = lum.unsqueeze(-1) # [B, H, W, 1]

            if feather > 0:
                low = max(0.0, threshold - feather)
                high = threshold + feather
                t = torch.clamp((lum - low) / (high - low + 1e-6), 0.0, 1.0)
                mask = t * t * (3.0 - 2.0 * t) # smoothstep
            else:
                mask = (lum >= threshold).float()

            result = image * mask

            if boost_neon > 1.0:
                neon_factor = 1.0 + (boost_neon - 1.0) * mask
                result = torch.clamp(result * neon_factor, 0.0, 1.0)

            return (result,)
        finally:
            try:
                import gc, torch
                import comfy.model_management as mm
                mm.soft_empty_cache()
                gc.collect()
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except Exception:
                pass


NODE_CLASS_MAPPINGS["PromptTagFilter"] = PromptTagFilter
NODE_DISPLAY_NAME_MAPPINGS["PromptTagFilter"] = "Prompt Tag Filter (Detailer)"

NODE_CLASS_MAPPINGS["PromptReviewer"] = PromptReviewer
NODE_DISPLAY_NAME_MAPPINGS["PromptReviewer"] = "Prompt Reviewer (Sanitizer & Anti-Conflict)"

NODE_CLASS_MAPPINGS["LoraWithTrigger"] = LoraWithTrigger
NODE_DISPLAY_NAME_MAPPINGS["LoraWithTrigger"] = "Load LoRA with Trigger"

NODE_CLASS_MAPPINGS["ImageScaleProportionalSDXL"] = ImageScaleProportionalSDXL
NODE_DISPLAY_NAME_MAPPINGS["ImageScaleProportionalSDXL"] = "Ajuste Proporcional SDXL"

NODE_CLASS_MAPPINGS["AMOLEDBlackLeveler"] = AMOLEDBlackLeveler
NODE_DISPLAY_NAME_MAPPINGS["AMOLEDBlackLeveler"] = "AMOLED True Black Leveler (OLED Crush)"


# --- NÓ CUSTOMIZADO: SELETOR DE RESOLUÇÃO (1:1, 16:9, 9:16) ---
class SDXLResolutionSelector:
    """
    Seletor simplificado de resolução para SDXL / Illustrious:
    - 1:1 (1024 x 1024 - Quadrado)
    - 16:9 (1344 x 768 - Wallpaper / Landscape)
    - 9:16 (832 x 1344 - Celular / Portrait)
    Gera diretamente o latent vazio pronto para o KSampler.
    """
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "resolution": ([
                    "9:16 (832 x 1344 - Celular)",
                    "16:9 (1344 x 768 - Wallpaper)",
                    "1:1 (1024 x 1024 - Quadrado)",
                ], {"default": "9:16 (832 x 1344 - Celular)"}),
                "batch_size": ("INT", {"default": 1, "min": 1, "max": 16, "step": 1}),
            }
        }

    RETURN_TYPES = ("LATENT", "INT", "INT")
    RETURN_NAMES = ("latent", "width", "height")
    FUNCTION = "generate_latent"
    CATEGORY = "latent"

    def generate_latent(self, resolution, batch_size=1):
        import torch
        if "16:9" in resolution:
            w, h = 1344, 768
        elif "1:1" in resolution:
            w, h = 1024, 1024
        else: # 9:16
            w, h = 832, 1344

        latent = torch.zeros([batch_size, 4, h // 8, w // 8])
        return ({"samples": latent}, w, h)


def _load_wc_options(fname, default_prefix=True, extra_options=None):
    import os
    base_dir = os.path.join(os.path.dirname(__file__), "..", "comfyui-impact-pack", "wildcards", "ia")
    p = os.path.abspath(os.path.join(base_dir, fname))
    opts = ["[ALEATORIO / WILDCARD]", "[NENHUM]"] if default_prefix else []
    if extra_options:
        opts.extend(extra_options)
    if os.path.exists(p):
        try:
            lines = [l.strip() for l in open(p, encoding="utf-8") if l.strip() and not l.strip().startswith("#")]
            seen = set(opts)
            for l in lines:
                if l not in seen:
                    opts.append(l)
                    seen.add(l)
        except Exception:
            pass
    return opts


# --- NÓ CUSTOMIZADO: CONSTRUTOR DE PROMPTS COM DROPDOWNS ---
class PromptDropdownBuilder:
    """
    Construtor de Prompts Interativo com Seletores Dropdown:
    Permite escolher manualmente qualquer opção dos wildcards em menus suspensos,
    ou deixar qualquer categoria como '[ALEATORIO / WILDCARD]' para sorteio dinâmico.
    """
    @classmethod
    def INPUT_TYPES(s):
        raca_opts = _load_wc_options("raca.txt")
        cabelo_cor_opts = _load_wc_options("cabelo_cor.txt")
        cabelo_estilo_opts = _load_wc_options("cabelo_estilo.txt")
        olhos_opts = _load_wc_options("olhos.txt")
        corpo_opts = _load_wc_options("corpo.txt")
        roupa_opts = _load_wc_options("roupa_sfw.txt", extra_options=["[COMPLETAMENTE NUA]"]) + [l for l in _load_wc_options("roupa_nsfw.txt", default_prefix=False) if l not in _load_wc_options("roupa_sfw.txt")]
        pose_opts = _load_wc_options("pose.txt")
        atividade_opts = _load_wc_options("atividade_sfw.txt") + [l for l in _load_wc_options("atividade_nsfw.txt", default_prefix=False)[:25] if l not in _load_wc_options("atividade_sfw.txt")]
        expressao_opts = _load_wc_options("expressao_sfw.txt") + [l for l in _load_wc_options("expressao_nsfw.txt", default_prefix=False)[:25] if l not in _load_wc_options("expressao_sfw.txt")]
        camera_opts = _load_wc_options("camera.txt") + [l for l in _load_wc_options("camera_wall.txt", default_prefix=False) if l not in _load_wc_options("camera.txt")]
        interacao_dupla_opts = _load_wc_options("interacao_2girls.txt")
        local_opts = _load_wc_options("local_outdoor.txt", extra_options=["[FUNDO SIMPLES]"]) + [l for l in _load_wc_options("local_indoor.txt", default_prefix=False) if l not in _load_wc_options("local_outdoor.txt")]
        iluminacao_opts = _load_wc_options("iluminacao.txt")
        brilho_opts = ["[DESATIVADO]", "[ALEATORIO / WILDCARD]"] + [l for l in _load_wc_options("brilho_partes.txt", default_prefix=False)]

        return {
            "required": {
                "modo": (["SFW", "NSFW"], {"default": "SFW"}),
                "personagens": (["1girl (Solo)", "2girls (Dupla Interagindo)", "[ALEATORIO / WILDCARD]"], {"default": "1girl (Solo)"}),
                "qualidade": ([
                    "masterpiece, best quality, very aesthetic, absurdres",
                    "masterpiece, best quality, ultra-detailed",
                    "masterpiece, best quality, stunning illustration",
                    "[NENHUM]"
                ], {"default": "masterpiece, best quality, very aesthetic, absurdres"}),
                "raca": (raca_opts, {"default": "[ALEATORIO / WILDCARD]"}),
                "cabelo_cor": (cabelo_cor_opts, {"default": "[ALEATORIO / WILDCARD]"}),
                "cabelo_estilo": (cabelo_estilo_opts, {"default": "[ALEATORIO / WILDCARD]"}),
                "olhos": (olhos_opts, {"default": "[ALEATORIO / WILDCARD]"}),
                "corpo": (corpo_opts, {"default": "[ALEATORIO / WILDCARD]"}),
                "roupa": (roupa_opts, {"default": "[ALEATORIO / WILDCARD]"}),
                "pose": (pose_opts, {"default": "[ALEATORIO / WILDCARD]"}),
                "atividade": (atividade_opts, {"default": "[ALEATORIO / WILDCARD]"}),
                "interacao_dupla": (interacao_dupla_opts, {"default": "[ALEATORIO / WILDCARD]"}),
                "expressao": (expressao_opts, {"default": "[ALEATORIO / WILDCARD]"}),
                "camera": (camera_opts, {"default": "[ALEATORIO / WILDCARD]"}),
                "local": (local_opts, {"default": "[ALEATORIO / WILDCARD]"}),
                "iluminacao": (iluminacao_opts, {"default": "[ALEATORIO / WILDCARD]"}),
                "brilho": (brilho_opts, {"default": "[DESATIVADO]"}),
            },
            "optional": {
                "custom_prompt": ("STRING", {"multiline": True, "default": "", "placeholder": "Tags extras personalizadas..."}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("positive_prompt", "negative_prompt")
    FUNCTION = "build_prompt"
    CATEGORY = "prompt/builder"

    def build_prompt(self, modo, personagens, qualidade, raca, cabelo_cor, cabelo_estilo, olhos, corpo, roupa, pose, atividade, interacao_dupla, expressao, camera, local, iluminacao, brilho, custom_prompt=""):
        import random, os
        base_dir = os.path.join(os.path.dirname(__file__), "..", "comfyui-impact-pack", "wildcards", "ia")

        def pick_val(choice, filename):
            if choice == "[NENHUM]" or choice == "[DESATIVADO]":
                return None
            if choice == "[ALEATORIO / WILDCARD]":
                p = os.path.abspath(os.path.join(base_dir, filename))
                if os.path.exists(p):
                    lines = [l.strip() for l in open(p, encoding="utf-8") if l.strip() and not l.strip().startswith("#")]
                    return random.choice(lines) if lines else None
                return None
            if choice == "[COMPLETAMENTE NUA]":
                return "completely_nude, bare_breasts, bare_pussy, natural_curves"
            if choice == "[FUNDO SIMPLES]":
                return "simple_background, minimalist_background"
            return choice

        tags = []
        if qualidade != "[NENHUM]":
            tags.append(qualidade)

        # Determinacao de Personagens (1girl vs 2girls)
        is_duo = False
        if "2girls" in personagens:
            is_duo = True
        elif personagens == "[ALEATORIO / WILDCARD]":
            if modo == "SFW" and random.random() < 0.30:
                is_duo = True

        if is_duo:
            tags.append("2girls")
            interac = pick_val(interacao_dupla, "interacao_2girls.txt")
            if interac:
                tags.append(interac)
        else:
            tags.append("1girl")
            if modo == "SFW":
                tags.append("solo")

        r_val = pick_val(raca, "raca.txt")
        if r_val: tags.append(r_val)

        cc_val = pick_val(cabelo_cor, "cabelo_cor.txt")
        ce_val = pick_val(cabelo_estilo, "cabelo_estilo.txt")
        if cc_val and ce_val:
            tags.append(f"{cc_val} hair, {ce_val}")
        elif cc_val:
            tags.append(f"{cc_val} hair")
        elif ce_val:
            tags.append(ce_val)

        o_val = pick_val(olhos, "olhos.txt")
        if o_val: tags.append(o_val)

        cp_val = pick_val(corpo, "corpo.txt")
        if cp_val: tags.append(cp_val)

        rp_file = "roupa_nsfw.txt" if modo == "NSFW" else "roupa_sfw.txt"
        rp_val = pick_val(roupa, rp_file)
        if rp_val: tags.append(rp_val)

        if not is_duo:
            ps_val = pick_val(pose, "pose.txt")
            if ps_val: tags.append(ps_val)

            at_file = "atividade_nsfw.txt" if modo == "NSFW" else "atividade_sfw.txt"
            at_val = pick_val(atividade, at_file)
            if at_val: tags.append(at_val)

        ex_file = "expressao_nsfw.txt" if modo == "NSFW" else "expressao_sfw.txt"
        ex_val = pick_val(expressao, ex_file)
        if ex_val: tags.append(ex_val)

        cm_val = pick_val(camera, "camera.txt")
        if cm_val: tags.append(cm_val)

        lc_val = pick_val(local, "local_outdoor.txt")
        if lc_val: tags.append(lc_val)

        il_val = pick_val(iluminacao, "iluminacao.txt")
        if il_val: tags.append(il_val)

        if brilho != "[DESATIVADO]":
            br_val = pick_val(brilho, "brilho_partes.txt")
            if br_val: tags.append(br_val)

        if modo == "NSFW":
            tags.append("nsfw")

        if custom_prompt and custom_prompt.strip():
            tags.append(custom_prompt.strip())

        positive_prompt = ", ".join(tags)

        # Base comum de qualidade negativa com bloqueio de câmeras, velas e peras
        quality_neg = "multiple_views, lowres, watermark, text, error, cropped, worst quality, low quality, jpeg artifacts, ugly, duplicate, mutilated, out of frame, extra fingers, mutated hands, poorly drawn hands, poorly drawn face, mutation, deformed, blurry, bad anatomy, bad proportions, headband, fake_animal_ears, cosplay, 4_ears, camera, tripod, handheld_camera, camera_lens, candles, candle, candlestick, pear, pears, fruit"

        # Detecção de monstros sem pernas humanas (centauro, sereia, lamia, aracne, scylla, etc)
        pos_lower = positive_prompt.lower()
        non_human_lower = any(k in pos_lower for k in [
            "centaur", "mermaid", "lamia", "scylla",
            "snake_lower_body", "fish_tail", "horse_lower_body", "tentacles_lower_body"
        ])
        arachne_neg = ", ((wings, fairy_wings, insect_wings, spider_lower_body, giant_spider_abdomen, monster_spider_body:1.5))" if any(k in pos_lower for k in ["arachne", "spider_girl"]) else ""
        lamia_neg = ", ((two_snake_tails, two_tails, multiple_tails, split_tail, extra_tails, second_tail, snake_legs, two_snakes:1.6))" if any(k in pos_lower for k in ["lamia", "serpent_girl", "snake_lower_body"]) else ""
        monster_legs_neg = arachne_neg + lamia_neg + ", ((human_legs, human_feet, feet, toes, human_knees, two_legs, bipedal, standing_on_human_legs, extra_legs:1.5))" if non_human_lower else ""

        # Bloqueio de auréola/halo indesejado se não for anjo
        is_angel = "angel" in positive_prompt.lower()
        halo_neg = "" if is_angel else ", halo, golden_halo, glowing_halo, head_accessory"

        if modo == "SFW":
            negative_prompt = f"nsfw, explicit, nude, nipples, pussy, penis, man, 1futa, sex{halo_neg}{monster_legs_neg}, {quality_neg}"
        else:
            # Em NSFW: bloqueia explicitamente toalhas aleatórias e calcinhas/roupas esticadas pela metade
            nsfw_cleaners = ", towel, bath_towel, slipping_towel, panties_aside, pulled_aside, bloomers_pulled_aside, half-undressed, clothes_pull, torn_clothes"
            ghost_neg = ", ((solid_opaque_skin, normal_human_skin, mascot, pet, floating_creature, cute_ghost, small_ghost, companion, familiar, separate_ghost, wisp_creature:1.5))" if any(g in pos_lower for g in ["ghost", "poltergeist", "phantom", "spectral"]) else ", ((ghost, spirit, wisp, phantom, slime_creature, mascot, pet, floating_creature, familiar, small_ghost, cute_ghost:1.4))"
            fist_neg = ", ((double_fisting, two_hands_fisting, two_hands_insertion, two_fists:1.6))" if any(f in pos_lower for f in ["fisting", "hand_insertion"]) and not any(df in pos_lower for df in ["double_fisting", "two_hands"]) else (", ((fisting, hand_insertion, double_fisting, two_hands_insertion:1.4))" if not any(f in pos_lower for f in ["fisting", "hand_insertion"]) else "")
            negative_prompt = f"general, censored, mosaic censoring, 1futa{halo_neg}{nsfw_cleaners}{monster_legs_neg}{ghost_neg}{fist_neg}, {quality_neg}"

        return (positive_prompt, negative_prompt)


NODE_CLASS_MAPPINGS["SDXLResolutionSelector"] = SDXLResolutionSelector
NODE_DISPLAY_NAME_MAPPINGS["SDXLResolutionSelector"] = "Seletor de Resolução SDXL"

NODE_CLASS_MAPPINGS["PromptDropdownBuilder"] = PromptDropdownBuilder
NODE_DISPLAY_NAME_MAPPINGS["PromptDropdownBuilder"] = "Construtor de Prompt (Dropdowns)"


# ==============================================================================
# --- SISTEMA DE TESTE E PERSISTÊNCIA DE COMBINAÇÕES DE MODELOS E LORAS ---
# ==============================================================================

APPROVED_COMBOS_FILE = COMFY_ROOT / "user" / "default" / "approved_combos.json"
CURRENT_TEST_FILE = COMFY_ROOT / "user" / "default" / "current_test_combo.json"
TESTER_OUTPUT_DIR = COMFY_ROOT / "output" / "tester"
TESTER_SAVED_DIR = COMFY_ROOT / "output" / "tester_saved"
CREATION_OUTPUT_DIR = COMFY_ROOT / "output" / "creation"
SAVED_IMAGES_FILE = COMFY_ROOT / "user" / "default" / "saved_tester_images.json"

def _load_saved_images_list():
    if not SAVED_IMAGES_FILE.exists():
        return []
    try:
        with open(SAVED_IMAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def _save_saved_images_list(items):
    SAVED_IMAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SAVED_IMAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2, ensure_ascii=False)

TESTER_SAVED_META_FILE = COMFY_ROOT / "user" / "default" / "tester_saved_metadata.json"

def _load_tester_saved_metadata():
    if not TESTER_SAVED_META_FILE.exists():
        return {}
    try:
        with open(TESTER_SAVED_META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_tester_saved_metadata(data):
    try:
        TESTER_SAVED_META_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TESTER_SAVED_META_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[TesterSavedMeta] Erro ao salvar metadados: {e}")

TESTER_ROUNDS_TRACKER_FILE = COMFY_ROOT / "user" / "default" / "tester_rounds_tracker.json"

def _load_rounds_tracker():
    if not TESTER_ROUNDS_TRACKER_FILE.exists():
        return {}
    try:
        with open(TESTER_ROUNDS_TRACKER_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _save_rounds_tracker(data):
    try:
        TESTER_ROUNDS_TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(TESTER_ROUNDS_TRACKER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[RoundsTracker] Erro ao salvar tracker: {e}")

def _advance_tester_rounds_and_cleanup():
    """
    Incrementa a contagem de resorteios das imagens não guardadas no diretório TESTER_OUTPUT_DIR.
    Se uma imagem atingir 6 resorteios de LoRAs sem ser guardada, é movida com segurança para tester_trash
    (impedindo perda acidental de imagens).
    """
    tracker = _load_rounds_tracker()
    valid_exts = {".png", ".webp", ".jpg", ".jpeg"}
    
    if not TESTER_OUTPUT_DIR.exists():
        return
        
    current_files = {f.name: f for f in TESTER_OUTPUT_DIR.glob("*") if f.is_file() and f.suffix.lower() in valid_exts}
    new_tracker = {}
    moved_count = 0

    trash_dir = TESTER_OUTPUT_DIR.parent / "tester_trash"

    for fname, fpath in current_files.items():
        age = tracker.get(fname, 0) + 1
        if age >= 3:
            try:
                trash_dir.mkdir(parents=True, exist_ok=True)
                dest = trash_dir / fname
                if dest.exists():
                    dest.unlink()
                fpath.rename(dest)
                moved_count += 1
                print(f"[RoundsTracker] Imagem '{fname}' movida para tester_trash após 6 resorteios sem ser guardada.")
            except Exception as err:
                print(f"[RoundsTracker] Erro ao mover {fname}: {err}")
        else:
            new_tracker[fname] = age

    _save_rounds_tracker(new_tracker)
    if moved_count > 0:
        print(f"[RoundsTracker] Limpeza de ciclo: {moved_count} imagem(ns) arquivada(s) em tester_trash.")


def _load_approved_combos_data():
    if not APPROVED_COMBOS_FILE.exists():
        return {"approved_combos": [], "rejected_combos": []}
    try:
        with open(APPROVED_COMBOS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"approved_combos": [], "rejected_combos": []}

def _save_approved_combos_data(data):
    APPROVED_COMBOS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(APPROVED_COMBOS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _load_current_test_data():
    if not CURRENT_TEST_FILE.exists():
        return None
    try:
        with open(CURRENT_TEST_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def _save_current_test_data(data):
    CURRENT_TEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(CURRENT_TEST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _get_approved_combo_names():
    data = _load_approved_combos_data()
    return [c.get("name", c.get("id")) for c in data.get("approved_combos", [])]

# Modelos oficiais padrão (fallback)
OFFICIAL_CHECKPOINTS = [
    r"illustrious\arthemyComics_v80.safetensors",
    r"illustrious\illustrijBTTR_v10.safetensors",
    r"illustrious\jedpointil_v7VAE.safetensors",
    r"illustrious\waiIllustriousSDXL_v170.safetensors",
]

def get_available_checkpoints(refresh=True):
    """Retorna dinamicamente todos os checkpoints disponíveis na biblioteca ComfyUI."""
    import folder_paths
    if refresh:
        try:
            folder_paths.filename_list_cache.pop("checkpoints", None)
        except Exception:
            pass
    try:
        ckpts = folder_paths.get_filename_list("checkpoints")
        if ckpts:
            return sorted(list(ckpts))
    except Exception:
        pass
    return OFFICIAL_CHECKPOINTS

def get_available_loras(refresh=True):
    """Retorna dinamicamente todos os LoRAs encontrados em todas as pastas de modelos."""
    import folder_paths
    if refresh:
        try:
            folder_paths.filename_list_cache.pop("loras", None)
        except Exception:
            pass
    try:
        all_l = folder_paths.get_filename_list("loras")
        valid = [l for l in all_l if not any(skip in l.lower() for skip in ["put_loras_here", "model.safetensors"])]
        return sorted(valid if valid else list(all_l))
    except Exception:
        return []

def get_sampleable_loras(refresh=False):
    """Retorna LoRAs adequados para sorteio aleatório, filtrando sliders utilitários, LoRAs dedicados de monster_girls e LoRAs contextuais de NSFW."""
    all_l = get_available_loras(refresh=refresh)
    sampleable = [l for l in all_l if not any(skip in l.lower() for skip in [
        "age_slider", "stabilizer", "monster_girls", "alamia", "amermaid", "arobot", "gorgon", "ghost",
        "draenei", "fsev", "fairy", "orc", "flesh_unit", "gazelle", "pand4w4", "serpent", "navi", "saber",
        "nsfw", "freaky_dicks", "masturbation with dildo", "spreadanus", "buttplug", "penetrator",
        "heldbygiant", "5-oral", "7-il_lesbian", "strap-on", "strapon", "lestraabed",
        "8-masterfist", "masterfist"
    ])]
    return sampleable if sampleable else all_l

LORA_CATEGORIES = {
    "contrast": [
        "d4rkl1nes", "flatline", "ptd", "glowing_in_dark", "shadow-circuit",
        "between pages", "g0thic", "flat_inking", "detr1mental"
    ],
    "style_comic": [
        "comics_gff", "comiks", "jmoxcomix", "retrocom", "sunstone", "disgea", "mad_tale", "thronebreaker", "tbcv1"
    ],
    "style_cartoon": [
        "disney", "carto4on", "fantasia", "cartoon_saloon", "heylittlekhana", "csstyle", "hlk_style"
    ],
    "style_pixel": [
        "n1coduran", "pixel_art", "dungeon_squad"
    ],
    "style_3d": [
        "3d_stylized", "ani2rel", "anime_in_real"
    ],
    "style_painterly": [
        "oil", "latrans", "paulinaapc", "between_pencils", "stbedap", "pencils"
    ],
    "enhancer": [
        "addmicrodetails", "hyperrealistic", "smooth_booster", "748cm", "realism_enhancer", "stabilizer", "raw-color"
    ],
    "lighting": [
        "s1 dramatic lighting", "s1_dram", "lighting"
    ],
    "dynamics": [
        "posingdynamics", "the_look", "creative-angle", "rule_of_thirds"
    ],
    "artistic_distinct": [
        "secretofkells", "kells", "sketch", "retro_scifi", "fantasyforge", "0nz9km",
        "rabbithole", "afkarena", "afkjourney", "nv_kawaiitech",
        "sarafaber", "wadu", "zynthra", "haiz_ai", "incoth", "chxrrygxg",
        "ickpot", "jab_illustrious", "jj_v2", "moriimee", "rapscallion", "d5jr09",
        "bluefley", "cutesexyrobutts", "explore_the_world", "exploreworld", "fantasy_art", "gem",
        "jonyeld", "muse_style", "vempire"
    ]
}

def categorize_lora(lora_name):
    """Retorna a categoria funcional e estética de um LoRA para amostragem balanceada e harmoniosa."""
    lname = str(lora_name).lower()
    for cat, keywords in LORA_CATEGORIES.items():
        if any(kw in lname for kw in keywords):
            return cat
    return "artistic_distinct"

def sample_harmonized_loras(available_loras, qtd=3):
    """
    Sorteia LoRAs com categorização estética e hierarquia de papéis:
    - Previne concorrência destrutiva (máx 1 alto contraste, 1 cartoon, 1 comic, 1 3d, 1 pintura a óleo, 1 pixel art).
    - Distribui papéis assimétricos com manifestação clara do LoRA principal (0.75 a 0.85).
    - Varia os pesos organicamente a cada sorteio, acabando com valores fixos em 0.50.
    """
    import random
    if not available_loras:
        return []

    qtd = max(1, min(len(available_loras), qtd))
    chosen_loras = []
    used_categories = set()
    single_allowed_cats = {"contrast", "style_comic", "style_cartoon", "style_3d", "style_painterly", "style_pixel"}

    for slot_idx in range(qtd):
        # Filtra candidatos respeitando exclusão de categorias concorrentes
        candidates = []
        for lora in available_loras:
            if lora in [c["lora"] for c in chosen_loras]:
                continue
            cat = categorize_lora(lora)
            if cat in used_categories and cat in single_allowed_cats:
                continue
            candidates.append(lora)

        if not candidates:
            # Fallback seguro caso as exclusões esgotem o subconjunto
            candidates = [l for l in available_loras if l not in [c["lora"] for c in chosen_loras]]
            if not candidates:
                break

        # Sorteio ponderado por slot e calibração de pesos
        if slot_idx == 0:
            # Slot 1: Protagonista / Estilo Principal marcante
            preferred = [l for l in candidates if categorize_lora(l) not in ["enhancer", "contrast", "dynamics"]]
            chosen = random.choice(preferred if preferred else candidates)
            cat = categorize_lora(chosen)
            if cat == "contrast":
                weight = random.choice([0.60, 0.65, 0.70])
            else:
                weight = random.choice([0.75, 0.80, 0.85])
        elif slot_idx == 1:
            # Slot 2: Co-protagonista / Modificador de Tom / Iluminação
            preferred = [l for l in candidates if categorize_lora(l) not in ["enhancer"]]
            chosen = random.choice(preferred if preferred else candidates)
            cat = categorize_lora(chosen)
            if cat == "contrast":
                weight = random.choice([0.45, 0.50, 0.55])
            elif cat in ["lighting", "dynamics"]:
                weight = random.choice([0.55, 0.60, 0.65])
            else:
                weight = random.choice([0.55, 0.60, 0.65, 0.70])
        elif slot_idx == 2:
            # Slot 3: Acento / Detalhe / Enhancer / Posing / Iluminação
            preferred = [l for l in candidates if categorize_lora(l) in ["enhancer", "lighting", "dynamics"]]
            chosen = random.choice(preferred if preferred else candidates)
            cat = categorize_lora(chosen)
            if cat == "contrast":
                weight = random.choice([0.40, 0.45, 0.50])
            elif cat == "enhancer":
                weight = random.choice([0.40, 0.45, 0.50, 0.55])
            else:
                weight = random.choice([0.45, 0.50, 0.55])
        else:
            # Slot 4+: Pesos complementares moderados
            chosen = random.choice(candidates)
            cat = categorize_lora(chosen)
            weight = random.choice([0.35, 0.40, 0.45])

        used_categories.add(cat)
        chosen_loras.append({
            "lora": chosen,
            "category": cat,
            "strength_model": round(weight, 2),
            "strength_clip": round(weight, 2)
        })

    return chosen_loras


class ApprovedCombosLoader:
    """
    Carregador Central de Combinações Aprovadas (Presets de Modelos + LoRAs):
    Permite selecionar qualquer combinação aprovada pelo testador ou sortear aleatoriamente entre as aprovadas.
    Disponibiliza o MODEL e CLIP com os LoRAs aplicados e os triggers compilados para os outros workflows.
    """
    @classmethod
    def INPUT_TYPES(s):
        combos = _get_approved_combo_names()
        opts = ["[DESATIVADO / MANUAL]", "[SORTEIO ALEATORIO APROVADO]"] + combos
        return {
            "required": {
                "combo": (opts, {"default": opts[0] if opts else "[DESATIVADO / MANUAL]"}),
            },
            "optional": {
                "opt_model": ("MODEL",),
                "opt_clip": ("CLIP",),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("MODEL", "CLIP", "checkpoint_name", "lora_triggers", "combo_name")
    FUNCTION = "load_approved_combo"
    CATEGORY = "loaders/presets"

    def load_approved_combo(self, combo, opt_model=None, opt_clip=None):
        import random
        from nodes import CheckpointLoaderSimple, LoraLoader

        if combo == "[DESATIVADO / MANUAL]":
            return (opt_model, opt_clip, "", "", "Manual / Sem Preset")

        data = _load_approved_combos_data()
        approved = data.get("approved_combos", [])
        if not approved:
            return (opt_model, opt_clip, "", "", "Nenhum combo aprovado encontrado")

        chosen_combo = None
        if combo == "[SORTEIO ALEATORIO APROVADO]":
            chosen_combo = random.choice(approved)
        else:
            for c in approved:
                if c.get("name") == combo or c.get("id") == combo:
                    chosen_combo = c
                    break
            if not chosen_combo:
                chosen_combo = approved[0]

        avail_ckpts = get_available_checkpoints(refresh=False)
        default_ckpt = avail_ckpts[0] if avail_ckpts else OFFICIAL_CHECKPOINTS[0]
        ckpt_name = chosen_combo.get("checkpoint", default_ckpt)
        loras = chosen_combo.get("loras", [])
        combo_name = chosen_combo.get("name", "Combo Aprovado")

        # Carregar Checkpoint
        model, clip, vae = CheckpointLoaderSimple().load_checkpoint(ckpt_name)

        # Aplicar LoRAs em cadeia
        applied_triggers = []
        lora_loader = LoraLoader()
        for item in loras:
            lora_path = item.get("lora")
            s_model = float(item.get("strength_model", 0.8))
            s_clip = float(item.get("strength_clip", s_model))
            try:
                model, clip = lora_loader.load_lora(model, clip, lora_path, s_model, s_clip)
                trig = find_lora_trigger(lora_path)
                if trig and trig not in applied_triggers:
                    applied_triggers.append(trig)
            except Exception as e:
                print(f"[ApprovedCombosLoader] Aviso ao carregar LoRA {lora_path}: {e}")

        triggers_str = ", ".join(applied_triggers)
        return (model, clip, ckpt_name, triggers_str, combo_name)


class ComboTesterRunner:
    """
    Nó Executor do Testador de Combinações:
    Carrega o combo atual em teste ou gera uma nova combinação sorteada para avaliação.
    Carrega o checkpoint (Jedpoint ou Wai), aplica os LoRAs e gera as saídas para a geração de 5-10 imagens.
    """
    @classmethod
    def INPUT_TYPES(s):
        ckpts = get_available_checkpoints(refresh=False)
        return {
            "required": {
                "modo_execucao": (["USAR COMBO ATUAL DO TESTER", "GERAR NOVO TESTE ALEATORIO", "[DESATIVADO]"], {"default": "USAR COMBO ATUAL DO TESTER"}),
                "forcar_modelo": (["Alternar Automaticamente"] + (ckpts if ckpts else OFFICIAL_CHECKPOINTS), {"default": "Alternar Automaticamente"}),
                "qtd_loras": (["2 a 3 LoRAs", "1 a 4 LoRAs", "Apenas 1 LoRA", "Apenas 2 LoRAs"], {"default": "2 a 3 LoRAs"}),
            },
            "optional": {
                "opt_model": ("MODEL",),
                "opt_clip": ("CLIP",),
            }
        }

    RETURN_TYPES = ("MODEL", "CLIP", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("MODEL", "CLIP", "checkpoint_name", "lora_triggers", "test_info")
    FUNCTION = "run_test_combo"
    CATEGORY = "testing/combos"

    def run_test_combo(self, modo_execucao, forcar_modelo="Alternar Automaticamente", qtd_loras="2 a 3 LoRAs", opt_model=None, opt_clip=None):
        import random, datetime
        from nodes import CheckpointLoaderSimple, LoraLoader

        if modo_execucao == "[DESATIVADO]":
            return (opt_model, opt_clip, "", "", "Tester Desativado")

        current_test = _load_current_test_data()

        # Determinar se gera novo teste
        if modo_execucao == "GERAR NOVO TESTE ALEATORIO" or not current_test:
            # 1. Definir Checkpoint
            available_ckpts = get_available_checkpoints(refresh=True)
            if forcar_modelo in available_ckpts:
                target_ckpt = forcar_modelo
            else:
                last_ckpt = current_test.get("checkpoint") if current_test else ""
                if available_ckpts:
                    try:
                        idx = available_ckpts.index(last_ckpt)
                        target_ckpt = available_ckpts[(idx + 1) % len(available_ckpts)]
                    except (ValueError, IndexError):
                        target_ckpt = available_ckpts[0]
                else:
                    target_ckpt = OFFICIAL_CHECKPOINTS[0]

            # 2. Sortear LoRAs da biblioteca
            illu_loras = get_sampleable_loras(refresh=True)

            if "Apenas 1" in qtd_loras:
                num_loras = 1
            elif "Apenas 2" in qtd_loras:
                num_loras = 2
            elif "1 a 4" in qtd_loras:
                num_loras = random.randint(1, 4)
            else: # "2 a 3 LoRAs"
                num_loras = random.randint(2, 3)

            sampled_loras = random.sample(illu_loras, min(num_loras, len(illu_loras)))
            weights_pool = [0.5, 0.6, 0.7, 0.8, 1.0]

            loras_config = []
            for sl in sampled_loras:
                w = random.choice(weights_pool)
                loras_config.append({
                    "lora": sl,
                    "strength_model": w,
                    "strength_clip": w
                })

            current_test = {
                "test_id": f"test_{int(datetime.datetime.now().timestamp())}",
                "checkpoint": target_ckpt,
                "loras": loras_config,
                "status": "testing",
                "created_at": datetime.datetime.now().isoformat()
            }
            _save_current_test_data(current_test)

        ckpt_name = current_test.get("checkpoint", OFFICIAL_CHECKPOINTS[0])
        loras = current_test.get("loras", [])

        # Carregar Checkpoint
        model, clip, vae = CheckpointLoaderSimple().load_checkpoint(ckpt_name)

        # Aplicar LoRAs
        lora_loader = LoraLoader()
        applied_triggers = []
        info_lines = [f"Modelo: {ckpt_name}"]
        for item in loras:
            l_path = item.get("lora")
            sm = float(item.get("strength_model", 0.8))
            sc = float(item.get("strength_clip", sm))
            try:
                model, clip = lora_loader.load_lora(model, clip, l_path, sm, sc)
                trig = find_lora_trigger(l_path)
                if trig and trig not in applied_triggers:
                    applied_triggers.append(trig)
                info_lines.append(f"- LoRA: {l_path} (peso {sm})")
            except Exception as e:
                print(f"[ComboTesterRunner] Erro ao carregar {l_path}: {e}")

        triggers_str = ", ".join(applied_triggers)
        test_info = "\n".join(info_lines)
        return (model, clip, ckpt_name, triggers_str, test_info)


# --- ROTAS HTTP: INTERFACE WEB E API DO TESTADOR DE COMBINAÇÕES ---

@server.PromptServer.instance.routes.get("/tester_images/{filename}")
async def get_tester_image(request):
    try:
        filename = request.match_info["filename"]
        target = TESTER_OUTPUT_DIR / filename
        if not target.exists() or not target.is_file():
            return web.Response(status=404, text="Imagem não encontrada")
        # Se o arquivo foi criado a menos de 2 segundos e tem menos de 30KB, esperar concluir gravação
        st = target.stat()
        if st.st_size < 30000 and (time.time() - st.st_mtime) < 2.0:
            await asyncio.sleep(0.4)
        resp = web.FileResponse(target)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp
    except Exception as e:
        return web.Response(status=500, text=str(e))

@server.PromptServer.instance.routes.get("/creation_images/{filename}")
async def get_creation_image(request):
    try:
        filename = request.match_info["filename"]
        target = CREATION_OUTPUT_DIR / filename
        if not target.exists() or not target.is_file():
            return web.Response(status=404, text="Imagem de criação não encontrada")
        st = target.stat()
        if st.st_size < 30000 and (time.time() - st.st_mtime) < 2.0:
            await asyncio.sleep(0.4)
        resp = web.FileResponse(target)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp
    except Exception as e:
        return web.Response(status=500, text=str(e))

def _friendly_lora_name(lora_str: str) -> str:
    """Retorna um nome amigável e legível para um LoRA, eliminando hashes criptográficos e extraindo o nome real."""
    if not lora_str:
        return ""
    import re
    raw = lora_str.replace('\\', '/').split('/')[-1].replace('.safetensors', '').strip()
    
    # 1. Se tem parênteses com nome amigável: ex: 0NZ9KMEEMSGGXKV1KM7G1SVNE0(FANTASYFORGE)
    if 'between_pencils' in raw.lower() or 'stbedap' in raw.lower():
        return "Between Pencils & Semi-Realism"
    if '7-il_lesbian' in raw.lower():
        return "Lesbian Anal Strap-On"
    if '8-masterfist' in raw.lower() or 'masterfist' in raw.lower():
        return "Masterfist (Fisting)"

    m = re.search(r'^(.*?)\(([^)]+)\)$', raw)
    if m:
        prefix, inside = m.group(1).strip(), m.group(2).strip()
        # Se o prefixo for um hash longo de Civitai (com mais de 12 caracteres ou com códigos conhecidos)
        if len(prefix) > 12 and (not '_' in prefix or any(k in prefix.lower() for k in ['0nz9', 'd5jr', 'ck-'])):
            return inside.replace('_', ' ').title()
        # Se o inside for mais curto ou representativo
        return inside.replace('_', ' ').title() if len(inside) <= len(prefix) else f"{prefix} ({inside})"

    # 2. Se o nome estiver em LORA_TRIGGER_REGISTRY
    clean_k = raw.lower()
    if clean_k in LORA_TRIGGER_REGISTRY:
        trig = LORA_TRIGGER_REGISTRY[clean_k].split(',')[0].strip()
        if len(raw) > 14 and not '_' in raw:
            return trig.replace('_', ' ').title()

    # 3. Formatação padrão: troca underlines por espaços e remove sufixos técnicos
    clean = re.sub(r'[-_]0000\d+', '', raw)
    clean = clean.replace('_', ' ').strip()
    return clean

def _match_approved_combo_name(ckpt_name: str, loras_list: list) -> str:
    """Verifica se o conjunto de LoRAs e checkpoint corresponde a um combo aprovado e retorna seu nome oficial."""
    try:
        approved_data = _load_approved_combos_data()
        approved_list = approved_data.get("approved_combos", [])
        if not approved_list or not loras_list:
            return ""

        RACIAL_OR_UTILITY_LORA_STEMS = {
            "alamiaxl_concept-10", "amermaidfxm_concept-10", "arobotgirls_concept-12",
            "concept_alamiaxl", "concept_amermaidfxm", "concept_arobotgirls",
            "gorgonlora-il-000014", "ghost-sfwnsfw-il.v1.0-000013", "ghost_sex",
            "draenei-il-000014", "fsev1.0-000011",
            "orc-e33_s1155", "flesh_unit_5.1", "gazelle_race-e66_s1122",
            "pand4w4_w4kfu_il", "serpent-e40_s1360", "navi_race_avatar_jc_illustrious_leaf1",
            "saber-toothed",
            "1-freaky_dicksv3", "freaky_dicks", "2-masturbation with dildo (illustrious) v1",
            "3-spreadanusill", "4-buttplugs", "5-oral", "6-heldbygiant",
            "7-il_lesbian_anal_strap-on", "il_lesbian_anal_strap-on",
            "8-masterfist_il", "masterfist_il", "masterfist"
        }

        img_lora_stems = {pathlib.Path(l["lora"].lower()).stem.split('(')[0].strip() for l in loras_list}
        filtered_img_stems = {s for s in img_lora_stems if s not in RACIAL_OR_UTILITY_LORA_STEMS}

        for combo in approved_list:
            c_loras = combo.get("loras", [])
            c_stems = {pathlib.Path(l["lora"].lower()).stem.split('(')[0].strip() for l in c_loras}
            if not c_stems:
                continue

            # 1. Igualdade exata de conjuntos de LoRAs (completo ou sem loras raciais/utilitários injetados)
            if img_lora_stems == c_stems or (filtered_img_stems and filtered_img_stems == c_stems):
                return combo.get("name") or combo.get("id")

            # 2. Se todos os LoRAs do combo aprovado estão contidos na imagem (subset)
            if c_stems.issubset(img_lora_stems) and len(c_stems) >= 2:
                return combo.get("name") or combo.get("id")

            # 3. Alta similaridade (se 75% dos LoRAs coincidirem e tiver >= 2 LoRAs)
            intersection = img_lora_stems.intersection(c_stems)
            if len(intersection) >= max(len(img_lora_stems), len(c_stems)) * 0.75 and len(intersection) >= 2:
                return combo.get("name") or combo.get("id")
    except Exception as e:
        print(f"[ComboMatcher] Erro ao buscar nome de combo aprovado: {e}")
    return ""

def _resolve_prompt_from_graph(p_data: dict) -> str:
    """Navega pelo grafo ComfyUI para extrair o prompt positivo gerado e populado."""
    def _trace(nid, visited=None):
        if visited is None:
            visited = set()
        if nid in visited:
            return ""
        visited.add(nid)
        node = p_data.get(str(nid), {})
        c_type = node.get("class_type", "")
        inputs = node.get("inputs", {})

        # 1. Se for ImpactWildcardProcessor ou tiver populated_text já resolvido
        pop = inputs.get("populated_text")
        if isinstance(pop, str) and pop.strip():
            return pop.strip()

        # 2. String ou texto primitivo
        val = inputs.get("value") or inputs.get("text") or inputs.get("string")
        if isinstance(val, str) and val.strip() and not any(k in str(nid) for k in ["negative", "37"]):
            return val.strip()

        # 3. StringConcatenate
        if "concatenate" in c_type.lower():
            parts = []
            for key in ["string_a", "string_b", "string_c", "string_d"]:
                if key in inputs:
                    ref = inputs[key]
                    if isinstance(ref, list) and len(ref) == 2:
                        res = _trace(ref[0], visited.copy())
                        if res:
                            parts.append(res)
                    elif isinstance(ref, str) and ref.strip():
                        parts.append(ref.strip())
            delim = inputs.get("delimiter", ", ")
            return delim.join(parts)

        # 4. easy ifElse
        if "ifelse" in c_type.lower():
            bool_ref = inputs.get("boolean")
            bool_val = None
            if isinstance(bool_ref, list) and len(bool_ref) == 2:
                bool_node = p_data.get(str(bool_ref[0]), {})
                bool_val = bool_node.get("inputs", {}).get("value")
            target_branch = "on_true" if bool_val else "on_false"
            if target_branch in inputs:
                ref = inputs[target_branch]
                if isinstance(ref, list) and len(ref) == 2:
                    return _trace(ref[0], visited.copy())

        # 5. PromptReviewer
        if "promptreviewer" in c_type.lower():
            p_ref = inputs.get("prompt")
            if isinstance(p_ref, list) and len(p_ref) == 2:
                base_txt = _trace(p_ref[0], visited.copy())
                opt_trigs = inputs.get("opt_lora_triggers", "")
                try:
                    reviewer = PromptReviewer()
                    reviewed, _ = reviewer.review_prompt(base_txt, opt_lora_triggers=opt_trigs)
                    if reviewed:
                        return reviewed
                except Exception:
                    pass
                if opt_trigs and opt_trigs not in base_txt:
                    base_txt = f"{base_txt}, {opt_trigs}"
                return base_txt
            elif isinstance(p_ref, str):
                try:
                    reviewer = PromptReviewer()
                    reviewed, _ = reviewer.review_prompt(p_ref, opt_lora_triggers=inputs.get("opt_lora_triggers", ""))
                    if reviewed:
                        return reviewed
                except Exception:
                    pass
                return p_ref

        # 6. ImpactWildcardEncode
        if "impactwildcardencode" in c_type.lower():
            pop_ref = inputs.get("populated_text")
            if isinstance(pop_ref, list) and len(pop_ref) == 2:
                return _trace(pop_ref[0], visited.copy())
            elif isinstance(pop_ref, str) and pop_ref.strip():
                return pop_ref.strip()

        return ""

    # Inicia a busca a partir dos nós principais do pipeline
    for root_id in ["41", "89", "99"]:
        if root_id in p_data:
            txt = _trace(root_id)
            if txt and len(txt) > 20:
                return txt

    # Fallback: maior texto populado entre os processadores de wildcard
    candidates = []
    for nid, nval in p_data.items():
        pop = nval.get("inputs", {}).get("populated_text")
        if isinstance(pop, str) and pop.strip() and len(pop) > 30:
            candidates.append(pop.strip())
    if candidates:
        candidates.sort(key=len, reverse=True)
        return candidates[0]

    return ""

_TESTER_IMAGE_META_CACHE = {}

def _extract_tester_image_meta(img_path):
    """Extrai o prompt positivo resolvido, seed, loras e checkpoint do arquivo PNG gerado pelo ComfyUI (com cache por mtime/size)."""
    img_path = pathlib.Path(img_path)
    cache_key = str(img_path)
    try:
        st = img_path.stat()
        mtime, size = st.st_mtime, st.st_size
    except Exception:
        mtime, size = 0, 0

    if cache_key in _TESTER_IMAGE_META_CACHE:
        c_mtime, c_size, cached_val = _TESTER_IMAGE_META_CACHE[cache_key]
        if c_mtime == mtime and c_size == size:
            return cached_val

    prompt_str = ""
    seed_val = ""
    loras = []
    checkpoint = ""
    combo_name = ""
    try:
        from PIL import Image
        with Image.open(img_path) as im:
            if "prompt" in im.info:
                p_data = json.loads(im.info["prompt"])
                # 1. Obter seed do nó de amostragem (KSampler)
                for nid, nval in p_data.items():
                    c_type = nval.get("class_type", "")
                    inputs = nval.get("inputs", {})
                    if "sampler" in c_type.lower() and "seed" in inputs:
                        seed_val = str(inputs.get("seed", ""))
                        break

                # 2. Obter prompt populado final resolvido pelo grafo
                prompt_str = _resolve_prompt_from_graph(p_data)

                # 3. Extrair Checkpoint
                for nid, nval in p_data.items():
                    c_type = nval.get("class_type", "")
                    inputs = nval.get("inputs", {})
                    if "checkpoint" in c_type.lower() and "ckpt_name" in inputs:
                        checkpoint = pathlib.Path(str(inputs["ckpt_name"])).stem
                        break

                # 4. Extrair LoRAs ativos com nomes amigáveis
                seen_loras = set()
                for nid, nval in p_data.items():
                    c_type = nval.get("class_type", "")
                    inputs = nval.get("inputs", {})
                    if "power lora loader" in c_type.lower() or "powerloraloader" in c_type.lower():
                        for k, v in inputs.items():
                            if k.lower().startswith("lora_") and isinstance(v, dict) and v.get("on"):
                                l_val = v.get("lora")
                                if l_val:
                                    clean_stem = pathlib.Path(str(l_val)).stem
                                    if clean_stem not in seen_loras:
                                        seen_loras.add(clean_stem)
                                        f_name = _friendly_lora_name(clean_stem)
                                        loras.append({
                                            "lora": clean_stem,
                                            "friendly_name": f_name,
                                            "strength_model": round(float(v.get("strength", 0.8)), 2)
                                        })
                    elif "lora" in c_type.lower():
                        l_name = inputs.get("lora_name") or inputs.get("lora") or inputs.get("name")
                        if l_name and isinstance(l_name, str):
                            clean_stem = pathlib.Path(str(l_name)).stem
                            if clean_stem not in seen_loras:
                                seen_loras.add(clean_stem)
                                f_name = _friendly_lora_name(clean_stem)
                                loras.append({
                                    "lora": clean_stem,
                                    "friendly_name": f_name,
                                    "strength_model": round(float(inputs.get("strength_model", inputs.get("strength", 0.8))), 2)
                                })

                # 4.1 Extrair LoRAs inline injetados no prompt (<lora:nome:peso>)
                if prompt_str:
                    for m_lora, m_strength in re.findall(r'<lora:([^:>]+)(?::([^>]+))?>', prompt_str):
                        clean_stem = pathlib.Path(m_lora).stem
                        if clean_stem not in seen_loras:
                            seen_loras.add(clean_stem)
                            f_name = _friendly_lora_name(clean_stem)
                            try:
                                st_val = round(float(m_strength), 2) if m_strength else 0.8
                            except ValueError:
                                st_val = 0.8
                            loras.append({
                                "lora": clean_stem,
                                "friendly_name": f_name,
                                "strength_model": st_val
                            })
                # (A) Primeiro verifica se bate com algum combo aprovado nomeado pelo usuário
                approved_combo_name = _match_approved_combo_name(checkpoint, loras)
                if approved_combo_name:
                    combo_name = approved_combo_name
                elif loras:
                    # (B) Resumo legível com nomes amigáveis
                    loras_part = " + ".join([f"{l.get('friendly_name', l['lora'])} ({l['strength_model']})" for l in loras[:3]])
                    if len(loras) > 3:
                        loras_part += f" +{len(loras)-3}"
                    combo_name = f"{checkpoint} | {loras_part}" if checkpoint else loras_part
                elif checkpoint:
                    combo_name = checkpoint
    except Exception as e:
        if cache_key in _TESTER_IMAGE_META_CACHE:
            return _TESTER_IMAGE_META_CACHE[cache_key][2]
        print(f"[ComboTester] Erro ao ler metadados de {img_path.name}: {e}")

    result = (prompt_str, seed_val, loras, checkpoint, combo_name)
    if size > 25000 and (prompt_str or checkpoint or loras):
        _TESTER_IMAGE_META_CACHE[cache_key] = (mtime, size, result)
    return result

@server.PromptServer.instance.routes.get("/tester_saved_images/{filename}")
async def get_tester_saved_image(request):
    try:
        filename = request.match_info["filename"]
        target = TESTER_SAVED_DIR / filename
        if not target.exists() or not target.is_file():
            return web.Response(status=404, text="Imagem salva não encontrada")
        resp = web.FileResponse(target)
        resp.headers["Cache-Control"] = "no-cache"
        return resp
    except Exception as e:
        return web.Response(status=500, text=str(e))

@server.PromptServer.instance.routes.get("/api/combo_tester/status")
async def api_combo_tester_status(request):
    try:
        current_test = _load_current_test_data()
        approved_data = _load_approved_combos_data()
        
        # 1. Coletar imagens salvas / guardadas (da pasta tester_saved) com persistência de metadados
        saved_gallery = []
        real_saved_filenames = []
        saved_metadata = _load_tester_saved_metadata()
        meta_updated = False

        if TESTER_SAVED_DIR.exists():
            valid_exts = {".png", ".webp", ".jpg", ".jpeg"}
            s_imgs = sorted([f for f in TESTER_SAVED_DIR.glob("*") if f.is_file() and f.suffix.lower() in valid_exts],
                            key=lambda f: f.stat().st_mtime, reverse=True)
            for img in s_imgs:
                real_saved_filenames.append(img.name)
                item_meta = saved_metadata.get(img.name, {})
                l_list = item_meta.get("loras", [])
                ckpt = item_meta.get("checkpoint", "")
                c_name = item_meta.get("combo_name", "")
                p_text = item_meta.get("prompt", "")
                s_val = item_meta.get("seed", "")

                # Se faltam metadados ou prompt, extrai do PNG e persiste
                if not l_list or not ckpt or not c_name or not p_text:
                    p_ext, s_ext, l_ext, ckpt_ext, c_ext = _extract_tester_image_meta(img)
                    p_text = p_text or p_ext
                    s_val = s_val or s_ext
                    l_list = l_list or l_ext
                    ckpt = ckpt or ckpt_ext
                    c_name = c_name or c_ext
                    saved_metadata[img.name] = {
                        "checkpoint": ckpt,
                        "loras": l_list,
                        "combo_name": c_name,
                        "prompt": p_text,
                        "seed": s_val,
                        "timestamp": img.stat().st_mtime
                    }
                    meta_updated = True

                # Enriquece LoRAs com friendly_name se faltar
                for l_item in l_list:
                    if isinstance(l_item, dict) and not l_item.get("friendly_name"):
                        l_item["friendly_name"] = _friendly_lora_name(l_item.get("lora", ""))
                        meta_updated = True

                # Atualiza com nome de combo aprovado se houver correspondência com preset aprovado
                approved_match = _match_approved_combo_name(ckpt, l_list)
                if approved_match and approved_match != c_name:
                    c_name = approved_match
                    if img.name in saved_metadata:
                        saved_metadata[img.name]["combo_name"] = c_name
                    meta_updated = True

                saved_gallery.append({
                    "filename": img.name,
                    "url": f"/tester_saved_images/{img.name}",
                    "size_bytes": img.stat().st_size,
                    "timestamp": img.stat().st_mtime,
                    "prompt": p_text,
                    "seed": s_val,
                    "loras": l_list,
                    "checkpoint": ckpt,
                    "combo_name": c_name,
                    "is_saved": True
                })
        
        if meta_updated:
            _save_tester_saved_metadata(saved_metadata)

        # Atualiza o arquivo saved_tester_images.json para refletir com exatidão a pasta
        _save_saved_images_list(real_saved_filenames)
        saved_imgs_set = set(real_saved_filenames)

        # 2. Coletar imagens ativas do testador (com ciclo de sobrevivência de rodadas)
        tester_images = []
        rounds_tracker = _load_rounds_tracker()
        if TESTER_OUTPUT_DIR.exists():
            valid_exts = {".png", ".webp", ".jpg", ".jpeg"}
            imgs = sorted([f for f in TESTER_OUTPUT_DIR.glob("*") if f.is_file() and f.suffix.lower() in valid_exts],
                          key=lambda f: f.stat().st_mtime, reverse=True)
            for img in imgs[:48]:
                try:
                    if img.stat().st_size < 25000:
                        continue
                except Exception:
                    continue
                p_text, s_val, l_list, ckpt, c_name = _extract_tester_image_meta(img)
                age = rounds_tracker.get(img.name, 0)
                if age >= 3:
                    continue
                tester_images.append({
                    "filename": img.name,
                    "url": f"/tester_images/{img.name}",
                    "size_bytes": img.stat().st_size,
                    "timestamp": img.stat().st_mtime,
                    "prompt": p_text,
                    "seed": s_val,
                    "loras": l_list,
                    "checkpoint": ckpt,
                    "combo_name": c_name,
                    "is_saved": False,
                    "rounds_age": age
                })

        # Obter lista de Checkpoints e LoRAs dinamicamente (usando cache sem I/O repetitivo de disco)
        available_ckpts = get_available_checkpoints(refresh=False)
        avail_loras = get_available_loras(refresh=False)

        # Obter estado real da fila do ComfyUI
        running_count = 0
        pending_count = 0
        prompt_q = getattr(server.PromptServer.instance, "prompt_queue", None)
        if prompt_q:
            try:
                q_data = prompt_q.get_current_queue_volatile()
                running_count = len(q_data[0]) if len(q_data) > 0 else 0
                pending_count = len(q_data[1]) if len(q_data) > 1 else 0
            except Exception:
                pass
        is_generating = (running_count + pending_count) > 0
        queue_remaining = running_count + pending_count

        # Enriquecer approved_combos com thumb_url e description
        raw_approved = approved_data.get("approved_combos", [])
        enriched_approved = []
        for c in raw_approved:
            c_copy = dict(c)
            thumb = c_copy.get("thumb", "")
            thumb_url = ""
            if thumb:
                if str(thumb).startswith("http") or str(thumb).startswith("/"):
                    thumb_url = thumb
                elif (TESTER_SAVED_DIR / thumb).exists():
                    thumb_url = f"/tester_saved_images/{thumb}"
                elif (TESTER_OUTPUT_DIR / thumb).exists():
                    thumb_url = f"/tester_images/{thumb}"

            # Se não tiver thumb explícita, associa automaticamente uma imagem gerada compatível
            if not thumb_url:
                c_name = c_copy.get("name", "")
                c_ckpt = c_copy.get("checkpoint", "")
                for s_img in saved_gallery:
                    if s_img.get("combo_name") == c_name or (s_img.get("checkpoint") == c_ckpt and s_img.get("combo_name")):
                        thumb_url = s_img.get("url")
                        c_copy["thumb"] = s_img.get("filename")
                        break
                if not thumb_url:
                    for t_img in tester_images:
                        if t_img.get("combo_name") == c_name or t_img.get("checkpoint") == c_ckpt:
                            thumb_url = t_img.get("url")
                            c_copy["thumb"] = t_img.get("filename")
                            break

            c_copy["thumb_url"] = thumb_url
            c_copy["description"] = c_copy.get("description", "")
            enriched_approved.append(c_copy)

        return web.json_response({
            "current_test": current_test,
            "images": tester_images,
            "saved_images": real_saved_filenames,
            "saved_gallery": saved_gallery,
            "approved_combos": enriched_approved,
            "rejected_combos": approved_data.get("rejected_combos", []),
            "checkpoints": available_ckpts,
            "available_loras": avail_loras,
            "is_generating": is_generating,
            "queue_remaining": queue_remaining,
            "running_count": running_count,
            "pending_count": pending_count
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/combo_tester/approve")
async def api_combo_tester_approve(request):
    try:
        data = await request.json() if request.can_read_body else {}
        current_test = _load_current_test_data()
        if not current_test:
            return web.json_response({"error": "Nenhum teste ativo para aprovar"}, status=400)

        import datetime
        approved_data = _load_approved_combos_data()

        custom_name = data.get("name", "").strip()
        custom_desc = data.get("description", "").strip()
        custom_thumb = data.get("thumb", "").strip()

        # Se não enviou thumb específica, tenta capturar a imagem mais recente do teste atual
        if not custom_thumb and TESTER_OUTPUT_DIR.exists():
            valid_exts = {".png", ".webp", ".jpg", ".jpeg"}
            imgs = sorted([f for f in TESTER_OUTPUT_DIR.glob("*") if f.is_file() and f.suffix.lower() in valid_exts],
                          key=lambda f: f.stat().st_mtime, reverse=True)
            if imgs:
                custom_thumb = imgs[0].name

        if not custom_name:
            ckpt_raw = current_test.get("checkpoint", "")
            ckpt_short = pathlib.Path(ckpt_raw).stem if ckpt_raw else "Modelo"
            lora_parts = []
            for l in current_test.get("loras", []):
                lp = pathlib.Path(l.get("lora", "")).stem[:16]
                lora_parts.append(f"{lp}({l.get('strength_model', 0.8)})")
            custom_name = f"{ckpt_short} + " + " + ".join(lora_parts)

        new_entry = {
            "id": f"combo_{int(datetime.datetime.now().timestamp())}",
            "name": custom_name,
            "checkpoint": current_test.get("checkpoint"),
            "loras": current_test.get("loras", []),
            "approved_at": datetime.datetime.now().isoformat(),
            "notes": data.get("notes", "Aprovado via Testador Web"),
            "description": custom_desc,
            "thumb": custom_thumb
        }

        current_test["status"] = "approved"
        current_test["approved_name"] = custom_name
        _save_current_test_data(current_test)

        approved_data.setdefault("approved_combos", []).append(new_entry)
        _save_approved_combos_data(approved_data)

        return web.json_response({
            "success": True,
            "message": f"Combinação '{custom_name}' aprovada com sucesso!",
            "entry": new_entry
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/combo_tester/reject")
async def api_combo_tester_reject(request):
    try:
        data = await request.json() if request.can_read_body else {}
        current_test = _load_current_test_data()
        if not current_test:
            return web.json_response({"error": "Nenhum teste ativo para reprovar"}, status=400)

        import datetime
        approved_data = _load_approved_combos_data()

        current_test["status"] = "rejected"
        _save_current_test_data(current_test)

        rejected_entry = {
            "test_id": current_test.get("test_id"),
            "checkpoint": current_test.get("checkpoint"),
            "loras": current_test.get("loras", []),
            "rejected_at": datetime.datetime.now().isoformat(),
            "reason": data.get("reason", "Reprovado na avaliação de imagens")
        }
        approved_data.setdefault("rejected_combos", []).append(rejected_entry)
        _save_approved_combos_data(approved_data)

        return web.json_response({
            "success": True,
            "message": "Combinação reprovada e registrada no histórico de exclusões."
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/combo_tester/preset/rename")
async def api_combo_tester_preset_rename(request):
    try:
        data = await request.json() if request.can_read_body else {}
        pid = data.get("id")
        new_name = data.get("new_name", "").strip()
        if not pid or not new_name:
            return web.json_response({"error": "ID e novo nome são obrigatórios"}, status=400)
        
        approved_data = _load_approved_combos_data()
        updated = False
        for c in approved_data.get("approved_combos", []):
            if c.get("id") == pid:
                c["name"] = new_name
                updated = True
                break
        
        if not updated:
            return web.json_response({"error": "Preset não encontrado"}, status=404)
            
        _save_approved_combos_data(approved_data)
        return web.json_response({"success": True, "message": f"Preset renomeado para '{new_name}'!"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/combo_tester/preset/delete")
async def api_combo_tester_preset_delete(request):
    try:
        data = await request.json() if request.can_read_body else {}
        pid = data.get("id")
        if not pid:
            return web.json_response({"error": "ID do preset é obrigatório"}, status=400)
        
        approved_data = _load_approved_combos_data()
        combos = approved_data.get("approved_combos", [])
        initial_len = len(combos)
        approved_data["approved_combos"] = [c for c in combos if c.get("id") != pid]
        
        if len(approved_data["approved_combos"]) == initial_len:
            return web.json_response({"error": "Preset não encontrado"}, status=404)
            
        _save_approved_combos_data(approved_data)
        return web.json_response({"success": True, "message": "Preset removido com sucesso!"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/combo_tester/preset/edit")
async def api_combo_tester_preset_edit(request):
    try:
        data = await request.json() if request.can_read_body else {}
        pid = data.get("id")
        if not pid:
            return web.json_response({"error": "ID do preset é obrigatório"}, status=400)
            
        approved_data = _load_approved_combos_data()
        target = None
        for c in approved_data.get("approved_combos", []):
            if c.get("id") == pid:
                target = c
                break
                
        if not target:
            return web.json_response({"error": "Preset não encontrado"}, status=404)
            
        if "name" in data and data["name"].strip():
            target["name"] = data["name"].strip()
        if "description" in data:
            target["description"] = str(data["description"]).strip()
        if "thumb" in data:
            target["thumb"] = str(data["thumb"]).strip()
        if "checkpoint" in data and data["checkpoint"]:
            target["checkpoint"] = data["checkpoint"]
        if "loras" in data and isinstance(data["loras"], list):
            target["loras"] = data["loras"]
            
        _save_approved_combos_data(approved_data)
        return web.json_response({"success": True, "message": "Preset atualizado com sucesso!"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/combo_tester/preset/update_description")
async def api_combo_tester_preset_update_description(request):
    try:
        data = await request.json() if request.can_read_body else {}
        pid = data.get("id")
        desc = str(data.get("description", "")).strip()
        if not pid:
            return web.json_response({"error": "ID do preset é obrigatório"}, status=400)
            
        approved_data = _load_approved_combos_data()
        updated = False
        for c in approved_data.get("approved_combos", []):
            if c.get("id") == pid:
                c["description"] = desc
                updated = True
                break
                
        if not updated:
            return web.json_response({"error": "Preset não encontrado"}, status=404)
            
        _save_approved_combos_data(approved_data)
        return web.json_response({"success": True, "message": "Descrição salva com sucesso!", "description": desc})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/combo_tester/preset/set_thumb")
async def api_combo_tester_preset_set_thumb(request):
    try:
        data = await request.json() if request.can_read_body else {}
        pid = data.get("id")
        thumb = str(data.get("thumb", "")).strip()
        if not pid or not thumb:
            return web.json_response({"error": "ID do preset e thumb são obrigatórios"}, status=400)
            
        approved_data = _load_approved_combos_data()
        updated = False
        for c in approved_data.get("approved_combos", []):
            if c.get("id") == pid:
                c["thumb"] = thumb
                updated = True
                break
                
        if not updated:
            return web.json_response({"error": "Preset não encontrado"}, status=404)
            
        _save_approved_combos_data(approved_data)
        return web.json_response({"success": True, "message": "Capa do preset atualizada com sucesso!", "thumb": thumb})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

# ==============================================================================
# --- CONTROLE DO MOTOR COMFYUI NATIVO (START / STOP / STATUS) ---
# ==============================================================================
@server.PromptServer.instance.routes.post("/api/manager/stop")
async def api_manager_stop(request):
    """Desliga o motor ComfyUI para liberar 100% da GPU/VRAM sem janela."""
    try:
        def _do_shutdown():
            import time, subprocess
            time.sleep(0.5)
            parar_bat = COMFY_ROOT / "parar.bat"
            if parar_bat.exists():
                subprocess.Popen(["cmd.exe", "/c", str(parar_bat)], cwd=str(COMFY_ROOT), creationflags=subprocess.CREATE_NO_WINDOW)
            else:
                os._exit(0)

        import threading
        threading.Thread(target=_do_shutdown, daemon=True).start()
        return web.json_response({"success": True, "message": "Desligando motor ComfyUI... GPU liberada!"})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/manager/start")
async def api_manager_start(request):
    return web.json_response({"success": True, "message": "ComfyUI já está online"})

@server.PromptServer.instance.routes.get("/api/manager/status")
async def api_manager_status(request):
    return web.json_response({"success": True, "comfyui_online": True})

@server.PromptServer.instance.routes.post("/api/manager/free_vram")
async def api_manager_free_vram(request):
    """Libera a memória de vídeo (VRAM) e RAM descarregando modelos ociosos e limpando fila."""
    try:
        import gc
        import comfy.model_management as mm

        # 1. Limpa fila do ComfyUI se houver itens travados/interrompidos
        try:
            server.PromptServer.instance.prompt_queue.wipe_queue()
        except Exception:
            pass

        # 2. Descarrega modelos e limpa cache da GPU/RAM
        mm.unload_all_models()
        mm.cleanup_models()
        mm.soft_empty_cache()
        gc.collect()

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            try:
                torch.cuda.ipc_collect()
            except Exception:
                pass

        return web.json_response({
            "success": True, 
            "message": "Modelos descarregados e VRAM/RAM liberadas com sucesso!"
        })
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/combo_tester/save_image")
async def api_combo_tester_save_image(request):
    try:
        data = await request.json() if request.can_read_body else {}
        filename = data.get("filename")
        if not filename:
            return web.json_response({"error": "Filename não fornecido"}, status=400)
            
        # Busca no diretório tester primeiro (origem padrão ao guardar)
        src = None
        candidates = [
            TESTER_OUTPUT_DIR / filename,
            TESTER_OUTPUT_DIR.parent / filename,
            pathlib.Path(r"D:\IA\ComfyUI\output\tester") / filename,
            pathlib.Path(r"D:\IA\ComfyUI\output") / filename,
            pathlib.Path(r"E:\ComfyUI_output\tester") / filename,
            pathlib.Path(r"E:\ComfyUI_output") / filename,
            TESTER_SAVED_DIR / filename
        ]
        for c in candidates:
            if c.exists() and c.is_file():
                src = c
                break

        if src is None:
            found = list(TESTER_OUTPUT_DIR.parent.glob(f"**/{filename}"))
            if found:
                src = found[0]

        if src is None or not src.exists():
            return web.json_response({"error": f"Arquivo '{filename}' não encontrado no servidor"}, status=404)
            
        TESTER_SAVED_DIR.mkdir(parents=True, exist_ok=True)
        import shutil, time
        dest = TESTER_SAVED_DIR / filename
        
        # Mover fisicamente para a pasta tester_saved evitando qualquer colisão
        if src.resolve() != dest.resolve():
            if dest.exists():
                dest = TESTER_SAVED_DIR / f"{src.stem}_{int(time.time())}{src.suffix}"
            shutil.move(str(src), str(dest))
        
        saved_list = _load_saved_images_list()
        if dest.name not in saved_list:
            saved_list.append(dest.name)
            _save_saved_images_list(saved_list)

        # Salvar metadados da combinação guardada
        try:
            saved_meta = _load_tester_saved_metadata()
            curr_test = _load_current_test_data()
            p_text, s_val, l_list, ckpt, c_name = _extract_tester_image_meta(dest)
            if not l_list and curr_test and curr_test.get("loras"):
                l_list = curr_test.get("loras", [])
            if not ckpt and curr_test and curr_test.get("checkpoint"):
                ckpt = pathlib.Path(str(curr_test.get("checkpoint"))).stem
            if not c_name and curr_test and curr_test.get("test_id"):
                c_name = curr_test.get("test_id")
            
            saved_meta[dest.name] = {
                "checkpoint": ckpt,
                "loras": l_list,
                "combo_name": c_name,
                "prompt": p_text,
                "seed": s_val,
                "timestamp": time.time()
            }
            _save_tester_saved_metadata(saved_meta)
        except Exception as meta_err:
            print(f"[ComboTester] Aviso ao salvar metadados da imagem guardada: {meta_err}")
            
        # Remove do tracker de idades para não sofrer remoção após resorteios
        tracker = _load_rounds_tracker()
        if filename in tracker:
            del tracker[filename]
            _save_rounds_tracker(tracker)
            
        return web.json_response({"success": True, "saved": True, "saved_filename": dest.name, "message": f"Imagem guardada com sucesso!"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/combo_tester/unsave_image")
async def api_combo_tester_unsave_image(request):
    try:
        data = await request.json() if request.can_read_body else {}
        filename = data.get("filename")
        if not filename:
            return web.json_response({"error": "Filename não fornecido"}, status=400)
            
        saved_list = _load_saved_images_list()
        if filename in saved_list:
            saved_list.remove(filename)
            _save_saved_images_list(saved_list)
            
        # Devolver o arquivo para a pasta de origem (tester ou creation)
        dest = TESTER_SAVED_DIR / filename
        if dest.exists() and dest.is_file():
            import shutil, time
            if filename.startswith("create_"):
                CREATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                target_restore = CREATION_OUTPUT_DIR / filename
                if target_restore.exists():
                    target_restore = CREATION_OUTPUT_DIR / f"{dest.stem}_restored_{int(time.time())}{dest.suffix}"
                shutil.move(str(dest), str(target_restore))
            else:
                TESTER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                target_restore = TESTER_OUTPUT_DIR / filename
                if target_restore.exists():
                    target_restore = TESTER_OUTPUT_DIR / f"{dest.stem}_restored_{int(time.time())}{dest.suffix}"
                shutil.move(str(dest), str(target_restore))
                # Reseta idade para 0 no testador
                tracker = _load_rounds_tracker()
                tracker[target_restore.name] = 0
                _save_rounds_tracker(tracker)

        return web.json_response({"success": True, "saved": False, "message": f"Imagem devolvida para a galeria do testador."})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/combo_tester/delete_saved_image")
async def api_combo_tester_delete_saved_image(request):
    try:
        data = await request.json() if request.can_read_body else {}
        filename = data.get("filename")
        if not filename:
            return web.json_response({"error": "Filename não fornecido"}, status=400)
            
        saved_list = _load_saved_images_list()
        if filename in saved_list:
            saved_list.remove(filename)
            _save_saved_images_list(saved_list)
            
        dest = TESTER_SAVED_DIR / filename
        if dest.exists() and dest.is_file():
            dest.unlink()

        return web.json_response({"success": True, "message": f"Imagem guardada {filename} excluída com sucesso."})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/combo_tester/delete_test_image")
async def api_combo_tester_delete_test_image(request):
    try:
        data = await request.json() if request.can_read_body else {}
        filename = data.get("filename")
        if not filename:
            return web.json_response({"error": "Filename não fornecido"}, status=400)

        filename = os.path.basename(str(filename).strip())
        # Remove exclusivamente do diretório de testes, sem afetar outras galerias ou pastas guardadas
        target = TESTER_OUTPUT_DIR / filename
        if target.exists() and target.is_file():
            target.unlink()

        tracker = _load_rounds_tracker()
        if filename in tracker:
            del tracker[filename]
            _save_rounds_tracker(tracker)

        return web.json_response({"success": True, "message": f"Imagem de teste {filename} excluída com sucesso."})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/combo_tester/new_test")
async def api_combo_tester_new_test(request):
    try:
        # Avança o ciclo de sobrevivência das imagens do testador
        # Imagens não guardadas com 3 ou mais resorteios de LoRAs são removidas
        _advance_tester_rounds_and_cleanup()

        req_data = await request.json() if request.can_read_body else {}
        target_model = req_data.get("checkpoint") # Opcional
        
        current_test = _load_current_test_data()
        import random, datetime, folder_paths

        # Alternar ou fixar modelo
        available_ckpts = get_available_checkpoints(refresh=True)
        if target_model and target_model in available_ckpts:
            chosen_ckpt = target_model
        else:
            last_ckpt = current_test.get("checkpoint") if current_test else ""
            if available_ckpts:
                try:
                    idx = available_ckpts.index(last_ckpt)
                    chosen_ckpt = available_ckpts[(idx + 1) % len(available_ckpts)]
                except (ValueError, IndexError):
                    chosen_ckpt = available_ckpts[0]
            else:
                chosen_ckpt = OFFICIAL_CHECKPOINTS[0]

        illu_loras = get_sampleable_loras(refresh=True)

        qtd_raw = req_data.get("qtd_loras", 3)
        if str(qtd_raw).lower() in ["random", "aleatorio", "aleatório", "2 a 4"]:
            qtd = random.randint(2, 4)
        elif isinstance(qtd_raw, str) and qtd_raw.isdigit():
            qtd = int(qtd_raw)
        elif isinstance(qtd_raw, int):
            qtd = qtd_raw
        else:
            qtd = 3
        qtd = max(1, min(6, qtd))

        # Sorteio Inteligente com Categorização e Variação Assimétrica de Pesos
        loras_config = sample_harmonized_loras(illu_loras, qtd=qtd)

        new_test = {
            "test_id": f"test_{int(datetime.datetime.now().timestamp())}",
            "checkpoint": chosen_ckpt,
            "loras": loras_config,
            "status": "testing",
            "created_at": datetime.datetime.now().isoformat()
        }
        _save_current_test_data(new_test)

        return web.json_response({
            "success": True,
            "message": f"Nova combinação sorteada com {len(loras_config)} LoRAs!",
            "test": new_test
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.get("/api/models/scan")
@server.PromptServer.instance.routes.post("/api/models/scan")
async def api_models_scan(request):
    try:
        ckpts = get_available_checkpoints(refresh=True)
        loras = get_available_loras(refresh=True)
        return web.json_response({
            "success": True,
            "checkpoints": ckpts,
            "checkpoints_count": len(ckpts),
            "loras": loras,
            "loras_count": len(loras)
        })
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/combo_tester/update_current")
async def api_combo_tester_update_current(request):
    try:
        data = await request.json() if request.can_read_body else {}
        current_test = _load_current_test_data()
        if not current_test:
            return web.json_response({"error": "Nenhum teste ativo para atualizar"}, status=400)

        if "checkpoint" in data:
            current_test["checkpoint"] = data["checkpoint"]
        if "loras" in data:
            current_test["loras"] = data["loras"]

        _save_current_test_data(current_test)
        return web.json_response({"success": True, "test": current_test})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

# Tabela de Resoluções Práticas e Homologadas para SDXL / Illustrious (Múltiplos de 64, ~1MP)
PRACTICAL_SDXL_RESOLUTIONS = {
    "9:16": {"width": 832, "height": 1344, "is_portrait": True, "label": "9:16 Celular"},
    "16:9": {"width": 1344, "height": 768, "is_portrait": False, "label": "16:9 Wallpaper"},
    "1:1": {"width": 1024, "height": 1024, "is_portrait": True, "label": "1:1 Quadrado"},
    "3:4": {"width": 896, "height": 1152, "is_portrait": True, "label": "3:4 Retrato Artbook"},
    "4:3": {"width": 1152, "height": 896, "is_portrait": False, "label": "4:3 Paisagem Clássica"},
    "2:3": {"width": 832, "height": 1216, "is_portrait": True, "label": "2:3 Retrato Foto"},
    "3:2": {"width": 1216, "height": 832, "is_portrait": False, "label": "3:2 Paisagem Foto"},
    "4:5": {"width": 896, "height": 1088, "is_portrait": True, "label": "4:5 Social Feed"},
    "21:9": {"width": 1536, "height": 640, "is_portrait": False, "label": "21:9 Cinema Ultrawide"},
}

@server.PromptServer.instance.routes.post("/api/combo_tester/generate_set")
async def api_combo_tester_generate_set(request):
    try:
        data = await request.json() if request.can_read_body else {}
        count = int(data.get("count", 6))
        count = max(1, min(12, count)) # Limite seguro entre 1 e 12 imagens
        client_id = data.get("client_id") or "combo_tester_ui"

        current_test = _load_current_test_data()
        if not current_test:
            return web.json_response({"error": "Nenhum teste ativo encontrado. Sorteie um combo primeiro."}, status=400)

        template_path = COMFY_ROOT / "user" / "default" / "tester_prompt_template.json"
        if not template_path.exists():
            template_path = pathlib.Path(r"D:\IA\ComfyUI\user\default\tester_prompt_template.json")
        if not template_path.exists():
            return web.json_response({"error": "Template de prompt não encontrado."}, status=500)

        with open(template_path, "r", encoding="utf-8") as f:
            base_prompt = json.load(f)

        # 1. Configurar Checkpoint (Node 9)
        avail_ckpts = get_available_checkpoints(refresh=False)
        default_ckpt = avail_ckpts[0] if avail_ckpts else OFFICIAL_CHECKPOINTS[0]
        ckpt_name = current_test.get("checkpoint", default_ckpt)
        if "9" in base_prompt and "inputs" in base_prompt["9"]:
            base_prompt["9"]["inputs"]["ckpt_name"] = ckpt_name

        # 1.1 Configurar Modo SFW / Seguro (Node 2: ON = NSFW | OFF = SFW)
        is_sfw = bool(data.get("is_sfw", False))
        if "2" in base_prompt and "inputs" in base_prompt["2"]:
            base_prompt["2"]["inputs"]["value"] = not is_sfw

        # 2. Configurar Resolução e Formato (Processado dinamicamente por imagem)
        aspect_ratio_param = str(data.get("aspect_ratio", "9:16")).strip().lower()
        is_random_ratio = aspect_ratio_param in ["random", "aleatorio", "aleatório", "var", "variado"]

        # 3. Configurar LoRAs (Node 47 - Power Lora Loader) e mapear triggers oficiais
        test_loras = current_test.get("loras", [])
        active_loras_count = len([item for item in test_loras if item.get("lora") and float(item.get("strength_model", 0.8)) > 0.05])

        # Orçamento Total Combinado: permite manifestação expressiva no LoRA dominante (0.75 - 0.85) com variação assimétrica,
        # evitando o achatamento estático em 0.50 e prevenindo sobrecarga cumulativa no latent space.
        if active_loras_count <= 1:
            max_total_budget = 1.10
            single_cap = 1.00
        elif active_loras_count == 2:
            max_total_budget = 1.60
            single_cap = 0.90
        elif active_loras_count == 3:
            max_total_budget = 1.95
            single_cap = 0.85
        else:
            max_total_budget = 2.15
            single_cap = 0.80

        # Primeiro aplica teto individual de segurança
        clamped_loras = []
        for item in test_loras:
            orig_s = float(item.get("strength_model", 0.8))
            eff_s = min(orig_s, single_cap)
            clamped_loras.append((item, eff_s))

        # Se a soma total ultrapassar o orçamento do modelo, escala proporcionalmente preservando a hierarquia de forças
        total_sum = sum(s for _, s in clamped_loras if s > 0.05)
        scale_factor = (max_total_budget / total_sum) if total_sum > max_total_budget else 1.0

        lora_triggers = []
        eff_test_loras = []
        for item, eff_s in clamped_loras:
            l_name = item.get("lora")
            if l_name:
                trig = find_lora_trigger(l_name)
                if trig and trig not in lora_triggers:
                    lora_triggers.append(trig)
                scaled_s = round(eff_s * scale_factor, 2)
                eff_test_loras.append({
                    **item,
                    "strength_model": scaled_s,
                    "strength_clip": scaled_s
                })

        if "47" in base_prompt and "inputs" in base_prompt["47"]:
            n47_inputs = base_prompt["47"]["inputs"]
            for k in list(n47_inputs.keys()):
                if k.startswith("lora_") and isinstance(n47_inputs[k], dict):
                    n47_inputs[k]["on"] = False

            for idx, item in enumerate(eff_test_loras, 1):
                slot_key = f"lora_{idx}"
                n47_inputs[slot_key] = {
                    "on": True,
                    "lora": item.get("lora"),
                    "strength": float(item.get("strength_model", 0.8)),
                    "strengthTwo": None
                }

        # Configurar Nó 89 (PromptReviewer) com modelo do nó 47 e triggers automáticos de teste
        if "89" in base_prompt and "inputs" in base_prompt["89"]:
            base_prompt["89"]["inputs"]["opt_model"] = ["47", 0]
            base_prompt["89"]["inputs"]["opt_lora_triggers"] = ", ".join(lora_triggers) if lora_triggers else ""

        # NOTA: Imagens não guardadas são preservadas acumulando por até 3 resorteios de LoRAs.
        # Imagens guardadas já foram movidas para tester_saved.

        # 4. Enfileirar 'count' imagens na fila do ComfyUI com seeds e wildcards 100% variados
        port = getattr(server.PromptServer.instance, "port", 8188)
        async with aiohttp.ClientSession() as session:
            for i in range(count):
                prompt_copy = copy.deepcopy(base_prompt)

                # Resolução & Formato Prático (aleatório por imagem ou fixado)
                if is_random_ratio:
                    sample_ratios = ["9:16", "16:9", "1:1", "3:4", "4:3", "2:3", "3:2", "4:5"]
                    cur_ratio_key = random.choice(sample_ratios)
                else:
                    cur_ratio_key = aspect_ratio_param if aspect_ratio_param in PRACTICAL_SDXL_RESOLUTIONS else "9:16"

                res_info = PRACTICAL_SDXL_RESOLUTIONS.get(cur_ratio_key, PRACTICAL_SDXL_RESOLUTIONS["9:16"])
                cur_w = res_info["width"]
                cur_h = res_info["height"]
                is_portrait = res_info["is_portrait"]

                # Node 1 (Switch Formato) orienta wildcards e ângulos de câmera (Retrato vs Paisagem)
                if "1" in prompt_copy and "inputs" in prompt_copy["1"]:
                    prompt_copy["1"]["inputs"]["value"] = is_portrait

                # Nós primitivos de largura e altura
                if is_portrait:
                    if "3" in prompt_copy and "inputs" in prompt_copy["3"]:
                        prompt_copy["3"]["inputs"]["value"] = cur_w
                    if "6" in prompt_copy and "inputs" in prompt_copy["6"]:
                        prompt_copy["6"]["inputs"]["value"] = cur_h
                else:
                    if "4" in prompt_copy and "inputs" in prompt_copy["4"]:
                        prompt_copy["4"]["inputs"]["value"] = cur_w
                    if "7" in prompt_copy and "inputs" in prompt_copy["7"]:
                        prompt_copy["7"]["inputs"]["value"] = cur_h

                # Node 43 (EmptyLatentImage) recebe a resolução exata homologada para SDXL
                if "43" in prompt_copy and "inputs" in prompt_copy["43"]:
                    prompt_copy["43"]["inputs"]["width"] = cur_w
                    prompt_copy["43"]["inputs"]["height"] = cur_h

                # Randomizar seeds e forcar sorteio dinâmico em todos os nós
                for nid, n_info in prompt_copy.items():
                    n_inputs = n_info.get("inputs", {})
                    if "seed" in n_inputs:
                        n_inputs["seed"] = random.randint(1, 999999999999999)
                    # Apenas processadores de wildcards Impact devem ter populated_text limpo para re-sorteio
                    if n_info.get("class_type") == "ImpactWildcardProcessor":
                        n_inputs["mode"] = "populate"
                        n_inputs["populated_text"] = ""

                # Garantir rigorosamente que o nó 89 (PromptReviewer) receba os triggers e modelo de LoRAs
                if "89" in prompt_copy and "inputs" in prompt_copy["89"]:
                    prompt_copy["89"]["inputs"]["opt_model"] = ["47", 0]
                    prompt_copy["89"]["inputs"]["opt_lora_triggers"] = ", ".join(lora_triggers) if lora_triggers else ""

                # Garantir rigorosamente que o nó 41 (ImpactWildcardEncode) receba o prompt positivo do PromptReviewer (Node 89)
                if "41" in prompt_copy and "inputs" in prompt_copy["41"]:
                    prompt_copy["41"]["inputs"]["populated_text"] = ["89", 0]
                    prompt_copy["41"]["inputs"]["mode"] = "fixed"

                # Garantir bloqueio de câmeras, velas, peras, cabeças extras/desmembradas e pernas humanas no Node 37 (Negativo base)
                if "37" in prompt_copy and "inputs" in prompt_copy["37"]:
                    n37_val = str(prompt_copy["37"]["inputs"].get("value", ""))
                    if "patreon" not in n37_val.lower():
                        n37_val += ", ((watermark, text, logo, patreon, patreon_logo, patreon_username, website, url, web_address, username, artist_name, signature, copyright, copyright_notice, stamp, social_media_logo, social_media_handle, handle, watermark_text, icon_watermark:1.4))"
                    if "camera" not in n37_val:
                        n37_val += ", camera, tripod, handheld_camera, camera_lens, candles, candle, candlestick, pear, pears, fruit"
                    if "floating_head" not in n37_val:
                        n37_val += ", ((floating_head, disembodied_head, extra_heads, second_head:1.4))"
                    if "two_tails" not in n37_val:
                        n37_val += ", ((two_tails, multiple_tails, split_tail, extra_tails, human_legs_on_mermaid:1.6)), ((braided_snakes, human_hair_on_medusa:1.4))"
                    if is_sfw:
                        n37_val += ", nsfw, nude, naked, nipples, pussy, breasts, bare_breasts, cleavage, suggestive, explicit"
                    all_prompt_texts = " ".join([
                        str(v.get("inputs", {}).get("text", "")) + " " + str(v.get("inputs", {}).get("populated_text", "")) + " " + str(v.get("inputs", {}).get("wildcard_text", ""))
                        for v in prompt_copy.values() if isinstance(v, dict)
                    ]).lower()
                    if any(m in all_prompt_texts for m in ["lamia", "serpent_girl", "serpent_race", "snake_lower_body"]):
                        n37_val += ", ((two_snake_tails, two_tails, multiple_tails, split_tail, extra_tails, second_tail, snake_legs, two_snakes:1.6))"
                    if any(m in all_prompt_texts for m in ["centaur", "mermaid", "lamia", "scylla", "snake_lower_body", "fish_tail", "horse_lower_body", "tentacles_lower_body"]):
                        n37_val += ", ((human_legs, human_feet, feet, toes, human_knees, two_legs, bipedal, standing_on_human_legs, extra_legs:1.6))"
                    if any(m in all_prompt_texts for m in ["arachne", "spider_girl"]):
                        n37_val += ", ((wings, fairy_wings, insect_wings, spider_lower_body, giant_spider_abdomen, monster_spider_body:1.5))"
                    if not any(g in all_prompt_texts for g in ["ghost_girl", "poltergeist", "phantom", "spectral", "spirit_girl"]):
                        n37_val += ", ((ghost, spirit, wisp, phantom, slime_creature, mascot, pet, floating_creature, familiar, small_ghost, cute_ghost:1.4))"
                    else:
                        n37_val += ", ((solid_opaque_skin, normal_human_skin, mascot, pet, floating_creature, cute_ghost, small_ghost, companion, familiar, separate_ghost, wisp_creature:1.5))"
                    
                    has_fisting_call = any(f in all_prompt_texts for f in ["fisting", "vaginal_fisting", "anal_fisting", "hand_insertion"])
                    has_double_fisting_call = any(df in all_prompt_texts for df in ["double_fisting", "two_hands_fisting", "two_hands_insertion", "two_fists"])
                    if not has_fisting_call:
                        n37_val += ", ((fisting, hand_insertion, double_fisting, two_hands_insertion:1.4))"
                    elif not has_double_fisting_call:
                        n37_val += ", ((double_fisting, two_hands_fisting, two_hands_insertion, two_fists, both_hands_insertion:1.6))"
                    n37_val += ", ((watermark, text, signature, artist_name, signature_on_bottom, artist_signature, copyright, copyright_notice, logo, stamp, username, patreon_logo, website_watermark:1.6))"
                    if "2girls" in all_prompt_texts or "two_girls" in all_prompt_texts:
                        n37_val += ", 3girls, 4girls, multiple_girls, group"
                    prompt_copy["37"]["inputs"]["value"] = n37_val

                # 5. Escala Dinâmica de CFG de 5.0 até 3.0 (Node 44 - KSampler)
                # Quanto mais LoRAs ativos, menor o CFG (curva proporcional de 5.0 até 3.0)
                if "44" in prompt_copy and "inputs" in prompt_copy["44"]:
                    heavy_contrast_stems = [
                        "d4rkl1nes", "flatline", "ptd", "glowing_in_dark", "ani2rel", 
                        "3d_stylized", "oil", "shadow-circuit", "incoth", "jab_illustrious", 
                        "retro_scifi", "retrocom1", "sarafaber", "flat_inking", "detr1mental"
                    ]
                    has_heavy_contrast = any(any(hc in (item.get("lora") or "").lower() for hc in heavy_contrast_stems) for item in eff_test_loras)

                    if active_loras_count == 0:
                        dynamic_cfg = 5.0
                    elif active_loras_count == 1:
                        dynamic_cfg = 4.3 if has_heavy_contrast else 4.5
                    elif active_loras_count == 2:
                        dynamic_cfg = 3.7 if has_heavy_contrast else 3.9
                    elif active_loras_count == 3:
                        dynamic_cfg = 3.2 if has_heavy_contrast else 3.4
                    else: # 4 ou mais LoRAs
                        dynamic_cfg = 3.0

                    prompt_copy["44"]["inputs"]["cfg"] = dynamic_cfg
                    prompt_copy["44"]["inputs"]["steps"] = 28

                # 6. Garantir VAEDecode nativo no Node 45 (evita kernel crashes de tiled_scale em ROCm/AMD)
                if "45" in prompt_copy:
                    prompt_copy["45"]["class_type"] = "VAEDecode"
                    if "inputs" in prompt_copy["45"]:
                        for k in ["tile_size", "overlap", "temporal_size", "temporal_overlap"]:
                            prompt_copy["45"]["inputs"].pop(k, None)

                payload = {
                    "prompt": prompt_copy,
                    "client_id": client_id
                }
                try:
                    async with session.post(f"http://127.0.0.1:{port}/prompt", json=payload) as resp:
                        if resp.status != 200:
                            err_text = await resp.text()
                            print(f"[ComboTester] Erro ao enfileirar imagem {i+1}: {err_text}")
                            return web.json_response({
                                "success": False,
                                "error": f"Erro de validação no ComfyUI: {err_text}"
                            }, status=400)
                except Exception as req_err:
                    print(f"[ComboTester] Erro na requisição {i+1}: {req_err}")
                    return web.json_response({
                        "success": False,
                        "error": f"Erro de conexão com ComfyUI: {req_err}"
                    }, status=500)
                await asyncio.sleep(0.15)

        return web.json_response({
            "success": True,
            "message": f"Iniciada a geração de {count} imagens para avaliação!",
            "target_count": count
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/creation/generate")
async def api_creation_generate(request):
    try:
        data = await request.json() if request.can_read_body else {}
        count = int(data.get("count", 2))
        count = max(1, min(10, count))
        client_id = data.get("client_id") or "creation_ui"

        ckpt_name = data.get("checkpoint") or OFFICIAL_CHECKPOINTS[0]
        chosen_loras = data.get("loras", [])
        prompt_mode = str(data.get("prompt_mode", "custom")).lower().strip()
        custom_prompt = str(data.get("custom_prompt", "")).strip()
        is_amoled = bool(data.get("is_amoled", data.get("amoled", False)))
        aspect_ratio_param = str(data.get("aspect_ratio", "9:16")).strip().lower()
        steps_param = int(data.get("steps", 28))
        steps_param = max(10, min(80, steps_param))

        template_path = COMFY_ROOT / "user" / "default" / "tester_prompt_template.json"
        if not template_path.exists():
            template_path = pathlib.Path(r"D:\IA\ComfyUI\user\default\tester_prompt_template.json")
        if not template_path.exists():
            return web.json_response({"error": "Template de prompt não encontrado."}, status=500)

        with open(template_path, "r", encoding="utf-8") as f:
            base_prompt = json.load(f)

        # 1. Configurar Checkpoint (Node 9)
        if "9" in base_prompt and "inputs" in base_prompt["9"]:
            available_ckpts = get_available_checkpoints(refresh=False)
            norm_target = str(ckpt_name).replace("/", "\\").lower().strip()
            target_base = pathlib.Path(norm_target).name.lower()
            matched_ckpt = None
            for c in available_ckpts:
                norm_c = str(c).replace("/", "\\").lower().strip()
                if norm_c == norm_target or pathlib.Path(norm_c).name.lower() == target_base:
                    matched_ckpt = c
                    break
            base_prompt["9"]["inputs"]["ckpt_name"] = matched_ckpt if matched_ckpt else ckpt_name

        # 2. Configurar Modo SFW / Seguro (Node 2: ON = NSFW | OFF = SFW)
        is_sfw = (prompt_mode == "sfw")
        if "2" in base_prompt and "inputs" in base_prompt["2"]:
            base_prompt["2"]["inputs"]["value"] = not is_sfw

        # 3. Configurar Estilo AMOLED (Node 67: ON = AMOLED | OFF = Normal)
        if "67" in base_prompt and "inputs" in base_prompt["67"]:
            base_prompt["67"]["inputs"]["value"] = is_amoled

        # 4. Configurar LoRAs (Node 47 - Power Lora Loader)
        active_loras = [item for item in chosen_loras if item.get("lora") and float(item.get("strength_model", 0.8)) > 0.05]
        active_loras_count = len(active_loras)
        lora_triggers = []
        if "47" in base_prompt and "inputs" in base_prompt["47"]:
            n47_inputs = base_prompt["47"]["inputs"]
            for k in list(n47_inputs.keys()):
                if k.startswith("lora_") and isinstance(n47_inputs[k], dict):
                    n47_inputs[k]["on"] = False

            for idx, item in enumerate(active_loras, 1):
                l_name = item.get("lora")
                if not l_name:
                    continue
                trig = find_lora_trigger(l_name)
                if trig and trig not in lora_triggers:
                    lora_triggers.append(trig)
                slot_key = f"lora_{idx}"
                s_model = float(item.get("strength_model", 0.8))
                s_clip = float(item.get("strength_clip", s_model))
                n47_inputs[slot_key] = {
                    "on": True,
                    "lora": l_name,
                    "strength": s_model,
                    "strengthTwo": s_clip
                }

        # 5. Configurar PromptReviewer (Node 89)
        if "89" in base_prompt and "inputs" in base_prompt["89"]:
            base_prompt["89"]["inputs"]["opt_model"] = ["47", 0]
            base_prompt["89"]["inputs"]["opt_lora_triggers"] = ", ".join(lora_triggers) if lora_triggers else ""

        # 6. Salvar em pasta 'creation'
        CREATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        if "46" in base_prompt and "inputs" in base_prompt["46"]:
            base_prompt["46"]["inputs"]["filename_prefix"] = "creation/create"

        # 7. Enfileirar imagens
        port = getattr(server.PromptServer.instance, "port", 8188)
        async with aiohttp.ClientSession() as session:
            for i in range(count):
                prompt_copy = copy.deepcopy(base_prompt)

                # Resolução
                is_random_ratio = aspect_ratio_param in ["random", "aleatorio", "aleatório", "var", "variado"]
                if is_random_ratio:
                    sample_ratios = ["9:16", "16:9", "1:1", "3:4", "4:3", "2:3", "3:2", "4:5"]
                    cur_ratio_key = random.choice(sample_ratios)
                else:
                    cur_ratio_key = aspect_ratio_param if aspect_ratio_param in PRACTICAL_SDXL_RESOLUTIONS else "9:16"

                res_info = PRACTICAL_SDXL_RESOLUTIONS.get(cur_ratio_key, PRACTICAL_SDXL_RESOLUTIONS["9:16"])
                cur_w = res_info["width"]
                cur_h = res_info["height"]
                is_portrait = res_info["is_portrait"]

                if "1" in prompt_copy and "inputs" in prompt_copy["1"]:
                    prompt_copy["1"]["inputs"]["value"] = is_portrait

                if is_portrait:
                    if "3" in prompt_copy and "inputs" in prompt_copy["3"]:
                        prompt_copy["3"]["inputs"]["value"] = cur_w
                    if "6" in prompt_copy and "inputs" in prompt_copy["6"]:
                        prompt_copy["6"]["inputs"]["value"] = cur_h
                else:
                    if "4" in prompt_copy and "inputs" in prompt_copy["4"]:
                        prompt_copy["4"]["inputs"]["value"] = cur_w
                    if "7" in prompt_copy and "inputs" in prompt_copy["7"]:
                        prompt_copy["7"]["inputs"]["value"] = cur_h

                if "43" in prompt_copy and "inputs" in prompt_copy["43"]:
                    prompt_copy["43"]["inputs"]["width"] = cur_w
                    prompt_copy["43"]["inputs"]["height"] = cur_h

                # Configuração do Prompt conforme o modo selecionado
                amoled_prefix = "pitch_black_background, pure black background, mostly black image, true black, " if is_amoled else ""
                if prompt_mode == "custom" and custom_prompt:
                    if "89" in prompt_copy and "inputs" in prompt_copy["89"]:
                        prompt_copy["89"]["inputs"]["prompt"] = amoled_prefix + custom_prompt
                    if "41" in prompt_copy and "inputs" in prompt_copy["41"]:
                        prompt_copy["41"]["inputs"]["populated_text"] = ["89", 0]
                        prompt_copy["41"]["inputs"]["mode"] = "fixed"
                elif prompt_mode == "hybrid" and custom_prompt:
                    if "89" in prompt_copy and "inputs" in prompt_copy["89"]:
                        existing_trigs = prompt_copy["89"]["inputs"].get("opt_lora_triggers", "")
                        combined = (existing_trigs + ", " + amoled_prefix + custom_prompt).strip(", ")
                        prompt_copy["89"]["inputs"]["opt_lora_triggers"] = combined
                    if "41" in prompt_copy and "inputs" in prompt_copy["41"]:
                        prompt_copy["41"]["inputs"]["populated_text"] = ["89", 0]
                        prompt_copy["41"]["inputs"]["mode"] = "fixed"
                elif is_amoled:
                    if "89" in prompt_copy and "inputs" in prompt_copy["89"]:
                        existing_trigs = prompt_copy["89"]["inputs"].get("opt_lora_triggers", "")
                        prompt_copy["89"]["inputs"]["opt_lora_triggers"] = (existing_trigs + ", " + amoled_prefix).strip(", ")
                    if "41" in prompt_copy and "inputs" in prompt_copy["41"]:
                        prompt_copy["41"]["inputs"]["populated_text"] = ["89", 0]
                        prompt_copy["41"]["inputs"]["mode"] = "fixed"
                else:
                    if "41" in prompt_copy and "inputs" in prompt_copy["41"]:
                        prompt_copy["41"]["inputs"]["populated_text"] = ["89", 0]
                        prompt_copy["41"]["inputs"]["mode"] = "fixed"

                # Randomizar seeds
                for nid, n_info in prompt_copy.items():
                    n_inputs = n_info.get("inputs", {})
                    if "seed" in n_inputs:
                        n_inputs["seed"] = random.randint(1, 999999999999999)
                    if n_info.get("class_type") == "ImpactWildcardProcessor":
                        n_inputs["mode"] = "populate"
                        n_inputs["populated_text"] = ""

                # CFG dinâmico pelo número de LoRAs (5.0 a 3.0)
                if "44" in prompt_copy and "inputs" in prompt_copy["44"]:
                    heavy_contrast_stems = [
                        "d4rkl1nes", "flatline", "ptd", "glowing_in_dark", "ani2rel", 
                        "3d_stylized", "oil", "shadow-circuit", "incoth", "jab_illustrious", 
                        "retro_scifi", "retrocom1", "sarafaber", "flat_inking", "detr1mental"
                    ]
                    has_heavy_contrast = any(any(hc in (item.get("lora") or "").lower() for hc in heavy_contrast_stems) for item in active_loras)

                    if active_loras_count == 0:
                        dynamic_cfg = 5.0
                    elif active_loras_count == 1:
                        dynamic_cfg = 4.3 if has_heavy_contrast else 4.5
                    elif active_loras_count == 2:
                        dynamic_cfg = 3.7 if has_heavy_contrast else 3.9
                    elif active_loras_count == 3:
                        dynamic_cfg = 3.2 if has_heavy_contrast else 3.4
                    else:
                        dynamic_cfg = 3.0
                    prompt_copy["44"]["inputs"]["cfg"] = dynamic_cfg
                    prompt_copy["44"]["inputs"]["steps"] = steps_param

                # 6. Garantir VAEDecode nativo no Node 45 (evita kernel crashes de tiled_scale em ROCm/AMD)
                if "45" in prompt_copy:
                    prompt_copy["45"]["class_type"] = "VAEDecode"
                    if "inputs" in prompt_copy["45"]:
                        for k in ["tile_size", "overlap", "temporal_size", "temporal_overlap"]:
                            prompt_copy["45"]["inputs"].pop(k, None)

                # 7. Roteamento AMOLED Estrito (Só ativo quando checkbox marcado)
                if not is_amoled:
                    if "46" in prompt_copy and "inputs" in prompt_copy["46"]:
                        prompt_copy["46"]["inputs"]["images"] = ["45", 0]
                    if "67" in prompt_copy and "inputs" in prompt_copy["67"]:
                        prompt_copy["67"]["inputs"]["value"] = False
                    if "95" in prompt_copy and "inputs" in prompt_copy["95"]:
                        prompt_copy["95"]["inputs"]["enabled"] = False
                else:
                    if "46" in prompt_copy and "inputs" in prompt_copy["46"]:
                        prompt_copy["46"]["inputs"]["images"] = ["95", 0]
                    if "67" in prompt_copy and "inputs" in prompt_copy["67"]:
                        prompt_copy["67"]["inputs"]["value"] = True
                    if "95" in prompt_copy and "inputs" in prompt_copy["95"]:
                        prompt_copy["95"]["inputs"]["enabled"] = True

                payload = {
                    "prompt": prompt_copy,
                    "client_id": client_id
                }
                try:
                    async with session.post(f"http://127.0.0.1:{port}/prompt", json=payload) as resp:
                        if resp.status != 200:
                            err_text = await resp.text()
                            print(f"[Creation] Erro ao enfileirar imagem {i+1}: {err_text}")
                            return web.json_response({
                                "success": False,
                                "error": f"Erro de validação no ComfyUI: {err_text}"
                            }, status=400)
                except Exception as req_err:
                    print(f"[Creation] Erro na requisição {i+1}: {req_err}")
                    return web.json_response({
                        "success": False,
                        "error": f"Erro de conexão com ComfyUI: {req_err}"
                    }, status=500)
                await asyncio.sleep(0.15)

        return web.json_response({
            "success": True,
            "message": f"Iniciada a criação planejada de {count} imagens!"
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.get("/api/creation/gallery")
async def api_creation_gallery(request):
    try:
        CREATION_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        valid_exts = {".png", ".webp", ".jpg", ".jpeg"}
        imgs = sorted(
            [f for f in CREATION_OUTPUT_DIR.glob("*") if f.is_file() and f.suffix.lower() in valid_exts],
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        gallery = []
        for img in imgs[:60]:
            p_text, s_val, l_list, ckpt, c_name = _extract_tester_image_meta(img)
            gallery.append({
                "filename": img.name,
                "url": f"/creation_images/{img.name}",
                "size_bytes": img.stat().st_size,
                "timestamp": img.stat().st_mtime,
                "prompt": p_text,
                "seed": s_val,
                "loras": l_list,
                "checkpoint": ckpt,
                "combo_name": c_name or "Criação Planejada"
            })
        return web.json_response({"success": True, "images": gallery})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/creation/save_image")
async def api_creation_save_image(request):
    try:
        data = await request.json() if request.can_read_body else {}
        filename = data.get("filename")
        if not filename:
            return web.json_response({"error": "Filename não fornecido"}, status=400)
        src = CREATION_OUTPUT_DIR / filename
        if not src.exists():
            # Pode já ter sido movido para tester_saved
            if (TESTER_SAVED_DIR / filename).exists():
                return web.json_response({"success": True, "message": "Imagem já está guardada!", "saved_filename": filename})
            return web.json_response({"error": f"Arquivo '{filename}' não encontrado em creation"}, status=404)
            
        TESTER_SAVED_DIR.mkdir(parents=True, exist_ok=True)
        import shutil, time
        dest = TESTER_SAVED_DIR / filename
        if src.resolve() != dest.resolve():
            if dest.exists():
                dest = TESTER_SAVED_DIR / f"{src.stem}_{int(time.time())}{src.suffix}"
            shutil.move(str(src), str(dest))

        saved_list = _load_saved_images_list()
        if dest.name not in saved_list:
            saved_list.append(dest.name)
            _save_saved_images_list(saved_list)

        # Salvar metadados da criação guardada
        try:
            saved_meta = _load_tester_saved_metadata()
            p_text, s_val, l_list, ckpt, c_name = _extract_tester_image_meta(dest)
            saved_meta[dest.name] = {
                "checkpoint": ckpt,
                "loras": l_list,
                "combo_name": "🎨 Criação Planejada",
                "prompt": p_text,
                "seed": s_val,
                "timestamp": dest.stat().st_mtime
            }
            _save_tester_saved_metadata(saved_meta)
        except Exception as meta_e:
            print(f"[Creation Save] Aviso ao salvar metadados: {meta_e}")

        return web.json_response({"success": True, "message": "Imagem guardada com sucesso!", "saved_filename": dest.name})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.post("/api/creation/delete_image")
async def api_creation_delete_image(request):
    try:
        data = await request.json() if request.can_read_body else {}
        filename = data.get("filename")
        if not filename:
            return web.json_response({"error": "Filename não fornecido"}, status=400)
        target = CREATION_OUTPUT_DIR / filename
        # Prevenção de Path Traversal
        if not target.resolve().is_relative_to(CREATION_OUTPUT_DIR.resolve()):
            return web.json_response({"error": "Acesso não autorizado"}, status=403)
        if not target.exists():
            return web.json_response({"error": f"Arquivo '{filename}' não encontrado"}, status=404)
        target.unlink()
        return web.json_response({"success": True, "message": "Imagem de criação excluída com sucesso!"})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)

@server.PromptServer.instance.routes.get("/combo_tester")
async def get_combo_tester_view(request):
    studio_html_path = pathlib.Path(__file__).parent / "studio.html"
    if studio_html_path.exists():
        try:
            with open(studio_html_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            resp = web.Response(text=html_content, content_type="text/html")
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
            return resp
        except Exception as e:
            print(f"[ComboTester] Erro ao ler studio.html: {e}")
    html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ComfyUI — Testador de Combinações de LoRAs e Modelos</title>
  <style>
    :root {
      --bg: #0b0c10;
      --card-bg: #151821;
      --card-border: rgba(255, 255, 255, 0.08);
      --accent: #6366f1;
      --accent-hover: #4f46e5;
      --success: #10b981;
      --success-hover: #059669;
      --danger: #ef4444;
      --danger-hover: #dc2626;
      --gold: #f59e0b;
      --text: #f3f4f6;
      --text-muted: #9ca3af;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: rgba(21, 24, 33, 0.85);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--card-border);
      padding: 14px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 100;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: -0.5px;
    }
    .badge-flask {
      background: var(--accent);
      color: #fff;
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 12px;
      text-transform: uppercase;
      font-weight: 800;
    }
    .header-links a {
      color: var(--text-muted);
      text-decoration: none;
      font-size: 13px;
      margin-left: 16px;
      transition: color 0.2s;
    }
    .header-links a:hover { color: #fff; }
    .container {
      max-width: 96vw;
      width: 96%;
      margin: 18px auto;
      padding: 0 12px;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 22px;
      box-shadow: 0 4px 20px rgba(0, 0, 0, 0.25);
    }
    .card-title {
      font-size: 16px;
      font-weight: 600;
      margin-bottom: 14px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid rgba(255, 255, 255, 0.05);
      padding-bottom: 10px;
    }
    .current-combo-grid {
      display: grid;
      grid-template-columns: 320px 1fr;
      gap: 16px;
      margin-bottom: 20px;
    }
    @media (max-width: 900px) {
      .current-combo-grid { grid-template-columns: 1fr; }
    }
    .info-box {
      background: rgba(0,0,0,0.3);
      padding: 14px;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.04);
    }
    .info-label {
      font-size: 11px;
      text-transform: uppercase;
      color: var(--text-muted);
      letter-spacing: 0.5px;
      margin-bottom: 4px;
    }
    .info-val {
      font-size: 14px;
      font-weight: 600;
      color: #fff;
      word-break: break-all;
    }
    .lora-chip-list {
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .lora-chip {
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: rgba(99, 102, 241, 0.12);
      border: 1px solid rgba(99, 102, 241, 0.3);
      border-radius: 6px;
      padding: 8px 12px;
      font-size: 13px;
    }
    .lora-chip-name { font-weight: 500; }
    .lora-chip-weight {
      background: var(--accent);
      color: #fff;
      font-weight: 700;
      padding: 2px 8px;
      border-radius: 4px;
      font-size: 11px;
    }

    /* Seção de Geração de Lote */
    .generate-panel {
      background: rgba(99, 102, 241, 0.08);
      border: 1px solid rgba(99, 102, 241, 0.25);
      border-radius: 10px;
      padding: 16px 20px;
      margin-bottom: 20px;
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .generate-row {
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 14px;
    }
    .generate-left {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 14px;
    }
    .control-group {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .select-custom {
      background: #0f1117;
      border: 1px solid rgba(255, 255, 255, 0.15);
      color: #fff;
      padding: 8px 12px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      outline: none;
      cursor: pointer;
    }
    .btn-generate {
      background: linear-gradient(135deg, #6366f1 0%, #4338ca 100%);
      color: #fff;
      font-size: 14px;
      font-weight: 700;
      padding: 11px 24px;
      border-radius: 8px;
      box-shadow: 0 4px 14px rgba(99, 102, 241, 0.35);
    }
    .btn-generate:hover:not(:disabled) {
      background: linear-gradient(135deg, #4f46e5 0%, #3730a3 100%);
      transform: translateY(-1px);
      box-shadow: 0 6px 20px rgba(99, 102, 241, 0.5);
    }
    .btn-generate:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    .progress-track {
      width: 100%;
      height: 8px;
      background: rgba(0,0,0,0.4);
      border-radius: 4px;
      overflow: hidden;
      margin-top: 6px;
    }
    .progress-fill {
      height: 100%;
      width: 0%;
      background: #10b981;
      transition: width 0.4s ease;
    }
    .progress-text {
      font-size: 12px;
      color: #cbd5e1;
      font-weight: 500;
    }

    /* Ações de Aprovação / Reprovação / Sorteio */
    .action-bar {
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      align-items: center;
      padding-top: 14px;
      border-top: 1px solid rgba(255,255,255,0.06);
    }
    button {
      cursor: pointer;
      font-family: inherit;
      border: none;
      border-radius: 8px;
      padding: 10px 18px;
      font-size: 13px;
      font-weight: 600;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      transition: all 0.2s ease;
    }
    .btn-approve {
      background: var(--success);
      color: #fff;
    }
    .btn-approve:hover { background: var(--success-hover); transform: translateY(-1px); }
    .btn-reject {
      background: var(--danger);
      color: #fff;
    }
    .btn-reject:hover { background: var(--danger-hover); transform: translateY(-1px); }
    .btn-new {
      background: rgba(255,255,255,0.08);
      color: #fff;
      border: 1px solid rgba(255,255,255,0.12);
    }
    .btn-new:hover { background: rgba(255,255,255,0.15); transform: translateY(-1px); }
    .new-test-group {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-left: auto;
    }

    /* Galeria Expandida */
    .gallery-grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
      gap: 18px;
      margin-top: 14px;
    }
    .gallery-card {
      background: #0d0f17;
      border: 1px solid var(--card-border);
      border-radius: 10px;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      transition: border-color 0.2s, transform 0.2s;
    }
    .gallery-card:hover {
      border-color: var(--accent);
      transform: translateY(-2px);
    }
    .gallery-thumb-wrap {
      position: relative;
      aspect-ratio: 9/16;
      background: #000;
      cursor: pointer;
      overflow: hidden;
    }
    .gallery-thumb-wrap.ratio-16-9 {
      aspect-ratio: 16/9;
    }
    .gallery-thumb-wrap.ratio-1-1 {
      aspect-ratio: 1/1;
    }
    .gallery-thumb-wrap img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      transition: transform 0.3s;
    }
    .gallery-thumb-wrap:hover img {
      transform: scale(1.03);
    }
    .gallery-badge {
      position: absolute;
      top: 8px;
      left: 8px;
      background: rgba(0,0,0,0.75);
      padding: 3px 8px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 700;
      color: #e2e8f0;
      pointer-events: none;
    }
    .gallery-saved-badge {
      position: absolute;
      top: 8px;
      right: 8px;
      background: rgba(245, 158, 11, 0.9);
      color: #000;
      font-weight: 700;
      font-size: 11px;
      padding: 2px 7px;
      border-radius: 4px;
      pointer-events: none;
    }
    .gallery-zoom-overlay {
      position: absolute;
      bottom: 8px;
      right: 8px;
      background: rgba(15,23,42,0.8);
      padding: 4px 8px;
      border-radius: 4px;
      font-size: 11px;
      color: #cbd5e1;
      pointer-events: none;
    }
    .gallery-caption {
      padding: 10px 12px;
      display: flex;
      flex-direction: column;
      gap: 6px;
      background: rgba(255,255,255,0.02);
      border-top: 1px solid rgba(255,255,255,0.05);
    }
    .caption-meta {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 11px;
      color: var(--text-muted);
    }
    .caption-seed {
      background: rgba(255,255,255,0.06);
      padding: 1px 6px;
      border-radius: 3px;
      font-family: monospace;
      font-size: 10px;
    }
    .caption-prompt-box {
      font-size: 11px;
      line-height: 1.4;
      color: #94a3b8;
      background: rgba(0,0,0,0.4);
      padding: 6px 8px;
      border-radius: 5px;
      max-height: 52px;
      overflow: hidden;
      display: -webkit-box;
      -webkit-line-clamp: 3;
      -webkit-box-orient: vertical;
      cursor: pointer;
      word-break: break-word;
    }
    .caption-prompt-box:hover {
      color: #e2e8f0;
      background: rgba(99,102,241,0.1);
    }
    .caption-actions {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
      margin-top: 4px;
    }
    .btn-star {
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.1);
      color: #cbd5e1;
      padding: 4px 10px;
      border-radius: 5px;
      font-size: 11px;
      font-weight: 600;
    }
    .btn-star:hover {
      background: rgba(245, 158, 11, 0.2);
      border-color: var(--gold);
      color: #fbbf24;
    }
    .btn-star.saved {
      background: rgba(245, 158, 11, 0.25);
      border-color: var(--gold);
      color: #fbbf24;
    }
    .btn-copy-small {
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.1);
      color: #cbd5e1;
      padding: 4px 8px;
      border-radius: 4px;
      font-size: 11px;
    }
    .btn-copy-small:hover {
      background: var(--accent);
      color: #fff;
    }
    .gallery-empty {
      grid-column: 1 / -1;
      padding: 50px 20px;
      text-align: center;
      color: var(--text-muted);
      font-size: 14px;
      background: rgba(0,0,0,0.2);
      border-radius: 8px;
    }

    /* Modal Zoom Widescreen */
    #image-modal {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.92);
      backdrop-filter: blur(10px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 1000;
      padding: 24px;
    }
    .modal-container {
      display: flex;
      flex-direction: row;
      background: #11141d;
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 12px;
      overflow: hidden;
      max-width: 96vw;
      max-height: 94vh;
      width: 1280px;
      box-shadow: 0 16px 50px rgba(0,0,0,0.8);
      position: relative;
    }
    @media (max-width: 960px) {
      .modal-container {
        flex-direction: column;
        max-height: 90vh;
        overflow-y: auto;
      }
    }
    .modal-img-col {
      flex: 1 1 65%;
      background: #000;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 400px;
    }
    .modal-img-col img {
      max-width: 100%;
      max-height: 90vh;
      object-fit: contain;
    }
    .modal-info-col {
      flex: 1 1 35%;
      padding: 24px;
      display: flex;
      flex-direction: column;
      gap: 14px;
      background: #151821;
      border-left: 1px solid rgba(255,255,255,0.08);
      overflow-y: auto;
    }
    .modal-info-title {
      font-size: 16px;
      font-weight: 700;
      color: #fff;
    }
    .modal-meta-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      font-size: 12px;
      color: var(--text-muted);
    }
    .modal-meta-tag {
      background: rgba(0,0,0,0.4);
      padding: 4px 8px;
      border-radius: 4px;
      border: 1px solid rgba(255,255,255,0.06);
    }
    .modal-prompt-label {
      font-size: 12px;
      text-transform: uppercase;
      font-weight: 700;
      color: #818cf8;
      letter-spacing: 0.5px;
    }
    .modal-prompt-text {
      background: #090a0f;
      border: 1px solid rgba(255,255,255,0.1);
      border-radius: 8px;
      padding: 12px;
      font-size: 12px;
      line-height: 1.5;
      color: #e2e8f0;
      word-break: break-word;
      user-select: text;
      max-height: 300px;
      overflow-y: auto;
    }
    .modal-actions-box {
      margin-top: auto;
      padding-top: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    .modal-close-btn {
      position: absolute;
      top: 12px;
      right: 14px;
      background: rgba(0,0,0,0.6);
      color: #fff;
      font-size: 22px;
      width: 34px;
      height: 34px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      z-index: 10;
      border: 1px solid rgba(255,255,255,0.2);
    }
    .modal-close-btn:hover {
      background: #ef4444;
    }

    /* Presets Salvos e Tabela */
    .presets-table {
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      font-size: 13px;
    }
    .presets-table th {
      text-align: left;
      padding: 10px 12px;
      color: var(--text-muted);
      font-weight: 600;
      border-bottom: 1px solid rgba(255,255,255,0.08);
    }
    .presets-table td {
      padding: 12px;
      border-bottom: 1px solid rgba(255,255,255,0.04);
      vertical-align: middle;
    }
    .badge-approved {
      background: rgba(16, 185, 129, 0.2);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.4);
      padding: 3px 8px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 600;
    }
    .tbl-actions {
      display: flex;
      align-items: center;
      gap: 6px;
    }
    .btn-tbl-action {
      background: rgba(255,255,255,0.06);
      border: 1px solid rgba(255,255,255,0.12);
      color: #cbd5e1;
      padding: 4px 8px;
      border-radius: 5px;
      font-size: 11px;
      font-weight: 600;
    }
    .btn-tbl-rename:hover {
      background: rgba(99,102,241,0.2);
      border-color: var(--accent);
      color: #a5b4fc;
    }
    .btn-tbl-edit:hover {
      background: rgba(16,185,129,0.2);
      border-color: var(--success);
      color: #6ee7b7;
    }
    .btn-tbl-delete:hover {
      background: rgba(239,68,68,0.2);
      border-color: var(--danger);
      color: #fca5a5;
    }

    #toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #1e293b;
      color: #fff;
      padding: 12px 20px;
      border-radius: 8px;
      border: 1px solid rgba(255,255,255,0.1);
      box-shadow: 0 10px 25px rgba(0,0,0,0.5);
      font-size: 13px;
      display: none;
      z-index: 3000;
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <span class="badge-flask">TESTER</span>
      <span>ComfyUI LoRA & Model Combo Evaluator</span>
    </div>
    <div class="header-links">
      <a href="http://localhost:8188" target="_blank">Abrir ComfyUI (8188)</a>
      <a href="/ha_view" target="_blank">Live View HA</a>
    </div>
  </header>

  <div class="container">
    <!-- Card do Teste Atual -->
    <div class="card">
      <div class="card-title">
        <span>Combinação em Avaliação</span>
        <span id="status-badge" class="badge-approved" style="background: rgba(99,102,241,0.2); color:#818cf8; border-color: rgba(99,102,241,0.4);">Avaliando</span>
      </div>

      <div class="current-combo-grid">
        <div class="info-box">
          <div class="info-label">Checkpoint Sorteado</div>
          <div class="info-val" id="val-checkpoint">Carregando...</div>
          <div style="margin-top: 12px;" class="info-label">Identificador do Teste</div>
          <div class="info-val" id="val-date" style="font-size: 12px; font-weight: normal; color: var(--text-muted);">-</div>
        </div>
        <div class="info-box">
          <div class="info-label">LoRAs e Pesos do Set</div>
          <div class="lora-chip-list" id="val-loras">
            <div style="color: var(--text-muted); font-size: 12px;">Nenhum LoRA carregado</div>
          </div>
        </div>
      </div>

      <!-- Seção de Ação de Geração com Formato / Resolução -->
      <div class="generate-panel">
        <div class="generate-row">
          <div class="generate-left">
            <div class="control-group">
              <span style="font-size:13px; font-weight:600;">Formato:</span>
              <select id="aspect-ratio" class="select-custom">
                <option value="random">🎲 Aleatória (Formatos SDXL)</option>
                <option value="9:16" selected>📱 Celular 9:16 (832x1344)</option>
                <option value="16:9">🖥️ Wallpaper 16:9 (1344x768)</option>
                <option value="1:1">🔲 Quadrado 1:1 (1024x1024)</option>
                <option value="3:4">🖼️ Retrato 3:4 (896x1152)</option>
                <option value="4:3">🏞️ Paisagem 4:3 (1152x896)</option>
                <option value="2:3">📸 Foto 2:3 (832x1216)</option>
                <option value="3:2">🌅 Foto 3:2 (1216x832)</option>
                <option value="4:5">📱 Social 4:5 (896x1088)</option>
                <option value="21:9">🎬 Cinema 21:9 (1536x640)</option>
              </select>
            </div>
            <div class="control-group">
              <span style="font-size:13px; font-weight:600;">Imagens:</span>
              <select id="set-count" class="select-custom">
                <option value="5">5 Imagens</option>
                <option value="6" selected>6 Imagens</option>
                <option value="8">8 Imagens</option>
                <option value="10">10 Imagens</option>
              </select>
            </div>
          </div>
          <button class="btn-generate" onclick="generateBatchSet()">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polygon points="5 3 19 12 5 21 5 3"></polygon>
            </svg>
            ▶ Gerar Lote de Teste (Executar no ComfyUI)
          </button>
        </div>
        <div id="generation-progress" style="display: none;">
          <div class="progress-text" id="prog-text">Iniciando geração no ComfyUI...</div>
          <div class="progress-track"><div id="progress-fill" class="progress-fill"></div></div>
        </div>
      </div>

      <!-- Barra de Decisão (Aprovar / Reprovar / Novo Sorteio com Qtd LoRAs) -->
      <div class="action-bar">
        <button class="btn-approve" onclick="openApproveModal()">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
          ✓ Aprovar Combinação (Salvar Preset)
        </button>
        <button class="btn-reject" onclick="openRejectModal()">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          ✗ Reprovar Combinação
        </button>
        <div class="new-test-group">
          <select id="select-qtd-loras" class="select-custom" style="padding: 7px 10px;">
            <option value="2">2 LoRAs</option>
            <option value="3" selected>3 LoRAs (Padrão)</option>
            <option value="4">4 LoRAs</option>
            <option value="5">5 LoRAs</option>
            <option value="random">🎲 Aleatório (2-4)</option>
          </select>
          <button class="btn-new" onclick="generateNewTest()">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
            Sorteador: Novo Teste
          </button>
        </div>
      </div>
    </div>

    <!-- Galeria do Set Atual -->
    <div class="card">
      <div class="card-title">
        <span>Galeria de Avaliação do Set (Clique para ampliar e ver o prompt completo)</span>
        <span style="font-size: 12px; font-weight: normal; color: var(--text-muted);" id="gallery-count">0 imagens</span>
      </div>
      <div class="gallery-grid" id="gallery-container">
        <div class="gallery-empty">Nenhuma imagem gerada neste lote ainda. Clique em "▶ Gerar Lote de Teste" acima para iniciar!</div>
      </div>
    </div>

    <!-- Lista de Presets Aprovados com Ações (Rename, Edit, Remove) -->
    <div class="card">
      <div class="card-title">
        <span>Combinações Aprovadas Disponíveis nos Workflows</span>
        <span class="badge-approved" id="approved-count">Carregando...</span>
      </div>
      <table class="presets-table">
        <thead>
          <tr>
            <th>Nome do Preset</th>
            <th>Modelo</th>
            <th>LoRAs & Pesos</th>
            <th>Status</th>
            <th style="text-align: right;">Ações</th>
          </tr>
        </thead>
        <tbody id="approved-table-body">
          <tr><td colspan="5" style="color: var(--text-muted); text-align: center;">Carregando combinações...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- Modal Zoom Widescreen -->
  <div id="image-modal">
    <div class="modal-close-btn" onclick="closeModal()">&times;</div>
    <div class="modal-container">
      <div class="modal-img-col">
        <img id="modal-img" src="" alt="Imagem Ampliada">
      </div>
      <div class="modal-info-col">
        <div class="modal-info-title" id="modal-title">Detalhes da Imagem #1</div>
        <div class="modal-meta-row">
          <span class="modal-meta-tag" id="modal-meta-filename">Test_00001_.png</span>
          <span class="modal-meta-tag" id="modal-meta-seed">Seed: -</span>
          <span class="modal-meta-tag" id="modal-meta-saved" style="display:none; color:var(--gold); border-color:var(--gold);">⭐ Guardada</span>
        </div>
        <div class="modal-prompt-label">Prompt Positivo Gerado:</div>
        <div class="modal-prompt-text" id="modal-prompt-text">Carregando prompt...</div>
        <div class="modal-actions-box">
          <button class="btn-star" id="btn-modal-star" style="width:100%; justify-content:center; padding:9px 16px;" onclick="toggleSaveCurrentModalImage()">
            ⭐ Guardar Imagem (Manter Segura)
          </button>
          <button class="btn-generate" style="width:100%; justify-content:center;" onclick="copyCurrentModalPrompt()">
            📋 Copiar Prompt Completo
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- Modal de Renomear Preset -->
  <div id="modal-rename-preset" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.85); backdrop-filter:blur(6px); z-index:2000; align-items:center; justify-content:center;">
    <div style="background:#151821; border:1px solid rgba(255,255,255,0.12); border-radius:12px; padding:24px; max-width:480px; width:90%; box-shadow:0 10px 40px rgba(0,0,0,0.6);">
      <h3 style="margin-bottom:12px; font-size:16px; color:#fff;">✏️ Renomear Preset Aprovado</h3>
      <input type="hidden" id="rename-preset-id">
      <label style="font-size:11px; text-transform:uppercase; color:#9ca3af; letter-spacing:0.5px; display:block; margin-bottom:6px;">Novo Nome:</label>
      <input id="rename-preset-input" type="text" style="width:100%; background:#0b0c10; border:1px solid rgba(255,255,255,0.18); color:#fff; padding:10px 12px; border-radius:8px; font-size:13px; margin-bottom:18px; outline:none;">
      <div style="display:flex; justify-content:flex-end; gap:10px;">
        <button style="background:rgba(255,255,255,0.1); color:#cbd5e1; padding:8px 16px; border-radius:6px;" onclick="closeRenameModal()">Cancelar</button>
        <button style="background:#6366f1; color:#fff; padding:8px 18px; border-radius:6px; font-weight:700;" onclick="submitRenamePreset()">Salvar Nome</button>
      </div>
    </div>
  </div>

  <!-- Modal de Excluir Preset -->
  <div id="modal-delete-preset" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.85); backdrop-filter:blur(6px); z-index:2000; align-items:center; justify-content:center;">
    <div style="background:#151821; border:1px solid rgba(255,255,255,0.12); border-radius:12px; padding:24px; max-width:440px; width:90%; box-shadow:0 10px 40px rgba(0,0,0,0.6);">
      <h3 style="margin-bottom:12px; font-size:16px; color:#ef4444;">🗑️ Remover Preset Aprovado</h3>
      <input type="hidden" id="delete-preset-id">
      <p style="font-size:13px; color:#cbd5e1; margin-bottom:18px;">Tem certeza que deseja remover o preset <strong id="delete-preset-name" style="color:#fff;"></strong>? Ele deixará de aparecer na lista dos workflows.</p>
      <div style="display:flex; justify-content:flex-end; gap:10px;">
        <button style="background:rgba(255,255,255,0.1); color:#cbd5e1; padding:8px 16px; border-radius:6px;" onclick="closeDeleteModal()">Cancelar</button>
        <button style="background:#ef4444; color:#fff; padding:8px 18px; border-radius:6px; font-weight:700;" onclick="submitDeletePreset()">Confirmar Exclusão</button>
      </div>
    </div>
  </div>

  <!-- Modal de Editar Preset (Checkpoint & Pesos dos LoRAs) -->
  <div id="modal-edit-preset" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.85); backdrop-filter:blur(6px); z-index:2000; align-items:center; justify-content:center;">
    <div style="background:#151821; border:1px solid rgba(255,255,255,0.12); border-radius:12px; padding:24px; max-width:560px; width:90%; max-height:85vh; overflow-y:auto; box-shadow:0 10px 40px rgba(0,0,0,0.6);">
      <h3 style="margin-bottom:14px; font-size:16px; color:#fff;">⚙️ Editar Preset de Combinação</h3>
      <input type="hidden" id="edit-preset-id">
      
      <div style="margin-bottom:14px;">
        <label style="font-size:11px; text-transform:uppercase; color:#9ca3af; display:block; margin-bottom:4px;">Nome do Preset:</label>
        <input id="edit-preset-name" type="text" style="width:100%; background:#0b0c10; border:1px solid rgba(255,255,255,0.18); color:#fff; padding:8px 12px; border-radius:8px; font-size:13px;">
      </div>

      <div style="margin-bottom:16px;">
        <label style="font-size:11px; text-transform:uppercase; color:#9ca3af; display:block; margin-bottom:4px;">Modelo / Checkpoint:</label>
        <select id="edit-preset-ckpt" class="select-custom" style="width:100%;">
          <option value="illustrious\\arthemyComics_v80.safetensors">Arthemy Comics v8.0</option>
          <option value="illustrious\\illustrijBTTR_v10.safetensors">Illustrij BTTR v1.0</option>
          <option value="illustrious\\jedpointil_v7VAE.safetensors">Jedpoint v7</option>
          <option value="illustrious\\waiIllustriousSDXL_v170.safetensors">Wai SDXL v1.7</option>
        </select>
      </div>

      <div style="margin-bottom:16px;">
        <label style="font-size:11px; text-transform:uppercase; color:#9ca3af; display:block; margin-bottom:6px;">LoRAs e Pesos do Preset:</label>
        <div id="edit-preset-loras-box" style="display:flex; flex-direction:column; gap:8px;">
          <!-- Linhas de LoRA geradas dinamicamente -->
        </div>
      </div>

      <div style="display:flex; justify-content:flex-end; gap:10px;">
        <button style="background:rgba(255,255,255,0.1); color:#cbd5e1; padding:8px 16px; border-radius:6px;" onclick="closeEditModal()">Cancelar</button>
        <button style="background:#10b981; color:#fff; padding:8px 18px; border-radius:6px; font-weight:700;" onclick="submitEditPreset()">Salvar Alterações</button>
      </div>
    </div>
  </div>

  <!-- Modal Customizado de Aprovação -->
  <div id="approve-modal-overlay" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.85); backdrop-filter:blur(6px); z-index:2000; align-items:center; justify-content:center;">
    <div style="background:#151821; border:1px solid rgba(255,255,255,0.12); border-radius:12px; padding:24px; max-width:480px; width:90%; box-shadow:0 10px 40px rgba(0,0,0,0.6);">
      <h3 style="margin-bottom:12px; font-size:16px; color:#fff;">✓ Salvar Preset de Combinação Aprovada</h3>
      <p style="font-size:13px; color:#9ca3af; margin-bottom:14px;">Esta combinação será salva e ficará disponível para todos os outros workflows.</p>
      <label style="font-size:11px; text-transform:uppercase; color:#9ca3af; letter-spacing:0.5px; display:block; margin-bottom:6px;">Nome do Preset:</label>
      <input id="input-preset-name" type="text" style="width:100%; background:#0b0c10; border:1px solid rgba(255,255,255,0.18); color:#fff; padding:10px 12px; border-radius:8px; font-size:13px; margin-bottom:18px; outline:none;" placeholder="Digite um nome...">
      <div style="display:flex; justify-content:flex-end; gap:10px;">
        <button style="background:rgba(255,255,255,0.1); color:#cbd5e1; padding:8px 16px; border-radius:6px;" onclick="closeApproveModal()">Cancelar</button>
        <button style="background:#10b981; color:#fff; padding:8px 18px; border-radius:6px; font-weight:700;" onclick="submitApproveCombo()">Salvar e Aprovar</button>
      </div>
    </div>
  </div>

  <!-- Modal Customizado de Reprovação -->
  <div id="reject-modal-overlay" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.85); backdrop-filter:blur(6px); z-index:2000; align-items:center; justify-content:center;">
    <div style="background:#151821; border:1px solid rgba(255,255,255,0.12); border-radius:12px; padding:24px; max-width:440px; width:90%; box-shadow:0 10px 40px rgba(0,0,0,0.6);">
      <h3 style="margin-bottom:12px; font-size:16px; color:#ef4444;">✗ Reprovar Combinação</h3>
      <p style="font-size:13px; color:#cbd5e1; margin-bottom:18px;">Tem certeza que deseja reprovar esta combinação? Ela será marcada como descartada e o sorteador não a sugerirá novamente.</p>
      <div style="display:flex; justify-content:flex-end; gap:10px;">
        <button style="background:rgba(255,255,255,0.1); color:#cbd5e1; padding:8px 16px; border-radius:6px;" onclick="closeRejectModal()">Cancelar</button>
        <button style="background:#ef4444; color:#fff; padding:8px 18px; border-radius:6px; font-weight:700;" onclick="submitRejectCombo()">Confirmar Reprovação</button>
      </div>
    </div>
  </div>

  <div id="toast">Notificação</div>

  <script>
    let isWatching = false;
    let targetBatch = 6;
    let currentGalleryImages = [];
    let currentSavedImages = [];
    let currentApprovedCombos = [];
    let currentActiveIdx = 0;

    function escapeHtml(text) {
      if (!text) return '';
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }

    function showToast(msg, isSuccess=true) {
      const t = document.getElementById('toast');
      t.textContent = msg;
      t.style.display = 'block';
      t.style.borderColor = isSuccess ? '#10b981' : '#ef4444';
      setTimeout(() => { t.style.display = 'none'; }, 4000);
    }

    function openModal(idx) {
      currentActiveIdx = idx;
      const img = currentGalleryImages[idx];
      if (!img) return;

      document.getElementById('modal-img').src = img.url;
      document.getElementById('modal-title').textContent = `Imagem #${idx + 1}`;
      document.getElementById('modal-meta-filename').textContent = img.filename;
      document.getElementById('modal-meta-seed').textContent = img.seed ? `Seed: ${img.seed}` : 'Seed: Automática';
      document.getElementById('modal-prompt-text').textContent = img.prompt || 'Prompt positivo não disponível nos metadados.';

      const isSaved = currentSavedImages.includes(img.filename);
      const starBadge = document.getElementById('modal-meta-saved');
      starBadge.style.display = isSaved ? 'inline-block' : 'none';

      const btnStar = document.getElementById('btn-modal-star');
      if (isSaved) {
        btnStar.className = 'btn-star saved';
        btnStar.innerHTML = '⭐ Imagem Guardada (Clique para Desmarcar)';
      } else {
        btnStar.className = 'btn-star';
        btnStar.innerHTML = '⭐ Guardar Imagem (Manter Segura)';
      }

      document.getElementById('image-modal').style.display = 'flex';
    }

    function closeModal() {
      document.getElementById('image-modal').style.display = 'none';
    }

    async function toggleSaveImage(filename) {
      const isCurrentlySaved = currentSavedImages.includes(filename);
      const endpoint = isCurrentlySaved ? '/api/combo_tester/unsave_image' : '/api/combo_tester/save_image';
      try {
        const res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename: filename })
        });
        const out = await res.json();
        if (out.success) {
          showToast(out.message || 'Atualizado!', true);
          await loadData();
          if (document.getElementById('image-modal').style.display === 'flex') {
            openModal(currentActiveIdx);
          }
        }
      } catch (e) {
        showToast('Erro ao salvar imagem', false);
      }
    }

    function toggleSaveCurrentModalImage() {
      const img = currentGalleryImages[currentActiveIdx];
      if (img) toggleSaveImage(img.filename);
    }

    function copyPromptText(idx) {
      const img = currentGalleryImages[idx];
      if (!img || !img.prompt) {
        showToast('Nenhum prompt disponível para copiar', false);
        return;
      }
      navigator.clipboard.writeText(img.prompt).then(() => {
        showToast('Prompt copiado para a área de transferência!', true);
      }).catch(() => {
        showToast('Erro ao copiar prompt', false);
      });
    }

    function copyCurrentModalPrompt() {
      copyPromptText(currentActiveIdx);
    }

    function openApproveModal() {
      const input = document.getElementById('input-preset-name');
      const ckpt = document.getElementById('val-checkpoint').textContent || 'Modelo';
      input.value = `${ckpt} + Preset Aprovado`;
      document.getElementById('approve-modal-overlay').style.display = 'flex';
    }

    function closeApproveModal() {
      document.getElementById('approve-modal-overlay').style.display = 'none';
    }

    async function submitApproveCombo() {
      const name = document.getElementById('input-preset-name').value.trim();
      closeApproveModal();
      try {
        const res = await fetch('/api/combo_tester/approve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name })
        });
        const out = await res.json();
        if (out.success) {
          showToast(out.message || 'Preset aprovado com sucesso!', true);
          await loadData();
        } else {
          showToast(out.error || 'Erro ao aprovar', false);
        }
      } catch (e) {
        showToast('Erro de conexão ao aprovar', false);
      }
    }

    function openRejectModal() {
      document.getElementById('reject-modal-overlay').style.display = 'flex';
    }

    function closeRejectModal() {
      document.getElementById('reject-modal-overlay').style.display = 'none';
    }

    async function submitRejectCombo() {
      closeRejectModal();
      try {
        const res = await fetch('/api/combo_tester/reject', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({})
        });
        const out = await res.json();
        if (out.success) {
          showToast(out.message || 'Combinação reprovada.', false);
          await loadData();
        }
      } catch (e) {
        showToast('Erro de conexão ao reprovar', false);
      }
    }

    /* Modais de Preset: Rename, Delete, Edit */
    function openRenameModal(id, currentName) {
      document.getElementById('rename-preset-id').value = id;
      document.getElementById('rename-preset-input').value = currentName;
      document.getElementById('modal-rename-preset').style.display = 'flex';
    }
    function closeRenameModal() {
      document.getElementById('modal-rename-preset').style.display = 'none';
    }
    async function submitRenamePreset() {
      const id = document.getElementById('rename-preset-id').value;
      const newName = document.getElementById('rename-preset-input').value.trim();
      if (!newName) return;
      closeRenameModal();
      try {
        const res = await fetch('/api/combo_tester/preset/rename', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: id, new_name: newName })
        });
        const out = await res.json();
        if (out.success) {
          showToast(out.message || 'Renomeado!', true);
          await loadData();
        } else {
          showToast(out.error || 'Erro ao renomear', false);
        }
      } catch (e) {
        showToast('Erro de conexão', false);
      }
    }

    function openDeleteModal(id, name) {
      document.getElementById('delete-preset-id').value = id;
      document.getElementById('delete-preset-name').textContent = `"${name}"`;
      document.getElementById('modal-delete-preset').style.display = 'flex';
    }
    function closeDeleteModal() {
      document.getElementById('modal-delete-preset').style.display = 'none';
    }
    async function submitDeletePreset() {
      const id = document.getElementById('delete-preset-id').value;
      closeDeleteModal();
      try {
        const res = await fetch('/api/combo_tester/preset/delete', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: id })
        });
        const out = await res.json();
        if (out.success) {
          showToast(out.message || 'Preset removido!', true);
          await loadData();
        } else {
          showToast(out.error || 'Erro ao remover', false);
        }
      } catch (e) {
        showToast('Erro de conexão', false);
      }
    }

    function openEditModal(id) {
      const preset = currentApprovedCombos.find(c => c.id === id);
      if (!preset) return;

      document.getElementById('edit-preset-id').value = preset.id;
      document.getElementById('edit-preset-name').value = preset.name;
      document.getElementById('edit-preset-ckpt').value = preset.checkpoint;

      const lorasBox = document.getElementById('edit-preset-loras-box');
      lorasBox.innerHTML = '';
      (preset.loras || []).forEach((l, idx) => {
        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.alignItems = 'center';
        row.style.gap = '8px';
        const lName = l.lora.split('\\\\').pop().split('/').pop().replace('.safetensors', '');

        row.innerHTML = `
          <span style="font-size:12px; color:#cbd5e1; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${l.lora}">${lName}</span>
          <span style="font-size:11px; color:#9ca3af;">Peso:</span>
          <input type="number" step="0.05" min="-2" max="2" value="${l.strength_model}" data-idx="${idx}" class="edit-lora-weight" style="width:70px; background:#0b0c10; border:1px solid rgba(255,255,255,0.18); color:#fff; padding:4px 6px; border-radius:5px; font-size:12px; text-align:center;">
        `;
        lorasBox.appendChild(row);
      });

      document.getElementById('modal-edit-preset').style.display = 'flex';
    }
    function closeEditModal() {
      document.getElementById('modal-edit-preset').style.display = 'none';
    }
    async function submitEditPreset() {
      const id = document.getElementById('edit-preset-id').value;
      const preset = currentApprovedCombos.find(c => c.id === id);
      if (!preset) return;

      const newName = document.getElementById('edit-preset-name').value.trim();
      const newCkpt = document.getElementById('edit-preset-ckpt').value;
      const weightInputs = document.querySelectorAll('.edit-lora-weight');

      const updatedLoras = (preset.loras || []).map((l, idx) => {
        const inp = Array.from(weightInputs).find(i => parseInt(i.dataset.idx) === idx);
        const w = inp ? parseFloat(inp.value) : l.strength_model;
        return {
          lora: l.lora,
          strength_model: w,
          strength_clip: w
        };
      });

      closeEditModal();
      try {
        const res = await fetch('/api/combo_tester/preset/edit', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id: id, name: newName, checkpoint: newCkpt, loras: updatedLoras })
        });
        const out = await res.json();
        if (out.success) {
          showToast(out.message || 'Preset atualizado!', true);
          await loadData();
        } else {
          showToast(out.error || 'Erro ao editar', false);
        }
      } catch (e) {
        showToast('Erro de conexão', false);
      }
    }

    async function loadData() {
      try {
        const res = await fetch('/api/combo_tester/status?t=' + Date.now());
        const data = await res.json();
        
        currentSavedImages = data.saved_images || [];
        currentApprovedCombos = data.approved_combos || [];

        if (data.current_test) {
          const ct = data.current_test;
          const ckptName = ct.checkpoint.split('\\\\').pop().split('/').pop();
          document.getElementById('val-checkpoint').textContent = ckptName;
          document.getElementById('val-date').textContent = ct.test_id || '-';
          
          const loraBox = document.getElementById('val-loras');
          loraBox.innerHTML = '';
          if (ct.loras && ct.loras.length > 0) {
            ct.loras.forEach(l => {
              const chip = document.createElement('div');
              chip.className = 'lora-chip';
              const name = l.lora.split('\\\\').pop().split('/').pop().replace('.safetensors', '');
              chip.innerHTML = `<span class="lora-chip-name">${name}</span><span class="lora-chip-weight">${l.strength_model}</span>`;
              loraBox.appendChild(chip);
            });
          } else {
            loraBox.innerHTML = '<div style="color:var(--text-muted);font-size:12px;">Nenhum LoRA nesta combinação</div>';
          }

          const badge = document.getElementById('status-badge');
          if (ct.status === 'approved') {
            badge.textContent = 'Aprovado ✓';
            badge.className = 'badge-approved';
            badge.style.background = 'rgba(16,185,129,0.2)';
            badge.style.color = '#34d399';
          } else if (ct.status === 'rejected') {
            badge.textContent = 'Reprovado ✗';
            badge.className = 'badge-approved';
            badge.style.background = 'rgba(239,68,68,0.2)';
            badge.style.color = '#f87171';
          } else {
            badge.textContent = 'Em Avaliação';
            badge.className = 'badge-approved';
            badge.style.background = 'rgba(99,102,241,0.2)';
            badge.style.color = '#818cf8';
          }
        }

        // Galeria com Card e Legenda com Prompt
        const gBox = document.getElementById('gallery-container');
        if (data.images && data.images.length > 0) {
          currentGalleryImages = data.images;
          document.getElementById('gallery-count').textContent = `${data.images.length} imagens geradas (${currentSavedImages.length} guardadas)`;
          gBox.innerHTML = '';
          data.images.forEach((img, idx) => {
            const card = document.createElement('div');
            card.className = 'gallery-card';
            
            const promptPreview = img.prompt ? escapeHtml(img.prompt) : 'Prompt não disponível';
            const seedBadge = img.seed ? `Seed: ${img.seed}` : 'Seed: auto';
            const isSaved = currentSavedImages.includes(img.filename);

            card.innerHTML = `
              <div class="gallery-thumb-wrap" onclick="openModal(${idx})">
                <img src="${img.url}?t=${img.timestamp}" alt="${img.filename}" loading="lazy" onerror="this.onerror=null; setTimeout(() => { this.src = '${img.url}?retry=' + Date.now(); }, 1200);">
                <span class="gallery-badge">#${idx + 1}</span>
                ${isSaved ? '<span class="gallery-saved-badge">⭐ Guardada</span>' : ''}
                <span class="gallery-zoom-overlay">🔍 Zoom</span>
              </div>
              <div class="gallery-caption">
                <div class="caption-meta">
                  <span style="font-weight:600; color:#cbd5e1;">${img.filename}</span>
                  <span class="caption-seed">${seedBadge}</span>
                </div>
                <div class="caption-prompt-box" title="Clique para abrir e ver o prompt completo" onclick="openModal(${idx})">
                  ${promptPreview}
                </div>
                <div class="caption-actions">
                  <button class="btn-star ${isSaved ? 'saved' : ''}" onclick="toggleSaveImage('${img.filename}')">
                    ${isSaved ? '⭐ Guardada' : '☆ Guardar'}
                  </button>
                  <button class="btn-copy-small" onclick="copyPromptText(${idx})">📋 Copiar</button>
                  <button class="btn-copy-small" onclick="openModal(${idx})">🔍 Zoom</button>
                </div>
              </div>
            `;
            gBox.appendChild(card);
          });
        } else {
          currentGalleryImages = [];
          document.getElementById('gallery-count').textContent = '0 imagens';
          gBox.innerHTML = '<div class="gallery-empty">Nenhuma imagem gerada neste lote ainda. Clique em "▶ Gerar Lote de Teste" acima para iniciar!</div>';
        }

        // Tabela de Presets Aprovados com Ações de Rename, Edit e Delete
        const tbody = document.getElementById('approved-table-body');
        tbody.innerHTML = '';
        if (currentApprovedCombos.length > 0) {
          document.getElementById('approved-count').textContent = `${currentApprovedCombos.length} Combinações`;
          currentApprovedCombos.forEach(c => {
            const tr = document.createElement('tr');
            const ckpt = c.checkpoint.split('\\\\').pop().split('/').pop();
            const lorasStr = (c.loras || []).map(l => {
              const ln = l.lora.split('\\\\').pop().split('/').pop().replace('.safetensors', '');
              return `${ln} (${l.strength_model})`;
            }).join(', ');

            tr.innerHTML = `
              <td style="font-weight:600; color:#fff;">${escapeHtml(c.name)}</td>
              <td style="color:var(--text-muted); font-size:12px;">${ckpt}</td>
              <td style="font-size:12px; color:#cbd5e1;">${lorasStr}</td>
              <td><span class="badge-approved">Aprovado</span></td>
              <td style="text-align: right;">
                <div class="tbl-actions" style="justify-content: flex-end;">
                  <button class="btn-tbl-action btn-tbl-rename" title="Renomear este preset" onclick="openRenameModal('${c.id}', '${escapeHtml(c.name)}')">✏️ Renomear</button>
                  <button class="btn-tbl-action btn-tbl-edit" title="Editar pesos dos LoRAs e checkpoint" onclick="openEditModal('${c.id}')">⚙️ Editar</button>
                  <button class="btn-tbl-action btn-tbl-delete" title="Excluir preset dos workflows" onclick="openDeleteModal('${c.id}', '${escapeHtml(c.name)}')">🗑️ Excluir</button>
                </div>
              </td>
            `;
            tbody.appendChild(tr);
          });
        } else {
          document.getElementById('approved-count').textContent = '0 Combinações';
          tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-muted); text-align:center;">Nenhum preset aprovado salvo ainda.</td></tr>';
        }
      } catch (err) {
        console.error(err);
      }
    }

    async function generateBatchSet() {
      const count = parseInt(document.getElementById('set-count').value) || 6;
      const aspectRatio = document.getElementById('aspect-ratio').value || '9:16';
      targetBatch = count;
      const btn = document.querySelector('.btn-generate');
      btn.disabled = true;
      btn.innerHTML = '<span>⏳ Enfileirando lote de imagens...</span>';

      const progressDiv = document.getElementById('generation-progress');
      const progressFill = document.getElementById('progress-fill');
      const progressText = document.getElementById('prog-text');
      progressDiv.style.display = 'block';
      progressFill.style.width = '5%';
      progressText.textContent = `Enfileirando ${count} imagens no formato ${aspectRatio}...`;

      try {
        const res = await fetch('/api/combo_tester/generate_set', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ count: count, clean_previous: true, aspect_ratio: aspectRatio })
        });
        const out = await res.json();
        if (out.success) {
          showToast(`Lote de ${count} imagens iniciado no formato ${aspectRatio}!`, true);
          btn.innerHTML = `<span>⏳ Gerando ${count} imagens (${aspectRatio})...</span>`;
          startWatcher(count);
        } else {
          showToast(out.error || 'Erro ao enfileirar', false);
          btn.disabled = false;
          btn.innerHTML = '<span>▶ Gerar Lote de Teste (Executar no ComfyUI)</span>';
          progressDiv.style.display = 'none';
        }
      } catch (e) {
        showToast('Erro de conexão ao solicitar geração', false);
        btn.disabled = false;
        btn.innerHTML = '<span>▶ Gerar Lote de Teste (Executar no ComfyUI)</span>';
        progressDiv.style.display = 'none';
      }
    }

    function startWatcher(targetCount) {
      if (isWatching) return;
      isWatching = true;
      const btn = document.querySelector('.btn-generate');
      const progressFill = document.getElementById('progress-fill');
      const progressText = document.getElementById('prog-text');

      let pollAttempts = 0;
      const watcher = setInterval(async () => {
        pollAttempts++;
        try {
          const res = await fetch('/api/combo_tester/status?t=' + Date.now());
          const data = await res.json();
          renderImages(data.images || []);

          if (data.is_generating || pollAttempts <= 1) {
            const queueMsg = data.queue_remaining ? ` (${data.queue_remaining} na fila)` : '';
            progressText.textContent = `Processando imagens no ComfyUI${queueMsg}...`;
            progressFill.style.width = '70%';
          } else {
            clearInterval(watcher);
            isWatching = false;
            btn.disabled = false;
            btn.innerHTML = '<span>▶ Gerar Novo Lote</span>';
            progressFill.style.width = '100%';
            progressText.textContent = `✓ Lote concluído! Inspecione as imagens abaixo e aprove ou reprove.`;
            showToast(`Lote concluído! Avalie a combinação agora.`, true);
          }
        } catch (e) {}
      }, 2500);
    }

    async function generateNewTest() {
      const btn = document.querySelector('.btn-new');
      const qtdLoras = document.getElementById('select-qtd-loras').value;
      const origText = btn ? btn.innerHTML : '';
      if (btn) {
        btn.disabled = true;
        btn.innerHTML = '<span>Sorteando...</span>';
      }
      try {
        const res = await fetch('/api/combo_tester/new_test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ qtd_loras: qtdLoras })
        });
        const out = await res.json();
        if (out.success) {
          showToast(out.message || 'Novo teste sorteado!', true);
          await loadData();
        } else {
          showToast(out.error || 'Erro ao sortear', false);
        }
      } catch (e) {
        showToast('Erro de conexão ao sortear', false);
      } finally {
        if (btn) {
          btn.disabled = false;
          btn.innerHTML = origText;
        }
      }
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeModal();
        closeRenameModal();
        closeDeleteModal();
        closeEditModal();
        closeApproveModal();
        closeRejectModal();
      }
    });

    setInterval(loadData, 3000);
    loadData();
  </script>
</body>
</html>
"""
    response = web.Response(text=html, content_type="text/html")
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


NODE_CLASS_MAPPINGS["ApprovedCombosLoader"] = ApprovedCombosLoader
NODE_DISPLAY_NAME_MAPPINGS["ApprovedCombosLoader"] = "Carregador de Combos Aprovados (Presets)"

NODE_CLASS_MAPPINGS["ComboTesterRunner"] = ComboTesterRunner
NODE_DISPLAY_NAME_MAPPINGS["ComboTesterRunner"] = "Runner do Testador de Combos (Modelos & LoRAs)"

try:
    from . import studio_backend
    studio_backend.register_studio_routes(server.PromptServer.instance.routes)
    server.PromptServer.instance.routes.get("/studio")(get_combo_tester_view)
    server.PromptServer.instance.routes.get("/ai_studio")(get_combo_tester_view)
    print("[HA-Endpoint] Studio Backend e rotas de Refinamento/Cartoon/FaceSwap/PixelArt registradas!")
except Exception as e:
    import traceback
    traceback.print_exc()
    print(f"[HA-Endpoint] Erro ao registrar studio_backend: {e}")

print("[HA-Endpoint] ApprovedCombosLoader, ComboTesterRunner e rotas /combo_tester carregados com sucesso!")



