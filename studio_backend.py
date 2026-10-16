import os
import sys
import json
import re
import copy
import time
import random
import shutil
import pathlib
import aiohttp
from PIL import Image
from aiohttp import web

import folder_paths
import server

CURRENT_DIR = pathlib.Path(__file__).parent.resolve()

# Diretórios principais no disco E: (com espelho D:)
BASE_INPUT_DIR = pathlib.Path(folder_paths.get_input_directory())
BASE_OUTPUT_DIR = pathlib.Path(folder_paths.get_output_directory())

STUDIO_UPLOAD_DIR = BASE_INPUT_DIR / "studio_uploads"
STUDIO_REFINED_DIR = BASE_OUTPUT_DIR / "studio" / "refined"
STUDIO_CARTOON_DIR = BASE_OUTPUT_DIR / "studio" / "cartoon"
STUDIO_FACESWAP_DIR = BASE_OUTPUT_DIR / "studio" / "faceswap"
STUDIO_PIXELART_DIR = BASE_OUTPUT_DIR / "studio" / "pixelart"
STUDIO_INPAINT_DIR = BASE_OUTPUT_DIR / "studio" / "inpaint"
BRAND_AVATAR_PATH = BASE_OUTPUT_DIR / "brand_avatar.png"

for d in [STUDIO_UPLOAD_DIR, STUDIO_REFINED_DIR, STUDIO_CARTOON_DIR, STUDIO_FACESWAP_DIR, STUDIO_PIXELART_DIR, STUDIO_INPAINT_DIR]:
    d.mkdir(parents=True, exist_ok=True)


def find_image_anywhere(filename):
    """
    Localiza um arquivo de imagem em diretórios conhecidos de input, output, tester e studio.
    """
    if not filename:
        return None
    basename = os.path.basename(filename)
    candidates = [
        BASE_INPUT_DIR / filename,
        BASE_INPUT_DIR / basename,
        STUDIO_UPLOAD_DIR / basename,
        BASE_OUTPUT_DIR / filename,
        BASE_OUTPUT_DIR / basename,
        BASE_OUTPUT_DIR / "tester" / basename,
        BASE_OUTPUT_DIR / "tester_saved" / basename,
        STUDIO_REFINED_DIR / basename,
        STUDIO_CARTOON_DIR / basename,
        STUDIO_FACESWAP_DIR / basename,
        STUDIO_PIXELART_DIR / basename,
        STUDIO_INPAINT_DIR / basename,
    ]
    for c in candidates:
        if c.exists() and c.is_file():
            return c
    # Busca recursiva de fallback
    try:
        for match in BASE_OUTPUT_DIR.rglob(basename):
            if match.is_file():
                return match
        for match in BASE_INPUT_DIR.rglob(basename):
            if match.is_file():
                return match
    except Exception:
        pass
    return None


def ensure_image_in_input(filename):
    """
    Garante que a imagem esteja acessível dentro de BASE_INPUT_DIR para o LoadImage do ComfyUI.
    Retorna o nome ou caminho relativo a BASE_INPUT_DIR esperado pelo LoadImage.
    """
    src = find_image_anywhere(filename)
    if not src:
        raise FileNotFoundError(f"Imagem não encontrada: {filename}")
    
    # Se já está dentro de BASE_INPUT_DIR, retorna o path relativo
    try:
        rel = src.relative_to(BASE_INPUT_DIR)
        return str(rel).replace("\\", "/")
    except ValueError:
        pass

    # Se estiver fora de BASE_INPUT_DIR, copia para a raiz do input
    target_name = os.path.basename(src.name)
    target_path = BASE_INPUT_DIR / target_name
    if not target_path.exists() or target_path.stat().st_mtime < src.stat().st_mtime:
        shutil.copy2(src, target_path)
    
    return target_name


# ==============================================================================
# --- EXTRATOR DE METADADOS DE IMAGENS (COMFYUI & WEBUI) ---
# ==============================================================================

def extract_image_metadata(file_path):
    """
    Lê uma imagem e extrai metadados completos (Checkpoint, LoRAs, Prompts, Sampler).
    Suporta tanto PNG chunks do ComfyUI quanto do A1111/WebUI/Forge.
    """
    res = {
        "success": False,
        "width": 1024,
        "height": 1024,
        "checkpoint": None,
        "loras": [],
        "prompt": "",
        "negative_prompt": "",
        "steps": 25,
        "cfg": 5.5,
        "sampler_name": "euler",
        "scheduler": "karras",
        "seed": None,
        "denoise": 1.0,
        "source_format": "unknown"
    }

    try:
        with Image.open(file_path) as img:
            res["width"] = img.width
            res["height"] = img.height
            info = img.info or {}

            # --- CASO 1: ComfyUI (prompt JSON) ---
            if "prompt" in info:
                res["source_format"] = "comfyui"
                res["success"] = True
                p_data = json.loads(info["prompt"])

                # Checkpoint
                for nid, nval in p_data.items():
                    inp = nval.get("inputs", {})
                    if "ckpt_name" in inp and not res["checkpoint"]:
                        res["checkpoint"] = inp["ckpt_name"]

                # LoRAs (LoraLoader padrão)
                for nid, nval in p_data.items():
                    ctype = nval.get("class_type", "")
                    inp = nval.get("inputs", {})
                    if "lora_name" in inp and inp["lora_name"]:
                        res["loras"].append({
                            "lora": inp["lora_name"],
                            "strength_model": float(inp.get("strength_model", 1.0)),
                            "strength_clip": float(inp.get("strength_clip", 1.0))
                        })
                    elif ctype == "Power Lora Loader (rgthree)":
                        for k, v in inp.items():
                            if isinstance(v, dict) and v.get("on") and v.get("lora"):
                                res["loras"].append({
                                    "lora": v["lora"],
                                    "strength_model": float(v.get("strength", 1.0)),
                                    "strength_clip": float(v.get("strength", 1.0))
                                })

                # Prompts (Positivo e Negativo)
                # Priorizar PromptReviewer ou ImpactWildcard
                for target_nid in ["89", "11", "13", "18", "20", "10", "12"]:
                    if target_nid in p_data:
                        inp = p_data[target_nid].get("inputs", {})
                        text = inp.get("populated_text") or inp.get("text") or inp.get("value")
                        if text and str(text).strip() and not res["prompt"]:
                            res["prompt"] = str(text).strip()
                            break

                for nid, nval in p_data.items():
                    ctype = nval.get("class_type", "")
                    inp = nval.get("inputs", {})
                    if ctype in ["CLIPTextEncode", "PrimitiveStringMultiline"]:
                        text = inp.get("text") or inp.get("value", "")
                        if text and isinstance(text, str) and text.strip():
                            if "bad" in text.lower() or "ugly" in text.lower() or "lowres" in text.lower() or "noise" in text.lower():
                                if not res["negative_prompt"]:
                                    res["negative_prompt"] = text.strip()
                            else:
                                if not res["prompt"]:
                                    res["prompt"] = text.strip()

                # Sampler info
                for nid, nval in p_data.items():
                    inp = nval.get("inputs", {})
                    if "steps" in inp:
                        res["steps"] = int(inp.get("steps", 25))
                        res["cfg"] = float(inp.get("cfg", 5.5))
                        res["sampler_name"] = str(inp.get("sampler_name", "euler"))
                        res["scheduler"] = str(inp.get("scheduler", "karras"))
                        res["seed"] = inp.get("seed")
                        if "denoise" in inp:
                            res["denoise"] = float(inp.get("denoise", 1.0))
                        break

            # --- CASO 2: A1111 / WebUI / Forge (parameters text) ---
            elif "parameters" in info:
                res["source_format"] = "webui"
                res["success"] = True
                params = info["parameters"]
                lines = params.split("\n")
                if lines:
                    res["prompt"] = lines[0].strip()
                for l in lines[1:]:
                    l_str = l.strip()
                    if l_str.startswith("Negative prompt:"):
                        res["negative_prompt"] = l_str.replace("Negative prompt:", "").strip()
                    if "Steps:" in l_str:
                        # Regex para extrair parâmetros padrão
                        m_steps = re.search(r"Steps:\s*(\d+)", l_str)
                        if m_steps: res["steps"] = int(m_steps.group(1))
                        m_cfg = re.search(r"CFG scale:\s*([\d\.]+)", l_str)
                        if m_cfg: res["cfg"] = float(m_cfg.group(1))
                        m_seed = re.search(r"Seed:\s*(\d+)", l_str)
                        if m_seed: res["seed"] = int(m_seed.group(1))
                        m_model = re.search(r"Model:\s*([^,]+)", l_str)
                        if m_model: res["checkpoint"] = m_model.group(1).strip()
                        m_sampler = re.search(r"Sampler:\s*([^,]+)", l_str)
                        if m_sampler: res["sampler_name"] = m_sampler.group(1).strip().lower()

                # Extrai tags <lora:name:strength> do prompt
                lora_matches = re.findall(r"<lora:([^:]+):?([^>]*)>", res["prompt"])
                for l_name, l_str in lora_matches:
                    st = float(l_str) if l_str else 0.8
                    res["loras"].append({
                        "lora": l_name,
                        "strength_model": st,
                        "strength_clip": st
                    })

    except Exception as e:
        print(f"[StudioMeta] Erro ao ler metadados de {file_path}: {e}")

    # Fallbacks inteligentes para garantir que a UI nunca quebre
    if not res["checkpoint"]:
        # Tenta pegar Wai ou Jedpoint
        res["checkpoint"] = r"illustrious\waiIllustriousSDXL_v170.safetensors"

    return res


