# -*- coding: utf-8 -*-
"""
MPA V1 — suite de non-régression : la spécification exécutable.
Rejoue chaque exigence des spécifications fonctionnelles V1.1 (F-xx / RG-xx)
contre l'API, avec assertions dures. Usage : python3 nonreg_v1.py [dossier]
"""
import importlib, json, threading, time, urllib.request, urllib.error, socket, sys, os
from decimal import Decimal

DIR = sys.argv[1] if len(sys.argv) > 1 else "."
sys.path.insert(0, os.path.abspath(DIR))
import mpa_core, mpa_api
importlib.reload(mpa_core); importlib.reload(mpa_api)
from http.server import ThreadingHTTPServer

s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
httpd = ThreadingHTTPServer(("127.0.0.1", PORT), mpa_api.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start(); time.sleep(0.3)
B = f"http://127.0.0.1:{PORT}"

def req(m, p, b=None):
    d = json.dumps(b).encode() if b is not None else None
    r = urllib.request.Request(B+p, data=d, method=m, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r, timeout=8) as x:
            ct = x.headers.get("Content-Type", "")
            raw = x.read()
            return x.status, (json.loads(raw) if "json" in ct else raw.decode()), ct
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read()), "json"
        except Exception: return e.code, {}, ""

N, FAILS = 0, []
def T(label, cond, detail=""):
    global N
    N += 1
    tag = "OK " if cond else "FAIL"
    print(f"  [{tag}] {N:02d} · {label}" + (f"  — {detail}" if (detail and not cond) else ""))
    if not cond: FAILS.append(label)

def pmv(aid):
    _, a, _ = req("GET", f"/api/assures/{aid}")
    e = a["pmv"]
    return {k: Decimal(e[k]) for k in ("credit_cumule", "disponible", "engage", "paye", "solde")}

def eq_ok(aid):
    e = pmv(aid)
    return (e["credit_cumule"] - e["paye"] == e["solde"]
            and e["solde"] - e["engage"] == e["disponible"]
            and min(e.values()) >= 0)

print("═"*74); print("  MPA V1 — spécification exécutable (specs V1.1 du 06/11/2026)"); print("═"*74)

# ── Seed & §9 numérotation ───────────────────────────────────────────────
_, st, _ = req("GET", "/api/state")
lea = next(a for a in st["assures"] if a["prenom"] == "Léa")
cla = next(a for a in st["assures"] if a["prenom"] == "Claire")
an = time.localtime().tm_year % 100
T("§9 n° de dossier GSA-AA-NNNNN", lea["id"] == f"GSA-{an:02d}-00001" and cla["id"] == f"GSA-{an:02d}-00002", lea["id"])
T("§9 références dérivées -Dnn", all(d["id"].startswith(cla["id"]+"-D") for d in st["devis"]))
T("F-43 équations du PMV (seed)", eq_ok(cla["id"]) and eq_ok(lea["id"]))
T("§7.3 états seed : Verrouillé RIB / Utilisable", lea["pmv_etat"] == "verrou_rib" and cla["pmv_etat"] == "utilisable")
T("Dossier : Pré-inscrit / Actif", lea["etat_dossier"] == "Pré-inscrit" and cla["etat_dossier"] == "Actif")

# ── F-20 / RG-41 / RG-13 : pré-inscription ───────────────────────────────
c, r, _ = req("POST", "/api/preinscriptions", {"prenom":"Paul","nom":"Martin","email":"p@x.fr",
    "contrat_ref":"GSA-2026-0002 — Branche de l'édition","ndd":2,"credit":"1200",
    "pfd":{"prenom":"Jeanne","lien":"Mère","naissance":"1945","ndd":2},"commentaire":"Décision du 05/11"})
paul = r["id"] if c == 201 else None
T("F-20 pré-inscription complète (201)", c == 201 and r["pmv"]["credit_cumule"] == "1200.00")
T("RG-41 PFD principal présent dès l'ouverture", c == 201 and any(x["principal"] for x in r["aides"]))
c2, r2, _ = req("POST", "/api/preinscriptions", {"prenom":"X","nom":"Y","email":"x@y.fr",
    "contrat_ref":"", "ndd":2, "credit":"100", "pfd":{}})
T("RG-41 refus sans PFD principal", c2 == 400 and "PFD" in r2.get("error",""))
c3, r3, _ = req("POST", "/api/preinscriptions", {"prenom":"X","nom":"Y","email":"x@y.fr",
    "contrat_ref":"", "ndd":5, "credit":"100", "pfd":{"prenom":"A","lien":"Père","naissance":"1940"}})
