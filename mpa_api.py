# -*- coding: utf-8 -*-
"""
MPA — API HTTP V1 (spécifications fonctionnelles V1.1 du 6 novembre 2026)
=========================================================================

Expose le cœur de domaine (mpa_core) en HTTP. Deux espaces (Assuré-aidant ·
Gestionnaire indemnisation) ; le professionnel n'a PAS de compte : il répond via
/?pro=<jeton> (A-1a), un formulaire mono-demande servi par les routes /api/pro/…
qui n'exposent QUE le nécessaire (n° de dossier, besoin exprimé, prestation).
stdlib uniquement (http.server), CORS ouvert, shell servi sur /.

Lancement :   python3 mpa_api.py            (port 8765, ou variable PORT)

Table des routes
----------------
  GET  /                                        shell (mpa_demo.html) ; ?pro=<jeton> ->
                                                formulaire pro mono-demande (A-1a)
  GET  /api/state                               instantané complet
  GET  /api/diag[?ping=1]                       diagnostic (clé LLM, catalogue)
  GET  /api/catalogue                           pros + prestations + départements
  GET  /api/assures/<n° dossier>                un dossier + journal PMV
  GET  /api/alertes                             F-25/F-70 : délais expirés, contestations
  GET  /api/emails                              notifications e-mail SIMULÉES
  GET  /api/exports/<quoi>.csv                  F-28 : dossiers|mouvements|devis|remboursements
  GET  /api/remboursements/<réf>/justificatif   F-51 : pièce déposée (PDF/image)
  POST /api/reset                               réinitialise le jeu d'essai
  POST /api/preinscriptions                     F-20 (PFD principal OBLIGATOIRE, crédit libre)
  POST /api/assures/<id>/profil                 F-41 (RIB, verrou 1)
  POST /api/assures/<id>/aides                  PFD complémentaire
  POST /api/assures/<id>/aides/<pfd>/profil     F-42 (verrou 2)
  POST /api/assures/<id>/analyse                F-44 (bilan validé)
  POST /api/assures/<id>/crediter               F-21 {montant, motif, commentaire}
  POST /api/assures/<id>/bloquer|debloquer      F-27 {motif}/{commentaire}
  POST /api/assures/<id>/mouvements/<mv>/commenter   F-26 {commentaire}
  POST /api/assures/<id>/contacts               F-52 {type, message}
  GET  /api/pro/<jeton>                         A-1a : la demande, vue PRO (minimisée —
                                                n° dossier, besoin, prestation ; compte
                                                les ouvertures, plafond « usage limité »)
  POST /api/pro/<jeton>/etablir                 F-60 {quantite, message_pro}
  POST /api/pro/<jeton>/refuser                 F-60 {motif}
  POST /api/pro/<jeton>/realisee                F-61 — ouvre le délai A-3
  POST /api/devis                               F-47 {assure_id, prestation_id, message, lien_base?}
  POST /api/devis/<réf>/accepter                F-48 = engagement automatique (RG-51)
  POST /api/devis/<réf>/refuser                 F-48 (assuré-aidant)
  POST /api/devis/<réf>/service-fait            F-49 {par?, motif?} (gestionnaire : F-25)
  POST /api/devis/<réf>/contester               F-49 {motif}
  POST /api/devis/<réf>/payer                   F-22 {montant?, commentaire?} — MANUEL (RG-52/53)
  POST /api/devis/<réf>/annuler                 F-25 {motif} — désengagement intégral
  POST /api/paiements                           F-22/F-23 marquage EN LOT {devis:[réfs], remboursements:[réfs], commentaire?}
  POST /api/remboursements                      F-51 {assure_id, libelle, motif, montant, justificatif_nom, justificatif_data?}
  POST /api/remboursements/<réf>/valider        F-23 (partiel auto RG-44 ; engage le PMV)
  POST /api/remboursements/<réf>/refuser        F-23 {motif}
  POST /api/remboursements/<réf>/piece          F-23
  POST /api/remboursements/<réf>/redeposer      §7.2 {justificatif_nom, justificatif_data?}
  POST /api/remboursements/<réf>/payer          F-23 (après virement, marquer payée)
  POST /api/tache-quotidienne                   F-70 (déclenchement manuel en maquette)
  POST /api/anticiper2                          F-45 proxy LLM (taxonomie fermée)
  POST /api/analyse/generer                     F-44 bilan situationnel (~40 lignes)
"""