# ==============================================================================
# --- CONSTRUTORES DE GRAFOS DE EXECUÇÃO (WORKFLOWS API) ---
# ==============================================================================

def build_refine_workflow(image_rel_path, ckpt_name, loras, prompt_pos, prompt_neg,
                          upscale_factor=1.5, denoise=0.35, run_facedetailer=True,
                          run_handdetailer=True):
    """
    Constrói grafo para Tratamento e Refinamento com Upscale, FaceDetailer e HandDetailer.
    Aplica DPMPP_2M + Karras e detalhamento contextual proporcional à intensidade escolhida.
    """
    nodes = {}
    denoise_val = float(denoise)
    
    # 1. Carregar imagem base
    nodes["1"] = {
        "class_type": "LoadImage",
        "inputs": {"image": image_rel_path}
    }
    current_img = ["1", 0]

    # 2. Upscale opcional
    if upscale_factor > 1.01:
        nodes["2"] = {
            "class_type": "ImageScaleBy",
            "inputs": {
                "image": current_img,
                "upscale_method": "lanczos",
                "scale_by": float(upscale_factor)
            }
        }
        current_img = ["2", 0]

    # 3. Checkpoint Loader
    nodes["3"] = {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": ckpt_name}
    }
    curr_model = ["3", 0]
    curr_clip = ["3", 1]
    curr_vae = ["3", 2]

    # LoRAs encadeados
    nid_cnt = 20
    for l in (loras or []):
        if not l.get("lora"):
            continue
        nid_cnt += 1
        lnid = str(nid_cnt)
        nodes[lnid] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": curr_model,
                "clip": curr_clip,
                "lora_name": l["lora"],
                "strength_model": float(l.get("strength_model", 0.8)),
                "strength_clip": float(l.get("strength_clip", 0.8))
            }
        }
        curr_model = [lnid, 0]
        curr_clip = [lnid, 1]

    # Prompts Positivos Dinâmicos com Enriquecimento de Detalhe por Modo
    if denoise_val >= 0.48:
        # Modo 3: Remasterização Criativa
        detail_boost = "masterpiece, best quality, ultra highres, exquisite details, sharp focus, cinematic rim lighting, volumetric shadows, rich depth of field"
    elif denoise_val >= 0.35:
        # Modo 2: Enriquecido & Texturizado
        detail_boost = "masterpiece, best quality, sharp focus, intricate micro-details, detailed eyes, detailed hair strands, soft natural skin texture, clean lineart"
    else:
        # Modo 1: Fiel & Nítido
        detail_boost = "masterpiece, best quality, pristine sharp lineart, high resolution, clean focus, artifact-free, crisp edges"

    final_pos = f"{prompt_pos.strip()}, {detail_boost}" if prompt_pos and prompt_pos.strip() else detail_boost
    final_neg = f"{prompt_neg.strip()}, blurry, lowres, noise, bad anatomy, deformed eyes, artifacts" if prompt_neg and prompt_neg.strip() else "blurry, lowres, noise, bad anatomy, deformed eyes, artifacts, jpeg artifacts"

    # Bloqueio de câmeras, velas, peras e pernas humanas para monstros sem pernas
    extra_negs = ", camera, tripod, handheld_camera, camera_lens, candles, candle, candlestick, pear, pears, fruit"
    if any(m in final_pos.lower() for m in ["centaur", "mermaid", "lamia", "arachne", "scylla", "snake_lower_body", "fish_tail", "horse_lower_body", "spider_lower_body", "tentacles_lower_body"]):
        extra_negs += ", ((human_legs, human_feet, feet, toes, human_knees, two_legs, bipedal, standing_on_human_legs, extra_legs:1.5))"
    final_neg += extra_negs

    nodes["4"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": final_pos,
            "clip": curr_clip
        }
    }
    nodes["5"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": final_neg,
            "clip": curr_clip
        }
    }

    # VAE Encode Tiled (evita hipErrorInvalidImage e estouro de VRAM em resoluções altas)
    nodes["6"] = {
        "class_type": "VAEEncodeTiled",
        "inputs": {
            "pixels": current_img,
            "vae": curr_vae,
            "tile_size": 512,
            "overlap": 64,
            "temporal_size": 64,
            "temporal_overlap": 8
        }
    }

    # KSampler para refinamento latente (euler + karras é 100% estável no ROCm)
    nodes["7"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": curr_model,
            "positive": ["4", 0],
            "negative": ["5", 0],
            "latent_image": ["6", 0],
            "seed": random.randint(1, 999999999999999),
            "steps": 28,
            "cfg": 5.5,
            "sampler_name": "euler",
            "scheduler": "karras",
            "denoise": denoise_val
        }
    }

    # VAE Decode Tiled
    nodes["8"] = {
        "class_type": "VAEDecodeTiled",
        "inputs": {
            "samples": ["7", 0],
            "vae": curr_vae,
            "tile_size": 512,
            "overlap": 64,
            "temporal_size": 64,
            "temporal_overlap": 8
        }
    }
    final_img = ["8", 0]

    # FaceDetailer Dedicado (com prompt específico para face e denoise proporcional)
    if run_facedetailer:
        face_denoise = round(min(0.42, max(0.20, denoise_val * 0.75)), 2)
        nodes["9"] = {
            "class_type": "UltralyticsDetectorProvider",
            "inputs": {"model_name": "bbox/face_yolov8m.pt"}
        }
        nodes["14"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "masterpiece, high quality face, intricate expressive eyes, detailed iris reflection, delicate eyelashes, natural skin texture, detailed lips, sharp focus",
                "clip": curr_clip
            }
        }
        nodes["10"] = {
            "class_type": "FaceDetailer",
            "inputs": {
                "image": final_img,
                "model": curr_model,
                "clip": curr_clip,
                "vae": curr_vae,
                "positive": ["14", 0],
                "negative": ["5", 0],
                "bbox_detector": ["9", 0],
                "guide_size": 512,
                "guide_size_for": True,
                "max_size": 1024,
                "seed": random.randint(1, 999999999999999),
                "steps": 22,
                "cfg": 5.0,
                "sampler_name": "euler",
                "scheduler": "karras",
                "denoise": face_denoise,
                "feather": 5,
                "noise_mask": True,
                "force_inpaint": True,
                "bbox_threshold": 0.5,
                "bbox_dilation": 10,
                "bbox_crop_factor": 3,
                "sam_detection_hint": "center-1",
                "sam_dilation": 0,
                "sam_threshold": 0.93,
                "sam_bbox_expansion": 0,
                "sam_mask_hint_threshold": 0.7,
                "sam_mask_hint_use_negative": "False",
                "drop_size": 10,
                "wildcard": "",
                "cycle": 1,
                "inpaint_model": False,
                "noise_mask_feather": 20,
                "tiled_encode": True,
                "tiled_decode": True
            }
        }
        final_img = ["10", 0]

    # HandDetailer Dedicado (Mãos & Dedos Perfeitos)
    if run_handdetailer:
        hand_denoise = round(min(0.38, max(0.18, denoise_val * 0.65)), 2)
        nodes["11"] = {
            "class_type": "UltralyticsDetectorProvider",
            "inputs": {"model_name": "bbox/hand_yolov8s.pt"}
        }
        nodes["12"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "detailed hands, perfect fingers, delicate fingernails, proper hand anatomy, sharp clean focus",
                "clip": curr_clip
            }
        }
        nodes["13"] = {
            "class_type": "FaceDetailer",
            "inputs": {
                "image": final_img,
                "model": curr_model,
                "clip": curr_clip,
                "vae": curr_vae,
                "positive": ["12", 0],
                "negative": ["5", 0],
                "bbox_detector": ["11", 0],
                "guide_size": 512,
                "guide_size_for": True,
                "max_size": 1024,
                "seed": random.randint(1, 999999999999999),
                "steps": 20,
                "cfg": 5.0,
                "sampler_name": "euler",
                "scheduler": "karras",
                "denoise": hand_denoise,
                "feather": 5,
                "noise_mask": True,
                "force_inpaint": True,
                "bbox_threshold": 0.35,
                "bbox_dilation": 12,
                "bbox_crop_factor": 2.5,
                "sam_detection_hint": "center-1",
                "sam_dilation": 0,
                "sam_threshold": 0.93,
                "sam_bbox_expansion": 0,
                "sam_mask_hint_threshold": 0.7,
                "sam_mask_hint_use_negative": "False",
                "drop_size": 10,
                "wildcard": "",
                "cycle": 1,
                "inpaint_model": False,
                "noise_mask_feather": 20,
                "tiled_encode": True,
                "tiled_decode": True
            }
        }
        final_img = ["13", 0]

    # Salvar Imagem Final
    nodes["99"] = {
        "class_type": "SaveImage",
        "inputs": {"images": final_img, "filename_prefix": "Studio_Refined"}
    }
    return nodes


