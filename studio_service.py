"""
Studio Max Independent Service (Serviço Web Desacoplado & Distribuído)
Porta padrão: 8180 | ComfyUI Engine: http://127.0.0.1:8188

Pode rodar no mesmo PC ou em um Home Server separado.
Mantém a galeria, zoom, favoritos, presets e Home Assistant (/latest_image)
SEMPRE ATIVOS e responsivos, mesmo com o ComfyUI desligado ou em repouso.
"""

import os
import sys
import json
import asyncio
import pathlib
import shutil
import time
import subprocess
from aiohttp import web, ClientSession, WSMsgType
from PIL import Image

CURRENT_DIR = pathlib.Path(__file__).parent.resolve()

# Configurações de Ambiente (Permite distribuição para Home Server via ENV)
STUDIO_HOST = os.getenv("STUDIO_HOST", "0.0.0.0")
STUDIO_PORT = int(os.getenv("STUDIO_PORT", 8180))
COMFYUI_URL = os.getenv("COMFYUI_URL", "http://127.0.0.1:8188").rstrip("/")

BASE_OUTPUT_DIR = pathlib.Path(os.getenv("COMFYUI_OUTPUT_DIR", r"D:\IA\ComfyUI\output"))
BASE_INPUT_DIR = pathlib.Path(os.getenv("COMFYUI_INPUT_DIR", r"D:\IA\ComfyUI\input"))
COMFY_ROOT = pathlib.Path(os.getenv("COMFYUI_ROOT", r"D:\IA\ComfyUI"))

STUDIO_UPLOAD_DIR = BASE_INPUT_DIR / "studio_uploads"
STUDIO_REFINED_DIR = BASE_OUTPUT_DIR / "studio" / "refined"
STUDIO_CARTOON_DIR = BASE_OUTPUT_DIR / "studio" / "cartoon"
STUDIO_FACESWAP_DIR = BASE_OUTPUT_DIR / "studio" / "faceswap"
STUDIO_PIXELART_DIR = BASE_OUTPUT_DIR / "studio" / "pixelart"
STUDIO_INPAINT_DIR = BASE_OUTPUT_DIR / "studio" / "inpaint"

for d in [STUDIO_UPLOAD_DIR, STUDIO_REFINED_DIR, STUDIO_CARTOON_DIR, STUDIO_FACESWAP_DIR, STUDIO_PIXELART_DIR, STUDIO_INPAINT_DIR]:
    d.mkdir(parents=True, exist_ok=True)

HTML_PATH = CURRENT_DIR / "studio.html"
PRESETS_DIR = CURRENT_DIR / "presets"
PRESETS_DIR.mkdir(parents=True, exist_ok=True)
PIXELART_PRESETS_FILE = PRESETS_DIR / "pixelart_presets.json"


# ==============================================================================
# --- VERIFICADOR DE STATUS DO COMFYUI ---
# ==============================================================================
async def check_comfyui_online():
    """Verifica se o motor ComfyUI está respondendo na URL configurada."""
    try:
        async with ClientSession() as session:
            async with session.get(f"{COMFYUI_URL}/system_stats", timeout=1.5) as resp:
                return resp.status == 200
    except Exception:
        return False


# ==============================================================================
# --- ROTAS PRINCIPAIS DO STUDIO WEB ---
# ==============================================================================
routes = web.RouteTableDef()


@routes.get("/")
@routes.get("/studio")
async def handle_studio_page(request):
    """Serve a página principal do Studio Max com cabeçalhos anti-cache."""
    if not HTML_PATH.exists():
        return web.Response(text="studio.html não encontrado no diretório.", status=404)
    content = HTML_PATH.read_text(encoding="utf-8")
    return web.Response(text=content, content_type="text/html", headers={
        "Cache-Control": "no-cache, no-store, must-revalidate"
    })