import base64
import json
import os
import sys
import threading
from dataclasses import fields, is_dataclass
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import mpa_core as core

HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mpa_demo.html")


# --------------------------------------------------------------------------- #
#  État partagé (un seul Store) + moteurs
# --------------------------------------------------------------------------- #
class App:
    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.store = core.seed()
        self.dossiers = core.MoteurDossiers(self.store)
        self.devis = core.MoteurDevis(self.store)
        self.remb = core.MoteurRemboursement(self.store)


APP = App()


# --------------------------------------------------------------------------- #
#  Sérialisation
# --------------------------------------------------------------------------- #
def jsonable(o):
    if isinstance(o, Decimal):
        return str(o)
    if is_dataclass(o):
        return {f.name: jsonable(getattr(o, f.name)) for f in fields(o)}
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(x) for x in o]
    return o


def pmv_view(env):
    """F-43 — les 5 chiffres et le journal complet."""
    if env is None:
        return None
    return {
        "credit_cumule": str(env.credit_cumule),
        "disponible": str(env.disponible),
        "engage": str(env.engage),
        "paye": str(env.paye),
        "solde": str(env.solde),
        "iban": env.iban,
        "bloque": env.bloque,
        "motif_blocage": env.motif_blocage,
        "mouvements": [jsonable(m) for m in env.mouvements],
    }


def remb_view(r):
    d = jsonable(r)
    d["justificatif_data"] = ""                       # jamais dans le state (poids)
    d["a_justificatif"] = bool(r.justificatif_data)
    return d


def pro_view(d, store):
    """A-1a — vue du formulaire pro : LE STRICT NÉCESSAIRE (minimisation).
    Ni identité de l'assuré-aidant, ni PMV, ni profils : n° de dossier,
    besoin exprimé, prestation, étape et consignes de facturation."""
    p = store.prestations.get(d.prestation_id)
    pro = store.pros.get(d.pro_id)
    return {
        "jeton": d.jeton,
        "ref": d.id,
        "dossier": d.assure_id,                       # = n° de dossier (§9)
        "statut": d.statut,
        "besoin": d.message,                          # F-47 — besoin exprimé
        "message_pro": d.message_pro,
        "quantite": str(d.quantite) if d.quantite is not None else None,
        "total": str(d.total) if d.total is not None else None,
        "date_demande": d.date_demande,
        "date_realisee": d.date_realisee,
        "echeance_confirmation": d.echeance_confirmation,
        "service_fait": d.service_fait,
        "motif_contestation": d.motif_contestation,
        "motif_refus": d.motif_refus,
        "motif_annulation": d.motif_annulation,
        "montant_paye": str(d.montant_paye) if d.montant_paye is not None else None,
        "date_paiement": d.date_paiement,
        "commentaire_paiement": d.commentaire_paiement,
        "prestation": {
            "nom": p.nom if p else d.prestation_id,
            "prix": str(p.prix) if p else None,
            "unite": p.unite if p else "",
            "forfait": bool(p and p.forfait),
        },
        "pro_nom": pro.nom if pro else "",
        "ouvertures": d.jeton_ouvertures,
        "max_ouvertures": core.PRO_LIEN_MAX_OUVERTURES,
        "parametres": {
            "delai_confirmation_jours": core.DELAI_CONFIRMATION_JOURS,
            "email_gestion": core.EMAIL_GESTION,
        },
    }


def assure_view(a, store):
    env = store.enveloppes.get(a.id)
    etat = core.pmv_etat(store, a.id)
    return {
        "id": a.id,                                   # = n° de dossier (§9)
        "prenom": a.prenom, "nom": a.nom, "nom_complet": a.nom_complet,
        "email": a.email, "telephone": a.telephone,
        "contrat_ref": a.contrat_ref,
        "ndd": a.ndd,
        "ndd_libelle": core.NDD[a.ndd].libelle if a.ndd in core.NDD else None,
        "date_preinscription": a.date_preinscription,
        "etat_dossier": core.etat_dossier(store, a.id),
        "aides": [jsonable(x) for x in a.aides],
        "profil": a.profil or {},
        "analyse": a.analyse,
        "profil_complet": bool(env and env.iban),
        "pmv_etat": etat,
        "pmv_pret": etat == "utilisable",
        "pmv_blocage": core.pmv_blocage(store, a.id),
        "rib": env.iban if env else "",
        "pmv": pmv_view(env),
        "barometre": core.barometre(store, a.id),
        "contacts": [jsonable(c) for c in store.contacts if c.assure_id == a.id],
    }