CARTOON_STYLES = {
    "disney": {
        "name": "Disney / 3D Animation",
        "lora": r"illustrious\Disney_Animation_v5-V7.safetensors",
        "trigger": "DISNEY_ANIMATION, disney animation style, 3d animated movie character, expressive eyes, smooth facial shading, pixar render style, masterpiece, best quality",
        "default_strength": 0.90
    },
    "carto4on": {
        "name": "Carto4on (Midjourney 2D Cel-Shaded)",
        "lora": r"illustrious\New_cartoon_midjourney(Carto4on).safetensors",
        "trigger": "carto4on, cartoon style, vibrant colors, clean lineart, 2d illustration, comic art, detailed eyes, expressive face, smooth cel shading, masterpiece, best quality",
        "default_strength": 0.85
    },
    "3d_stylized": {
        "name": "3D Stylized Moderno",
        "lora": r"illustrious\3D_Stylized_Style_v2.safetensors",
        "trigger": "3d stylized, 3d style, stylized character, clean smooth shading, modern cgi animation, masterpiece, best quality",
        "default_strength": 0.85
    },
    "comics": {
        "name": "Comics & Graphic Novel",
        "lora": r"illustrious\Comics_gff_style-000008(COMIKS FGG).safetensors",
        "trigger": "comiks, fgg, comic book art, vibrant ink, graphic novel illustration, stylized bold lineart, masterpiece, best quality",
        "default_strength": 0.80
    },
    "flatline": {
        "name": "Flatline / Vector Niji",
        "lora": r"illustrious\flatline_v2_-_Illus_x_Niji.safetensors",
        "trigger": "flatline, flat vector illustration, clean lines, minimalist anime style, masterpiece, best quality",
        "default_strength": 0.85
    },
    "fantasia": {
        "name": "Fantasia / Livro Encantado",
        "lora": r"illustrious\fantasiaStyle_illustrious_byJaneB.safetensors",
        "trigger": "fantasia style, fantasia, fairytale book illustration, enchanting colors, painterly cartoon, masterpiece, best quality",
        "default_strength": 0.85
    },
    "kells": {
        "name": "Secret of Kells (Celta Estilizado)",
        "lora": r"illustrious\SecretOfKells-ArtStyle.safetensors",
        "trigger": "k3lls-style, toon (style), stylized celtic animation, artistic geometry, ornate ornamental cartoon, masterpiece, best quality",
        "default_strength": 0.90
    },
    "sarafaber": {
        "name": "Sara Faber (Cute Toon)",
        "lora": r"illustrious\SaraFaber-ArtStyle.safetensors",
        "trigger": "sf4b3r-style, cute modern cartoon illustration, expressive warm character art, masterpiece, best quality",
        "default_strength": 0.85
    },
    "retrocom": {
        "name": "Retro Sci-Fi Comic",
        "lora": r"illustrious\Retrocom1.safetensors",
        "trigger": "retro, science fiction, vintage 80s animated movie style, retro anime comic, masterpiece, best quality",
        "default_strength": 0.80
    }
}


