#!/usr/bin/env python3
# mcp-sketchup — SketchUp MCP Server para Linux (compatible con opencode)
# Basado en mhyrr/sketchup-mcp y Shattenjagger/sketchup-mcp-bridge, adaptado para Linux con modo mock.
# Usa FastMCP (mcp>=1.3,<2) con TCP connect-per-command hacia SketchUp (puerto 9876) + fallback mock JSON.

import os
import sys
import json
import socket
import time
import uuid
import base64
from pathlib import Path
from typing import Optional, Any

# Compatibilidad FastMCP (mcp 1.x vs 2.x)
try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    from mcp.server.mcpserver import MCPServer as FastMCP  # mcp 2.x fallback

# Config
HOST = os.environ.get("SKETCHUP_MCP_HOST", "localhost")
PORT = int(os.environ.get("SKETCHUP_MCP_PORT", "9876"))
TIMEOUT = float(os.environ.get("SKETCHUP_MCP_TIMEOUT", "8"))
SCREENSHOT_DIR = os.environ.get("SKETCHUP_MCP_SCREENSHOT_DIR", "")
CACHE_DIR = Path(os.environ.get("SKETCHUP_MCP_CACHE", str(Path.home() / ".cache/sketchup-mcp")))
SCENE_FILE = CACHE_DIR / "scene.json"

# Asegurar cache
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# FastMCP con instructions (no description — bug de mhyrr)
try:
    mcp = FastMCP(
        "sketchup",
        instructions="SketchUp integration — conecta IA a SketchUp vía TCP 9876 o modo mock Linux. Herramientas para crear, transformar, materializar y evaluar Ruby.",
    )
except TypeError:
    # fallback si la versión espera 'description' (muy vieja)
    mcp = FastMCP("sketchup")

# ---- Mock Scene Helpers ----
def load_scene():
    if SCENE_FILE.exists():
        try:
            return json.loads(SCENE_FILE.read_text())
        except:
            pass
    # escena por defecto
    return {
        "title": "Mock Scene — Linux (sin SketchUp)",
        "units": "mm",
        "bounds": {"min": [0,0,0], "max": [1000,1000,1000]},
        "entities": [],
        "selection": [],
        "materials": ["Default", "Red", "Blue", "Green", "Wood", "Glass"],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

def save_scene(scene):
    SCENE_FILE.write_text(json.dumps(scene, indent=2, ensure_ascii=False))

def tcp_available(timeout=1.0):
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout):
            return True
    except:
        return False

def tcp_command(cmd: str, args: dict = None, timeout: float = TIMEOUT):
    """Connect-per-command — fix desync bug de mhyrr (abre, envía, cierra)."""
    payload = {"id": str(uuid.uuid4())[:8], "cmd": cmd, "args": args or {}}
    # Wire protocol de Shattenjagger: {"id", "cmd", "args"} + compat con mhyrr {"type", "params"}
    alt_payload = {"type": cmd, "params": args or {}, "id": payload["id"]}
    for p in [payload, alt_payload]:
        try:
            with socket.create_connection((HOST, PORT), timeout=timeout) as s:
                s.settimeout(timeout)
                data = (json.dumps(p) + "\n").encode()
                s.sendall(data)
                # leer hasta \n
                buf = b""
                s.settimeout(timeout)
                while not buf.endswith(b"\n"):
                    chunk = s.recv(8192)
                    if not chunk:
                        break
                    buf += chunk
                    if len(buf) > 2_000_000:
                        break
                if buf:
                    resp = json.loads(buf.decode().strip())
                    # normalizar respuesta
                    if resp.get("ok") is True or resp.get("status") == "success" or "result" in resp:
                        return resp
                    if resp.get("ok") is False or resp.get("status") == "error":
                        return resp
                    return resp
        except Exception as e:
            last_err = str(e)
            continue
    raise ConnectionError(f"No se pudo conectar a SketchUp en {HOST}:{PORT} — {last_err if 'last_err' in locals() else 'sin respuesta'}")

def ensure_mock_materials(scene):
    if "materials" not in scene:
        scene["materials"] = ["Default", "Red", "Blue", "Green", "Wood", "Glass"]

# ---- Tools ----
@mcp.tool()
def sketchup_status() -> str:
    """Estado de conexión a SketchUp + info mock. Usa esto primero."""
    connected = tcp_available()
    scene = load_scene()
    info = {
        "host": HOST,
        "port": PORT,
        "connected": connected,
        "mode": "TCP (SketchUp vivo)" if connected else "MOCK (Linux sin SketchUp)",
        "scene_file": str(SCENE_FILE),
        "entities": len(scene.get("entities", [])),
        "selection": len(scene.get("selection", [])),
        "units": scene.get("units", "mm"),
        "title": scene.get("title", ""),
    }
    if connected:
        try:
            r = tcp_command("get_scene_info")
            info["sketchup_response"] = r.get("result") or r
        except Exception as e:
            info["sketchup_error"] = str(e)
    # tips linux
    info["linux_tips"] = "SketchUp no es nativo Linux. Instala via Wine (yay -S wine vinegar + SketchUp Make 2017) o usa app.sketchup.com. Este MCP funciona igual en mock."
    return json.dumps(info, indent=2, ensure_ascii=False)

