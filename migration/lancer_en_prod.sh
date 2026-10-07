#!/bin/bash
# Lance la migration (contacts puis inventaire) vers la PRODUCTION Odoo.sh.
# Demande l'adresse, la base, l'identifiant et la cle API (non affichee),
# verifie la connexion, lance les 2 scripts, puis efface la cle des fichiers.
# Usage : cd ~/odoo20-test/migration && bash lancer_en_prod.sh
set -e
cd "$(dirname "$0")"

for f in contacts_odoo.py inventaire_odoo.py; do
  [ -f "$f" ] || { echo "Fichier $f introuvable : lance d'abord python3 exporter_vers_odoo_sh.py"; exit 1; }
done

echo "=== Migration vers la PRODUCTION Odoo.sh ==="
read -r -p "Adresse de la production (ex. https://volcandesigndev-monroy.odoo.com) : " URL
URL="${URL%/}"; URL="${URL%/odoo}"
read -r -p "Nom de la base de production : " DB
read -r -p "Identifiant Odoo [hbassou@volcan.ca] : " LOGIN
LOGIN="${LOGIN:-hbassou@volcan.ca}"
read -r -s -p "Cle API de la production (rien ne s'affiche) : " CLE; echo

echo "Verification de la connexion..."
URL="$URL" DB="$DB" LOGIN="$LOGIN" CLE="$CLE" python3 - <<'EOF' || exit 1
import os, sys, xmlrpc.client
try:
    uid = xmlrpc.client.ServerProxy(os.environ["URL"] + "/xmlrpc/2/common").authenticate(
        os.environ["DB"], os.environ["LOGIN"], os.environ["CLE"], {})
except Exception as e:
    print("Connexion impossible :", e); sys.exit(1)
if not uid:
    print("Refuse : verifie le nom de la base, l'identifiant et la cle API (scope RPC)."); sys.exit(1)
print("Connexion OK.")
EOF

read -r -p "Lancer l'import des contacts PUIS de l'inventaire sur $URL ? (oui/non) : " OK
[ "$OK" = "oui" ] || { echo "Annule."; exit 0; }

ecrire() {  # $1 = cle a ecrire dans les fichiers
  for f in contacts_odoo.py inventaire_odoo.py; do
    python3 - "$f" "$URL" "$DB" "$LOGIN" "$1" <<'EOF'
import re, sys
f, url, db, login, cle = sys.argv[1:]
s = open(f, encoding="utf-8").read()
for k, v in (("URL", url), ("DB", db), ("USERNAME", login), ("PASSWORD", cle)):
    s = re.sub(rf'^{k}\s*=.*$', f'{k:<8} = {v!r}'.replace("'", '"'), s, count=1, flags=re.M)
open(f, "w", encoding="utf-8").write(s)
EOF
  done
}
trap 'ecrire "CLE_API"; echo "(cle API effacee des fichiers)"' EXIT
ecrire "$CLE"

echo; echo "=== 1/2 Contacts ==="
python3 contacts_odoo.py
echo; echo "=== 2/2 Inventaire ==="
python3 inventaire_odoo.py

echo
echo "Migration terminee. Pense a SUPPRIMER la cle API dans Odoo :"
echo "  Mon profil > Securite du compte > corbeille a cote de la cle."