def build_cartoon_workflow(image_rel_path, ckpt_name, custom_tags="", style_strength=0.48, variation_index=0,
                           cartoon_lora_strength=0.85, booster_lora_strength=0.40, face_denoise=0.25,
                           cartoon_style="disney", cartoon_lora_name=None):
    """
    Constrói grafo para Cartoonização / Estilização Anime baseado no fluxo comprovado com múltiplos estilos de LoRAs.
    Permite calibração completa dos pesos dos LoRAs e denoises.
    """
    nodes = {}

    style_cfg = CARTOON_STYLES.get(cartoon_style, CARTOON_STYLES["disney"])
    chosen_lora = cartoon_lora_name if cartoon_lora_name else style_cfg["lora"]
    base_pos = style_cfg["trigger"] if not cartoon_lora_name or cartoon_style != "custom" else "cartoon style, masterpiece, best quality"

    # 1. Entrada de Imagem
    nodes["1"] = {
        "class_type": "LoadImage",
        "inputs": {"image": image_rel_path}
    }

    # 2. Escala proporcional SDXL
    nodes["2"] = {
        "class_type": "ImageScaleProportionalSDXL",
        "inputs": {
            "image": ["1", 0],
            "target_longer_side": 1024,
            "upscale_method": "lanczos"
        }
    }

    # 3. Checkpoint Anime / Illustrious
    nodes["3"] = {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": ckpt_name}
    }

    # 4. LoRA 1: Cartoon Selecionado (Disney Animation, Carto4on, 3D Stylized, etc)
    nodes["4"] = {
        "class_type": "LoraLoader",
        "inputs": {
            "model": ["3", 0],
            "clip": ["3", 1],
            "lora_name": chosen_lora,
            "strength_model": float(cartoon_lora_strength),
            "strength_clip": float(cartoon_lora_strength)
        }
    }

    # 5. LoRA 2: Smooth Booster (Paramétrico)
    nodes["5"] = {
        "class_type": "LoraLoader",
        "inputs": {
            "model": ["4", 0],
            "clip": ["4", 1],
            "lora_name": r"illustrious\Smooth_Booster_v5.safetensors",
            "strength_model": float(booster_lora_strength),
            "strength_clip": float(booster_lora_strength)
        }
    }

    # 6. Prompts Positivos
    if custom_tags and custom_tags.strip():
        full_pos = f"{base_pos}, {custom_tags.strip()}"
    else:
        full_pos = f"{base_pos}, 1person, expressive eyes, clear details"

    base_neg = "photorealistic, photo, 3d, realistic skin texture, realistic pores, skin blemish, noise, bad anatomy, bad hands, mutated fingers, deformed, blurry, lowres, watermark, camera, tripod, handheld_camera, camera_lens, candles, candle, candlestick, pear, pears, fruit"
    if any(m in full_pos.lower() for m in ["centaur", "mermaid", "lamia", "arachne", "scylla", "snake_lower_body", "fish_tail", "horse_lower_body", "spider_lower_body", "tentacles_lower_body"]):
        base_neg += ", ((human_legs, human_feet, feet, toes, human_knees, two_legs, bipedal, standing_on_human_legs, extra_legs:1.5))"

    nodes["6"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": full_pos, "clip": ["5", 1]}
    }
    nodes["7"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": base_neg, "clip": ["5", 1]}
    }

    # 8. VAE Encode
    nodes["8"] = {
        "class_type": "VAEEncode",
        "inputs": {"pixels": ["2", 0], "vae": ["3", 2]}
    }

    # Variação sutil de denoise para cada opção do lote (ex: -0.015, 0.0, +0.015)
    step_delta = (variation_index - 1.5) * 0.015
    eff_denoise = round(max(0.30, min(0.70, float(style_strength) + step_delta)), 2)

    # 9. KSampler Img2Img Estilização
    nodes["9"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": ["5", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["8", 0],
            "seed": random.randint(1, 999999999999999),
            "steps": 24,
            "cfg": 5.5,
            "sampler_name": "euler",
            "scheduler": "karras",
            "denoise": eff_denoise
        }
    }

    # 10. VAE Decode
    nodes["10"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["9", 0], "vae": ["3", 2]}
    }

    # 11. FaceDetailer Anime
    nodes["11"] = {
        "class_type": "UltralyticsDetectorProvider",
        "inputs": {"model_name": "bbox/face_yolov8m.pt"}
    }
    face_subject = f", {custom_tags.strip()}" if custom_tags and custom_tags.strip() else ""
    nodes["12"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": f"carto4on, beautiful cartoon face, detailed cartoon eyes, expressive smile, clean lineart{face_subject}",
            "clip": ["5", 1]
        }
    }
    nodes["13"] = {
        "class_type": "FaceDetailer",
        "inputs": {
            "image": ["10", 0],
            "model": ["5", 0],
            "clip": ["5", 1],
            "vae": ["3", 2],
            "positive": ["12", 0],
            "negative": ["7", 0],
            "bbox_detector": ["11", 0],
            "guide_size": 512,
            "guide_size_for": True,
            "max_size": 1024,
            "seed": random.randint(1, 999999999999999),
            "steps": 20,
            "cfg": 5.0,
            "sampler_name": "euler",
            "scheduler": "karras",
            "denoise": float(face_denoise),
            "feather": 5,
            "noise_mask": True,
            "force_inpaint": True,
            "bbox_threshold": 0.5,
            "bbox_dilation": 10,
            "bbox_crop_factor": 3,
            "sam_detection_hint": "center-1",
            "sam_dilation": 0,
            "sam_threshold": 0.93,
            "sam_bbox_expansion": 0,
            "sam_mask_hint_threshold": 0.7,
            "sam_mask_hint_use_negative": "False",
            "drop_size": 10,
            "wildcard": "",
            "cycle": 1,
            "inpaint_model": False,
            "noise_mask_feather": 20,
            "tiled_encode": False,
            "tiled_decode": False
        }
    }

    # 14. Salvar Imagem
    nodes["99"] = {
        "class_type": "SaveImage",
        "inputs": {"images": ["13", 0], "filename_prefix": "Cartoon_Anime"}
    }
    return nodes


def build_faceswap_workflow(source_rel_path, target_rel_path, codeformer_weight=0.85,
                            face_restore_visibility=0.60, face_restore_model="codeformer-v0.1.0.pth",
                            run_texture_detailer=False):
    """
    Constrói grafo para FaceSwap usando ReActor + CodeFormer otimizado para alta semelhança.
    """
    nodes = {}

    # 1. Rosto Fonte
    nodes["1"] = {
        "class_type": "LoadImage",
        "inputs": {"image": source_rel_path}
    }

    # 2. Imagem Alvo
    nodes["2"] = {
        "class_type": "LoadImage",
        "inputs": {"image": target_rel_path}
    }

    # 3. ReActor Face Swap com parâmetros reforçados para fidelidade máxima
    model_restore = str(face_restore_model) if face_restore_model else "codeformer-v0.1.0.pth"
    visibility = float(face_restore_visibility) if model_restore != "none" else 0.0

    nodes["3"] = {
        "class_type": "ReActorFaceSwap",
        "inputs": {
            "input_image": ["2", 0],
            "source_image": ["1", 0],
            "enabled": True,
            "swap_model": "inswapper_128.onnx",
            "facedetection": "retinaface_resnet50",
            "face_restore_model": model_restore,
            "face_restore_visibility": visibility,
            "codeformer_weight": float(codeformer_weight),
            "detect_gender_input": "no",
            "detect_gender_source": "no",
            "input_faces_index": "0",
            "source_faces_index": "0",
            "console_log_level": 1
        }
    }
    final_img = ["3", 0]

    # 4. Texturização ultra-realista opcional (desligada por padrão para não deformar fotos reais)
    if run_texture_detailer:
        nodes["4"] = {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": r"illustrious\waiIllustriousSDXL_v170.safetensors"}
        }
        nodes["5"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "detailed realistic skin texture, natural skin pores, high fidelity, 8k, photorealistic face, sharp focus, natural lighting, expressive eyes",
                "clip": ["4", 1]
            }
        }
        nodes["6"] = {
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": "plastic skin, fake, oversmoothed, doll, mannequin, blurry, bad anatomy, deformed eyes, noise, artifacts, 3d render, cartoon",
                "clip": ["4", 1]
            }
        }
        nodes["7"] = {
            "class_type": "UltralyticsDetectorProvider",
            "inputs": {"model_name": "bbox/face_yolov8m.pt"}
        }
        nodes["8"] = {
            "class_type": "FaceDetailer",
            "inputs": {
                "image": final_img,
                "model": ["4", 0],
                "clip": ["4", 1],
                "vae": ["4", 2],
                "positive": ["5", 0],
                "negative": ["6", 0],
                "bbox_detector": ["7", 0],
                "guide_size": 512,
                "guide_size_for": True,
                "max_size": 1024,
                "seed": random.randint(1, 999999999999999),
                "steps": 20,
                "cfg": 4.5,
                "sampler_name": "euler",
                "scheduler": "karras",
                "denoise": 0.15,
                "feather": 5,
                "noise_mask": True,
                "force_inpaint": True,
                "bbox_threshold": 0.5,
                "bbox_dilation": 10,
                "bbox_crop_factor": 3,
                "sam_detection_hint": "center-1",
                "sam_dilation": 0,
                "sam_threshold": 0.93,
                "sam_bbox_expansion": 0,
                "sam_mask_hint_threshold": 0.7,
                "sam_mask_hint_use_negative": "False",
                "drop_size": 10,
                "wildcard": "",
                "cycle": 1,
                "inpaint_model": False,
                "noise_mask_feather": 20,
                "tiled_encode": False,
                "tiled_decode": False
            }
        }
        final_img = ["8", 0]

    # Salvar Imagem
    nodes["99"] = {
        "class_type": "SaveImage",
        "inputs": {"images": final_img, "filename_prefix": "Faceswap"}
    }
    return nodes


def resolve_dynamic_wildcards(text):
    """
    Resolve sintaxe de sorteio dinâmico {opcao1|opcao2|opcao3} recursivamente.
    Permite sorteio variado e único entre cada imagem de um mesmo lote.
    """
    if not text:
        return ""
    pattern = re.compile(r"\{([^{}]+)\}")
    cur = str(text)
    for _ in range(5):
        if not pattern.search(cur):
            break
        cur = pattern.sub(lambda m: random.choice([opt.strip() for opt in m.group(1).split("|") if opt.strip()]), cur)
    return cur