@mcp.tool()
def get_scene_info() -> str:
    """Info de la escena actual — intenta SketchUp, fallback a mock."""
    if tcp_available(timeout=0.8):
        try:
            resp = tcp_command("get_scene_info", timeout=TIMEOUT)
            # Shattenjagger: get_scene_info sin args; mhyrr usa type get_scene_info
            if resp.get("ok"):
                return json.dumps(resp.get("result"), indent=2, ensure_ascii=False)
            if resp.get("result"):
                return json.dumps(resp["result"], indent=2, ensure_ascii=False)
            return json.dumps(resp, indent=2, ensure_ascii=False)
        except Exception as e:
            pass  # fallback a mock
    scene = load_scene()
    mock = {
        "title": scene["title"],
        "units": scene["units"],
        "bounds": scene["bounds"],
        "entity_count": len(scene["entities"]),
        "selection_count": len(scene["selection"]),
        "materials": scene.get("materials", []),
        "mode": "mock" if not tcp_available() else "sketchup_unreachable_fallback",
        "entities_preview": scene["entities"][:5],
    }
    return json.dumps(mock, indent=2, ensure_ascii=False)

@mcp.tool()
def get_selection() -> str:
    """Entidades seleccionadas (mock o SketchUp)."""
    if tcp_available(timeout=0.8):
        try:
            for cmd in ["get_selection", "get_selected_components"]:
                try:
                    resp = tcp_command(cmd, timeout=TIMEOUT)
                    if resp.get("ok") or resp.get("result"):
                        return json.dumps(resp.get("result") or resp, indent=2, ensure_ascii=False)
                except: continue
        except: pass
    scene = load_scene()
    sel_ids = scene.get("selection", [])
    entities = [e for e in scene["entities"] if e["id"] in sel_ids]
    return json.dumps({"count": len(entities), "selection": entities, "mode": "mock"}, indent=2, ensure_ascii=False)

@mcp.tool()
def get_selected_components() -> str:
    """Alias de get_selection para compatibilidad con mhyrr."""
    return get_selection()

@mcp.tool()
def create_component(name: str, component_type: str = "cube", position: str = "0,0,0", size: str = "100,100,100", material: str = "Default") -> str:
    """Crea un componente en la escena. Tipos: cube, sphere, cylinder, face, custom. Position/size como 'x,y,z'."""
    # intentar SketchUp primero
    if tcp_available(timeout=0.8):
        try:
            resp = tcp_command("create_component", {"name": name, "type": component_type, "position": position, "size": size, "material": material}, timeout=TIMEOUT)
            if resp.get("ok") or resp.get("result") or resp.get("status") == "success":
                return json.dumps({"status": "creado en SketchUp", "response": resp}, indent=2, ensure_ascii=False)
        except Exception as e:
            # seguir a mock
            pass

    # Mock
    scene = load_scene()
    ensure_mock_materials(scene)
    try:
        pos = [float(x.strip()) for x in position.split(",")]
        sz = [float(x.strip()) for x in size.split(",")]
    except:
        pos = [0,0,0]
        sz = [100,100,100]
    comp = {
        "id": str(uuid.uuid4())[:8],
        "name": name,
        "type": component_type,
        "position": pos,
        "size": sz,
        "material": material,
        "rotation": [0,0,0],
        "scale": [1,1,1],
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "bounds": {"min": pos, "max": [pos[i]+sz[i] for i in range(3)]}
    }
    scene["entities"].append(comp)
    scene["selection"] = [comp["id"]]
    save_scene(scene)
    return json.dumps({"status": "creado en mock (Linux sin SketchUp)", "component": comp, "hint": "Conecta SketchUp en 9876 para que sea real. Exporta con export_scene."}, indent=2, ensure_ascii=False)