# ==============================================================================
# --- ROTAS COMPATIBILIDADE HOME ASSISTANT (/latest_image) ---
# ==============================================================================
@routes.get("/latest_image")
async def handle_ha_latest_image(request):
    """Retorna a imagem mais recente gerada para o card do Home Assistant."""
    try:
        if not BASE_OUTPUT_DIR.exists():
            return web.Response(status=404, text="Output directory not found")
        valid_exts = {".png", ".webp", ".jpg", ".jpeg"}
        images = [f for f in BASE_OUTPUT_DIR.rglob("*") if f.is_file() and f.suffix.lower() in valid_exts]
        if not images:
            return web.Response(status=404, text="No images found yet")
        latest_file = max(images, key=lambda f: f.stat().st_mtime)
        resp = web.FileResponse(latest_file)
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        return resp
    except Exception as e:
        return web.Response(status=500, text=f"Error retrieving latest image: {e}")


@routes.get("/latest_image_info")
async def handle_ha_latest_image_info(request):
    """Retorna metadados em JSON da última imagem para o Home Assistant."""
    try:
        if not BASE_OUTPUT_DIR.exists():
            return web.json_response({"error": "Output directory not found"}, status=404)
        valid_exts = {".png", ".webp", ".jpg", ".jpeg"}
        images = [f for f in BASE_OUTPUT_DIR.rglob("*") if f.is_file() and f.suffix.lower() in valid_exts]
        if not images:
            return web.json_response({"has_image": False, "filename": None})
        latest_file = max(images, key=lambda f: f.stat().st_mtime)
        stat = latest_file.stat()
        rel_path = latest_file.relative_to(BASE_OUTPUT_DIR).as_posix()
        return web.json_response({
            "has_image": True,
            "filename": latest_file.name,
            "relative_path": rel_path,
            "size_bytes": stat.st_size,
            "timestamp": stat.st_mtime
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ==============================================================================
# --- VISUALIZADOR DE IMAGENS (/view) ---
# ==============================================================================
@routes.get("/view")
async def handle_view_image(request):
    """Serve imagens geradas diretamente do disco (mesmo com ComfyUI offline)."""
    filename = request.query.get("filename", "")
    subfolder = request.query.get("subfolder", "")
    img_type = request.query.get("type", "output")

    if not filename:
        return web.Response(status=400, text="Nome do arquivo ausente")

    base = BASE_INPUT_DIR if img_type == "input" else BASE_OUTPUT_DIR
    target = base / subfolder / filename if subfolder else base / filename

    if not target.exists():
        # Busca recursiva no disco de output
        for m in base.rglob(filename):
            if m.is_file():
                target = m
                break

    if target.exists() and target.is_file():
        resp = web.FileResponse(target)
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    return web.Response(status=404, text=f"Imagem não encontrada: {filename}")


@routes.get("/brand_avatar.png")
async def handle_brand_avatar(request):
    """Serve o mascote oficial do Studio para o header e favicon."""
    for p in [BASE_INPUT_DIR / "brand_avatar.png", CURRENT_DIR / "brand_avatar.png", COMFY_ROOT / "input" / "brand_avatar.png"]:
        if p.exists() and p.is_file():
            resp = web.FileResponse(p)
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp
    return web.Response(status=404, text="Avatar não encontrado")


@routes.get("/tester_images/{filename}")
async def handle_tester_images(request):
    """Serve imagens geradas do testador de combinações."""
    filename = request.match_info["filename"]
    target = BASE_OUTPUT_DIR / "tester" / filename
    if not target.exists() or not target.is_file():
        target = BASE_OUTPUT_DIR / "tester_saved" / filename
    if target.exists() and target.is_file():
        resp = web.FileResponse(target)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp
    return web.Response(status=404, text="Imagem não encontrada")


@routes.get("/tester_saved_images/{filename}")
async def handle_tester_saved_images(request):
    """Serve imagens guardadas do testador de combinações."""
    filename = request.match_info["filename"]
    target = BASE_OUTPUT_DIR / "tester_saved" / filename
    if not target.exists() or not target.is_file():
        target = BASE_OUTPUT_DIR / "tester" / filename
    if target.exists() and target.is_file():
        resp = web.FileResponse(target)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp
    return web.Response(status=404, text="Imagem salva não encontrada")


# ==============================================================================
# --- CONTROLE DE CICLO DE VIDA DO COMFYUI (START / STOP / RESTART / STATUS) ---
# ==============================================================================
@routes.get("/api/manager/status")
async def handle_manager_status(request):
    """Retorna o status em tempo real do motor ComfyUI."""
    online = await check_comfyui_online()
    return web.json_response({
        "comfyui_online": online,
        "comfyui_url": COMFYUI_URL,
        "studio_port": STUDIO_PORT,
        "output_dir": str(BASE_OUTPUT_DIR)
    })


@routes.post("/api/manager/start")
async def handle_manager_start(request):
    """Inicia o ComfyUI em segundo plano."""
    if await check_comfyui_online():
        return web.json_response({"success": True, "message": "ComfyUI já está online"})

    iniciar_bat = COMFY_ROOT / "iniciar.bat"
    if iniciar_bat.exists():
        subprocess.Popen(["cmd.exe", "/c", str(iniciar_bat)], cwd=str(COMFY_ROOT), creationflags=subprocess.CREATE_NO_WINDOW)
        return web.json_response({"success": True, "message": "Iniciando ComfyUI..."})
    else:
        return web.json_response({"success": False, "error": "iniciar.bat não encontrado em COMFY_ROOT"}, status=404)


@routes.post("/api/manager/stop")
async def handle_manager_stop(request):
    """Desliga o ComfyUI para liberar 100% da GPU/VRAM."""
    parar_bat = COMFY_ROOT / "parar.bat"
    if parar_bat.exists():
        subprocess.Popen(["cmd.exe", "/c", str(parar_bat)], cwd=str(COMFY_ROOT), creationflags=subprocess.CREATE_NO_WINDOW)
        return web.json_response({"success": True, "message": "ComfyUI encerrado com sucesso"})
    else:
        return web.json_response({"success": False, "error": "parar.bat não encontrado"}, status=404)


@routes.post("/api/manager/restart")
async def handle_manager_restart(request):
    """Reinicia o processo do ComfyUI."""
    parar_bat = COMFY_ROOT / "parar.bat"
    iniciar_bat = COMFY_ROOT / "iniciar.bat"
    if parar_bat.exists() and iniciar_bat.exists():
        subprocess.run(["cmd.exe", "/c", str(parar_bat)], cwd=str(COMFY_ROOT), creationflags=subprocess.CREATE_NO_WINDOW)
        await asyncio.sleep(2)
        subprocess.Popen(["cmd.exe", "/c", str(iniciar_bat)], cwd=str(COMFY_ROOT), creationflags=subprocess.CREATE_NO_WINDOW)
        return web.json_response({"success": True, "message": "Reiniciando ComfyUI..."})
    return web.json_response({"success": False, "error": "Scripts de controle ausentes"}, status=404)


# ==============================================================================
# --- GALERIA AUTÔNOMA DO DISCO (/api/studio/gallery) ---
# ==============================================================================
def listar_arquivos_galeria(diretorio, subpasta=""):
    """Lê diretamente do disco as imagens de cada pasta para o frontend."""
    if not diretorio.exists():
        return []
    valid_exts = {".png", ".webp", ".jpg", ".jpeg"}
    arquivos = [f for f in diretorio.glob("*") if f.is_file() and f.suffix.lower() in valid_exts]
    arquivos.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    return [{
        "filename": f.name,
        "url": f"/view?filename={f.name}&subfolder={subpasta}&type=output",
        "mtime": f.stat().st_mtime
    } for f in arquivos]


@routes.get("/api/studio/gallery")
async def handle_studio_gallery(request):
    """Retorna as imagens de todas as galerias lidas diretamente do sistema de arquivos."""
    try:
        refined = listar_arquivos_galeria(STUDIO_REFINED_DIR, "studio/refined")
        cartoon = listar_arquivos_galeria(STUDIO_CARTOON_DIR, "studio/cartoon")
        faceswap = listar_arquivos_galeria(STUDIO_FACESWAP_DIR, "studio/faceswap")
        pixelart = listar_arquivos_galeria(STUDIO_PIXELART_DIR, "studio/pixelart")
        inpaint = listar_arquivos_galeria(STUDIO_INPAINT_DIR, "studio/inpaint")
        tester_saved = listar_arquivos_galeria(BASE_OUTPUT_DIR / "tester_saved", "tester_saved")
        tester = listar_arquivos_galeria(BASE_OUTPUT_DIR / "tester", "tester")

        return web.json_response({
            "refined": refined[:40],
            "cartoon": cartoon[:40],
            "faceswap": faceswap[:40],
            "pixelart": pixelart[:40],
            "inpaint": inpaint[:40],
            "tester_saved": tester_saved[:100],
            "tester": tester[:60]
        })
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


# ==============================================================================
# --- LEITOR AUTÔNOMO DE PNG INFO (/api/studio/read_png_info) ---
# ==============================================================================
@routes.post("/api/studio/read_png_info")
async def handle_read_png_info(request):
    """Extrai prompt, checkpoint, LoRAs e semente de qualquer PNG no disco."""
    try:
        data = await request.json()
        filename = data.get("filename")
        if not filename:
            return web.json_response({"success": False, "error": "Filename não informado"}, status=400)

        target = None
        for base in [BASE_OUTPUT_DIR, BASE_INPUT_DIR]:
            if (base / filename).exists():
                target = base / filename
                break
            for m in base.rglob(filename):
                if m.is_file():
                    target = m
                    break
            if target:
                break

        if not target or not target.exists():
            return web.json_response({"success": False, "error": "Imagem não encontrada no disco"}, status=404)

        im = Image.open(target)
        prompt_raw = im.info.get("prompt")
        workflow_raw = im.info.get("workflow")
        prompt_data = json.loads(prompt_raw) if prompt_raw else {}

        detected_prompt = ""
        detected_neg = ""
        detected_ckpt = ""
        detected_loras = []

        for nid, n in prompt_data.items():
            ctype = n.get("class_type", "")
            inputs = n.get("inputs", {})
            if "prompt" in ctype.lower() or "wildcard" in ctype.lower() or "reviewer" in ctype.lower():
                for k in ["populated_text", "wildcard_text", "text", "prompt"]:
                    if isinstance(inputs.get(k), str) and len(inputs[k]) > len(detected_prompt):
                        detected_prompt = inputs[k]
            if "loader" in ctype.lower() and "checkpoint" in inputs:
                detected_ckpt = inputs["checkpoint"]
            if "lora" in ctype.lower():
                for lk, lv in inputs.items():
                    if isinstance(lv, dict) and lv.get("on") and lv.get("lora"):
                        detected_loras.append({"lora": lv["lora"], "strength_model": lv.get("strength", 0.8)})

        return web.json_response({
            "success": True,
            "filename": filename,
            "width": im.width,
            "height": im.height,
            "checkpoint": detected_ckpt,
            "prompt": detected_prompt,
            "negative_prompt": detected_neg,
            "loras": detected_loras
        })
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


# ==============================================================================
# --- PRESETS DINÂMICOS & OPÇÕES CUSTOMIZÁVEIS (/api/studio/presets/pixelart) ---
# ==============================================================================
@routes.get("/api/studio/presets/pixelart")
async def handle_get_pixelart_presets(request):
    """Retorna os presets e opções customizáveis de Pixel Art do arquivo JSON."""
    try:
        if not PIXELART_PRESETS_FILE.exists():
            return web.json_response({"success": False, "error": "Arquivo de presets não existe"}, status=404)
        with open(PIXELART_PRESETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return web.json_response({"success": True, "presets": data})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


@routes.post("/api/studio/presets/pixelart")
async def handle_save_pixelart_presets(request):
    """Salva opções customizadas ou editadas no arquivo JSON de presets."""
    try:
        body = await request.json()
        presets_data = body.get("presets")
        if not presets_data:
            return web.json_response({"success": False, "error": "Dados de presets ausentes"}, status=400)
        with open(PIXELART_PRESETS_FILE, "w", encoding="utf-8") as f:
            json.dump(presets_data, f, indent=2, ensure_ascii=False)
        return web.json_response({"success": True, "message": "Presets salvos com sucesso!"})
    except Exception as e:
        return web.json_response({"success": False, "error": str(e)}, status=500)


# ==============================================================================
# --- FALLBACK AUTÔNOMO DE DADOS QUANDO COMFYUI ESTIVER OFFLINE ---
# ==============================================================================
def get_offline_combo_tester_status():
    """Gera resposta autônoma do testador lendo do disco caso o ComfyUI esteja desligado."""
    user_default_dir = COMFY_ROOT / "user" / "default"

    current_test = {}
    for ct_path in [user_default_dir / "current_test_combo.json", user_default_dir / "current_test.json"]:
        if ct_path.exists():
            try:
                with open(ct_path, "r", encoding="utf-8") as f:
                    current_test = json.load(f)
                break
            except Exception:
                pass

    approved_combos = []
    approved_file = user_default_dir / "approved_combos.json"
    if approved_file.exists():
        try:
            with open(approved_file, "r", encoding="utf-8") as f:
                approved_combos = json.load(f).get("approved_combos", [])
        except Exception:
            pass

    rejected_combos = []
    rejected_file = user_default_dir / "rejected_combos.json"
    if rejected_file.exists():
        try:
            with open(rejected_file, "r", encoding="utf-8") as f:
                rejected_combos = json.load(f).get("rejected_combos", [])
        except Exception:
            pass

    saved_metadata = {}
    saved_meta_file = user_default_dir / "tester_saved_metadata.json"
    if saved_meta_file.exists():
        try:
            with open(saved_meta_file, "r", encoding="utf-8") as f:
                saved_metadata = json.load(f)
        except Exception:
            pass

    saved_gallery = []
    tester_saved_dir = BASE_OUTPUT_DIR / "tester_saved"
    if tester_saved_dir.exists():
        valid_exts = {".png", ".webp", ".jpg", ".jpeg"}
        s_imgs = sorted([f for f in tester_saved_dir.glob("*") if f.is_file() and f.suffix.lower() in valid_exts],
                        key=lambda f: f.stat().st_mtime, reverse=True)
        for img in s_imgs:
            im_meta = saved_metadata.get(img.name, {})
            saved_gallery.append({
                "filename": img.name,
                "url": f"/tester_saved_images/{img.name}",
                "size_bytes": img.stat().st_size,
                "timestamp": img.stat().st_mtime,
                "prompt": im_meta.get("prompt", ""),
                "seed": im_meta.get("seed", ""),
                "loras": im_meta.get("loras", []),
                "checkpoint": im_meta.get("checkpoint", ""),
                "combo_name": im_meta.get("combo_name", ""),
                "is_saved": True
            })

    tester_images = []
    tester_dir = BASE_OUTPUT_DIR / "tester"
    if tester_dir.exists():
        valid_exts = {".png", ".webp", ".jpg", ".jpeg"}
        t_imgs = sorted([f for f in tester_dir.glob("*") if f.is_file() and f.suffix.lower() in valid_exts],
                        key=lambda f: f.stat().st_mtime, reverse=True)
        for img in t_imgs[:48]:
            tester_images.append({
                "filename": img.name,
                "url": f"/tester_images/{img.name}",
                "size_bytes": img.stat().st_size,
                "timestamp": img.stat().st_mtime,
                "prompt": "",
                "seed": "",
                "loras": [],
                "checkpoint": current_test.get("checkpoint", ""),
                "combo_name": "",
                "is_saved": False,
                "rounds_age": 0
            })

    return {
        "status": "comfyui_offline",
        "current_test": current_test,
        "approved_combos": approved_combos,
        "rejected_combos": rejected_combos,
        "checkpoints": [],
        "available_loras": [],
        "images": tester_images,
        "saved_images": [img["filename"] for img in saved_gallery],
        "saved_gallery": saved_gallery,
        "is_generating": False,
        "queue_remaining": 0,
        "running_count": 0,
        "pending_count": 0
    }


# ==============================================================================
# --- PROXY BIDIRECIONAL DE WEBSOCKET (/ws) ---
# ==============================================================================
@routes.get("/ws")
async def proxy_comfyui_ws(request):
    """Proxy bidirecional de WebSocket entre o navegador e o motor ComfyUI."""
    ws_client = web.WebSocketResponse()
    await ws_client.prepare(request)

    query_str = request.query_string
    target_ws_url = f"{COMFYUI_URL.replace('http://', 'ws://').replace('https://', 'wss://')}/ws"
    if query_str:
        target_ws_url = f"{target_ws_url}?{query_str}"

    try:
        async with ClientSession() as session:
            async with session.ws_connect(target_ws_url) as ws_server:
                async def client_to_server():
                    async for msg in ws_client:
                        if msg.type == WSMsgType.TEXT:
                            await ws_server.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await ws_server.send_bytes(msg.data)
                        elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                            break

                async def server_to_client():
                    async for msg in ws_server:
                        if msg.type == WSMsgType.TEXT:
                            await ws_client.send_str(msg.data)
                        elif msg.type == WSMsgType.BINARY:
                            await ws_client.send_bytes(msg.data)
                        elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                            break

                await asyncio.gather(client_to_server(), server_to_client())
    except Exception:
        pass
    finally:
        await ws_client.close()

    return ws_client


# ==============================================================================
# --- PROXY REVERSO COMPLETO PARA O COMFYUI (/api/*, /prompt, /queue, etc.) ---
# ==============================================================================
@routes.route("*", "/api/combo_tester/{tail:.*}")
@routes.route("*", "/api/models/{tail:.*}")
@routes.route("*", "/api/studio/upload")
@routes.route("*", "/api/studio/refine")
@routes.route("*", "/api/studio/cartoon")
@routes.route("*", "/api/studio/faceswap")
@routes.route("*", "/api/studio/pixelart")
@routes.route("*", "/api/studio/inpaint")
@routes.route("*", "/api/studio/detect_subject")
@routes.route("*", "/api/studio/cartoon_best_weights")
@routes.route("*", "/api/studio/cartoon_feedback")
@routes.route("*", "/api/studio/delete_image")
@routes.route("*", "/api/studio/active_status")
@routes.route("*", "/prompt")
@routes.route("*", "/queue")
@routes.route("*", "/history")
@routes.route("*", "/history/{tail:.*}")
@routes.route("*", "/system_stats")
@routes.route("*", "/upload/image")
@routes.route("*", "/object_info")
@routes.route("*", "/object_info/{tail:.*}")
@routes.route("*", "/extensions")
@routes.route("*", "/customnode/{tail:.*}")
async def proxy_comfyui_http(request):
    """Repassa requisições para o ComfyUI ou entrega fallback offline seguro."""
    if not await check_comfyui_online():
        if request.path.startswith("/api/combo_tester/status"):
            return web.json_response(get_offline_combo_tester_status())
        return web.json_response({
            "error": "ComfyUI está desligado ou reiniciando.",
            "comfyui_offline": True,
            "message": "Inicie o motor do ComfyUI no botão superior para despachar execuções."
        }, status=503)

    target_url = f"{COMFYUI_URL}{request.path_qs}"
    try:
        body = await request.read()
        headers = {k: v for k, v in request.headers.items() if k.lower() not in ["host", "content-length"]}
        async with ClientSession() as session:
            async with session.request(request.method, target_url, headers=headers, data=body, timeout=180) as resp:
                resp_data = await resp.read()
                return web.Response(body=resp_data, status=resp.status, content_type=resp.content_type)
    except Exception as e:
        if request.path.startswith("/api/combo_tester/status"):
            return web.json_response(get_offline_combo_tester_status())
        return web.json_response({"error": f"Erro de comunicação com o ComfyUI: {e}"}, status=502)


# ==============================================================================
# --- INICIALIZAÇÃO DA APLICAÇÃO ---
# ==============================================================================
def create_studio_app():
    app = web.Application(client_max_size=100 * 1024 * 1024)
    app.add_routes(routes)
    return app


if __name__ == "__main__":
    print("=" * 70)
    print("[INICIALIZACAO] STUDIO MAX - SERVICO WEB DESACOPLADO & DISTRIBUIDO")
    print(f"[HTTP] Interface Web: http://localhost:{STUDIO_PORT}/studio")
    print(f"[TARGET] Motor ComfyUI Alvo: {COMFYUI_URL}")
    print(f"[PATH] Diretorio de Saidas: {BASE_OUTPUT_DIR}")
    print("=" * 70)
    app = create_studio_app()
    web.run_app(app, host=STUDIO_HOST, port=STUDIO_PORT)
