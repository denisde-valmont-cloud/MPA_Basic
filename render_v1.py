"""Harness de rendu V1 : exécute les vues des 3 rôles sur l'état seed réel
servi par l'API, plus les fonctions asynchrones (replis IA). Détecte toute
exception et vérifie des contenus clés exigés par les specs."""
import re, sys, json, subprocess, importlib, threading, time, socket, urllib.request, os

DIR = sys.argv[1] if len(sys.argv) > 1 else "."
sys.path.insert(0, os.path.abspath(DIR))
import mpa_core, mpa_api
importlib.reload(mpa_core); importlib.reload(mpa_api)
from http.server import ThreadingHTTPServer
s = socket.socket(); s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]; s.close()
httpd = ThreadingHTTPServer(("127.0.0.1", PORT), mpa_api.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start(); time.sleep(0.3)
def _req(m, p, b=None):
    d = json.dumps(b).encode() if b is not None else None
    rq = urllib.request.Request(f"http://127.0.0.1:{PORT}"+p, data=d, method=m,
                                headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(rq, timeout=8) as x:
        return json.loads(x.read().decode())

# A-1a — le pro répond par lien : on constitue de VRAIES vues /api/pro/<jeton>
_st0 = _req("GET", "/api/state")
_cla = next(a for a in _st0["assures"] if a["prenom"] == "Claire")["id"]
_d_dem = _req("POST", "/api/devis", {"assure_id": _cla, "prestation_id": "PR-86",
              "message": "Classement des courriers CAF.", "quantite": "3",
              "lien_base": "http://x/"})
_d_eng = _req("POST", "/api/devis", {"assure_id": _cla, "prestation_id": "PR-86",
              "message": "Suivi du dossier MDPH."})
_req("POST", f"/api/pro/{_d_eng['jeton']}/etablir", {"quantite": 2})
_req("POST", f"/api/devis/{_d_eng['id']}/accepter")
_r3 = _req("POST", "/api/remboursements", {"assure_id": _cla, "libelle": "Taxi consultation gériatre",
            "motif": "Transport", "montant": "18",
            "justificatif_nom": "taxi.svg",
            "justificatif_data": "data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciLz4="})
_req("POST", f"/api/remboursements/{_r3['id']}/valider")
_st0b = _req("GET", "/api/state")
_d5 = next(d["id"] for d in _st0b["devis"] if d["id"].endswith("D05"))
_req("POST", f"/api/devis/{_d5}/accepter", {"accepter_reste_a_charge": True})   # RG-43
_st1 = _req("GET", "/api/state")
def _jeton(suff):
    return next(d["jeton"] for d in _st1["devis"] if d["id"].endswith(suff))
PRO_VIEWS = {
    "demande":     _req("GET", f"/api/pro/{_d_dem['jeton']}"),
    "devisé":      _req("GET", f"/api/pro/{_jeton('D04')}"),
    "engagé":      _req("GET", f"/api/pro/{_jeton('D03')}"),
    "engagé2":     _req("GET", f"/api/pro/{_d_eng['jeton']}"),
    "engagé_rac":  _req("GET", f"/api/pro/{_jeton('D05')}"),
    "facturée":    _req("GET", f"/api/pro/{_jeton('D02')}"),
    "payé":        _req("GET", f"/api/pro/{_jeton('D01')}"),
}
PRO_VIEWS_JSON = json.dumps(PRO_VIEWS, ensure_ascii=False)
NOM_CLAIRE = next(a for a in _st0["assures"] if a["prenom"] == "Claire")["nom_complet"]

with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/state", timeout=8) as r:
    STATE_JSON = r.read().decode()
with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/emails", timeout=8) as r:
    EMAILS_JSON = r.read().decode()
httpd.shutdown()

h = open(f"{DIR}/mpa_demo.html", encoding="utf-8").read()
js = re.search(r"<script>(.*)</script>", h, re.S).group(1)
js = js.replace('$("#apiUrl").value = API;\nrefresh();', '/*boot neutralisé*/')

harness = r"""
globalThis.window={}; globalThis.location={protocol:"file:",origin:"http://x",pathname:"/",href:"",search:""}; globalThis.navigator={userAgent:"node"};
globalThis.URLSearchParams=class{constructor(){} get(){return null}};
globalThis.document={querySelector:()=>null,querySelectorAll:()=>[],getElementById:()=>null,addEventListener:()=>{},body:{},createElement:()=>({style:{},appendChild:()=>{},setAttribute:()=>{}}),head:{appendChild:()=>{}}};
globalThis.localStorage={getItem:()=>null,setItem:()=>{}};
globalThis.CSS={escape:s=>s};
"""

tail = r"""
render=()=>{}; toast=()=>{};
STATE=__STATE__;
const EMS=__EMAILS__;
const READY=STATE.assures.find(a=>a.prenom==="Claire");
const BLOCKED=STATE.assures.find(a=>a.prenom==="Léa");
AIDANT_ID=READY.id;
AID=aidSeed(); AID.boundTo=READY.id; GEST=gestSeed(); PROF={devisQty:"",motifOpen:false};
const PV=__PROVIEWS__;            // vraies réponses de GET /api/pro/<jeton> (A-1a)
const out={}; const cap=(k,f)=>{ try{ const v=String(f()); if(!v) throw new Error("vide"); out[k]=v; }catch(e){ out[k]="ERR::"+e.message; } };

/* — assuré-aidant — */
cap("viewAidant_ready",()=>viewAidant());
AIDANT_ID=BLOCKED.id; AID=aidSeed(); AID.boundTo=BLOCKED.id;
cap("viewAidant_verrou",()=>viewAidant());
AIDANT_ID=READY.id; AID=aidSeed(); AID.boundTo=READY.id;
cap("accueil",()=>aidAccueil(READY));
cap("accueil_verrou",()=>aidAccueil(BLOCKED));
cap("fiche",()=>aidFiche());
AID.analyseEdit=true; AID.analyseTexte="Brouillon."; cap("fiche_bilanEdit",()=>aidFiche()); AID=aidSeed(); AID.boundTo=READY.id;
AID.parcours=[{categorie:"repit",horizon:3,justification:"x"}];
cap("catalogue",()=>aidCatalogue(READY));
AID.catTitre="Répit de l'aidant"; AID.cat.famille="Aide au parcours de vie";
cap("catalogue_categorie",()=>aidCatalogue(READY));
AID=aidSeed(); AID.boundTo=READY.id;
cap("catalogue_verrou",()=>aidCatalogue(BLOCKED));
cap("prestations",()=>aidPrestations(READY));
AID.demandePid=(STATE.prestations.find(p=>p.unite!=="Prestation complète")||{}).id; AID.demandeQty="200";
cap("catalogue_demande",()=>aidCatalogue(READY));
AID.demandePid=null; AID.demandeQty="";
AID.rac={ref:"GSA-26-00002-D05", total:"1374.00", prise_en_charge:"1130.60", reste_a_charge:"243.40", disponible:"1130.60"};
cap("racmodal",()=>racModal()); AID.rac=null;
cap("pmvremb",()=>aidPmvRemb(READY));
cap("pmvremb_verrou",()=>aidPmvRemb(BLOCKED));
cap("dossier",()=>aidDossier(READY));
cap("dossier_verrou",()=>aidDossier(BLOCKED));
cap("profilform",()=>aidProfilForm(BLOCKED));
cap("pdform",()=>pdForm(READY.aides[0]));
cap("contactmodal",()=>contactModal());

/* — pro : formulaire mono-demande ouvert par ?pro=<jeton> (A-1a) — */
PRO_JETON="jeton-harness";
for(const st of Object.keys(PV)){ PRO_DATA=PV[st]; PRO_ERR=null; cap("proForm_"+st,()=>viewProForm()); }
PROF.motifOpen=true; PRO_DATA=PV["demande"]; cap("proForm_decliner",()=>viewProForm()); PROF.motifOpen=false;
PRO_DATA=null; PRO_ERR="Lien expiré (nombre d'ouvertures atteint) — contactez le gestionnaire : gsa@assur-aidant.com";
cap("proForm_erreur",()=>viewProForm());
PRO_ERR=null; PRO_JETON=null;

/* — gestionnaire — */
cap("gDossiers",()=>{GEST=gestSeed(); return viewGest();});
cap("gDossierDetail",()=>gDossierDetail(READY));
cap("gDossierDetail_verrou",()=>gDossierDetail(BLOCKED));
cap("gForm",()=>{GEST.showForm=true; const r=viewGest(); GEST.showForm=false; return r;});
cap("gPaiements",()=>{GEST.tab="paiements"; return viewGest();});
cap("gRemb",()=>{GEST.tab="remb"; return viewGest();});
GEST.brdOpen="BRD-26-001";
cap("gPaiementsBrd",()=>{GEST.tab="paiements"; return viewGest();});
GEST.brdOpen=null;
cap("gAlertes",()=>{GEST.tab="alertes"; return viewGest();});
cap("gEmails",()=>{GEST.tab="emails"; GEST.emails=EMS.emails; GEST.emailsLoaded=true; return viewGest();});
cap("gExports",()=>{GEST.tab="exports"; return viewGest();});
GM={kind:"partiel",ref:STATE.devis[0].id}; cap("gModal_partiel",()=>gModal());
GM={kind:"bloquer",aid:READY.id}; cap("gModal_bloquer",()=>gModal());
GM={kind:"crediter",aid:READY.id}; cap("gModal_crediter",()=>gModal());
GM={kind:"commenter",aid:READY.id,ref:"MV-0001"}; cap("gModal_commenter",()=>gModal());
GM={kind:null};

/* — exécution réelle des fonctions async (repli sans clé) — */
(async()=>{
  let fails=Object.entries(out).filter(([k,v])=>v.startsWith("ERR::"));
  // aidEvaluer : repli
  GEST=gestSeed(); AID=aidSeed(); AID.boundTo=READY.id; AID.consent=true; AID.recit="Je suis épuisée.";
  api=async(m,p,b)=>({text:null});
  await aidEvaluer();
  const evalOk = AID.loading===false && (AID.besoins||[]).length>0 && AID.aiNote && AID.aiNote.kind==="warn";
  // succès LLM simulé
  AID=aidSeed(); AID.boundTo=READY.id; AID.consent=true;
  api=async(m,p,b)=>({text:JSON.stringify({besoins:[{categorie:"repit",horizon:3,justification:"x"}],relances:[]})});
  await aidEvaluer();
  const evalOk2 = AID.loading===false && AID.besoins.length===1 && AID.aiNote.kind==="ok";
  // bilan : repli local
  AID=aidSeed(); AID.boundTo=READY.id;
  api=async(m,p,b)=>({texte:null});
  await aidGenererAnalyse();
  const bilanOk = AID.analyseLoading===false && (AID.analyseTexte||"").length>0 && AID.analyseEdit===true;
  // baromètre : lecture, repli local (cite la dimension la plus en tension)
  AID=aidSeed(); AID.boundTo=READY.id; AIDANT_ID=READY.id;
  api=async(m,p,b)=>({texte:null});
  await baroLecture();
  const baroOk = AID.baroLoading===false && (AID.baroTexte||"").includes("santé & répit");

  const checks={
    "equations F-43": /Crédit cumulé/.test(out.pmvremb) && /= solde/.test(out.pmvremb) && /disponible/.test(out.pmvremb),
    "n° dossier permanent": new RegExp("Dossier "+READY.id).test(out.viewAidant_ready),
    "contact conseiller permanent": /Contacter un conseiller/.test(out.viewAidant_ready),
    "accueil actions prioritaires": /À faire en priorité/.test(out.accueil) && /à accepter ou refuser/i.test(out.accueil),
    "accueil verrou étapes": /étape 1\/2/.test(out.accueil_verrou),
    "catalogue catégories retenues": /VOS CATÉGORIES RETENUES/.test(out.catalogue),
    "catalogue tooltip pro": /ptip-box/.test(out.catalogue),
    "catalogue verrou RIB msg": /Verrouillé — complétez votre profil \(RIB\)/.test(out.catalogue_verrou),
    "demande : volume souhaité + estimation + RAC estimé": /Volume souhaité/.test(out.catalogue_demande) && /a-dv-qty/.test(out.catalogue_demande) && /reste à charge estimé/i.test(out.catalogue_demande),
    "modal RAC : chiffres + maintien": /Reste à charge à confirmer/.test(out.racmodal) && /1\s?130,60/.test(out.racmodal.replace(/\u202f/g," ")) && /243,40/.test(out.racmodal) && /Maintenir/.test(out.racmodal),
    "prestations : devis engagé avec RAC affiché": /à votre charge/.test(out.prestations) && /pris en charge/.test(out.prestations),
    "pro engagé avec RAC : deux facturations": /deux facturations/.test(out.proForm_engagé_rac) && /directement à l'assuré-aidant/.test(out.proForm_engagé_rac),
    "pro demande : volume souhaité affiché et pré-rempli": /Volume souhaité : 3 heure\(s\)/.test(out.proForm_demande) && /value="3"/.test(out.proForm_demande),
    "gest factures attendues : chip RAC": /\+ RAC/.test(out.gPaiements),
    "prestations stepper 5 étapes (facturé)": /Demandé<\/span><span>Devisé/.test(out.prestations) && /Facturé<\/span><span>Payé/.test(out.prestations),
    "prestations engagé : facture directe au gestionnaire": /adressera sa facture directement au gestionnaire/.test(out.prestations),
    "prestations facturée : vaut validation, paiement en préparation (RG-45)": /vaut validation/.test(out.prestations) && /Paiement en préparation/.test(out.prestations),
    "prestations : plus AUCUNE action de confirmation côté aidant": !/service fait/i.test(out.prestations) && !/[Cc]ontest/.test(out.prestations),
    "remb upload file": /type="file" id="ar-file"/.test(out.pmvremb),
    "journal commentaires": /Commentaire du gestionnaire/.test(out.pmvremb),
    "dossier profils": /id="ai-iban"/.test(out.profilform) && /id="ai-tel"/.test(out.profilform),
    "pdform aidesf autre": /pd-aidesf-autre/.test(out.pdform),
    "bilan situationnel libellé": /Bilan situationnel/.test(out.fiche),
    "pro A-1a sans compte, usage limité": /sans compte \(A-1a\)/.test(out.proForm_demande) && /usage limité/.test(out.proForm_demande) && /consultation \d+\/\d+/.test(out.proForm_demande),
    "pro A-1a minimisation (jamais le nom de l'aidant)": __NOMCLAIRE__.split(" ").every(m=>Object.keys(PV).every(st=>!out["proForm_"+st].includes(m))),
    "pro n° dossier + besoin exprimé": new RegExp("Dossier <b>"+PV["demande"].dossier).test(out.proForm_demande) && /Besoin exprimé : « Classement des courriers CAF. »/.test(out.proForm_demande),
    "pro consigne facture F-62": /n° de dossier/.test(out.proForm_payé) && new RegExp("référence "+PV["payé"].ref).test(out.proForm_payé),
    "pro decliner motif": /Motif du refus \(obligatoire/.test(out.proForm_decliner),
    "pro engagé = consigne de facturation (RG-45)": /adressez votre facture/.test(out.proForm_engagé) && /vaut validation/.test(out.proForm_engagé) && /RG-53/.test(out.proForm_engagé),
    "pro engagé : aucune action attendue dans MPA": !/p-realisee/.test(out.proForm_engagé) && !/data-act="p-devis"/.test(out.proForm_engagé),
    "pro facturée : paiement en préparation": /Facture reçue le/.test(out.proForm_facturée) && /vaut validation/.test(out.proForm_facturée),
    "pro lien expiré (page d'erreur)": /Lien invalide, révoqué ou expiré/.test(out.proForm_erreur),
    "header sans rôle pro (2 espaces)": __HDROK__,
    "gest e-mails : lien ?pro= cliquable": /href="http:\/\/x\/\?pro=|\?pro=/.test(out.gEmails) && /<a href=/.test(out.gEmails),
    "gest dossier : renvoi du formulaire pro": /formulaire pro ↗/.test(out.gDossierDetail),
    "gest file paiements RG-52": /acte manuel \(RG-52\)/.test(out.gPaiements) && /Marquer payés \(\d+\) → bordereau/.test(out.gPaiements),
    "gest factures attendues (engagés) + Facture reçue": /Factures attendues/.test(out.gPaiements) && /data-act="g-facture"/.test(out.gPaiements) && /engagé il y a \d+ j/.test(out.gPaiements),
    "gest case unique par ligne (tout cocher si ≥2)": !/data-paygrp/.test(out.gPaiements) && /data-act="g-pay-grp"/.test(out.gPaiements),
    "gest file partiel bouton": /Partiel…/.test(out.gPaiements),
    "gest file groupée par bénéficiaire": /\(assuré-aidant\)/.test(out.gPaiements) && /sur facture \(F-62\)/.test(out.gPaiements),
    "gest file : nom de l'assuré sur chaque ligne": new RegExp(READY.nom_complet+" — "+READY.id).test(out.gPaiements),
    "gest bordereaux : section + seed exécuté": /BORDEREAUX DE VIREMENT/.test(out.gPaiements) && /BRD-26-001/.test(out.gPaiements) && /Exécuté le/.test(out.gPaiements) && /bordereaux\.csv/.test(out.gPaiements),
    "gest bordereau détail : IBAN + total": /Total du bordereau/.test(out.gPaiementsBrd) && /sur facture \(F-62\)/.test(out.gPaiementsBrd),
    "gest remb valider RG-44": /partiel automatique — RG-44/i.test(out.gRemb),
    "gest remb : onglet instruction, validées → paiements": /Demandes de remboursement/.test(out.gRemb) && /→ Paiements à effectuer/.test(out.gRemb) && !/Marquer payées/.test(out.gRemb),
    "gest remb : groupée par dossier avec PMV (solde/engagé/disponible)": new RegExp(READY.nom_complet).test(out.gRemb) && /Solde/.test(out.gRemb) && /Engagé/.test(out.gRemb) && /Disponible/.test(out.gRemb),
    "gest justificatif lien": /justificatif" target="_blank"|justificatif"/.test(out.gRemb),
    "gest alertes : facture attendue (A-3) + tâche F-70": /Facture attendue/.test(out.gAlertes) && /tâche quotidienne \(F-70\)/.test(out.gAlertes),
    "gest alertes : Facture reçue + Annuler (litige)": /Facture reçue \(vaut validation\)/.test(out.gAlertes) && /Annuler \(litige/.test(out.gAlertes),
    "gest form PFD obligatoire": /PFD principal/.test(out.gForm) && /obligatoire \(RG-41\)/.test(out.gForm),
    "gest form crédit libre": /saisie libre/.test(out.gForm),
    "gest NDD 5-6 refusés": /NDD 5 — non éligible/.test(out.gForm),
    "gest dossier journal commenter": /g-commenter-open/.test(out.gDossierDetail),
    "gest dossier bloquer": /Bloquer le PMV…/.test(out.gDossierDetail),
    "gest emails simulés": /Activez votre espace|Demande de devis/.test(out.gEmails),
    "gest exports 4 CSV": (out.gExports.match(/\.csv/g)||[]).length>=4,
    "aidEvaluer repli": evalOk, "aidEvaluer llm": evalOk2, "bilan repli local": bilanOk,
    "barometre carte (gauge global + 6 dimensions)": /Mon baromètre aidant/.test(out.accueil) && /aria-label="Baromètre aidant/.test(out.accueil) && /Charge mentale/.test(out.accueil) && /Budget &(amp;)? droits/.test(out.accueil),
    "barometre détail dimension (accordéon)": (()=>{AID.baroDim="sante"; const s2=aidAccueil(READY); AID.baroDim=null; return /Fatigue élevée/.test(s2);})(),
    "barometre mention usage": /service\(s\) mobilisé/.test(out.accueil),
    "barometre invite si profil vide": /Complétez votre profil .écran « Dossier ».( pour afficher votre positionnement)/.test(out.accueil_verrou.replace(/\s+/g," ")),
    "barometre conseiller en zone chaude": /a-contact-open/.test(out.accueil),
    "barometre lecture repli": baroOk,
  };
  const bad=Object.entries(checks).filter(([k,v])=>!v);
  console.log("@@@"+JSON.stringify({nvues:Object.keys(out).length,
    errs:fails.map(([k,v])=>k+" :: "+v.slice(0,90)),
    badChecks:bad.map(([k])=>k), okChecks:Object.keys(checks).length-bad.length}));
})();
"""
HDR_OK = ('data-role="pro"' not in h) and h.count('data-act="role"') == 2
tail = (tail.replace("__STATE__", STATE_JSON).replace("__EMAILS__", EMAILS_JSON)
            .replace("__PROVIEWS__", PRO_VIEWS_JSON)
            .replace("__NOMCLAIRE__", json.dumps(NOM_CLAIRE, ensure_ascii=False))
            .replace("__HDROK__", "true" if HDR_OK else "false"))
open("/tmp/_rv1.js", "w", encoding="utf-8").write(harness + js + tail)
r = subprocess.run(["node", "/tmp/_rv1.js"], capture_output=True, text=True, timeout=90)
if r.returncode != 0:
    print("NODE ERROR:\n", r.stderr[:2500]); sys.exit(1)
line = [l for l in r.stdout.splitlines() if l.startswith("@@@")][-1][3:]
res = json.loads(line)
print(f"vues rendues : {res['nvues']}")
print("exceptions   :", res["errs"] if res["errs"] else "aucune")
print(f"assertions   : {res['okChecks']} OK ; échecs : {res['badChecks'] if res['badChecks'] else 'aucun'}")
sys.exit(1 if (res["errs"] or res["badChecks"]) else 0)