@mcp.tool()
def delete_component(id_or_name: str) -> str:
    """Borra componente por id o nombre."""
    if tcp_available(timeout=0.8):
        try:
            resp = tcp_command("delete_component", {"id": id_or_name, "name": id_or_name}, timeout=TIMEOUT)
            if resp.get("ok") or resp.get("status") == "success":
                return json.dumps(resp, indent=2, ensure_ascii=False)
        except: pass
    scene = load_scene()
    before = len(scene["entities"])
    scene["entities"] = [e for e in scene["entities"] if e["id"] != id_or_name and e["name"] != id_or_name]
    scene["selection"] = [s for s in scene["selection"] if s != id_or_name]
    # también borrar por nombre matching
    after = len(scene["entities"])
    save_scene(scene)
    if before == after:
        return f"No encontrado en mock: {id_or_name}. Entidades: {[e['name']+':'+e['id'] for e in scene['entities']]}"
    return json.dumps({"status": "borrado mock", "before": before, "after": after, "id_or_name": id_or_name}, indent=2, ensure_ascii=False)

@mcp.tool()
def transform_component(id_or_name: str, translation: str = "0,0,0", rotation: str = "0,0,0", scale: str = "1,1,1") -> str:
    """Mueve/rota/escala componente. Formato: 'x,y,z' para cada uno."""
    if tcp_available(timeout=0.8):
        try:
            resp = tcp_command("transform_component", {"id": id_or_name, "translation": translation, "rotation": rotation, "scale": scale}, timeout=TIMEOUT)
            if resp.get("ok") or resp.get("status") == "success":
                return json.dumps(resp, indent=2, ensure_ascii=False)
        except: pass
    scene = load_scene()
    def parse(s, d):
        try: return [float(x.strip()) for x in s.split(",")]
        except: return d
    t = parse(translation, [0,0,0])
    r = parse(rotation, [0,0,0])
    sc = parse(scale, [1,1,1])
    found = None
    for e in scene["entities"]:
        if e["id"] == id_or_name or e["name"] == id_or_name:
            # aplicar
            e["position"] = [e["position"][i]+t[i] for i in range(3)]
            e["rotation"] = [e["rotation"][i]+r[i] for i in range(3)]
            e["scale"] = [e["scale"][i]*sc[i] for i in range(3)]
            e["bounds"] = {"min": e["position"], "max": [e["position"][i]+e["size"][i]*e["scale"][i] for i in range(3)]}
            found = e
            break
    if not found:
        return f"No encontrado: {id_or_name}"
    save_scene(scene)
    return json.dumps({"status": "transformado mock", "component": found}, indent=2, ensure_ascii=False)

@mcp.tool()
def set_material(id_or_name: str, material: str = "Red", color: str = "") -> str:
    """Aplica material/color a componente. Colores: Red, Blue, #ff0000, etc."""
    mat = color if color else material
    if tcp_available(timeout=0.8):
        try:
            resp = tcp_command("set_material", {"id": id_or_name, "material": mat}, timeout=TIMEOUT)
            if resp.get("ok") or resp.get("status") == "success":
                return json.dumps(resp, indent=2, ensure_ascii=False)
        except: pass
    scene = load_scene()
    if mat not in scene.get("materials", []):
        scene.setdefault("materials", []).append(mat)
    found = None
    for e in scene["entities"]:
        if e["id"] == id_or_name or e["name"] == id_or_name:
            e["material"] = mat
            found = e
            break
    if not found:
        return f"No encontrado: {id_or_name}, material {mat} registrado igual."
    save_scene(scene)
    return json.dumps({"status": "material aplicado mock", "component": found}, indent=2, ensure_ascii=False)

@mcp.tool()
def eval_ruby(code: str) -> str:
    """Ejecuta Ruby arbitrario en SketchUp. Si no hay SketchUp, mockea con info."""
    if tcp_available(timeout=0.8):
        try:
            resp = tcp_command("eval", {"code": code}, timeout=TIMEOUT)
            # Shattenjagger usa cmd=eval args={code}
            # mhyrr usa type=eval_ruby params={code}
            if resp.get("ok") or "result" in resp:
                return json.dumps({"mode": "sketchup", "result": resp.get("result") or resp, "raw": resp}, indent=2, ensure_ascii=False)
            # intentar segundo formato
            resp2 = tcp_command("eval_ruby", {"code": code}, timeout=TIMEOUT)
            return json.dumps({"mode": "sketchup", "result": resp2}, indent=2, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"mode": "sketchup_error", "error": str(e), "code": code, "fallback": "SketchUp respondió error, revisa Ruby Console"}, indent=2, ensure_ascii=False)
    # mock: interpretar algunos comandos comunes
    mock_results = {
        "Sketchup.version": "26.1.256 (mock — Linux sin SketchUp)",
        "Sketchup.active_model.title": load_scene().get("title"),
    }
    # si es pregunta simple, devolver mock
    if code.strip() in mock_results:
        return json.dumps({"mode": "mock", "code": code, "result": mock_results[code.strip()]}, indent=2, ensure_ascii=False)
    # crear componente vía Ruby mock
    scene = load_scene()
    return json.dumps({
        "mode": "mock (sin SketchUp)",
        "code": code,
        "result": f"[MOCK] Código recibido: {code[:200]}. Sin SketchUp vivo, no se ejecuta Ruby real. Escena mock tiene {len(scene['entities'])} entidades. Conecta SketchUp en {HOST}:{PORT} para ejecución real.",
        "hint": "Ejecuta sketchup_status para verificar conexión. En Linux instala SketchUp vía Wine o usa app.sketchup.com",
        "scene_preview": scene["entities"][:2]
    }, indent=2, ensure_ascii=False)