T("RG-13 refus NDD 5", c3 == 400 and "RG-13" in r3.get("error",""))
_, ems, _ = req("GET", "/api/emails")
act = [e for e in ems["emails"] if paul and paul in e["objet"] and "Activez" in e["objet"]]
T("F-20 lien d'activation adressé (e-mail simulé)", bool(act) and f"?dossier={paul}" in act[0]["corps"])

# ── F-40/41/42 : activation, double verrou ───────────────────────────────
c, r, _ = req("POST", "/api/devis", {"assure_id": paul, "prestation_id": "PR-86"})
T("RG-42 devis refusé : verrou 1 (RIB)", c == 400 and "RIB" in r.get("error",""))
c, r, _ = req("POST", f"/api/assures/{paul}/profil", {"iban":"FR00INVALIDE"})
T("F-41 IBAN invalide refusé", c == 400)
req("POST", f"/api/assures/{paul}/profil", {"iban":"FR7630006000011234567890189","telephone":"0600000000"})
_, a, _ = req("GET", f"/api/assures/{paul}")
T("§7.3 Verrouillé RIB → Verrouillé PFD", a["pmv_etat"] == "verrou_pfd")
c, r, _ = req("POST", "/api/devis", {"assure_id": paul, "prestation_id": "PR-86"})
T("RG-42 devis refusé : verrou 2 (profil PFD)", c == 400 and "proche" in r.get("error",""))
pfd_id = next(x["id"] for x in a["aides"] if x["principal"])
req("POST", f"/api/assures/{paul}/aides/{pfd_id}/profil", {"profil":{"lieu":"Domicile, seul(e)","mobilite":"Marche avec aide"}})
_, a, _ = req("GET", f"/api/assures/{paul}")
T("F-42 PMV utilisable après les 2 verrous", a["pmv_etat"] == "utilisable" and a["etat_dossier"] == "Actif")

# ── F-47 / F-60 / F-48 / RG-51 : cycle devis jusqu'à l'engagement ────────
_, d, _ = req("POST", "/api/devis", {"assure_id": paul, "prestation_id": "PR-86", "message": "Dossier MDPH, le mercredi."})
did = d["id"]
T("§9 réf. devis dérivée", did == f"{paul}-D01")
_, emn, _ = req("GET", "/api/emails")
mail_pro = [e for e in emn["emails"] if did in e["objet"]]
T("F-47 e-mail au pro : n° dossier + lien + consigne facture", bool(mail_pro) and paul in mail_pro[0]["corps"] and "Lien sécurisé" in mail_pro[0]["corps"])
c, r, _ = req("POST", f"/api/devis/{did}/etablir", {"quantite": 0})
T("F-60 quantité > 0 exigée", c == 400)
req("POST", f"/api/devis/{did}/etablir", {"quantite": 4, "message_pro": "OK pour deux mercredis."})
avant = pmv(paul)
c, d, _ = req("POST", f"/api/devis/{did}/accepter")
apres = pmv(paul)
T("F-48/RG-51 acceptation = engagement automatique", c == 200 and d["statut"] == "engagé"
  and apres["engage"] - avant["engage"] == Decimal("112.00") and eq_ok(paul))
c, r, _ = req("POST", "/api/devis", {"assure_id": paul, "prestation_id": "PR-54", "message": ""})
big = r["id"]; req("POST", f"/api/devis/{big}/etablir", {"quantite": 9999})
c, r, _ = req("POST", f"/api/devis/{big}/accepter")
T("RG-43 engagement > disponible refusé", c == 400 and "disponible" in r.get("error",""))
req("POST", f"/api/devis/{big}/refuser")
_, df, _ = req("POST", "/api/devis", {"assure_id": paul, "prestation_id": "PR-27", "message": ""})
T("F-47 forfait → « devisé » immédiat", df["statut"] == "devisé" and df["total"] == "65.00")
c, r, _ = req("POST", f"/api/devis/{df['id']}/refuser-pro", {"motif": ""})
T("F-60 refus pro sans motif refusé", c == 400)
c, r, _ = req("POST", f"/api/devis/{df['id']}/refuser-pro", {"motif": "Agenda complet"})
T("F-60 décliner avec motif", c == 200 and r["statut"] == "refusé" and "Agenda" in r["motif_refus"])

