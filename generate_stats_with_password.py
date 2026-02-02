#!/usr/bin/env python3
"""
Script MEJORADO para generar estadísticas de Minecraft
- Mejor logging para debugging
- Manejo de errores mejorado
- Validación de datos
"""

import paramiko
import json
import hashlib
import re
import os
import base64
from datetime import datetime

# ================= CONFIG =================
SSH_HOST = os.getenv('MINECRAFT_SSH_HOST')
SSH_PORT = int(os.getenv('MINECRAFT_SSH_PORT', '22'))
SSH_USER = os.getenv('MINECRAFT_SSH_USER')
SSH_PASSWORD = os.getenv('MINECRAFT_SSH_PASSWORD')
WORLD_PATH = os.getenv('MINECRAFT_WORLD_PATH', '/world')

if not all([SSH_HOST, SSH_USER, SSH_PASSWORD]):
    print("❌ ERROR: Faltan variables de entorno")
    exit(1)

OUTPUT_HTML = "index.html"
TOP_LIMIT = 100

STATS_FOLDER = WORLD_PATH.rstrip("/") + "/stats"
ADVANCEMENTS_FOLDER = WORLD_PATH.rstrip("/") + "/advancements"

# ================= UTILS =================
def offline_uuid(name):
    base = ("OfflinePlayer:" + name).encode("utf-8")
    return hashlib.md5(base).hexdigest()

def ticks_to_time(ticks):
    seconds = ticks // 20
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}h {minutes}m"

def sum_values(d):
    try:
        return sum(int(v) for v in d.values())
    except:
        return 0

def is_bot(p):
    ticks = p["ticks"]
    blocks = p["total_blocks"]
    kills = p["total_killed"]
    jumps = p["jumps"]
    
    walk = int(p["extras"].get("minecraft:walk_one_cm", 0))
    sprint = int(p["extras"].get("minecraft:sprint_one_cm", 0))
    
    score = 0
    
    if ticks < 1200: score += 4
    if walk < 500 and sprint < 200: score += 3
    if blocks == 0 and kills == 0: score += 3
    if jumps == 0 and ticks > 600: score += 3
    
    name_lower = p["name"].lower()
    bot_patterns = [
        r"^(bot|npc|test|debug|dummy|fake|afk)",
        r"(bot|npc|test|afk)$",
    ]
    
    for pattern in bot_patterns:
        if re.match(pattern, name_lower):
            score += 5
            break
    
    return score >= 7

# ================= CONNECT SSH =================
print(f"🔌 Conectando a {SSH_HOST}:{SSH_PORT}...")

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

try:
    ssh.connect(
        SSH_HOST, 
        port=SSH_PORT, 
        username=SSH_USER, 
        password=SSH_PASSWORD,
        timeout=15
    )
    print("✅ Conexión SSH exitosa")
except Exception as e:
    print(f"❌ Error de conexión SSH: {e}")
    exit(1)

sftp = ssh.open_sftp()

# ================= UUID → NAME =================
uuid_to_name = {}

def try_json(path):
    try:
        with sftp.open(path) as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  No se pudo leer {path}: {e}")
        return None

print("📝 Cargando nombres de jugadores...")

uc = try_json("/usercache.json")
if uc:
    for e in uc:
        uuid_to_name[e["uuid"].replace("-", "")] = e["name"]
    print(f"✅ {len(uuid_to_name)} nombres cargados desde usercache.json")
else:
    print("⚠️  No se pudo cargar usercache.json")

# ================= LOAD SKINRESTORER =================
print("🎨 Cargando texturas de skins...")
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
        except Exception as e:
            continue
    
    print(f"✅ {len(skin_textures)} texturas cargadas")
except Exception as e:
    print(f"⚠️  SkinRestorer no disponible: {e}")

# ================= READ STATS =================
print(f"📊 Leyendo estadísticas desde {STATS_FOLDER}...")
players = []

# Verificar advancements
advancements_available = False
try:
    sftp.chdir(ADVANCEMENTS_FOLDER)
    advancements_available = True
    print("✅ Carpeta de logros encontrada")
except:
    print("⚠️  Carpeta de logros no encontrada")

try:
    sftp.chdir(STATS_FOLDER)
    files = sftp.listdir()
    json_files = [f for f in files if f.endswith('.json')]
    print(f"📁 {len(json_files)} archivos de estadísticas encontrados")
    
    if len(json_files) == 0:
        print("❌ ERROR: No hay archivos de estadísticas en la carpeta")
        print(f"   Verifica que existe: {STATS_FOLDER}")
        print(f"   Y que contiene archivos .json")
        sftp.close()
        ssh.close()
        exit(1)
        
except Exception as e:
    print(f"❌ ERROR al acceder a {STATS_FOLDER}: {e}")
    sftp.close()
    ssh.close()
    exit(1)

