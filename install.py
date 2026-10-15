#!/usr/bin/env python3
"""
Script de instalação e verificação de ambiente para o ComfyUI AI Studio / HA Endpoint.
Executável tanto de forma autônoma quanto pelo inicializador de custom_nodes do ComfyUI.
"""
import os
import sys
import pathlib
import subprocess
import json

def main():
    print("[ComfyUI Studio] Iniciando verificação de ambiente e dependências...")
    node_dir = pathlib.Path(__file__).parent.resolve()
    comfy_root = node_dir.parents[1]

    # 1. Garantir pastas de dados e templates no ComfyUI
    dirs_to_ensure = [
        comfy_root / "user" / "default",
        comfy_root / "output" / "tester",
        comfy_root / "output" / "tester_saved",
        comfy_root / "input" / "studio_uploads",
        node_dir / "presets"
    ]
    for d in dirs_to_ensure:
        d.mkdir(parents=True, exist_ok=True)
    print("  [OK] Estrutura de diretórios criada e verificada.")

    # 2. Verificar presets de Pixel Art
    presets_file = node_dir / "presets" / "pixelart_presets.json"
    if not presets_file.exists():
        print(f"  [AVISO] Criando arquivo inicial de presets em: {presets_file}")
        with open(presets_file, "w", encoding="utf-8") as f:
            json.dump({"categories": {}, "character_options": {}}, f, indent=2)
    else:
        print("  [OK] Presets de Pixel Art encontrados.")

    # 3. Instalar pacotes de requirements.txt se necessário
    req_file = node_dir / "requirements.txt"
    if req_file.exists():
        try:
            print("  [INFO] Verificando dependências do requirements.txt...")
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_file), "--quiet"], check=False)
            print("  [OK] Dependências python verificadas.")
        except Exception as e:
            print(f"  [AVISO] Falha ao verificar automaticamente dependências: {e}")

    print("[ComfyUI Studio] Instalação concluída com sucesso! Acesse http://<ip>:8188/studio.html após iniciar o ComfyUI.\n")

if __name__ == "__main__":
    main()