# ── F-61 / F-49 / RG-52 : réalisation, service fait, AUCUN paiement auto ─
req("POST", f"/api/devis/{did}/realisee")
_, d, _ = req("GET", "/api/state"); dv = next(x for x in d["devis"] if x["id"] == did)
import datetime
ech = datetime.date.fromisoformat(dv["echeance_confirmation"]) - datetime.date.fromisoformat(dv["date_realisee"])
T("F-61 échéance = réalisation + délai (A-3)", ech.days == mpa_core.DELAI_CONFIRMATION_JOURS)
c, r, _ = req("POST", f"/api/devis/{did}/payer", {})
T("RG-52 paiement refusé sans service fait", c == 400 and "RG-52" in r.get("error",""))
c, r, _ = req("POST", f"/api/devis/{did}/contester", {"motif": ""})
T("F-49 contestation sans commentaire refusée", c == 400)
req("POST", f"/api/devis/{did}/contester", {"motif": "Deux heures seulement ont été assurées."})
c, r, _ = req("POST", f"/api/devis/{did}/service-fait", {})
T("F-49 devis contesté : l'assuré-aidant ne peut plus confirmer seul", c == 400)
_, al, _ = req("GET", "/api/alertes")
T("F-25 contestation dans les alertes", any(x["type"] == "contestation" and x["devis_id"] == did for x in al["alertes"]))
c, r, _ = req("POST", f"/api/devis/{did}/service-fait", {"par": "gestionnaire", "motif": ""})
T("F-25 décision gestionnaire sans motif refusée", c == 400)
c, r, _ = req("POST", f"/api/devis/{did}/service-fait", {"par": "gestionnaire", "motif": "Accord trouvé au téléphone le 06/11"})
T("F-25 confirmation pour le compte (motif tracé)", c == 200 and r["service_fait"] and "gestionnaire" in r["confirme_par"])
mid = pmv(paul)
c, r, _ = req("POST", f"/api/devis/{did}/payer", {"montant": "9999"})
T("RG-53 paiement > engagé refusé", c == 400 and "RG-53" in r.get("error",""))
c, r, _ = req("POST", f"/api/devis/{did}/payer", {"montant": "84", "commentaire": "2 h non assurées — accord"})
fin = pmv(paul)
T("F-22 paiement MANUEL partiel : engagé→payé, reliquat→disponible",
  c == 200 and r["statut"] == "payé" and r["montant_paye"] == "84.00"
  and fin["paye"] - mid["paye"] == Decimal("84.00")
  and fin["disponible"] - mid["disponible"] == Decimal("28.00") and eq_ok(paul))
_, emp, _ = req("GET", "/api/emails")
T("F-24 e-mail « virement effectué » à l'assuré-aidant", any("Paiement effectué" in e["objet"] and did in e["objet"] for e in emp["emails"]))

# ── F-25 annulation → désengagement intégral ─────────────────────────────
_, d2, _ = req("POST", "/api/devis", {"assure_id": paul, "prestation_id": "PR-86", "message": ""})
d2 = d2["id"]; req("POST", f"/api/devis/{d2}/etablir", {"quantite": 2}); req("POST", f"/api/devis/{d2}/accepter")
req("POST", f"/api/devis/{d2}/realisee")
avant = pmv(paul)
c, r, _ = req("POST", f"/api/devis/{d2}/annuler", {"motif": "Prestation non réalisée — pro injoignable"})
apres = pmv(paul)
T("F-25 annulation : désengagement intégral", c == 200 and r["statut"] == "annulé"
  and apres["disponible"] - avant["disponible"] == Decimal("56.00") and eq_ok(paul))

