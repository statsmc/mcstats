#!/usr/bin/env python3
"""
Script para generar estadísticas de Minecraft usando CONTRASEÑA
- Lee credenciales desde variables de entorno
- Usa contraseña en lugar de SSH key
- Genera HTML estático
"""

import paramiko
import json
import hashlib
import re
import os
import base64
from datetime import datetime

# ================= CONFIG DESDE VARIABLES DE ENTORNO =================
SSH_HOST = os.getenv('MINECRAFT_SSH_HOST')
SSH_PORT = int(os.getenv('MINECRAFT_SSH_PORT', '22'))
SSH_USER = os.getenv('MINECRAFT_SSH_USER')
SSH_PASSWORD = os.getenv('MINECRAFT_SSH_PASSWORD')  # ← CONTRASEÑA
WORLD_PATH = os.getenv('MINECRAFT_WORLD_PATH', '/world')

# Validar que las variables existan
if not all([SSH_HOST, SSH_USER, SSH_PASSWORD]):
    print("❌ ERROR: Faltan variables de entorno requeridas")
    print("   MINECRAFT_SSH_HOST")
    print("   MINECRAFT_SSH_USER")
    print("   MINECRAFT_SSH_PASSWORD")
    exit(1)

OUTPUT_HTML = "index.html"
TOP_LIMIT = 100

STATS_FOLDER = WORLD_PATH.rstrip("/") + "/stats"
ADVANCEMENTS_FOLDER = WORLD_PATH.rstrip("/") + "/advancements"

# ================= UTILS =================
def offline_uuid(name):
    """Genera UUID offline de Minecraft"""
    base = ("OfflinePlayer:" + name).encode("utf-8")
    return hashlib.md5(base).hexdigest()

def ticks_to_time(ticks):
    """Convierte ticks a tiempo legible"""
    seconds = ticks // 20
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"

def sum_values(d):
    """Suma todos los valores de un diccionario"""
    try:
        return sum(int(v) for v in d.values())
    except:
        return 0

def is_bot(p):
    """Detección mejorada de bots"""
    ticks = p["ticks"]
    blocks = p["total_blocks"]
    kills = p["total_killed"]
    jumps = p["jumps"]
    deaths = p["deaths"]
    
    walk = int(p["extras"].get("minecraft:walk_one_cm", 0))
    sprint = int(p["extras"].get("minecraft:sprint_one_cm", 0))
    sneak = int(p["extras"].get("minecraft:sneak_time", 0))
    leaves = int(p["extras"].get("minecraft:leave_game", 0))
    crafted = int(p["extras"].get("minecraft:interact_with_crafting_table", 0))
    chests = int(p["extras"].get("minecraft:open_chest", 0))
    
    score = 0
    
    if ticks < 1200: score += 4
    if walk < 500 and sprint < 200: score += 3
    if blocks == 0 and kills == 0 and crafted == 0: score += 3
    if jumps == 0 and ticks > 600: score += 3
    
    name_lower = p["name"].lower()
    bot_patterns = [
        r"^(bot|npc|test|debug|dummy|fake|afk)",
        r"(bot|npc|test|afk)$",
        r"^player[_-]?\d+$",
        r"^[0-9a-f]{8,}$",
    ]
    
    for pattern in bot_patterns:
        if re.match(pattern, name_lower):
            score += 5
            break
    
    if ticks > 20000 and blocks < 10 and kills < 5 and jumps < 100: score += 4
    
    return score >= 7

# ================= CONNECT SSH =================
print(f"🔌 Conectando a {SSH_HOST}:{SSH_PORT}...")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

# Conectar usando CONTRASEÑA
try:
    ssh.connect(
        SSH_HOST, 
        port=SSH_PORT, 
        username=SSH_USER, 
        password=SSH_PASSWORD,  # ← AQUÍ USA LA CONTRASEÑA
        timeout=15
    )
    print("✅ Conexión exitosa")
except Exception as e:
    print(f"❌ Error de conexión: {e}")
    exit(1)

