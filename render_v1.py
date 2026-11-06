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
AID=aidSeed(); AID.boundTo=READY.id; GEST=gestSeed(); PRO=proSeed();
PRO_ID=(STATE.devis[0]||{}).pro_id;
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
AID.contesteId=STATE.devis.find(d=>d.statut==="réalisée"&&!d.service_fait).id;
cap("prestations_conteste",()=>aidPrestations(READY)); AID.contesteId=null;
cap("pmvremb",()=>aidPmvRemb(READY));
cap("pmvremb_verrou",()=>aidPmvRemb(BLOCKED));
cap("dossier",()=>aidDossier(READY));
cap("dossier_verrou",()=>aidDossier(BLOCKED));
cap("profilform",()=>aidProfilForm(BLOCKED));
cap("pdform",()=>pdForm(READY.aides[0]));
cap("contactmodal",()=>contactModal());

/* — pro — */
cap("viewPro",()=>viewPro());
for(const st of ["demande","devisé","engagé","réalisée","payé"]){
  const d=STATE.devis.find(x=>x.statut===st)||Object.assign({},STATE.devis[0],{statut:st,service_fait:false});
  PRO.selId=d.id; cap("proDetail_"+st,()=>viewProDetail(d));
}
cap("proDetail_contestée",()=>viewProDetail(Object.assign({},STATE.devis[0],{statut:"contestée",motif_contestation:"Incomplète"})));
PRO.motifOpen=true; cap("proDetail_decliner",()=>viewProDetail(Object.assign({},STATE.devis[0],{statut:"demande",total:null,quantite:null}))); PRO.motifOpen=false;

/* — gestionnaire — */
cap("gDossiers",()=>{GEST=gestSeed(); return viewGest();});
cap("gDossierDetail",()=>gDossierDetail(READY));
cap("gDossierDetail_verrou",()=>gDossierDetail(BLOCKED));
cap("gForm",()=>{GEST.showForm=true; const r=viewGest(); GEST.showForm=false; return r;});
cap("gPaiements",()=>{GEST.tab="paiements"; return viewGest();});
cap("gRemb",()=>{GEST.tab="remb"; return viewGest();});
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

  const checks={
    "equations F-43": /Crédit cumulé/.test(out.pmvremb) && /= solde/.test(out.pmvremb) && /disponible/.test(out.pmvremb),
    "n° dossier permanent": new RegExp("Dossier "+READY.id).test(out.viewAidant_ready),
    "contact conseiller permanent": /Contacter un conseiller/.test(out.viewAidant_ready),
    "accueil actions prioritaires": /À faire en priorité/.test(out.accueil) && /confirmez le service fait/i.test(out.accueil),
    "accueil verrou étapes": /étape 1\/2/.test(out.accueil_verrou),
    "catalogue catégories retenues": /VOS CATÉGORIES RETENUES/.test(out.catalogue),
    "catalogue tooltip pro": /ptip-box/.test(out.catalogue),
    "catalogue verrou RIB msg": /Verrouillé — complétez votre profil \(RIB\)/.test(out.catalogue_verrou),
    "prestations stepper": /Demandé<\/span><span>Devisé/.test(out.prestations),
    "prestations délai": /j restants|délai expiré/.test(out.prestations),
    "prestations contestation form": /Pourquoi contestez-vous/.test(out.prestations_conteste),
    "prestations attente paiement (RG-52)": /En attente du paiement par le gestionnaire/.test(out.prestations),
    "remb upload file": /type="file" id="ar-file"/.test(out.pmvremb),
    "journal commentaires": /Commentaire du gestionnaire/.test(out.pmvremb),
    "dossier profils": /id="ai-iban"/.test(out.profilform) && /id="ai-tel"/.test(out.profilform),
    "pdform aidesf autre": /pd-aidesf-autre/.test(out.pdform),
    "bilan situationnel libellé": /Bilan situationnel/.test(out.fiche),
    "pro bandeau lien sécurisé": /lien sécurisé à usage limité/.test(out.viewPro),
    "pro consigne facture F-62": /n° de dossier/.test(out.viewPro) && /référence du devis/.test(out.viewPro),
    "pro decliner motif": /Motif du refus \(obligatoire/.test(out.proDetail_decliner),
    "pro réalisée aucun paiement auto": /Aucun paiement automatique/.test(out.proDetail_réalisée)||/En attente du virement/.test(out.proDetail_réalisée),
    "gest file paiements RG-52": /acte manuel \(RG-52\)/.test(out.gPaiements) && /Marquer payés/.test(out.gPaiements),
    "gest file partiel bouton": /Partiel…/.test(out.gPaiements),
    "gest remb valider RG-44": /partiel automatique — RG-44/i.test(out.gRemb),
    "gest remb payer lot": /Marquer payées/.test(out.gRemb),
    "gest justificatif lien": /justificatif" target="_blank"|justificatif"/.test(out.gRemb),
    "gest alertes délai+tâche": /Délai expiré/.test(out.gAlertes) && /tâche quotidienne \(F-70\)/.test(out.gAlertes),
    "gest alertes 3 actions F-25": /Confirmer pour le compte/.test(out.gAlertes) && /Payer partiellement/.test(out.gAlertes) && /Annuler \(désengagement intégral\)/.test(out.gAlertes),
    "gest form PFD obligatoire": /PFD principal/.test(out.gForm) && /obligatoire \(RG-41\)/.test(out.gForm),
    "gest form crédit libre": /saisie libre/.test(out.gForm),
    "gest NDD 5-6 refusés": /NDD 5 — non éligible/.test(out.gForm),
    "gest dossier journal commenter": /g-commenter-open/.test(out.gDossierDetail),
    "gest dossier bloquer": /Bloquer le PMV…/.test(out.gDossierDetail),
    "gest emails simulés": /Activez votre espace|Demande de devis/.test(out.gEmails),
    "gest exports 4 CSV": (out.gExports.match(/\.csv/g)||[]).length>=4,
    "aidEvaluer repli": evalOk, "aidEvaluer llm": evalOk2, "bilan repli local": bilanOk,
  };
  const bad=Object.entries(checks).filter(([k,v])=>!v);
  console.log("@@@"+JSON.stringify({nvues:Object.keys(out).length,
    errs:fails.map(([k,v])=>k+" :: "+v.slice(0,90)),
    badChecks:bad.map(([k])=>k), okChecks:Object.keys(checks).length-bad.length}));
})();
"""
tail = tail.replace("__STATE__", STATE_JSON).replace("__EMAILS__", EMAILS_JSON)
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