for fname in json_files:
    uuid = fname[:-5]
    name = uuid_to_name.get(uuid.replace("-", ""), uuid)

    try:
        with sftp.open(fname) as f:
            stats_data = json.load(f)
    except Exception as e:
        print(f"⚠️  Error leyendo {fname}: {e}")
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
    
    # Leer advancements
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

print(f"✅ {len(players)} jugadores procesados")

# ================= CLASSIFY =================
print("🤖 Clasificando jugadores y bots...")
real = []
bots = []

for p in players:
    if is_bot(p):
        bots.append(p)
        print(f"   🤖 Bot detectado: {p['name']}")
    else:
        real.append(p)
        print(f"   👤 Jugador: {p['name']} - {p['time_txt']}")

real.sort(key=lambda x: x["ticks"], reverse=True)
bots.sort(key=lambda x: x["ticks"], reverse=True)

real = real[:TOP_LIMIT]

print(f"\n📊 RESUMEN:")
print(f"   👥 Jugadores reales: {len(real)}")
print(f"   🤖 Bots detectados: {len(bots)}")

if len(real) == 0:
    print("\n❌ ERROR: No hay jugadores reales!")
    print("   Posibles causas:")
    print("   1. Todos fueron clasificados como bots")
    print("   2. No hay jugadores en el servidor")
    print("   3. Los archivos de stats están vacíos")
    print("\n💡 Solución: Revisa los criterios de detección de bots")
    # Continuar de todos modos para generar el HTML

# ================= CALCULATE AGGREGATES =================
def calculate_aggregates(lst):
    if not lst:
        return {
            "total_time": "0h 0m",
            "total_blocks": "0",
            "total_kills": "0",
            "total_deaths": "0",
            "total_distance": "0",
            "player_count": 0,
            "avg_time": "0h 0m"
        }
        
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
        "avg_time": ticks_to_time(total_time // len(lst)) if lst else "0h 0m"
    }

server_stats = calculate_aggregates(real)

# ================= HTML BUILD =================
def get_skin_url(uuid, name, size=80):
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
} for p in real], indent=2)

print(f"\n📝 JSON generado ({len(players_json)} caracteres)")
print(f"   Primeros 200 caracteres: {players_json[:200]}")

now = datetime.now().strftime("%d/%m/%Y %H:%M")

# Leer template
print("\n📄 Leyendo template HTML...")
template_path = 'template.html'

if not os.path.exists(template_path):
    print(f"❌ ERROR: No se encontró {template_path}")
    exit(1)

with open(template_path, 'r', encoding='utf-8') as f:
    html_template = f.read()

print(f"✅ Template leído ({len(html_template)} caracteres)")

# Reemplazar variables
print("\n🔄 Reemplazando placeholders...")
html = html_template.replace('{PLAYERS_DATA}', players_json)
html = html.replace('{SERVER_STATS}', json.dumps(server_stats))
html = html.replace('{UPDATE_TIME}', now)
html = html.replace('{PLAYER_COUNT}', str(server_stats['player_count']))
html = html.replace('{TOTAL_TIME}', server_stats['total_time'])
html = html.replace('{TOTAL_BLOCKS}', server_stats['total_blocks'])
html = html.replace('{TOTAL_DISTANCE}', server_stats['total_distance'])
html = html.replace('{TOTAL_KILLS}', server_stats['total_kills'])
html = html.replace('{AVG_TIME}', server_stats['avg_time'])

# Verificar que se reemplazaron
if '{PLAYERS_DATA}' in html:
    print("⚠️  WARNING: {PLAYERS_DATA} no se reemplazó")
if '{UPDATE_TIME}' in html:
    print("⚠️  WARNING: {UPDATE_TIME} no se reemplazó")

# Guardar
print(f"\n💾 Guardando {OUTPUT_HTML}...")
with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
    f.write(html)

print(f"✅ Archivo guardado ({len(html)} caracteres)")

# Verificar que se guardó
if os.path.exists(OUTPUT_HTML):
    size = os.path.getsize(OUTPUT_HTML)
    print(f"✅ {OUTPUT_HTML} creado ({size} bytes)")
else:
    print(f"❌ ERROR: No se pudo crear {OUTPUT_HTML}")
    exit(1)

print("\n" + "=" * 60)
print("✅ GENERACIÓN COMPLETADA")
print("=" * 60)
print(f"📊 Estadísticas:")
print(f"   👥 Jugadores: {len(real)}")
print(f"   🤖 Bots: {len(bots)}")
print(f"   📅 Actualizado: {now}")
print(f"   📄 Archivo: {OUTPUT_HTML}")
print("\n🚀 Listo para GitHub Pages!")