sftp = ssh.open_sftp()

# ================= UUID → NAME =================
uuid_to_name = {}

def try_json(path):
    try:
        with sftp.open(path) as f:
            return json.load(f)
    except:
        return None

print("📝 Cargando nombres...")

uc = try_json("/usercache.json")
if uc:
    for e in uc:
        uuid_to_name[e["uuid"].replace("-", "")] = e["name"]

# ================= LOAD SKINRESTORER =================
print("🎨 Cargando texturas...")
skin_textures = {}
SKINRESTORER_FOLDER = WORLD_PATH.rstrip("/") + "/skinrestorer"

try:
    sftp.chdir(SKINRESTORER_FOLDER)
    for fname in sftp.listdir():
        if not fname.endswith(".json"):
            continue
        
        uuid = fname[:-5]
        try:
            with sftp.open(fname) as f:
                skin_data = json.load(f)
                
            if "value" in skin_data and "value" in skin_data["value"]:
                texture_data = base64.b64decode(skin_data["value"]["value"]).decode('utf-8')
                texture_json = json.loads(texture_data)
                
                if "textures" in texture_json and "SKIN" in texture_json["textures"]:
                    skin_url = texture_json["textures"]["SKIN"]["url"]
                    texture_hash = skin_url.split("/")[-1]
                    skin_textures[uuid.replace("-", "")] = texture_hash
        except:
            continue
    
    print(f"✅ {len(skin_textures)} texturas cargadas")
except:
    print("⚠️ SkinRestorer no disponible")

# ================= READ STATS =================
print("📊 Leyendo estadísticas...")
players = []

# Verificar advancements
advancements_available = False
try:
    sftp.chdir(ADVANCEMENTS_FOLDER)
    advancements_available = True
    print("✅ Carpeta de logros encontrada")
except:
    print("⚠️ Carpeta de logros no encontrada")

sftp.chdir(STATS_FOLDER)

for fname in sftp.listdir():
    if not fname.endswith(".json"):
        continue

    uuid = fname[:-5]
    name = uuid_to_name.get(uuid.replace("-", ""), uuid)

    try:
        with sftp.open(fname) as f:
            stats_data = json.load(f)
    except:
        continue

    s = stats_data.get("stats", {})
    mined = s.get("minecraft:mined", {}) or {}
    killed = s.get("minecraft:killed", {}) or {}
    custom = s.get("minecraft:custom", {}) or {}

    total_blocks = sum_values(mined)
    total_killed = sum_values(killed) + int(custom.get("minecraft:mob_kills", 0))
    deaths = int(custom.get("minecraft:deaths", 0))
    jumps = int(custom.get("minecraft:jump", 0))
    ticks = int(custom.get("minecraft:play_time", 0))
    time_txt = ticks_to_time(ticks)

    extras = {}
    for k, v in custom.items():
        if k not in ("minecraft:deaths", "minecraft:jump", "minecraft:play_time"):
            extras[k] = v
    
    # Leer logros/advancements si están disponibles
    advancements = {}
    if advancements_available:
        try:
            adv_file = f"{ADVANCEMENTS_FOLDER}/{fname}"
            with sftp.open(adv_file) as f:
                adv_data = json.load(f)
                for adv_key, adv_value in adv_data.items():
                    if isinstance(adv_value, dict) and adv_value.get("done", False):
                        advancements[adv_key] = adv_value
        except:
            pass

    players.append({
        "uuid": uuid,
        "name": name,
        "total_blocks": total_blocks,
        "total_killed": total_killed,
        "deaths": deaths,
        "jumps": jumps,
        "ticks": ticks,
        "time_txt": time_txt,
        "extras": extras,
        "advancements": advancements
    })

sftp.close()
ssh.close()

print(f"✅ {len(players)} jugadores encontrados")

# ================= CLASSIFY =================
print("🤖 Detectando bots...")
real = []
bots = []

for p in players:
    if is_bot(p):
        bots.append(p)
    else:
        real.append(p)