def build_pixelart_workflow(prompt_pos, prompt_neg, ckpt_name, resolution=1024,
                            use_dungeon_squad=False, dungeon_squad_strength=0.85,
                            remove_bg=False, is_nsfw=False):
    """
    Constrói grafo para criação de Ícones e Pixel Art com suporte a Dungeon Squad, Remoção de Fundo e NSFW.
    """
    nodes = {}

    if is_nsfw:
        if "nsfw" not in prompt_pos.lower():
            prompt_pos = f"nsfw, explicit, uncensored, spicy pixel art, {prompt_pos}"
        if not prompt_neg or prompt_neg == "blurry, photorealistic, 3d, realistic":
            prompt_neg = "blurry, photorealistic, 3d, realistic, smooth plastic, render, bad anatomy, deformed hands, mutated fingers"

    extra_pixel_negs = ", camera, tripod, handheld_camera, camera_lens, candles, candle, candlestick, pear, pears, fruit"
    if any(m in prompt_pos.lower() for m in ["centaur", "mermaid", "lamia", "arachne", "scylla", "snake_lower_body", "fish_tail", "horse_lower_body", "spider_lower_body", "tentacles_lower_body"]):
        extra_pixel_negs += ", ((human_legs, human_feet, feet, toes, human_knees, two_legs, bipedal, standing_on_human_legs, extra_legs:1.5))"
    prompt_neg = f"{prompt_neg}{extra_pixel_negs}" if prompt_neg else extra_pixel_negs.strip(", ")

    # 1. Checkpoint
    nodes["1"] = {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": ckpt_name}
    }
    curr_model = ["1", 0]
    curr_clip = ["1", 1]
    curr_vae = ["1", 2]

    # LoRA Dungeon Squad opcional (Sprites clássicos / RPG retro)
    if use_dungeon_squad:
        nodes["10"] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": curr_model,
                "clip": curr_clip,
                "lora_name": r"illustrious\Dungeon_Squad_IllustriousV5.safetensors",
                "strength_model": float(dungeon_squad_strength),
                "strength_clip": float(dungeon_squad_strength)
            }
        }
        curr_model = ["10", 0]
        curr_clip = ["10", 1]

    # 2. Empty Latent (1:1 Quadrado para ícones)
    nodes["2"] = {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": int(resolution),
            "height": int(resolution),
            "batch_size": 1
        }
    }

    # 3. Prompts
    nodes["3"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": prompt_pos, "clip": curr_clip}
    }
    nodes["4"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": prompt_neg, "clip": curr_clip}
    }

    # 4. KSampler
    nodes["5"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": curr_model,
            "positive": ["3", 0],
            "negative": ["4", 0],
            "latent_image": ["2", 0],
            "seed": random.randint(1, 999999999999999),
            "steps": 26,
            "cfg": 6.5,
            "sampler_name": "euler",
            "scheduler": "karras",
            "denoise": 1.0
        }
    }

    # 5. VAE Decode
    nodes["6"] = {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["5", 0], "vae": curr_vae}
    }
    final_img = ["6", 0]

    # 6. Remoção automática de fundo com RemBG (WAS Suite) se solicitada
    if remove_bg:
        nodes["20"] = {
            "class_type": "Image Rembg (Remove Background)",
            "inputs": {
                "images": final_img,
                "transparency": True,
                "model": "u2net",
                "post_processing": False,
                "only_mask": False,
                "alpha_matting": False,
                "alpha_matting_foreground_threshold": 240,
                "alpha_matting_background_threshold": 10,
                "alpha_matting_erode_size": 10,
                "background_color": "none"
            }
        }
        final_img = ["20", 0]

    # 7. Salvar Imagem
    nodes["99"] = {
        "class_type": "SaveImage",
        "inputs": {"images": final_img, "filename_prefix": "PixelArt_Icon"}
    }
    return nodes


def build_inpaint_workflow(image_rel_path, mask_rel_path, ckpt_name, loras, prompt_pos, prompt_neg,
                           denoise=0.55, grow_mask_by=6, steps=28, cfg=5.5, sampler_name="euler", scheduler="karras", seed=None):
    """
    Constrói grafo modular para Refinamento Manual Fino (Inpainting / Selective Resampling).
    Permite resampar apenas a região demarcada pela máscara com controle de denoise e linguagem natural/tags.
    """
    if seed is None:
        seed = random.randint(1, 999999999999999)
    nodes = {}
    
    # 1. Carregar imagem base
    nodes["1"] = {
        "class_type": "LoadImage",
        "inputs": {"image": image_rel_path}
    }
    # 2. Carregar máscara (LoadImage exporta MASK no output index 1)
    nodes["2"] = {
        "class_type": "LoadImage",
        "inputs": {"image": mask_rel_path}
    }
    
    # 3. Checkpoint Loader
    nodes["3"] = {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": ckpt_name}
    }
    curr_model = ["3", 0]
    curr_clip = ["3", 1]
    curr_vae = ["3", 2]
    
    # 4. LoRAs encadeados
    nid_cnt = 20
    for l in (loras or []):
        if not l.get("lora"):
            continue
        nid_cnt += 1
        lnid = str(nid_cnt)
        nodes[lnid] = {
            "class_type": "LoraLoader",
            "inputs": {
                "model": curr_model,
                "clip": curr_clip,
                "lora_name": l["lora"],
                "strength_model": float(l.get("strength_model", 0.8)),
                "strength_clip": float(l.get("strength_clip", 0.8))
            }
        }
        curr_model = [lnid, 0]
        curr_clip = [lnid, 1]
        
    # 5. Prompt Reviewer para polimento defensivo e injeção de triggers
    nodes["5"] = {
        "class_type": "PromptReviewer",
        "inputs": {
            "prompt": prompt_pos,
            "resolve_clothing": True,
            "resolve_pose": True,
            "resolve_gaze": True,
            "resolve_oral": True,
            "auto_lora_triggers": True,
            "deduplicate": True,
            "opt_model": curr_model
        }
    }
    
    # 6. CLIPTextEncode (Positivo)
    nodes["6"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": ["5", 0],
            "clip": curr_clip
        }
    }
    
    # 7. CLIPTextEncode (Negativo)
    nodes["7"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": prompt_neg if prompt_neg else "ugly, deformed, bad anatomy, bad hands, blurry, low quality",
            "clip": curr_clip
        }
    }
    
    # 8. VAEEncodeForInpaint
    nodes["8"] = {
        "class_type": "VAEEncodeForInpaint",
        "inputs": {
            "pixels": ["1", 0],
            "vae": curr_vae,
            "mask": ["2", 1],
            "grow_mask_by": int(grow_mask_by)
        }
    }
    
    # 9. KSampler
    nodes["9"] = {
        "class_type": "KSampler",
        "inputs": {
            "model": curr_model,
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["8", 0],
            "seed": int(seed),
            "steps": int(steps),
            "cfg": float(cfg),
            "sampler_name": str(sampler_name),
            "scheduler": str(scheduler),
            "denoise": float(denoise)
        }
    }
    
    # 10. VAEDecode
    nodes["10"] = {
        "class_type": "VAEDecode",
        "inputs": {
            "samples": ["9", 0],
            "vae": curr_vae
        }
    }
    
    # 11. SaveImage
    nodes["11"] = {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": "studio/inpaint/Inpaint",
            "images": ["10", 0]
        }
    }
    
    return nodes


# ==============================================================================
# --- ANALISADOR VISUAL DE FOTOS E STORE DE FEEDBACK ---
# ==============================================================================

CARTOON_FEEDBACK_FILE = CURRENT_DIR / "cartoon_feedback.json"
_face_analyzer = None

def get_face_analyzer():
    global _face_analyzer
    if _face_analyzer is None:
        try:
            import insightface
            comfy_root = pathlib.Path(__file__).resolve().parents[2]
            root = str(comfy_root / "models" / "insightface")
            if not os.path.exists(root):
                root = r"D:\IA\ComfyUI\models\insightface"
            if os.path.exists(os.path.join(root, "models", "buffalo_l")):
                _face_analyzer = insightface.app.FaceAnalysis(name="buffalo_l", root=root)
                _face_analyzer.prepare(ctx_id=-1, det_size=(640, 640))
                print("[StudioSubject] Analisador facial InsightFace carregado com sucesso!")
        except Exception as e:
            print(f"[StudioSubject] Aviso ao carregar analisador facial: {e}")
            _face_analyzer = False
    return _face_analyzer if _face_analyzer is not False else None