@mcp.tool()
def export_scene(format: str = "json", path: str = "") -> str:
    """Exporta escena mock o pide a SketchUp que exporte. Formatos: json, obj, skp, glb."""
    scene = load_scene()
    if not path:
        path = str(CACHE_DIR / f"export.{format}")
        if format == "json":
            path = str(CACHE_DIR / "export.json")
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    if tcp_available(timeout=0.8) and format in ["skp", "obj", "glb", "dae", " stl"]:
        try:
            resp = tcp_command("export_scene", {"format": format, "path": str(p)}, timeout=15)
            return json.dumps(resp, indent=2, ensure_ascii=False)
        except: pass

    if format == "json":
        p.write_text(json.dumps(scene, indent=2, ensure_ascii=False))
        return json.dumps({"status": "exportado json mock", "path": str(p), "entities": len(scene["entities"])}, indent=2, ensure_ascii=False)
    elif format == "obj":
        # generar OBJ simple con cubos
        lines = ["# mock export from mcp-sketchup", f"# entities: {len(scene['entities'])}", "o scene"]
        v_offset = 1
        for e in scene["entities"]:
            x,y,z = e["position"]
            sx,sy,sz = [e["size"][i]*e["scale"][i] for i in range(3)]
            # 8 vértices cubo
            verts = [
                [x,y,z], [x+sx,y,z], [x+sx,y+sy,z], [x,y+sy,z],
                [x,y,z+sz], [x+sx,y,z+sz], [x+sx,y+sy,z+sz], [x,y+sy,z+sz]
            ]
            for v in verts:
                lines.append(f"v {v[0]} {v[1]} {v[2]}")
            # 6 caras (12 triángulos simplificados como quads)
            faces = [
                [0,1,2,3], [4,5,6,7], [0,1,5,4], [1,2,6,5], [2,3,7,6], [3,0,4,7]
            ]
            for f in faces:
                lines.append(f"f {f[0]+v_offset} {f[1]+v_offset} {f[2]+v_offset} {f[3]+v_offset}")
            v_offset += 8
        p.write_text("\n".join(lines))
        return json.dumps({"status": "exportado obj mock (cubos)", "path": str(p), "entities": len(scene["entities"])}, indent=2, ensure_ascii=False)
    else:
        p.write_text(json.dumps(scene, indent=2))
        return json.dumps({"status": f"exportado mock como json (formato {format} no soportado sin SketchUp)", "path": str(p)}, indent=2, ensure_ascii=False)

@mcp.tool()
def screenshot() -> str:
    """Captura de SketchUp. Requiere SketchUp vivo y SCREENSHOT_DIR configurado, si no mock."""
    if tcp_available(timeout=0.8):
        try:
            args = {}
            if SCREENSHOT_DIR:
                args["screenshot_dir"] = SCREENSHOT_DIR
            resp = tcp_command("screenshot", args, timeout=12)
            # si devuelve imagen base64 o path
            if resp.get("ok") and resp.get("result"):
                r = resp["result"]
                # si es dict con image
                return json.dumps(r if isinstance(r, str) else resp, indent=2, ensure_ascii=False)
            return json.dumps(resp, indent=2, ensure_ascii=False)
        except Exception as e:
            return json.dumps({"error": str(e), "mode": "sketchup_error"}, indent=2, ensure_ascii=False)
    return json.dumps({
        "mode": "mock",
        "message": "Sin SketchUp, no hay screenshot real. Escena mock: usa get_scene_info / export_scene json para ver.",
        "entities": len(load_scene()["entities"]),
        "tip": "Configura SKETCHUP_MCP_SCREENSHOT_DIR=/mnt/c/Users/.../Temp si usas WSL+Windows host"
    }, indent=2, ensure_ascii=False)

@mcp.tool()
def clear_scene() -> str:
    """Limpia la escena mock (borra todos los componentes). No afecta SketchUp vivo."""
    scene = load_scene()
    count = len(scene["entities"])
    scene["entities"] = []
    scene["selection"] = []
    save_scene(scene)
    return json.dumps({"status": "escena mock limpiada", "borrados": count}, indent=2, ensure_ascii=False)

def main():
    # compatibilidad: mcp.run() bloqueante stdio
    mcp.run()

if __name__ == "__main__":
    main()