def state_snapshot(s):
    return {
        "app": "MPA — V1 (specs V1.1 du 06/11/2026)",
        "parametres": {
            "delai_confirmation_jours": core.DELAI_CONFIRMATION_JOURS,      # A-3
            "references_contrat": core.REFERENCES_CONTRAT,
            "email_gestion": core.EMAIL_GESTION,
        },
        "depts": core.DEPTS,
        "assures": [assure_view(a, s) for a in s.assures.values()],
        "pros": [jsonable(p) for p in s.pros.values()],
        "prestations": [jsonable(p) for p in s.prestations.values()],
        "devis": [jsonable(d) for d in s.devis.values()],
        "remboursements": [remb_view(r) for r in s.remboursements.values()],
        "alertes": core.alertes(s),
        "contacts": [jsonable(c) for c in s.contacts],
        "nb_emails": len(s.emails),
    }


# --------------------------------------------------------------------------- #
#  Serveur HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    server_version = "MPA-API/2.0-V1"

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _err(self, msg, status=400):
        self._json({"error": str(msg)}, status)

    def _raw(self, body, ctype, disposition=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self):
        try:
            with open(HTML_PATH, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            return self._json({"service": "MPA API V1", "ok": True,
                               "note": "mpa_demo.html absent — placez-le à côté de mpa_api.py",
                               "voir": "/api/state"})
        self._raw(body, "text/html; charset=utf-8")

    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    def log_message(self, *a):
        pass

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _parts(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        return parts, q

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        parts, q = self._parts()
        s = APP.store
        try:
            if not parts or parts == ["mpa_demo.html"]:
                return self._serve_html()

            if parts == ["api", "state"]:
                return self._json(state_snapshot(s))

            if parts == ["api", "diag"]:
                key = os.environ.get("ANTHROPIC_API_KEY")
                out = {
                    "app": "MPA — V1",
                    "anthropic_api_key_present": bool(key),
                    "key_format_ok": bool(key and key.startswith("sk-ant-")),
                    "model": "claude-sonnet-4-6",
                    "assistant_mode": "llm" if key else "repli déterministe (RG-63)",
                    "catalogue_source": getattr(core, "CATALOGUE_SOURCE", "snapshot"),
                    "catalogue_lignes": len(getattr(core, "CATALOGUE_ROWS", [])),
                    "delai_confirmation_jours": core.DELAI_CONFIRMATION_JOURS,
                    "astuce": "Ajoutez ?ping=1 pour un vrai test d'appel au modèle.",
                }
                if q.get("ping") == "1":
                    try:
                        txt = core.anticiper_prompt("Réponds exactement : pong", max_tokens=10)
                        out["ping_ok"] = True
                        out["ping_sample"] = txt[:60]
                    except Exception as e:
                        out["ping_ok"] = False
                        out["ping_error"] = f"{e.__class__.__name__}: {e}"
                return self._json(out)

            if parts == ["api", "catalogue"]:
                return self._json({
                    "pros": [jsonable(p) for p in s.pros.values()],
                    "prestations": [jsonable(p) for p in s.prestations.values()],
                    "depts": core.DEPTS,
                    "source": getattr(core, "CATALOGUE_SOURCE", "snapshot"),
                })

            if len(parts) == 3 and parts[:2] == ["api", "assures"]:
                a = s.assures.get(parts[2])
                if a is None:
                    return self._err("Dossier introuvable", 404)
                return self._json(assure_view(a, s))

            if len(parts) == 3 and parts[:2] == ["api", "pro"]:
                with APP.lock:
                    d = core.devis_par_jeton(s, parts[2])
                    if d is None:
                        return self._err("Lien invalide ou révoqué", 404)
                    if d.jeton_ouvertures >= core.PRO_LIEN_MAX_OUVERTURES:
                        return self._err("Lien expiré (nombre d'ouvertures atteint) — "
                                         "contactez le gestionnaire : "
                                         + core.EMAIL_GESTION, 410)
                    d.jeton_ouvertures += 1            # « usage limité » (A-1a)
                    return self._json(pro_view(d, s))

            if parts == ["api", "alertes"]:
                return self._json({"alertes": core.alertes(s)})

            if parts == ["api", "emails"]:
                return self._json({"emails": [jsonable(e) for e in s.emails]})

            if len(parts) == 3 and parts[:2] == ["api", "exports"] and parts[2].endswith(".csv"):
                quoi = parts[2][:-4]
                csv = core.exporter(s, quoi)
                return self._raw(csv.encode("utf-8"), "text/csv; charset=utf-8",
                                 f'attachment; filename="MPA_{quoi}.csv"')

            if (len(parts) == 4 and parts[:2] == ["api", "remboursements"]
                    and parts[3] == "justificatif"):
                r = s.remboursements.get(parts[2])
                if r is None:
                    return self._err("Demande introuvable", 404)
                data = r.justificatif_data or ""
                if data.startswith("data:"):
                    head, _, b64 = data.partition(",")
                    ctype = head[5:].split(";")[0] or "application/octet-stream"
                    try:
                        return self._raw(base64.b64decode(b64), ctype,
                                         f'inline; filename="{r.justificatif_nom}"')
                    except Exception:
                        return self._err("Justificatif illisible", 500)
                return self._json({"nom": r.justificatif_nom,
                                   "note": "Aucune pièce déposée (nom seul)."})

            return self._err("Route inconnue", 404)
        except Exception as e:
            return self._err(e, 500)

    # ----------------------------------------------------------------- POST
    def do_POST(self):
        parts, q = self._parts()
        body = self._body()
        with APP.lock:
            s = APP.store
            try:
                if parts == ["api", "reset"]:
                    APP.reset()
                    return self._json({"ok": True})

                # — Gestionnaire : pré-inscription (F-20, RG-41) —
                if parts == ["api", "preinscriptions"]:
                    a = APP.dossiers.preinscrire(
                        body.get("prenom"), body.get("nom"), body.get("email"),
                        body.get("contrat_ref", ""), body.get("ndd"),
                        body.get("credit"), body.get("pfd") or {},
                        commentaire=body.get("commentaire", ""),
                        lien_base=body.get("lien_base", ""))
                    return self._json(assure_view(a, s), 201)

                # — Dossier : profil, PFD, analyse, crédit, blocage, contact… —
                if len(parts) >= 4 and parts[:2] == ["api", "assures"]:
                    aid, action = parts[2], parts[3]
                    if aid not in s.assures:
                        return self._err("Dossier introuvable", 404)

                    if action == "profil" and len(parts) == 4:
                        a = APP.dossiers.completer_profil(
                            aid, body.get("iban", ""), body.get("telephone", ""),
                            body.get("profil"))
                        return self._json(assure_view(a, s))

                    if action == "aides" and len(parts) == 4:
                        a = APP.dossiers.ajouter_aide(
                            aid, body.get("prenom", ""), body.get("lien", ""),
                            body.get("ndd", 0), body.get("principal", False),
                            body.get("naissance", ""))
                        return self._json(assure_view(a, s), 201)

                    if action == "aides" and len(parts) == 6 and parts[5] == "profil":
                        a = APP.dossiers.completer_profil_pfd(aid, parts[4], body.get("profil"))
                        return self._json(assure_view(a, s))

                    if action == "analyse" and len(parts) == 4:
                        a = APP.dossiers.completer_analyse(aid, body.get("texte", ""))
                        return self._json(assure_view(a, s))

                    if action == "crediter" and len(parts) == 4:
                        a = APP.dossiers.crediter(aid, body.get("montant"),
                                                  body.get("motif", "Crédit initial"),
                                                  body.get("commentaire", ""))
                        return self._json(assure_view(a, s))

                    if action == "bloquer" and len(parts) == 4:
                        a = APP.dossiers.bloquer(aid, body.get("motif", ""))
                        return self._json(assure_view(a, s))

                    if action == "debloquer" and len(parts) == 4:
                        a = APP.dossiers.debloquer(aid, body.get("commentaire", ""))
                        return self._json(assure_view(a, s))

                    if action == "mouvements" and len(parts) == 6 and parts[5] == "commenter":
                        a = APP.dossiers.commenter_mouvement(aid, parts[4],
                                                             body.get("commentaire", ""))
                        return self._json(assure_view(a, s))

                    if action == "contacts" and len(parts) == 4:
                        c = APP.dossiers.contacter(aid, body.get("type", ""),
                                                   body.get("message", ""))
                        return self._json(jsonable(c), 201)

                # — A-1a : réponses du PRO, exclusivement via son jeton —
                if len(parts) == 4 and parts[:2] == ["api", "pro"]:
                    d = core.devis_par_jeton(s, parts[2])
                    if d is None:
                        return self._err("Lien invalide ou révoqué", 404)
                    action = parts[3]
                    if action == "etablir":
                        d = APP.devis.etablir(d.id, body.get("quantite"),
                                              body.get("message_pro", ""))
                    elif action == "refuser":
                        d = APP.devis.refuser_pro(d.id, body.get("motif", ""))
                    elif action == "realisee":
                        d = APP.devis.declarer_realisee(d.id)
                    else:
                        return self._err("Action pro inconnue", 404)
                    return self._json(pro_view(d, s))

                # — Cycle devis (§7.1) —
                if parts == ["api", "devis"]:
                    d = APP.devis.demander(body.get("assure_id"), body.get("prestation_id"),
                                           body.get("message", ""),
                                           lien_base=body.get("lien_base", ""))
                    return self._json(jsonable(d), 201)

                if len(parts) == 4 and parts[:2] == ["api", "devis"]:
                    did, action = parts[2], parts[3]
                    if did not in s.devis:
                        return self._err("Devis introuvable", 404)
                    if action == "accepter":
                        d = APP.devis.accepter(did)
                    elif action == "refuser":
                        d = APP.devis.refuser(did)
                    elif action == "service-fait":
                        d = APP.devis.confirmer_service_fait(
                            did, body.get("par", "assuré-aidant"), body.get("motif", ""))
                    elif action == "contester":
                        d = APP.devis.contester(did, body.get("motif", ""))
                    elif action == "payer":
                        d = APP.devis.payer(did, body.get("montant"),
                                            body.get("commentaire", ""))
                    elif action == "annuler":
                        d = APP.devis.annuler(did, body.get("motif", ""))
                    else:
                        return self._err("Action devis inconnue", 404)
                    return self._json(jsonable(d))

                # — F-22 / F-23 : marquage de PLUSIEURS paiements en une fois —
                if parts == ["api", "paiements"]:
                    done, errs = [], []
                    for did in body.get("devis", []) or []:
                        try:
                            APP.devis.payer(did, None, body.get("commentaire", ""))
                            done.append(did)
                        except Exception as e:
                            errs.append({"ref": did, "erreur": str(e)})
                    for rid in body.get("remboursements", []) or []:
                        try:
                            APP.remb.marquer_payee(rid, body.get("commentaire", ""))
                            done.append(rid)
                        except Exception as e:
                            errs.append({"ref": rid, "erreur": str(e)})
                    return self._json({"payes": done, "erreurs": errs})

                # — Remboursements (§7.2) —
                if parts == ["api", "remboursements"]:
                    r = APP.remb.soumettre(
                        body.get("assure_id"), body.get("libelle", ""),
                        body.get("motif", ""), body.get("montant"),
                        body.get("justificatif_nom", ""),
                        body.get("justificatif_data", ""))
                    return self._json(remb_view(r), 201)

                if len(parts) == 4 and parts[:2] == ["api", "remboursements"]:
                    rid, action = parts[2], parts[3]
                    if rid not in s.remboursements:
                        return self._err("Demande introuvable", 404)
                    if action == "valider":
                        r = APP.remb.valider(rid)
                    elif action == "refuser":
                        r = APP.remb.refuser(rid, body.get("motif", ""))
                    elif action == "piece":
                        r = APP.remb.demander_piece(rid)
                    elif action == "redeposer":
                        r = APP.remb.redeposer(rid, body.get("justificatif_nom", ""),
                                               body.get("justificatif_data", ""))
                    elif action == "payer":
                        r = APP.remb.marquer_payee(rid, body.get("commentaire", ""))
                    else:
                        return self._err("Action remboursement inconnue", 404)
                    return self._json(remb_view(r))

                # — F-70 : tâche quotidienne (déclenchement manuel en maquette) —
                if parts == ["api", "tache-quotidienne"]:
                    return self._json(core.tache_quotidienne(s))

                # — Assistant IA : évaluation des besoins (F-45) —
                if parts == ["api", "anticiper2"]:
                    try:
                        txt = core.anticiper_prompt(body.get("prompt", ""))
                        return self._json({"text": txt})
                    except Exception:
                        return self._json({"text": None})

                # — Baromètre aidant : lecture personnalisée par l'assistant —
                if parts == ["api", "barometre"]:
                    sys_p = (
                        "Tu accompagnes un aidant familial dans le cadre d'une garantie "
                        "de soutien aux aidants. On te donne son « baromètre aidant » : "
                        "un positionnement global (zone verte/orange/rouge) décliné par "
                        "dimension (charge d'aide, charge mentale, santé & répit, vie "
                        "professionnelle, entourage & relais, budget & droits), avec les "
                        "facteurs qui pèsent et les points d'appui — y compris des "
                        "signaux d'usage de son porte-monnaie (services mobilisés, "
                        "remboursements). Rédige en français une lecture chaleureuse et "
                        "factuelle en 4 phrases maximum, en le vouvoyant : (1) reconnais "
                        "la situation d'ensemble sans dramatiser ni minimiser ; "
                        "(2) nomme LA dimension la plus en tension et ce qui l'explique ; "
                        "(3) souligne un appui réel (surtout ce qu'il a déjà mobilisé) ; "
                        "(4) propose UN pas concret cohérent avec la zone (vert : "
                        "anticiper ; orange : demander de l'aide ; rouge : se protéger "
                        "et solliciter le conseiller). Aucun diagnostic médical, aucun "
                        "chiffre inventé, aucun prestataire nommé, pas de culpabilisation."
                    )
                    try:
                        txt = core.anticiper_prompt(body.get("prompt", ""),
                                                    system=sys_p, max_tokens=300)
                        return self._json({"texte": txt})
                    except Exception:
                        return self._json({"texte": None})

                # — Assistant IA : bilan situationnel (F-44) —
                if parts == ["api", "analyse", "generer"]:
                    sys_p = (
                        "Tu es un travailleur social qui rédige un BILAN SITUATIONNEL "
                        "pour un aidant familial et son proche dépendant, dans le cadre "
                        "d'une garantie de soutien aux aidants. Rédige en français, ton "
                        "neutre et factuel, 40 lignes maximum, en courts paragraphes : "
                        "(1) la situation de l'aidant et sa charge, (2) la situation et "
                        "l'autonomie du proche, (3) les tensions, risques et points de "
                        "vigilance, (4) les axes de soutien prioritaires. Appuie-toi "
                        "UNIQUEMENT sur les informations fournies ; n'invente aucun fait, "
                        "aucun chiffre, aucun nom de dispositif ou de prestataire. Pas de "
                        "diagnostic médical (RG-62). Reste descriptif et analytique, sans "
                        "recommander de prestation nommée."
                    )
                    try:
                        txt = core.anticiper_prompt(body.get("prompt", ""),
                                                    system=sys_p, max_tokens=1400)
                        return self._json({"texte": txt})
                    except Exception:
                        return self._json({"texte": None})

                return self._err("Route inconnue", 404)
            except KeyError as e:
                return self._err(f"Champ ou ressource manquant : {e}", 400)
            except ValueError as e:
                return self._err(e, 400)
            except Exception as e:
                return self._err(e, 500)


def serve(port=None):
    port = port if port is not None else int(os.environ.get("PORT", 8765))
    httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"  MPA V1 — port {port}")
    print(f"  Shell  →  http://127.0.0.1:{port}/")
    print(f"  API    →  http://127.0.0.1:{port}/api/state")
    print("  Ctrl+C pour arrêter.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  Arrêt.")
        httpd.shutdown()


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else None)