real.sort(key=lambda x: x["ticks"], reverse=True)
bots.sort(key=lambda x: x["ticks"], reverse=True)

real = real[:TOP_LIMIT]

print(f"👥 Jugadores reales: {len(real)}")
print(f"🤖 Bots detectados: {len(bots)}")

# ================= CALCULATE AGGREGATES =================
def calculate_aggregates(lst):
    """Calcula estadísticas agregadas del servidor"""
    total_time = sum(p["ticks"] for p in lst)
    total_blocks = sum(p["total_blocks"] for p in lst)
    total_kills = sum(p["total_killed"] for p in lst)
    total_deaths = sum(p["deaths"] for p in lst)
    
    total_distance = 0
    for p in lst:
        for key in ["minecraft:walk_one_cm", "minecraft:sprint_one_cm", "minecraft:fly_one_cm", 
                    "minecraft:swim_one_cm", "minecraft:aviate_one_cm", "minecraft:boat_one_cm",
                    "minecraft:minecart_one_cm", "minecraft:horse_one_cm"]:
            total_distance += int(p["extras"].get(key, 0))
    
    total_distance_km = total_distance / 100000
    
    return {
        "total_time": ticks_to_time(total_time),
        "total_blocks": f"{total_blocks:,}".replace(",", "."),
        "total_kills": f"{total_kills:,}".replace(",", "."),
        "total_deaths": f"{total_deaths:,}".replace(",", "."),
        "total_distance": f"{total_distance_km:,.0f}".replace(",", "."),
        "player_count": len(lst),
        "avg_time": ticks_to_time(total_time // len(lst)) if lst else "0m"
    }

server_stats = calculate_aggregates(real)

# ================= HTML BUILD =================
def get_skin_url(uuid, name, size=80):
    """Obtiene la URL de la skin"""
    uuid_clean = uuid.replace("-", "")
    if uuid_clean in skin_textures:
        return f"https://mc-heads.net/avatar/{skin_textures[uuid_clean]}/{size}"
    else:
        return f"https://mc-heads.net/avatar/{name}/{size}"

# Convertir datos a JSON
players_json = json.dumps([{
    "uuid": p["uuid"],
    "name": p["name"],
    "skin": get_skin_url(p["uuid"], p["name"], 80),
    "time_txt": p["time_txt"],
    "ticks": p["ticks"],
    "blocks": p["total_blocks"],
    "kills": p["total_killed"],
    "deaths": p["deaths"],
    "jumps": p["jumps"],
    "extras": p["extras"],
    "advancements": p.get("advancements", {})
} for p in real])

now = datetime.now().strftime("%d/%m/%Y %H:%M")

# Leer el template HTML
print("📝 Leyendo template HTML...")
template_path = os.path.join(os.path.dirname(__file__), 'template.html')

if not os.path.exists(template_path):
    print("❌ ERROR: No se encontró template.html")
    exit(1)

with open(template_path, 'r', encoding='utf-8') as f:
    html_template = f.read()

# Reemplazar variables
html = html_template.replace('{PLAYERS_DATA}', players_json)
html = html.replace('{SERVER_STATS}', json.dumps(server_stats))
html = html.replace('{UPDATE_TIME}', now)
html = html.replace('{PLAYER_COUNT}', str(server_stats['player_count']))
html = html.replace('{TOTAL_TIME}', server_stats['total_time'])
html = html.replace('{TOTAL_BLOCKS}', server_stats['total_blocks'])
html = html.replace('{TOTAL_DISTANCE}', server_stats['total_distance'])
html = html.replace('{TOTAL_KILLS}', server_stats['total_kills'])
html = html.replace('{AVG_TIME}', server_stats['avg_time'])

# ================= SAVE HTML =================
with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\n✅ Página web generada: {OUTPUT_HTML}")
print(f"📊 Estadísticas:")
print(f"   👥 Jugadores: {len(real)}")
print(f"   🤖 Bots: {len(bots)}")
print(f"   📅 Actualizado: {now}")
print("\n🚀 Listo para publicar en GitHub Pages!")
