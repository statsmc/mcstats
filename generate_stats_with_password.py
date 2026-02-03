#!/usr/bin/env python3
"""
Script CORREGIDO para generar estadísticas de Minecraft
- Detección de bots MEJORADA (más permisiva)
- Logging completo para debugging
- Manejo de errores robusto
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
    """
    Detección de bots MEJORADA - Más permisiva
    Solo marca como bot si es MUY obvio
    """
    name = p["name"]
    ticks = p["ticks"]
    blocks = p["total_blocks"]
    kills = p["total_killed"]
    jumps = p["jumps"]
    
    score = 0
    
    # 1. Tiempo de juego muy bajo (menos de 1 minuto)
    if ticks < 1200:  # Menos de 1 minuto
        score += 5
    
    # 2. Nombre sospechoso (muy estricto)
    name_lower = name.lower()
    obvious_bots = [
        r'^bot[_-]',           # bot_123, bot-test
        r'^test[_-]',          # test_user
        r'^npc[_-]',           # npc_villager
        r'^dummy',             # dummy, dummy123
        r'^fake',              # fake_player
    ]
    
    for pattern in obvious_bots:
        if re.match(pattern, name_lower):
            score += 10  # Muy sospechoso
            break
    
    # 3. Absolutamente sin actividad (ni un salto)
    if ticks > 1200 and blocks == 0 and kills == 0 and jumps == 0:
        score += 8
    
    # 4. UUID sospechoso (solo números/letras random)
    if re.match(r'^[0-9a-f]{32}$', name):  # UUID sin nombre
        score += 3
    
    # DECISIÓN: Solo marca como bot si score >= 12
    # Esto es MUY estricto, casi nadie será bot
    is_bot_result = score >= 12
    
    if is_bot_result:
        print(f"   🤖 Bot detectado: {name} (score: {score})")
    else:
        print(f"   👤 Jugador: {name} - {p['time_txt']} (score: {score})")
    
    return is_bot_result

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
    except:
        return None

print("📝 Cargando nombres de jugadores...")

uc = try_json("/usercache.json")
if uc:
    for e in uc:
        uuid_to_name[e["uuid"].replace("-", "")] = e["name"]
    print(f"✅ {len(uuid_to_name)} nombres cargados")

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
        except:
            continue
    
    print(f"✅ {len(skin_textures)} texturas cargadas")
except:
    print("⚠️  SkinRestorer no disponible")

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
        print("❌ ERROR: No hay archivos de estadísticas")
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

print(f"\n✅ {len(players)} jugadores procesados")

# ================= CLASSIFY =================
print("\n🤖 Clasificando jugadores y bots...")
print("-" * 60)

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

print("-" * 60)
print(f"\n📊 RESUMEN:")
print(f"   👥 Jugadores reales: {len(real)}")
print(f"   🤖 Bots detectados: {len(bots)}")

if len(real) == 0:
    print("\n⚠️  ADVERTENCIA: No hay jugadores reales!")
    print("   Todos fueron clasificados como bots")
    print("   Revisa los criterios de detección arriba")

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
} for p in real], ensure_ascii=False)

print(f"\n📝 JSON de jugadores generado:")
print(f"   Tamaño: {len(players_json)} caracteres")
print(f"   Jugadores en JSON: {len(real)}")

now = datetime.now().strftime("%d/%m/%Y %H:%M")

# Leer template
print("\n📄 Leyendo template HTML...")
template_path = 'template.html'

if not os.path.exists(template_path):
    print(f"❌ ERROR: No se encontró {template_path}")
    exit(1)

with open(template_path, 'r', encoding='utf-8') as f:
    html_template = f.read()

print(f"✅ Template leído: {len(html_template)} caracteres")

# VERIFICAR placeholder
print("\n🔍 Verificando placeholders...")
if '{PLAYERS_DATA}' in html_template:
    print("   ✅ {PLAYERS_DATA} encontrado")
else:
    print("   ❌ {PLAYERS_DATA} NO encontrado")
    if '{{PLAYERS_DATA}}' in html_template:
        print("   ⚠️  Corrigiendo {{PLAYERS_DATA}} → {PLAYERS_DATA}")
        html_template = html_template.replace('{{PLAYERS_DATA}}', '{PLAYERS_DATA}')

# Reemplazar placeholders
print("\n🔄 Reemplazando placeholders...")
html = html_template.replace('{PLAYERS_DATA}', players_json)
html = html.replace('{UPDATE_TIME}', now)
html = html.replace('{PLAYER_COUNT}', str(server_stats['player_count']))
html = html.replace('{TOTAL_TIME}', server_stats['total_time'])
html = html.replace('{TOTAL_BLOCKS}', server_stats['total_blocks'])
html = html.replace('{TOTAL_DISTANCE}', server_stats['total_distance'])
html = html.replace('{TOTAL_KILLS}', server_stats['total_kills'])
html = html.replace('{AVG_TIME}', server_stats['avg_time'])

# Verificar reemplazo
if '{PLAYERS_DATA}' in html:
    print("   ❌ ERROR: {PLAYERS_DATA} NO se reemplazó")
else:
    print("   ✅ Todos los placeholders reemplazados")

# Guardar
print(f"\n💾 Guardando {OUTPUT_HTML}...")
with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
    f.write(html)

size = os.path.getsize(OUTPUT_HTML)
print(f"✅ Archivo guardado: {size} bytes")

print("\n" + "=" * 60)
print("✅ GENERACIÓN COMPLETADA")
print("=" * 60)
print(f"📊 Estadísticas:")
print(f"   👥 Jugadores: {len(real)}")
print(f"   🤖 Bots: {len(bots)}")
print(f"   📅 Actualizado: {now}")
print(f"   📄 Archivo: {OUTPUT_HTML} ({size} bytes)")
print("\n🚀 Listo para GitHub Pages!")