def analyze_real_photo_subject(target_path):
    """
    Analisa fotos reais (sem metadados de IA) usando InsightFace e heurísticas visuais
    para sugerir tags anatômicas precisas: gênero, idade estimada, enquadramento e cor de cabelo.
    """
    tags = []
    details = {}
    try:
        from PIL import Image
        import cv2, numpy as np

        with Image.open(target_path) as pil_img:
            w, h = pil_img.size

        analyzer = get_face_analyzer()
        if analyzer:
            bgr = cv2.imread(str(target_path))
            if bgr is not None:
                faces = analyzer.get(bgr)
                if len(faces) == 1:
                    f = faces[0]
                    gender = "female" if f.gender == 0 else "male"
                    age = int(f.age)
                    details["gender"] = gender
                    details["age"] = age

                    if gender == "female":
                        person_tag = "1girl" if age < 24 else ("mature woman" if age >= 48 else "1woman")
                        tags.append(f"{person_tag}, beautiful face")
                    else:
                        person_tag = "1boy" if age < 24 else ("mature man" if age >= 48 else "1man")
                        tags.append(f"{person_tag}, handsome face")

                    # Bounding box & framing
                    bbox = f.bbox # [x1, y1, x2, y2]
                    face_w = bbox[2] - bbox[0]
                    face_h = bbox[3] - bbox[1]
                    face_area_pct = (face_w * face_h) / max(1, (w * h))

                    if face_area_pct > 0.18:
                        framing = "close-up portrait"
                    elif face_area_pct > 0.05:
                        framing = "upper body portrait"
                    else:
                        framing = "full body portrait"
                    tags.append(framing)
                    details["framing"] = framing

                    # Estimativa de cor de cabelo baseada na região acima da testa
                    try:
                        x1 = max(0, int(bbox[0]))
                        x2 = min(w, int(bbox[2]))
                        y1 = max(0, int(bbox[1] - face_h * 0.45))
                        y2 = min(h, int(bbox[1] + face_h * 0.15))
                        if y2 > y1 and x2 > x1:
                            hair_crop = bgr[y1:y2, x1:x2]
                            hsv = cv2.cvtColor(hair_crop, cv2.COLOR_BGR2HSV)
                            mean_h = np.mean(hsv[:, :, 0])
                            mean_s = np.mean(hsv[:, :, 1])
                            mean_v = np.mean(hsv[:, :, 2])
                            if mean_v < 60:
                                hair_color = "black hair"
                            elif mean_s < 45 and mean_v > 150:
                                hair_color = "grey hair"
                            elif 15 <= mean_h <= 35 and mean_s > 60 and mean_v > 120:
                                hair_color = "blonde hair"
                            elif 0 <= mean_h < 15 and mean_s > 70:
                                hair_color = "red hair"
                            else:
                                hair_color = "brown hair"
                            tags.append(hair_color)
                            details["hair"] = hair_color
                    except Exception:
                        pass

                elif len(faces) >= 2:
                    tags.append("couple, 2persons")
                    details["count"] = len(faces)
    except Exception as e:
        print(f"[StudioSubject] Erro na análise fotográfica: {e}")

    if not tags:
        ratio_tag = "close-up portrait" if (h / max(1, w)) >= 1.2 else "upper body portrait"
        tags.append(f"1person, {ratio_tag}")

    tags.extend(["expressive eyes", "detailed facial features", "natural skin", "clean lighting", "sharp focus"])
    return ", ".join(tags), details


