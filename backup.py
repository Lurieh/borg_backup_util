import os
import sys
import subprocess
import shutil
import tomllib
from datetime import datetime
# Autorise Borg à accéder au dépôt même si le chemin de montage a changé
os.environ["BORG_RELOCATED_REPO_ACCESS_IS_OK"] = "yes"

def get_mount_point(uuid):
    try:
        # On ajoute text=True pour manipuler des strings et non des bytes
        out = subprocess.check_output(
            ["findmnt", "-rn", "-S", f"UUID={uuid}", "-o", "TARGET"], 
            text=True
        )
        # On split par ligne et on prend la première (au cas où le disque est monté 2x)
        lines = out.strip().split('\n')
        return lines[0] if lines else None
    except:
        return None

def check_space(path, threshold_gb):
    stat = shutil.disk_usage(path)
    free_gb = stat.free / (1024**3)
    if free_gb < threshold_gb:
        print(f"⚠️ ATTENTION : Espace faible ({free_gb:.1f} Go libres).")
        confirm = input(f"Le seuil est de {threshold_gb} Go. Taper 'OUI' pour forcer : ")
        return confirm == "OUI"
    return True

# --- 1. Chemins de base ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.toml")

# --- 2. Chargement Config ---
if not os.path.exists(CONFIG_PATH):
    print(f"❌ Erreur : Impossible de trouver {CONFIG_PATH}")
    sys.exit(1)

with open(CONFIG_PATH, "rb") as f:
    config = tomllib.load(f)

# --- 3. Localisation du disque via UUID ---
mnt = get_mount_point(config['global']['uuid'])
if not mnt:
    print(f"❌ Erreur : Disque USB (UUID {config['global']['uuid']}) introuvable.")
    sys.exit(1)

# --- 4. Sélection du Contexte ---
ctx_keys = list(config['contextes'].keys())
print("\n--- GESTIONNAIRE DE SAUVEGARDE BORG ---")
for i, k in enumerate(ctx_keys):
    print(f"[{i}] {k} : {config['contextes'][k]['description']}")

try:
    choice = int(input("\nChoisissez un contexte : "))
    ctx = config['contextes'][ctx_keys[choice]]
except (ValueError, IndexError):
    print("Choix invalide.")
    sys.exit(1)

# --- 5. Préparation des Chemins (Maintenant que 'ctx' existe) ---
# Chemin absolu vers le dépôt (résolu par rapport au script)
repo_path = os.path.abspath(os.path.join(SCRIPT_DIR, config['global']['repo_relative_path']))
# Chemin absolu vers le fichier d'exclusion
exclude_path = os.path.join(SCRIPT_DIR, ctx['exclude_file'])
# Gestion des logs
log_dir = os.path.join(SCRIPT_DIR, "logs")
os.makedirs(log_dir, exist_ok=True)

timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
log_file = os.path.join(log_dir, f"{ctx['prefix']}_{timestamp}.log")

# --- 6. Vérifications de sécurité ---
if not check_space(mnt, config['global']['free_space_threshold_gb']):
    print("Abandon par l'utilisateur.")
    sys.exit(0)

# --- 7. Exécution Borg avec feedback temps réel ---
archive_name = f"{ctx['prefix']}-{timestamp}"
print(f"\n🚀 Démarrage : {archive_name}")

cmd_create = [
    "borg", "create", "--stats", "--compression", "zstd,3",
    f"{repo_path}::{archive_name}", ctx['source'],
    "--exclude-from", exclude_path
]

# On utilise Popen pour streamer la sortie
with open(log_file, "w") as f_log:
    process = subprocess.Popen(cmd_create, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    
    # On lit ligne par ligne
    for line in process.stdout:
        sys.stdout.write(line) # Affiche dans la console
        f_log.write(line)      # Écrit dans le log
        
    process.wait() # On attend la fin propre du processus

# --- 8. Pruning ---
print(f"\n🧹 Élagage (Rétention : {ctx['keep_archives']} versions)...")
cmd_prune = [
    "borg", "prune", "-v", "--list", repo_path,
    "--prefix", f"{ctx['prefix']}-",
    "--keep-last", str(ctx['keep_archives'])
]
subprocess.run(cmd_prune)

print(f"\n✅ Terminé. Log disponible ici : {log_file}")