# ── F-51 / F-23 / RG-44 : remboursements ─────────────────────────────────
c, r, _ = req("POST", "/api/remboursements", {"assure_id": paul, "libelle": "Taxi", "motif": "Transport", "montant": "30", "justificatif_nom": ""})
T("F-51 justificatif obligatoire", c == 400)
c, r, _ = req("POST", "/api/remboursements", {"assure_id": paul, "libelle": "Taxi", "motif": "Transport",
    "montant": "30", "justificatif_nom": "taxi.svg",
    "justificatif_data": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4="})
rid = r["id"]
T("§9 réf. remboursement -R01", c == 201 and rid == f"{paul}-R01")
c, raw, ct = req("GET", f"/api/remboursements/{rid}/justificatif")
T("F-51 justificatif consultable (content-type)", c == 200 and "svg" in ct)
req("POST", f"/api/remboursements/{rid}/piece")
c, r, _ = req("POST", f"/api/remboursements/{rid}/redeposer", {"justificatif_nom": "taxi2.svg", "justificatif_data": ""})
T("§7.2 nouveau dépôt → retour à « soumise »", c == 200 and r["statut"] == "soumise")
avant = pmv(paul)
c, r, _ = req("POST", f"/api/remboursements/{rid}/valider")
apres = pmv(paul)
T("F-23 « validée » ENGAGE le PMV", c == 200 and r["statut"] == "validée"
  and apres["engage"] - avant["engage"] == Decimal("30.00") and eq_ok(paul))
c, r, _ = req("POST", f"/api/remboursements/{rid}/payer", {})
T("F-23 marquer payée : engagé→payé + date", c == 200 and r["statut"] == "payée" and r["date_paiement"] and eq_ok(paul))
# RG-44 partiel automatique à hauteur du disponible
dispo = pmv(paul)["disponible"]
c, r, _ = req("POST", "/api/remboursements", {"assure_id": paul, "libelle": "Gros frais", "motif": "Répit",
    "montant": str(dispo + 500), "justificatif_nom": "g.svg"})
c, r, _ = req("POST", f"/api/remboursements/{r['id']}/valider")
T("RG-44 validation partielle automatique (= disponible)", c == 200 and r["partiel"] and Decimal(r["montant_valide"]) == dispo)
c2, r2, _ = req("POST", f"/api/remboursements/{r['id']}/refuser", {"motif": "x"})
T("§7.2 refus impossible après validation", c2 == 400)

# ── F-22/F-23 : marquage de PLUSIEURS paiements en une fois (seed Claire) ─
fileP = [d["id"] for d in st["devis"] if d["statut"] == "réalisée" and d["service_fait"]]
fileR = [x["id"] for x in st["remboursements"] if x["statut"] == "validée"]
c, lot, _ = req("POST", "/api/paiements", {"devis": fileP, "remboursements": fileR, "commentaire": "Virements CERA"})
T("F-22/23 marquage en lot", c == 200 and len(lot["payes"]) == len(fileP) + len(fileR) and not lot["erreurs"] and eq_ok(cla["id"]))

# ── F-21 : crédit manuel — correction tracée (recharge aussi le dossier) ─
avant = pmv(paul)
c, r, _ = req("POST", f"/api/assures/{paul}/crediter", {"montant": "200", "motif": "Correction", "commentaire": "Rétablissement après trop-validé (test)"})
T("F-21 crédit manuel journalisé (Correction +200)", c == 200
  and Decimal(r["pmv"]["credit_cumule"]) - avant["credit_cumule"] == Decimal("200.00") and eq_ok(paul))
c, r, _ = req("POST", f"/api/assures/{paul}/crediter", {"montant": "-50", "motif": "Correction", "commentaire": "Mouvement inverse tracé"})
T("F-21 correction négative = mouvement inverse tracé", c == 200 and eq_ok(paul))
c, r, _ = req("POST", f"/api/assures/{paul}/crediter", {"montant": "-99999", "motif": "Correction"})
T("F-21 correction négative > disponible refusée", c == 400)
c, r, _ = req("POST", f"/api/assures/{paul}/crediter", {"montant": "-10", "motif": "Crédit initial"})
T("F-21 crédit initial négatif refusé", c == 400)

# ── F-27 / RG-50 : blocage ───────────────────────────────────────────────
c, r, _ = req("POST", f"/api/assures/{paul}/bloquer", {"motif": ""})
T("F-27 blocage sans motif refusé", c == 400)
avant = pmv(paul)
req("POST", f"/api/assures/{paul}/bloquer", {"motif": "Vérification RG-49 en cours"})
_, a, _ = req("GET", f"/api/assures/{paul}")
T("RG-50 le blocage ne retire aucun crédit", a["pmv_etat"] == "bloque" and pmv(paul) == avant)
c, r, _ = req("POST", "/api/devis", {"assure_id": paul, "prestation_id": "PR-86"})
T("F-27 bloqué : nouveau devis refusé", c == 400 and "bloqué" in r.get("error",""))
c, r, _ = req("POST", "/api/remboursements", {"assure_id": paul, "libelle": "x", "motif": "x", "montant": "5", "justificatif_nom": "x.svg"})
T("F-27 bloqué : remboursement refusé", c == 400)
# engagement en cours honoré : devis engagé AVANT blocage → réalisée + service fait + payé
_, d3, _ = req("POST", f"/api/assures/{paul}/debloquer", {"commentaire": "pour préparer le cas"})
_, d3, _ = req("POST", "/api/devis", {"assure_id": paul, "prestation_id": "PR-86", "message": ""})
d3 = d3["id"]; req("POST", f"/api/devis/{d3}/etablir", {"quantite": 1}); req("POST", f"/api/devis/{d3}/accepter")
req("POST", f"/api/assures/{paul}/bloquer", {"motif": "Nouveau blocage"})
req("POST", f"/api/devis/{d3}/realisee"); req("POST", f"/api/devis/{d3}/service-fait", {})
c, r, _ = req("POST", f"/api/devis/{d3}/payer", {})
T("F-27 engagements en cours honorés malgré le blocage", c == 200 and r["statut"] == "payé")
req("POST", f"/api/assures/{paul}/debloquer", {"commentaire": "Vérification levée"})

# ── F-26 : commentaire d'un mouvement ────────────────────────────────────
_, a, _ = req("GET", f"/api/assures/{paul}")
mv = a["pmv"]["mouvements"][0]["id"]
c, r, _ = req("POST", f"/api/assures/{paul}/mouvements/{mv}/commenter", {"commentaire": "Crédit validé par le comité du 05/11"})
T("F-26 commentaire visible dans le journal", c == 200 and r["pmv"]["mouvements"][0]["commentaire"].startswith("Crédit validé"))

# ── F-70 : alerte délai (seed D03) + tâche quotidienne ───────────────────
_, al, _ = req("GET", "/api/alertes")
T("F-70 alerte « délai expiré » (seed D03) — aucune libération auto",
  any(x["type"] == "delai_expire" for x in al["alertes"])
  and all(dd["statut"] != "payé" or dd["service_fait"] for dd in req("GET","/api/state")[1]["devis"]))
c, t, _ = req("POST", "/api/tache-quotidienne")
T("F-70 tâche quotidienne exécutable", c == 200 and "alerte" in t["message"])

# ── F-52 : contact conseiller ────────────────────────────────────────────
c, r, _ = req("POST", f"/api/assures/{paul}/contacts", {"type": "chatbot", "message": "x"})
T("F-52 type de contact contrôlé (aucun chatbot)", c == 400)
c, r, _ = req("POST", f"/api/assures/{paul}/contacts", {"type": "rendez-vous", "message": "Mercredi matin de préférence"})
_, a, _ = req("GET", f"/api/assures/{paul}")
T("F-52 demande enregistrée, visible gestionnaire", c == 201 and any(x["type"] == "rendez-vous" for x in a["contacts"]))

# ── F-28 : exports CSV ───────────────────────────────────────────────────
heads = {"dossiers": "N_dossier;Nom", "mouvements": "N_dossier;Date;Type",
         "devis": "Reference;N_dossier", "remboursements": "Reference;N_dossier"}
okx = True
for quoi, head in heads.items():
    c, csv, ct = req("GET", f"/api/exports/{quoi}.csv")
    okx = okx and c == 200 and "csv" in ct and head in csv.splitlines()[0]
T("F-28 exports CSV (4) avec en-têtes", okx)

# ── F-44/F-45 : assistant (sans clé → repli) ─────────────────────────────
c, r, _ = req("POST", "/api/analyse/generer", {"prompt": "x"})
T("F-44 bilan : LLM absent → null (repli client déterministe)", c == 200 and r["texte"] is None)
c, r, _ = req("POST", "/api/anticiper2", {"prompt": "x"})
T("F-45/RG-63 besoins : LLM absent → null (repli client)", c == 200 and r["text"] is None)
c, r, _ = req("POST", f"/api/assures/{paul}/analyse", {"texte": "Bilan validé par l'assuré-aidant."})
T("F-44 seule la version validée est stockée", c == 200 and r["analyse"].startswith("Bilan validé"))

# ── F-72 : catalogue ─────────────────────────────────────────────────────
_, cat, _ = req("GET", "/api/catalogue")
T("F-72 catalogue aidance-pro chargé (source explicite)", len(cat["prestations"]) >= 80 and cat["source"] in ("snapshot", "aidance-pro"))

httpd.shutdown()
print("─"*74)
print(f"  {N} vérifications · {N-len(FAILS)} OK · {len(FAILS)} échec(s)")
if FAILS:
    for f in FAILS: print("   ✗", f)
    sys.exit(1)
print("  CONFORME aux spécifications V1.1.")