def load_cartoon_feedback():
    if not CARTOON_FEEDBACK_FILE.exists():
        return []
    try:
        with open(CARTOON_FEEDBACK_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_cartoon_feedback(data):
    try:
        with open(CARTOON_FEEDBACK_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[StudioFeedback] Erro ao salvar feedback: {e}")


# ==============================================================================
# --- REGISTRO DE ROTAS DO SERVIDOR WEB ---
# ==============================================================================

def register_studio_routes(routes):

    @routes.get("/brand_avatar.png")
    async def get_brand_avatar(request):
        try:
            if not BRAND_AVATAR_PATH.exists() or not BRAND_AVATAR_PATH.is_file():
                return web.Response(status=404, text="Avatar não encontrado")
            resp = web.FileResponse(BRAND_AVATAR_PATH)
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp
        except Exception as e:
            return web.Response(status=500, text=str(e))

    @routes.post("/api/studio/upload")
    async def api_studio_upload(request):
        """
        Recebe upload de imagem via multipart/form-data e salva em input/studio_uploads.
        """
        try:
            reader = await request.multipart()
            field = await reader.next()
            if not field or field.name != "file":
                return web.json_response({"error": "Campo 'file' não fornecido."}, status=400)

            orig_filename = field.filename or "upload.png"
            clean_name = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", orig_filename)
            unique_name = f"studio_{int(time.time()*1000)}_{clean_name}"
            dest_path = BASE_INPUT_DIR / unique_name

            with open(dest_path, "wb") as f:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    f.write(chunk)

            # Extrai metadados imediatamente
            meta = extract_image_metadata(dest_path)

            return web.json_response({
                "success": True,
                "filename": unique_name,
                "url": f"/view?filename={unique_name}&type=input",
                "meta": meta
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/studio/read_png_info")
    async def api_studio_read_png_info(request):
        """
        Lê metadados de um arquivo já salvo ou recém-enviado.
        """
        try:
            body = await request.json()
            filename = body.get("filename")
            if not filename:
                return web.json_response({"error": "Filename não fornecido."}, status=400)

            target = find_image_anywhere(filename)
            if not target:
                return web.json_response({"error": "Arquivo não encontrado."}, status=404)

            meta = extract_image_metadata(target)
            return web.json_response({
                "success": True,
                "filename": filename,
                "meta": meta
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/studio/detect_subject")
    async def api_studio_detect_subject(request):
        """
        Analisa a imagem enviada (metadados PNG se IA, ou análise visual InsightFace se foto real)
        e sugere tags anatômicas e estilísticas precisas prontas para cartoonização.
        """
        try:
            body = await request.json()
            filename = body.get("filename")
            if not filename:
                return web.json_response({"error": "Filename não fornecido."}, status=400)

            target = find_image_anywhere(filename)
            if not target:
                return web.json_response({"error": "Arquivo não encontrado."}, status=404)

            # 1. Prioriza metadados PNG pré-existentes caso a imagem venha de geração IA
            meta = extract_image_metadata(target)
            if meta.get("prompt"):
                raw_p = meta.get("prompt", "")
                clean_tags = re.sub(r"\b(masterpiece|best quality|ultra highres|highres|sharp focus)\b,?\s*", "", raw_p, flags=re.I).strip()
                if clean_tags.startswith(","): clean_tags = clean_tags[1:].strip()
                return web.json_response({
                    "success": True,
                    "source": "metadata",
                    "suggested_tags": clean_tags[:350],
                    "checkpoint": meta.get("checkpoint"),
                    "details": {"source": "ai_png"}
                })

            # 2. Análise visual inteligente para fotos reais (sem metadados de IA)
            suggested, details = analyze_real_photo_subject(target)

            return web.json_response({
                "success": True,
                "source": "photo_vision",
                "suggested_tags": suggested,
                "details": details
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/studio/refine")
    async def api_studio_refine(request):
        try:
            body = await request.json()
            filename = body.get("filename")
            if not filename:
                return web.json_response({"error": "Filename obrigatório."}, status=400)

            input_rel_image = ensure_image_in_input(filename)

            ckpt = body.get("checkpoint", r"illustrious\waiIllustriousSDXL_v170.safetensors")
            loras = body.get("loras", [])
            prompt_pos = body.get("prompt", "")
            prompt_neg = body.get("negative_prompt", "")
            upscale_factor = float(body.get("upscale_factor", 1.5))
            denoise = float(body.get("denoise", 0.35))
            run_facedetailer = bool(body.get("run_facedetailer", True))
            run_handdetailer = bool(body.get("run_handdetailer", True))

            graph = build_refine_workflow(
                image_rel_path=input_rel_image,
                ckpt_name=ckpt,
                loras=loras,
                prompt_pos=prompt_pos,
                prompt_neg=prompt_neg,
                upscale_factor=upscale_factor,
                denoise=denoise,
                run_facedetailer=run_facedetailer,
                run_handdetailer=run_handdetailer
            )

            client_id = body.get("client_id", "studio_refine_ui")

            port = getattr(server.PromptServer.instance, "port", 8188)
            prompt_id = None
            async with aiohttp.ClientSession() as session:
                payload = {"prompt": graph, "client_id": client_id}
                async with session.post(f"http://127.0.0.1:{port}/prompt", json=payload) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        return web.json_response({"error": err_text}, status=resp.status)
                    try:
                        resp_data = await resp.json()
                        prompt_id = resp_data.get("prompt_id")
                    except Exception:
                        pass

            return web.json_response({
                "success": True,
                "prompt_id": prompt_id,
                "message": "Refinamento enfileirado com sucesso!"
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/studio/inpaint")
    async def api_studio_inpaint(request):
        try:
            body = await request.json()
            filename = body.get("filename")
            mask_data = body.get("mask_base64")
            if not filename:
                return web.json_response({"error": "Imagem base obrigatória."}, status=400)
            if not mask_data:
                return web.json_response({"error": "Máscara de pintura obrigatória."}, status=400)

            input_rel_image = ensure_image_in_input(filename)

            # Decodificar e salvar máscara PNG
            import base64
            if "," in mask_data:
                mask_data = mask_data.split(",", 1)[1]
            mask_bytes = base64.b64decode(mask_data)
            mask_fname = f"inpaint_mask_{int(time.time() * 1000)}.png"
            mask_path = STUDIO_UPLOAD_DIR / mask_fname
            with open(mask_path, "wb") as f:
                f.write(mask_bytes)
            input_rel_mask = ensure_image_in_input(mask_fname)

            ckpt = body.get("checkpoint", r"illustrious\waiIllustriousSDXL_v170.safetensors")
            loras = body.get("loras", [])
            prompt_pos = body.get("prompt", "")
            prompt_neg = body.get("negative_prompt", "")
            denoise = float(body.get("denoise", 0.55))
            grow_mask_by = int(body.get("grow_mask_by", 6))
            steps = int(body.get("steps", 28))
            cfg = float(body.get("cfg", 5.5))
            sampler_name = body.get("sampler_name", "euler")
            scheduler = body.get("scheduler", "karras")
            seed = body.get("seed")

            graph = build_inpaint_workflow(
                image_rel_path=input_rel_image,
                mask_rel_path=input_rel_mask,
                ckpt_name=ckpt,
                loras=loras,
                prompt_pos=prompt_pos,
                prompt_neg=prompt_neg,
                denoise=denoise,
                grow_mask_by=grow_mask_by,
                steps=steps,
                cfg=cfg,
                sampler_name=sampler_name,
                scheduler=scheduler,
                seed=seed
            )

            client_id = body.get("client_id", "studio_inpaint_ui")
            port = getattr(server.PromptServer.instance, "port", 8188)
            prompt_id = None
            async with aiohttp.ClientSession() as session:
                payload = {"prompt": graph, "client_id": client_id}
                async with session.post(f"http://127.0.0.1:{port}/prompt", json=payload) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        return web.json_response({"error": err_text}, status=resp.status)
                    try:
                        resp_data = await resp.json()
                        prompt_id = resp_data.get("prompt_id")
                    except Exception:
                        pass

            return web.json_response({
                "success": True,
                "prompt_id": prompt_id,
                "message": "Refinamento fino manual enfileirado com sucesso!"
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/studio/cartoon")
    async def api_studio_cartoon(request):
        try:
            body = await request.json()
            filename = body.get("filename")
            if not filename:
                return web.json_response({"error": "Filename obrigatório."}, status=400)

            input_rel_image = ensure_image_in_input(filename)

            ckpt = body.get("checkpoint", r"illustrious\waiIllustriousSDXL_v170.safetensors")
            variations = int(body.get("variations_count", 4))
            variations = max(3, min(variations, 5))
            style_strength = float(body.get("style_strength", 0.48))
            custom_tags = body.get("custom_tags", "")
            cartoon_lora_strength = float(body.get("cartoon_lora_strength", 0.85))
            booster_lora_strength = float(body.get("booster_lora_strength", 0.40))
            face_denoise = float(body.get("face_denoise", 0.25))
            cartoon_style = body.get("cartoon_style", "disney")
            cartoon_lora_name = body.get("cartoon_lora_name", None)
            client_id = body.get("client_id", "studio_cartoon_ui")

            port = getattr(server.PromptServer.instance, "port", 8188)
            async with aiohttp.ClientSession() as session:
                for idx in range(variations):
                    graph = build_cartoon_workflow(
                        image_rel_path=input_rel_image,
                        ckpt_name=ckpt,
                        custom_tags=custom_tags,
                        style_strength=style_strength,
                        variation_index=idx,
                        cartoon_lora_strength=cartoon_lora_strength,
                        booster_lora_strength=booster_lora_strength,
                        face_denoise=face_denoise,
                        cartoon_style=cartoon_style,
                        cartoon_lora_name=cartoon_lora_name
                    )
                    payload = {"prompt": graph, "client_id": client_id}
                    async with session.post(f"http://127.0.0.1:{port}/prompt", json=payload) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            print(f"[StudioCartoon] Aviso ao enfileirar: {err}")

            return web.json_response({
                "success": True,
                "message": f"{variations} variações de cartoonização enfileiradas!",
                "count": variations
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/studio/cartoon_feedback")
    async def api_studio_cartoon_feedback(request):
        """
        Recebe feedback de aprovação/nota sobre uma geração de cartoonização
        e salva para recalibrar automaticamente as combinações de pesos ideais.
        """
        try:
            body = await request.json()
            feedback_list = load_cartoon_feedback()
            r_raw = body.get("rating", 5)
            if isinstance(r_raw, str):
                if r_raw == "star":
                    rating_score = 5
                elif r_raw == "up":
                    rating_score = 4
                elif r_raw == "down":
                    rating_score = 1
                else:
                    try:
                        rating_score = int(r_raw)
                    except ValueError:
                        rating_score = 3
            else:
                rating_score = int(r_raw)

            entry = {
                "timestamp": time.time(),
                "filename": body.get("filename", ""),
                "rating": rating_score,
                "weights": {
                    "cartoon_lora_strength": float(body.get("cartoon_lora_strength", 0.85)),
                    "booster_lora_strength": float(body.get("booster_lora_strength", 0.40)),
                    "style_strength": float(body.get("style_strength", 0.48)),
                    "face_denoise": float(body.get("face_denoise", 0.25))
                },
                "tags": body.get("tags", "")
            }
            feedback_list.append(entry)
            # Mantém os últimos 150 feedbacks
            if len(feedback_list) > 150:
                feedback_list = feedback_list[-150:]
            save_cartoon_feedback(feedback_list)
            return web.json_response({"success": True, "message": "Feedback registrado com sucesso!", "entry": entry})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/studio/cartoon_best_weights")
    async def api_studio_cartoon_best_weights(request):
        """
        Calcula os melhores pesos médios baseados nas gerações com avaliação positiva (rating >= 4).
        """
        try:
            feedbacks = load_cartoon_feedback()
            high_rated = [f for f in feedbacks if f.get("rating", 0) >= 4]
            if not high_rated:
                # Retorna os pesos padrão comprovados
                defaults = {
                    "cartoon_lora_strength": 0.85,
                    "booster_lora_strength": 0.40,
                    "style_strength": 0.48,
                    "face_denoise": 0.25
                }
                return web.json_response({
                    "success": True,
                    "has_feedback": False,
                    "count": 0,
                    "sample_count": 0,
                    "best_weights": defaults,
                    "weights": defaults
                })

            total_w = sum(f.get("rating", 4) for f in high_rated)
            avg_cartoon = sum(f["weights"].get("cartoon_lora_strength", 0.85) * f.get("rating", 4) for f in high_rated) / total_w
            avg_booster = sum(f["weights"].get("booster_lora_strength", 0.40) * f.get("rating", 4) for f in high_rated) / total_w
            avg_style = sum(f["weights"].get("style_strength", 0.48) * f.get("rating", 4) for f in high_rated) / total_w
            avg_face = sum(f["weights"].get("face_denoise", 0.25) * f.get("rating", 4) for f in high_rated) / total_w

            best_w = {
                "cartoon_lora_strength": round(avg_cartoon, 2),
                "booster_lora_strength": round(avg_booster, 2),
                "style_strength": round(avg_style, 2),
                "face_denoise": round(avg_face, 2)
            }

            return web.json_response({
                "success": True,
                "has_feedback": True,
                "count": len(high_rated),
                "sample_count": len(high_rated),
                "best_weights": best_w,
                "weights": best_w
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/studio/faceswap")
    async def api_studio_faceswap(request):
        try:
            body = await request.json()
            source_file = body.get("source_filename")
            target_files = body.get("target_filenames", [])

            if not source_file or not target_files:
                return web.json_response({"error": "Source e targets são obrigatórios."}, status=400)

            input_source = ensure_image_in_input(source_file)

            codeformer_weight = float(body.get("codeformer_weight", 0.85))
            face_restore_visibility = float(body.get("face_restore_visibility", 0.60))
            face_restore_model = str(body.get("face_restore_model", "codeformer-v0.1.0.pth"))
            run_detailer = bool(body.get("run_texture_detailer", False))
            client_id = body.get("client_id", "studio_faceswap_ui")

            port = getattr(server.PromptServer.instance, "port", 8188)
            async with aiohttp.ClientSession() as session:
                for tgt in target_files:
                    input_tgt = ensure_image_in_input(tgt)
                    graph = build_faceswap_workflow(
                        source_rel_path=input_source,
                        target_rel_path=input_tgt,
                        codeformer_weight=codeformer_weight,
                        face_restore_visibility=face_restore_visibility,
                        face_restore_model=face_restore_model,
                        run_texture_detailer=run_detailer
                    )
                    payload = {"prompt": graph, "client_id": client_id}
                    async with session.post(f"http://127.0.0.1:{port}/prompt", json=payload) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            print(f"[StudioFaceSwap] Aviso ao enfileirar swap para {tgt}: {err}")

            return web.json_response({
                "success": True,
                "message": f"FaceSwap enfileirado para {len(target_files)} imagem(ns)!",
                "count": len(target_files)
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/studio/active_status")
    async def api_studio_active_status(request):
        try:
            port = getattr(server.PromptServer.instance, "port", 8188)
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://127.0.0.1:{port}/queue") as resp:
                    if resp.status == 200:
                        q_data = await resp.json()
                        running = q_data.get("queue_running", [])
                        pending = q_data.get("queue_pending", [])
                        return web.json_response({
                            "is_generating": len(running) > 0 or len(pending) > 0,
                            "running_count": len(running),
                            "pending_count": len(pending),
                            "total_queue": len(running) + len(pending)
                        })
            return web.json_response({"is_generating": False, "total_queue": 0})
        except Exception as e:
            return web.json_response({"error": str(e), "is_generating": False}, status=500)

    @routes.post("/api/studio/pixelart")
    async def api_studio_pixelart(request):
        try:
            body = await request.json()
            prompt = body.get("prompt", "pixel art icon, rpg item")
            neg_prompt = body.get("negative_prompt", "blurry, photorealistic, 3d, realistic")
            ckpt = body.get("checkpoint", r"illustrious\waiIllustriousSDXL_v170.safetensors")
            count = int(body.get("count", 1))
            resolution = int(body.get("resolution", 1024))
            use_dungeon = bool(body.get("use_dungeon_squad", False))
            dungeon_str = float(body.get("dungeon_squad_strength", 0.85))
            remove_bg = bool(body.get("remove_bg", False))
            is_nsfw = bool(body.get("is_nsfw", False))
            client_id = body.get("client_id", "studio_pixelart_ui")

            port = getattr(server.PromptServer.instance, "port", 8188)
            async with aiohttp.ClientSession() as session:
                for idx in range(count):
                    # Resolve os wildcards dinamicamente para que cada imagem receba um sorteio único!
                    prompt_iter = resolve_dynamic_wildcards(prompt)
                    graph = build_pixelart_workflow(
                        prompt_pos=prompt_iter,
                        prompt_neg=neg_prompt,
                        ckpt_name=ckpt,
                        resolution=resolution,
                        use_dungeon_squad=use_dungeon,
                        dungeon_squad_strength=dungeon_str,
                        remove_bg=remove_bg,
                        is_nsfw=is_nsfw
                    )
                    payload = {"prompt": graph, "client_id": client_id}
                    async with session.post(f"http://127.0.0.1:{port}/prompt", json=payload) as resp:
                        if resp.status != 200:
                            err = await resp.text()
                            print(f"[StudioPixel] Aviso ao enfileirar: {err}")

            return web.json_response({
                "success": True,
                "message": f"{count} ícone(s) pixel art enfileirado(s)!",
                "count": count
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/studio/delete_image")
    async def api_studio_delete_image(request):
        """
        Exclui permanentemente uma imagem das galerias ativas (output/ ou tester_saved/).
        """
        try:
            body = await request.json()
            filename = body.get("filename")
            if not filename:
                return web.json_response({"error": "Filename não fornecido."}, status=400)

            # Prevenção de directory traversal
            clean_name = pathlib.Path(filename).name
            target = BASE_OUTPUT_DIR / clean_name
            if not target.exists():
                target = find_image_anywhere(clean_name)

            if target and target.exists() and target.is_file():
                target.unlink()
                return web.json_response({"success": True, "message": f"Imagem '{clean_name}' excluída com sucesso."})
            else:
                return web.json_response({"error": f"Arquivo '{clean_name}' não encontrado para exclusão."}, status=404)
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/studio/gallery")
    async def api_studio_gallery(request):
        """
        Retorna imagens geradas recentemente no output agrupadas por tipo.
        """
        try:
            valid_exts = {".png", ".webp", ".jpg", ".jpeg"}
            all_files = sorted([f for f in BASE_OUTPUT_DIR.glob("*") if f.is_file() and f.suffix.lower() in valid_exts],
                               key=lambda f: f.stat().st_mtime, reverse=True)

            refined = []
            cartoon = []
            faceswap = []
            pixelart = []
            inpaint = []

            for f in all_files[:60]:
                item = {
                    "filename": f.name,
                    "url": f"/view?filename={f.name}&type=output",
                    "timestamp": f.stat().st_mtime,
                    "size_bytes": f.stat().st_size
                }
                fn = f.name.lower()
                if "studio_refined" in fn:
                    refined.append(item)
                elif "cartoon_anime" in fn:
                    cartoon.append(item)
                elif "faceswap" in fn:
                    faceswap.append(item)
                elif "pixelart" in fn:
                    pixelart.append(item)
                elif "inpaint" in fn:
                    inpaint.append(item)

            return web.json_response({
                "success": True,
                "refined": refined[:12],
                "cartoon": cartoon[:12],
                "faceswap": faceswap[:12],
                "pixelart": pixelart[:12],
                "inpaint": inpaint[:12]
            })
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.get("/api/studio/presets/pixelart")
    async def api_studio_get_pixelart_presets(request):
        """
        Retorna as listas e categorias de presets para Pixel Art do arquivo JSON editavel.
        """
        try:
            preset_file = pathlib.Path(__file__).parent / "presets" / "pixelart_presets.json"
            if not preset_file.exists():
                return web.json_response({"error": "Arquivo de presets nao encontrado"}, status=404)
            with open(preset_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return web.json_response({"success": True, "presets": data})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    @routes.post("/api/studio/presets/pixelart")
    async def api_studio_save_pixelart_presets(request):
        """
        Salva alteracoes no arquivo JSON de presets para Pixel Art.
        """
        try:
            body = await request.json()
            presets_data = body.get("presets")
            if not presets_data:
                return web.json_response({"error": "Dados de presets ausentes"}, status=400)
            preset_file = pathlib.Path(__file__).parent / "presets" / "pixelart_presets.json"
            preset_file.parent.mkdir(parents=True, exist_ok=True)
            with open(preset_file, "w", encoding="utf-8") as f:
                json.dump(presets_data, f, indent=2, ensure_ascii=False)
            return web.json_response({"success": True, "message": "Presets salvos com sucesso"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)
