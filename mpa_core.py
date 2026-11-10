# -*- coding: utf-8 -*-
"""
MPA — Cœur de domaine V1 (spécifications fonctionnelles V1.1 du 6 novembre 2026)
================================================================================

Maquette opérationnelle de la V1 « a minima » : un seul état partagé (Store),
un seul Porte-Monnaie Virtuel (PMV) par dossier, trois rôles :

    • Assuré-aidant               -> active son dossier, évalue sa situation,
      choisit un pro, accepte un devis (= engagement automatique — la suite
      est entre le pro et le gestionnaire : facture puis paiement), demande
      des remboursements, contacte un conseiller
    • Professionnel de l'aidance  -> PAS DE COMPTE MPA : à chaque demande de
      devis il reçoit un e-mail (adresse du catalogue) avec le n° de dossier,
      le besoin exprimé et un LIEN SÉCURISÉ À USAGE LIMITÉ (?pro=<jeton>) vers
      un formulaire mono-demande : chiffrer ou décliner, puis déclarer la
      réalisation (arbitrage A-1a)
    • Gestionnaire indemnisation  -> pré-inscrit, crédite, instruit les
      demandes de remboursement, PAIE MANUELLEMENT : il marque payé (unitaire
      ou en lot), l'outil génère un BORDEREAU DE VIREMENT par bénéficiaire
      (BRD-AA-NNN) qu'il exécute ensuite à sa banque (hors outil) puis marque
      exécuté ; traite les alertes, bloque/débloque, commente, exporte

RÈGLES MÉTIER (source : §8 des spécifications)
----------------------------------------------
RG-13   NDD 1–4 éligibles ; saisie d'un NDD 5–6 refusée.
RG-20/21 Un seul montant, celui du PFD de référence ; jamais une somme.
RG-41   PFD principal obligatoire à la pré-inscription (contrôle serveur).
RG-42   Double verrou du PMV : RIB puis profil du PFD principal.
RG-43   disponible = solde − engagé ; solde = crédit cumulé − payé ;
        (amendé 09/11/2026) un devis peut DÉPASSER le disponible : l'engagement
        PMV est alors plafonné au disponible, l'excédent constitue un RESTE À
        CHARGE dû par l'assuré-aidant directement au professionnel, et
        l'acceptation exige une confirmation explicite, chiffres à l'appui
        (ResteACharge → confirmation → engagement partiel) ;
        engagement refusé si > disponible ; aucun compartiment négatif.
RG-44   Remboursement validé au plus à hauteur du disponible (partiel auto).
RG-45   Cycle devis : demande → devisé (forfait : direct) → engagé → facturée
        → payé. PAS de confirmation du service par l'assuré-aidant : la
        RÉCEPTION DE LA FACTURE du pro (hors outil), enregistrée par le
        gestionnaire, VAUT VALIDATION de la prestation (confiance dans le
        réseau) ; les litiges sont réglés par le gestionnaire (F-25).
RG-49   Le PMV ne finance que des dépenses liées à la situation d'aidant.
RG-50   Un blocage ne retire jamais un crédit acquis.
RG-51   L'engagement résulte EXCLUSIVEMENT de l'acceptation du devis par
        l'assuré-aidant (clic) ; automatique, sans validation du gestionnaire.
RG-52   Aucun paiement sans facture reçue (statut « facturée »). Le paiement
        est TOUJOURS un acte manuel du gestionnaire : le marquage « payé »
        dans MPA génère un bordereau de virement par bénéficiaire, exécuté
        ensuite à la banque (hors outil) puis marqué exécuté dans MPA.
RG-53   Montant payé au pro ≤ montant engagé ; la facture (hors outil) porte
        le n° de dossier et la référence du devis.
RG-54   Le RENOUVELLEMENT du PMV est un acte manuel du gestionnaire,
        conditionné à une demande de renouvellement reçue et jugée valide
        (document hors outil) : crédit « Renouvellement » (montant libre) qui
        reporte l'échéance d'un an ; le gestionnaire met à jour le NDD retenu
        si le PFD a changé de niveau (1–4, RG-13 — PFD principal synchronisé,
        changement journalisé et porté par l'e-mail F-24). Le NON-RENOUVELLEMENT est tracé (motif
        obligatoire) et notifié à l'assuré-aidant. AUCUN recrédit automatique ;
        l'outil notifie le gestionnaire PREAVIS_ECHEANCE_JOURS avant
        l'échéance (F-30). Effets du non-renouvellement sur le solde : A-11.
RG-60–63 Orientation : taxonomie fermée ; bilan validé fait foi ; assistant
        factuel, sans diagnostic ni prestataire nommé ; repli déterministe.

ARBITRAGES RETENUS POUR CETTE MAQUETTE (§10)
--------------------------------------------
A-1 (a) lien sécurisé par e-mail : un jeton aléatoire PAR DEMANDE (?pro=…),
    limité à PRO_LIEN_MAX_OUVERTURES consultations, inactif dès la clôture
    (payé/refusé/annulé) — en production : + expiration temporelle ;
A-2 snapshot catalogue embarqué + AIDANCE_PRO_CATALOGUE_URL (repli auto) ;
A-3 (recyclé) délai d'attente de la facture = DELAI_FACTURE_JOURS (30 j,
    paramétrable) avant alerte « facture attendue » au gestionnaire ;
A-7 bordereau non exécuté depuis DELAI_BORDEREAU_JOURS (3 j) -> alerte
    (réconciliation bancaire) ;
A-4 n° de dossier sans clé de contrôle (format GSA-AA-NNNNN, §9) ;
A-5 prestation incomplète : paiement partiel décidé par le gestionnaire (F-25).

HORS OUTIL (rappel §1) : étude des droits et NDD, contrats et barèmes,
facture du pro (e-mail), virements bancaires, rejets, renouvellement,
reliquats, reporting assureur (sur export CSV).

stdlib uniquement · arithmétique Decimal · e-mails SIMULÉS (journal interne).
"""

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, List, Dict
import datetime
import itertools
import json
import secrets
import os
import sys
import urllib.request


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  §0 · Paramètres V1                                                   ║
# ╚══════════════════════════════════════════════════════════════════════╝
DELAI_FACTURE_JOURS = 30              # A-3 recyclé : alerte « facture attendue »
DELAI_BORDEREAU_JOURS = 3             # A-7 : alerte « bordereau non exécuté »
EMAIL_GESTION = "gsa@assur-aidant.com"   # §9 / F-62 : destinataire des factures pros
PRO_LIEN_MAX_OUVERTURES = 40          # A-1a : « usage limité » — plafond de consultations
PREAVIS_ECHEANCE_JOURS = 7            # F-30 : notification avant l'échéance annuelle du PMV
DUREE_GARANTIE_JOURS = 365            # F-30 : échéance = crédit initial + 1 an
REFERENCES_CONTRAT = [                 # référentiel INITIAL des références contrat —
    "GSA-2026-0001 — Branche détaillants en chaussures",   # la gestion des contrats
    "GSA-2026-0002 — Branche de l'édition",                # reste HORS outil (§1) ;
]                                      # le gestionnaire enrichit la liste (F-20)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Utilitaires                                                           ║
# ╚══════════════════════════════════════════════════════════════════════╝
def D(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fq(q) -> str:
    """Quantité lisible : 60.00 -> « 60 », 2.50 -> « 2,5 »."""
    if q is None:
        return ""
    t = f"{q}".rstrip("0").rstrip(".")
    return (t or "0").replace(".", ",")


def eur(d: Optional[Decimal]) -> str:
    if d is None:
        return "—"
    return f"{d:,.2f}".replace(",", " ").replace(".", ",") + " €"


def _today() -> str:
    return datetime.date.today().isoformat()


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")


def iban_valide(iban: str) -> bool:
    """Validation IBAN par clé mod-97 (ISO 13616) — verrou 1 (F-41)."""
    s = iban.replace(" ", "").upper()
    if len(s) < 15:
        return False
    s = s[4:] + s[:4]
    try:
        n = "".join(str(int(c, 36)) for c in s)
    except ValueError:
        return False
    return int(n) % 97 == 1


_seq = itertools.count(1)
def _uid(prefix: str) -> str:
    return f"{prefix}-{next(_seq):04d}"


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Référentiel NDD (grille GSA — CG V6) — détermination HORS outil      ║
# ╚══════════════════════════════════════════════════════════════════════╝
@dataclass(frozen=True)
class Ndd:
    niveau: int
    libelle: str
    eligible: bool
    heures_min: Optional[int]


NDD: Dict[int, Ndd] = {
    1: Ndd(1, "Dépendance totale", True, 6),
    2: Ndd(2, "Dépendance sévère", True, 6),
    3: Ndd(3, "Dépendance importante", True, 4),
    4: Ndd(4, "Dépendance moyenne", True, 4),
    5: Ndd(5, "Dépendance faible", False, None),
    6: Ndd(6, "Aucune dépendance", False, None),
}


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Entités V1 (§2)                                                       ║
# ╚══════════════════════════════════════════════════════════════════════╝
@dataclass
class Aide:                          # le Proche Familial Dépendant (PFD)
    prenom: str
    lien: str
    ndd: int = 0
    principal: bool = False           # PFD de référence (ouvre l'indemnisation)
    id: str = field(default_factory=lambda: _uid("PFD"))
    naissance: str = ""               # année de naissance — saisie gestionnaire
    profil: dict = field(default_factory=dict)   # situationnel — complété par l'aidant


@dataclass
class Mouvement:
    """Journal du PMV (F-43) : chaque ligne porte libellé, auteur et un
    commentaire libre que le gestionnaire peut ajouter à tout moment (F-26)."""
    id: str
    date: str
    type: str                        # crédit|engagement|paiement|désengagement
    montant: Decimal
    libelle: str
    ref: str = ""                    # référence devis / remboursement
    auteur: str = ""                 # gestionnaire | assuré-aidant | système
    commentaire: str = ""            # F-26 — visible par l'assuré-aidant


class ResteACharge(ValueError):
    """RG-43 (amendé) — le devis dépasse le disponible : l'acceptation exige
    la confirmation explicite de l'assuré-aidant, chiffres à l'appui."""
    def __init__(self, total: Decimal, disponible: Decimal):
        self.total = total
        self.disponible = disponible
        self.prise_en_charge = min(total, disponible)
        self.reste = (total - self.prise_en_charge).quantize(Decimal("0.01"))
        super().__init__(
            f"Ce devis ({eur(total)}) dépasse votre disponible ({eur(disponible)}) : "
            f"prise en charge {eur(self.prise_en_charge)}, reste à votre charge "
            f"{eur(self.reste)} à régler directement au professionnel. "
            "Confirmation requise (RG-43).")


class IntegriteError(ValueError):
    """F-71 — violation d'intégrité du PMV (contrôle serveur, journalisé)."""


@dataclass
class Enveloppe:
    """PMV canonique V1 (F-43) — 5 chiffres et deux équations :
        crédit cumulé − payé   = solde
        solde         − engagé = disponible
    Compartiments jamais négatifs (RG-43). États : Verrouillé RIB ·
    Verrouillé PFD · Utilisable · Bloqué (§7.3)."""
    assure_id: str
    iban: str = ""
    credit_cumule: Decimal = field(default_factory=lambda: D(0))
    disponible: Decimal = field(default_factory=lambda: D(0))
    engage: Decimal = field(default_factory=lambda: D(0))
    paye: Decimal = field(default_factory=lambda: D(0))
    bloque: bool = False                      # F-27
    motif_blocage: str = ""
    mouvements: List[Mouvement] = field(default_factory=list)

    @property
    def solde(self) -> Decimal:               # crédit cumulé − payé
        return self.credit_cumule - self.paye

    def _verifier(self):                      # F-71 : aucun compartiment négatif
        for nom, v in (("disponible", self.disponible), ("engagé", self.engage),
                       ("payé", self.paye)):
            if v < 0:
                raise IntegriteError(f"Intégrité PMV : compartiment {nom} négatif ({eur(v)})")
        if self.credit_cumule != self.disponible + self.engage + self.paye:
            raise IntegriteError("Intégrité PMV : crédit cumulé ≠ disponible + engagé + payé")

    def _log(self, type_, montant, libelle, ref="", auteur="", commentaire=""):
        self.mouvements.append(Mouvement(_uid("MV"), _today(), type_, montant,
                                         libelle, ref, auteur, commentaire))
        self._verifier()

    # — F-21 : crédit manuel (initial · correction), journalisé, irréversible —
    def crediter(self, montant: Decimal, motif: str, commentaire: str = "",
                 auteur: str = "gestionnaire"):
        if motif not in ("Crédit initial", "Renouvellement", "Correction"):
            raise ValueError("Motif de crédit : « Crédit initial », « Renouvellement » ou « Correction ».")
        if montant == 0:
            raise ValueError("Crédit : montant non nul requis.")
        if montant < 0 and motif != "Correction":
            raise ValueError("Seule une correction peut être négative (mouvement inverse tracé).")
        if montant < 0 and -montant > self.disponible:
            raise IntegriteError(f"Correction {eur(montant)} : dépasse le disponible {eur(self.disponible)}")
        self.credit_cumule += montant
        self.disponible += montant
        self._log("crédit", montant, motif, auteur=auteur, commentaire=commentaire)

    # — RG-51 : engagement automatique à l'acceptation (ou validation remboursement) —
    def engager(self, montant: Decimal, libelle: str, ref: str, auteur: str):
        if montant <= 0:
            raise ValueError("Engagement : montant positif requis.")
        if montant > self.disponible:
            raise IntegriteError(f"Engagement {eur(montant)} > disponible {eur(self.disponible)}")
        self.disponible -= montant
        self.engage += montant
        self._log("engagement", montant, libelle, ref, auteur)

    # — RG-52/53 : paiement = saisie manuelle du gestionnaire —
    def payer(self, montant: Decimal, libelle: str, ref: str, commentaire: str = ""):
        if montant <= 0:
            raise ValueError("Paiement : montant positif requis.")
        if montant > self.engage:
            raise IntegriteError(f"Paiement {eur(montant)} > engagé {eur(self.engage)}")
        self.engage -= montant
        self.paye += montant
        self._log("paiement", montant, libelle, ref, "gestionnaire", commentaire)

    # — annulation / reliquat d'un paiement partiel : retour au disponible —
    def desengager(self, montant: Decimal, libelle: str, ref: str, commentaire: str = ""):
        if montant <= 0:
            return
        if montant > self.engage:
            raise IntegriteError(f"Désengagement {eur(montant)} > engagé {eur(self.engage)}")
        self.engage -= montant
        self.disponible += montant
        self._log("désengagement", montant, libelle, ref, "gestionnaire", commentaire)


@dataclass
class Contact:
    """F-52 — demande de contact conseiller (aucun chatbot), visible gestionnaire."""
    id: str
    assure_id: str
    type: str                         # appel | rappel | message | rendez-vous
    message: str
    date: str


@dataclass
class Email:
    """Notification e-mail SIMULÉE (F-20, F-24, §4) : en production, envoi réel ;
    dans la maquette, journal consultable dans le back-office."""
    date: str
    a: str
    objet: str
    corps: str


@dataclass
class Assure:
    """Dossier assuré-aidant (§2, §9). L'identifiant EST le n° de dossier
    (GSA-AA-NNNNN), affiché en permanence et exigé sur les factures."""
    id: str
    prenom: str
    nom: str
    email: str
    contrat_ref: str                  # simple référence — gestion des contrats hors outil
    ndd: int                          # NDD retenu (déterminé hors outil)
    date_preinscription: str = field(default_factory=_today)
    date_echeance: str = ""           # F-30 : crédit initial + 1 an, reportée au renouvellement
    echeance_traitee: str = ""        # dernière échéance pour laquelle une décision est prise
    non_renouvellement: dict = field(default_factory=dict)  # {date, echeance, motif}
    telephone: str = ""
    aides: List[Aide] = field(default_factory=list)
    profil: dict = field(default_factory=dict)    # situationnel aidant
    analyse: str = ""                              # bilan situationnel VALIDÉ (F-44)
    seq_devis: int = 0                             # références dérivées §9 (-D01…)
    seq_remb: int = 0                              # (-R01…)

    @property
    def nom_complet(self): return f"{self.prenom} {self.nom}"


@dataclass
class Pro:
    id: str
    nom: str
    email: str = ""                   # e-mail de contact (F-72 : à fournir par aidance-pro)


@dataclass
class Prestation:
    id: str
    pro_id: str
    nom: str
    unite: str                        # "Par heure" | "Par jour" | "Prestation complète"
    prix: Decimal
    pid: str = ""
    familles: List[str] = field(default_factory=list)
    metiers: List[str] = field(default_factory=list)
    mod: List[str] = field(default_factory=list)
    nat: bool = True
    deps: List[str] = field(default_factory=list)
    rank: int = 2                     # 0 premium · 1 labellisé · 2 autre
    desc: str = ""

    @property
    def forfait(self): return self.unite == "Prestation complète"


@dataclass
class Devis:
    """Cycle §7.1 : demande · devisé · engagé · facturée · payé · refusé ·
    annulé. La réception de la facture (gestionnaire) vaut validation."""
    id: str                           # GSA-AA-NNNNN-Dnn (§9)
    assure_id: str
    prestation_id: str
    pro_id: str
    statut: str
    quantite: Optional[Decimal] = None
    total: Optional[Decimal] = None
    quantite_souhaitee: Optional[Decimal] = None  # F-47 — volume souhaité par l'assuré
    montant_engage: Optional[Decimal] = None      # RG-43 — part prise en charge (≤ disponible)
    reste_a_charge: Optional[Decimal] = None      # RG-43 — dû par l'assuré au pro
    message: str = ""                 # message de l'assuré-aidant (F-47)
    message_pro: str = ""             # message du pro (F-60)
    date_demande: str = field(default_factory=_today)
    date_engagement: str = ""         # acceptation de l'assuré-aidant (RG-51)
    date_facture: str = ""            # réception de la facture = VALIDATION (RG-45)
    motif_refus: str = ""             # F-48 (aidant) / F-60 (pro)
    motif_annulation: str = ""        # F-25
    montant_paye: Optional[Decimal] = None   # F-22 — partiel possible
    date_paiement: str = ""
    commentaire_paiement: str = ""
    jeton: str = ""                   # A-1a — lien sécurisé pro, propre à la demande
    jeton_ouvertures: int = 0         # consultations (plafond PRO_LIEN_MAX_OUVERTURES)
    bordereau_id: str = ""            # bordereau de virement du paiement


@dataclass
class Bordereau:
    """Bordereau de virement généré à CHAQUE passage en « payé » (RG-52).
    Lignes groupées par bénéficiaire : le PROFESSIONNEL pour un devis
    (coordonnées bancaires : sur sa facture — F-62), l'ASSURÉ-AIDANT pour un
    remboursement (IBAN du dossier). Exécuté à la banque hors outil, puis
    marqué exécuté ici (réconciliation bancaire)."""
    id: str                                   # BRD-AA-NNN (séquence annuelle)
    date: str
    lignes: List[dict] = field(default_factory=list)
    # ligne = {type, ref, dossier, beneficiaire, iban, montant}
    total: Decimal = Decimal("0")
    statut: str = "à exécuter"                # à exécuter | exécuté
    date_execution: str = ""
    commentaire: str = ""


@dataclass
class Remboursement:
    """Cycle §7.2 : soumise · piece_demandee · validée (= engagée) · refusée · payée."""
    id: str                           # GSA-AA-NNNNN-Rnn (§9)
    assure_id: str
    libelle: str
    motif: str
    montant: Decimal
    statut: str
    justificatif_nom: str = ""        # F-51 — dépôt réel (PDF / image)
    justificatif_data: str = ""       # dataURL (maquette ; stockage fichier en prod)
    montant_valide: Optional[Decimal] = None
    partiel: bool = False
    motif_refus: str = ""
    date_paiement: str = ""
    bordereau_id: str = ""            # bordereau de virement du paiement


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Store — l'unique état partagé                                         ║
# ╚══════════════════════════════════════════════════════════════════════╝
class Store:
    def __init__(self):
        self.assures: Dict[str, Assure] = {}
        self.enveloppes: Dict[str, Enveloppe] = {}      # clé = n° de dossier
        self.pros: Dict[str, Pro] = {}
        self.prestations: Dict[str, Prestation] = {}
        self.devis: Dict[str, Devis] = {}
        self.remboursements: Dict[str, Remboursement] = {}
        self.contacts: List[Contact] = []               # F-52
        self.bordereaux: Dict[str, Bordereau] = {}      # bordereaux de virement
        self.emails: List[Email] = []                   # notifications simulées
        self.lien_base: str = ""                        # base des liens (?dossier= / ?pro=)
        self.references_contrat: List[str] = list(REFERENCES_CONTRAT)  # référentiel (F-20)
        self._seq_dossier: Dict[int, int] = {}          # §9 : séquence par année
        self._seq_bordereau: Dict[int, int] = {}        # bordereaux : séquence annuelle

    def pmv(self, assure_id: str) -> Enveloppe:
        return self.enveloppes[assure_id]

    def numero_dossier(self, annee: Optional[int] = None) -> str:
        """§9 — GSA-AA-NNNNN : séquence annuelle sans trou, remise à 1 au 1er janvier."""
        a = annee or datetime.date.today().year
        self._seq_dossier[a] = self._seq_dossier.get(a, 0) + 1
        return f"GSA-{a % 100:02d}-{self._seq_dossier[a]:05d}"

    def numero_bordereau(self, annee: Optional[int] = None) -> str:
        a = annee or datetime.date.today().year
        self._seq_bordereau[a] = self._seq_bordereau.get(a, 0) + 1
        return f"BRD-{a % 100:02d}-{self._seq_bordereau[a]:03d}"

    def email(self, a: str, objet: str, corps: str):
        self.emails.append(Email(_now(), a, objet, corps))


def echeances(store: Store) -> List[dict]:
    """F-30 — pilotage des fins d'échéance : à traiter dès J−PREAVIS_ECHEANCE_JOURS."""
    out = []
    today = datetime.date.today()
    for a in store.assures.values():
        if not a.date_echeance:
            continue
        jours = (datetime.date.fromisoformat(a.date_echeance) - today).days
        if a.non_renouvellement.get("echeance") == a.date_echeance:
            statut = "non_renouvele"
        elif jours <= PREAVIS_ECHEANCE_JOURS and a.echeance_traitee != a.date_echeance:
            statut = "a_traiter"
        else:
            statut = "a_venir"
        out.append({"assure_id": a.id, "nom": a.nom_complet, "date_echeance": a.date_echeance,
                    "jours": jours, "statut": statut,
                    "non_renouvellement": a.non_renouvellement or None})
    out.sort(key=lambda x: x["date_echeance"])
    return out


def devis_par_jeton(store: Store, jeton: str) -> Optional[Devis]:
    """A-1a — résout le lien sécurisé pro. Jeton vide/inconnu -> None."""
    j = (jeton or "").strip()
    if not j:
        return None
    return next((d for d in store.devis.values() if d.jeton == j), None)


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  État du PMV et du dossier (§7.3)                                      ║
# ╚══════════════════════════════════════════════════════════════════════╝
def pmv_etat(store: Store, assure_id: str) -> str:
    """Verrouillé RIB · Verrouillé PFD · Bloqué · Utilisable."""
    a = store.assures.get(assure_id)
    env = store.enveloppes.get(assure_id)
    if env is not None and env.bloque:
        return "bloque"
    if not (env and env.iban):
        return "verrou_rib"
    princ = next((x for x in (a.aides if a else []) if x.principal), None)
    if princ is None or not princ.profil:
        return "verrou_pfd"
    return "utilisable"


PMV_ETAT_LIBELLE = {
    "verrou_rib": "Verrouillé — complétez votre profil (RIB) pour accéder à votre PMV.",
    "verrou_pfd": "Verrouillé — complétez le profil de votre proche (PFD) pour accéder à votre PMV.",
    "bloque": "Bloqué par le gestionnaire.",
    "utilisable": "",
}


def pmv_blocage(store: Store, assure_id: str) -> Optional[str]:
    """Raison pour laquelle le PMV n'est pas mobilisable, ou None (RG-42, F-27)."""
    etat = pmv_etat(store, assure_id)
    if etat == "utilisable":
        return None
    if etat == "bloque":
        env = store.enveloppes.get(assure_id)
        m = (env.motif_blocage or "").strip()
        return "PMV bloqué par le gestionnaire" + (f" : {m}" if m else ".")
    return PMV_ETAT_LIBELLE[etat]


def etat_dossier(store: Store, assure_id: str) -> str:
    """Pré-inscrit · Actif · Bloqué (la clôture n'est pas outillée en V1)."""
    e = pmv_etat(store, assure_id)
    if e == "bloque":
        return "Bloqué"
    return "Actif" if e == "utilisable" else "Pré-inscrit"


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Moteur 1 — Dossiers (Gestionnaire indemnisation · Assuré-aidant)      ║
# ╚══════════════════════════════════════════════════════════════════════╝
class MoteurDossiers:
    def __init__(self, store: Store):
        self.s = store

    # — F-20 : pré-inscription (PFD principal OBLIGATOIRE — RG-41) —
    # — F-20 : le gestionnaire tient le référentiel des références contrat —
    #   (il rattache les dossiers à des contrats gérés HORS outil, §1)
    def ajouter_contrat(self, reference: str) -> List[str]:
        ref = (reference or "").strip()
        if not ref:
            raise ValueError("Référence contrat vide.")
        if len(ref) > 120:
            raise ValueError("Référence contrat trop longue (120 caractères maximum).")
        if any(ref.casefold() == x.casefold() for x in self.s.references_contrat):
            raise ValueError(f"Référence déjà au référentiel : {ref}")
        self.s.references_contrat.append(ref)
        return self.s.references_contrat

    def preinscrire(self, prenom, nom, email, contrat_ref, ndd, credit_initial,
                    pfd: dict, commentaire: str = "", lien_base: str = "") -> Assure:
        try:
            ndd = int(ndd)
        except (TypeError, ValueError):
            raise ValueError("NDD retenu invalide.")
        if ndd not in NDD or not NDD[ndd].eligible:
            raise ValueError(f"NDD {ndd} non éligible : saisie refusée (RG-13, NDD 1–4).")
        if not (prenom or "").strip() or not (nom or "").strip() or not (email or "").strip():
            raise ValueError("Prénom, nom et e-mail requis.")
        if not isinstance(pfd, dict) or not (pfd.get("prenom") or "").strip() \
                or not (pfd.get("lien") or "").strip() or not str(pfd.get("naissance") or "").strip():
            raise ValueError("PFD principal obligatoire : prénom, lien et année de naissance (RG-41).")
        if (contrat_ref or "").strip() not in self.s.references_contrat:
            raise ValueError("Référence contrat inconnue : choisissez-la dans le référentiel "
                             "ou ajoutez-la d'abord (F-20 — la gestion des contrats reste hors outil).")
        try:
            pfd_ndd = int(pfd.get("ndd", ndd))
        except (TypeError, ValueError):
            pfd_ndd = ndd
        if pfd_ndd not in NDD or not NDD[pfd_ndd].eligible:
            raise ValueError(f"NDD du PFD {pfd_ndd} non éligible : saisie refusée (RG-13).")
        montant = D(credit_initial)
        if montant <= 0:
            raise ValueError("Crédit initial : montant positif requis (saisie libre, F-20).")

        a = Assure(self.s.numero_dossier(), prenom.strip(), nom.strip(), email.strip(),
                   (contrat_ref or "").strip(), ndd)
        a.aides.append(Aide(pfd["prenom"].strip(), pfd["lien"].strip(), pfd_ndd,
                            principal=True, naissance=str(pfd["naissance"]).strip()))
        self.s.assures[a.id] = a
        env = Enveloppe(a.id)
        self.s.enveloppes[a.id] = env
        env.crediter(montant, "Crédit initial", commentaire, "gestionnaire")
        a.date_echeance = (datetime.date.today()
                           + datetime.timedelta(days=DUREE_GARANTIE_JOURS)).isoformat()

        if (lien_base or "").strip():
            self.s.lien_base = lien_base.strip()
        lien = f"{self.s.lien_base}?dossier={a.id}"
        self.s.email(a.email, f"[MPA] Activez votre espace — dossier {a.id}",
                     f"Bonjour {a.prenom},\n\nVotre garantie GSA est ouverte. "
                     f"Votre n° de dossier : {a.id} (à communiquer aux professionnels).\n"
                     f"Activez votre espace : {lien}\n\n"
                     "Étapes : 1) votre profil et votre RIB ; 2) le profil de votre proche. "
                     "Votre PMV devient alors utilisable.")
        return a

    # — F-21 : crédit manuel · F-30/RG-54 : renouvellement sur demande valide,
    #   avec mise à jour du NDD retenu si le PFD a changé de niveau (RG-13) —
    def crediter(self, assure_id, montant, motif, commentaire="", ndd=None):
        a = self.s.assures.get(assure_id)
        if a is None:
            raise KeyError(f"Dossier introuvable : {assure_id}")
        changement_ndd, nd = "", None
        if motif == "Renouvellement" and ndd not in (None, ""):
            try:
                nd = int(ndd)
            except (TypeError, ValueError):
                raise ValueError("NDD invalide : entier attendu (RG-13, NDD 1–4).")
            if nd not in NDD or not NDD[nd].eligible:
                raise ValueError(f"NDD {nd} non éligible : saisie refusée (RG-13, NDD 1–4).")
            if nd != a.ndd:
                changement_ndd = f"NDD retenu : {a.ndd} → {nd}"
        comm = (commentaire or "").strip()
        if changement_ndd:
            comm = f"{comm} · {changement_ndd}" if comm else changement_ndd
        env = self.s.pmv(assure_id)
        env.crediter(D(montant), motif, comm)      # contrôle le motif/montant AVANT toute mutation du dossier
        if changement_ndd:
            a.ndd = nd
            for pfd in a.aides:                    # le NDD retenu suit le PFD de référence (RG-20/21)
                if pfd.principal:
                    pfd.ndd = nd
        if motif == "Renouvellement":
            base = a.date_echeance or _today()
            a.date_echeance = (datetime.date.fromisoformat(base)
                               + datetime.timedelta(days=DUREE_GARANTIE_JOURS)).isoformat()
            a.echeance_traitee = ""
            a.non_renouvellement = {}
            self.s.email(a.email, f"[MPA] Votre PMV est renouvelé — {a.id}",
                         f"Votre Pouvoir Mon Village est renouvelé : {eur(D(montant))} sont "
                         f"crédités. Votre garantie court désormais jusqu'au {a.date_echeance}."
                         + (f" Le niveau de dépendance retenu pour votre proche est désormais "
                            f"le NDD {nd}." if changement_ndd else ""))
        return a

    # — F-30/RG-54 : non-renouvellement tracé (motif obligatoire), notifié —
    def ne_pas_renouveler(self, assure_id, motif) -> Assure:
        a = self.s.assures.get(assure_id)
        if a is None:
            raise KeyError(f"Dossier introuvable : {assure_id}")
        if not (motif or "").strip():
            raise ValueError("Motif obligatoire (ex. aucune demande de renouvellement reçue, "
                             "demande non valide) — RG-54.")
        if not a.date_echeance:
            raise ValueError("Aucune échéance posée sur ce dossier.")
        a.echeance_traitee = a.date_echeance
        a.non_renouvellement = {"date": _today(), "echeance": a.date_echeance,
                                "motif": motif.strip()}
        self.s.email(a.email, f"[MPA] Votre garantie n'a pas été renouvelée — {a.id}",
                     f"Votre garantie est arrivée à échéance le {a.date_echeance} et n'a pas "
                     "été renouvelée. Pour toute question, rapprochez-vous de votre conseiller "
                     "(rubrique « Contacter un conseiller »).")
        return a

    # — F-41 : profil + RIB (verrou 1) —
    def completer_profil(self, assure_id, iban, telephone="", profil=None) -> Assure:
        a = self.s.assures.get(assure_id)
        if a is None:
            raise KeyError(f"Dossier introuvable : {assure_id}")
        iban = (iban or "").replace(" ", "").upper()
        if not iban_valide(iban):
            raise ValueError("IBAN invalide : vérifiez votre RIB.")
        env = self.s.enveloppes[assure_id]
        env.iban = iban
        if telephone:
            a.telephone = telephone
        if profil:
            a.profil = dict(profil)
        return a

    # — PFD complémentaires (F-42, sans effet sur le montant — RG-20/21) —
    def ajouter_aide(self, assure_id, prenom, lien, ndd=0, principal=False, naissance="") -> Assure:
        a = self.s.assures.get(assure_id)
        if a is None:
            raise KeyError("Dossier introuvable.")
        try:
            nd = int(ndd)
        except (TypeError, ValueError):
            nd = 0
        a.aides.append(Aide(prenom, lien, nd, bool(principal), naissance=str(naissance)))
        return a

    # — F-42 : profil situationnel du PFD (verrou 2) —
    def completer_profil_pfd(self, assure_id, pfd_id, profil) -> Assure:
        a = self.s.assures.get(assure_id)
        if a is None:
            raise KeyError("Dossier introuvable.")
        for pfd in a.aides:
            if pfd.id == pfd_id:
                pfd.profil = dict(profil or {})
                return a
        raise KeyError(f"PFD introuvable : {pfd_id}")

    # — F-44 : bilan situationnel validé (seule la version validée est stockée) —
    def completer_analyse(self, assure_id, texte) -> Assure:
        a = self.s.assures.get(assure_id)
        if a is None:
            raise KeyError(f"Dossier introuvable : {assure_id}")
        a.analyse = (texte or "").strip()
        return a

    # — F-27 : blocage / déblocage (RG-50 : ne retire jamais un crédit acquis) —
    def bloquer(self, assure_id, motif) -> Assure:
        if not (motif or "").strip():
            raise ValueError("Motif de blocage obligatoire.")
        env = self.s.pmv(assure_id)
        env.bloque = True
        env.motif_blocage = motif.strip()
        env._log("blocage", D(0), "Blocage du PMV", auteur="gestionnaire", commentaire=motif.strip())
        return self.s.assures[assure_id]

    def debloquer(self, assure_id, commentaire="") -> Assure:
        env = self.s.pmv(assure_id)
        env.bloque = False
        env.motif_blocage = ""
        env._log("déblocage", D(0), "Déblocage du PMV", auteur="gestionnaire", commentaire=commentaire)
        return self.s.assures[assure_id]

    # — F-26 : commentaire du gestionnaire sur un mouvement —
    def commenter_mouvement(self, assure_id, mouvement_id, commentaire) -> Assure:
        env = self.s.pmv(assure_id)
        for m in env.mouvements:
            if m.id == mouvement_id:
                m.commentaire = (commentaire or "").strip()
                return self.s.assures[assure_id]
        raise KeyError(f"Mouvement introuvable : {mouvement_id}")

    # — F-52 : contact conseiller —
    def contacter(self, assure_id, type_, message="") -> Contact:
        if type_ not in ("appel", "rappel", "message", "rendez-vous"):
            raise ValueError("Type de contact : appel, rappel, message ou rendez-vous.")
        a = self.s.assures.get(assure_id)
        if a is None:
            raise KeyError("Dossier introuvable.")
        c = Contact(_uid("CT"), assure_id, type_, (message or "").strip(), _now())
        self.s.contacts.append(c)
        return c


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Moteur 2 — Cycle devis (§7.1) : Assuré-aidant ↔ Pro ↔ Gestionnaire   ║
# ╚══════════════════════════════════════════════════════════════════════╝
class MoteurDevis:
    def __init__(self, store: Store):
        self.s = store

    def _ref(self, a: Assure) -> str:
        a.seq_devis += 1
        return f"{a.id}-D{a.seq_devis:02d}"

    def _lien_pro(self, d: "Devis") -> str:
        """A-1a — lien sécurisé à usage limité vers le formulaire mono-demande."""
        return f"{self.s.lien_base}?pro={d.jeton}"

    # — F-47 : demande (message libre) ; forfait → devisé ; e-mail + lien au pro —
    def demander(self, assure_id, prestation_id, message="", lien_base="", quantite=None) -> Devis:
        if (lien_base or "").strip():
            self.s.lien_base = lien_base.strip()
        return self._demander(assure_id, prestation_id, message, quantite)

    def _demander(self, assure_id, prestation_id, message="", quantite=None) -> Devis:
        a = self.s.assures.get(assure_id)
        if a is None:
            raise KeyError(f"Dossier introuvable : {assure_id}")
        _b = pmv_blocage(self.s, assure_id)
        if _b:
            raise ValueError(_b)
        p = self.s.prestations[prestation_id]
        d = Devis(self._ref(a), assure_id, prestation_id, p.pro_id,
                  statut="demande", message=(message or "").strip(),
                  jeton=secrets.token_urlsafe(9))     # A-1a : un jeton PAR demande
        if quantite not in (None, "") and not p.forfait:   # F-47 — volume souhaité
            q = D(quantite)
            if q <= 0:
                raise ValueError("Quantité souhaitée positive requise.")
            d.quantite_souhaitee = q
        if p.forfait:                       # forfait à prix fixe : devisé immédiatement
            d.quantite = D(1)
            d.total = p.prix
            d.statut = "devisé"
        self.s.devis[d.id] = d
        pro = self.s.pros[p.pro_id]
        self.s.email(pro.email or f"{pro.nom} (adresse du catalogue aidance-pro)",
                     f"[MPA] Demande de devis {d.id} — dossier {a.id}",
                     f"Prestation : {p.nom}\nN° de dossier : {a.id}\n"
                     f"Besoin exprimé : {d.message or '(non précisé)'}\n"
                     + (f"Volume souhaité par l'assuré-aidant : {fq(d.quantite_souhaitee)} "
                        f"{'jour(s)' if p.unite == 'Par jour' else 'heure(s)'} "
                        f"(à confirmer ou ajuster dans votre devis).\n" if d.quantite_souhaitee else "")
                     + f"Répondez (chiffrage ou refus) via votre lien sécurisé à usage limité,\n"
                     f"sans création de compte : {self._lien_pro(d)}\n"
                     f"Rappel : la facture sera à adresser à {EMAIL_GESTION} en mentionnant "
                     f"le n° de dossier {a.id} et la référence {d.id}.")
        return d

    # — F-60 : le pro chiffre… —
    def etablir(self, devis_id, quantite, message_pro="") -> Devis:
        d = self.s.devis[devis_id]
        if d.statut != "demande":
            raise ValueError(f"Chiffrage impossible : devis « {d.statut} ».")
        p = self.s.prestations[d.prestation_id]
        q = D(quantite)
        if q <= 0:
            raise ValueError("Quantité positive requise.")
        d.quantite = q
        d.total = (q * p.prix).quantize(Decimal("0.01"), ROUND_HALF_UP)
        if message_pro:
            d.message_pro = str(message_pro).strip()
        d.statut = "devisé"
        a = self.s.assures[d.assure_id]
        self.s.email(a.email, f"[MPA] Devis reçu — {d.id}",
                     f"{self.s.pros[d.pro_id].nom} propose : {p.nom}, "
                     f"{fq(q)} × {eur(p.prix)} = {eur(d.total)}. À accepter ou refuser dans votre espace.")
        return d

    # — … ou décline avec motif —
    def refuser_pro(self, devis_id, motif) -> Devis:
        d = self.s.devis[devis_id]
        if d.statut not in ("demande", "devisé"):
            raise ValueError(f"Refus impossible : devis « {d.statut} ».")
        if not (motif or "").strip():
            raise ValueError("Motif de refus obligatoire (F-60).")
        d.statut = "refusé"
        d.motif_refus = f"Décliné par le professionnel : {motif.strip()}"
        return d

    # — F-48 / RG-51 : acceptation = ENGAGEMENT AUTOMATIQUE, plafonné au
    #   disponible ; l'excédent = reste à charge CONFIRMÉ par l'assuré (RG-43) —
    def accepter(self, devis_id, accepter_reste_a_charge=False) -> Devis:
        d = self.s.devis[devis_id]
        if d.statut != "devisé":
            raise ValueError(f"Acceptation impossible : devis « {d.statut} ».")
        _b = pmv_blocage(self.s, d.assure_id)
        if _b:
            raise ValueError(_b)
        p = self.s.prestations[d.prestation_id]
        env = self.s.pmv(d.assure_id)
        pec = min(d.total, env.disponible)
        rac = (d.total - pec).quantize(Decimal("0.01"))
        if rac > 0 and not accepter_reste_a_charge:
            raise ResteACharge(d.total, env.disponible)
        if pec > 0:
            env.engager(pec, f"Engagement — {p.nom}"
                             + (f" (devis {eur(d.total)}, reste à charge {eur(rac)})" if rac > 0 else ""),
                        d.id, "assuré-aidant")
        d.montant_engage = pec
        d.reste_a_charge = rac
        d.statut = "engagé"
        d.date_engagement = _today()
        pro = self.s.pros[d.pro_id]
        if rac > 0:
            corps = (f"Votre devis ({eur(d.total)}) est accepté : la prestation peut être réalisée.\n"
                     f"L'assuré-aidant a confirmé un RESTE À CHARGE : la garantie prend en charge "
                     f"{eur(pec)}, le solde est dû par l'assuré-aidant directement auprès de vous.\n"
                     f"Après réalisation, établissez DEUX facturations :\n"
                     f"  • {eur(pec)} (part garantie) : facture à {EMAIL_GESTION}, mentionnant le "
                     f"n° de dossier {d.assure_id} et la référence {d.id} — sa réception vaut "
                     f"validation de la prestation et déclenche le paiement ;\n"
                     f"  • {eur(rac)} (reste à charge) : à facturer DIRECTEMENT à l'assuré-aidant, "
                     f"hors garantie.\n"
                     f"Suivi de la demande : {self._lien_pro(d)}")
        else:
            corps = (f"Votre devis ({eur(d.total)}) est accepté : la prestation peut être réalisée.\n"
                     f"Après réalisation, adressez votre facture à {EMAIL_GESTION} en mentionnant :\n"
                     f"  • le n° de dossier : {d.assure_id}\n"
                     f"  • la référence du devis : {d.id}\n"
                     f"  • le montant, au plus égal au montant engagé : {eur(pec)}\n"
                     f"La réception de votre facture vaut validation de la prestation et "
                     f"déclenche le paiement (aucune autre démarche).\n"
                     f"Suivi de la demande : {self._lien_pro(d)}")
        self.s.email(pro.email or f"{pro.nom} (adresse du catalogue aidance-pro)",
                     f"[MPA] Devis accepté — {d.id} — à facturer après réalisation", corps)
        return d

    def refuser(self, devis_id) -> Devis:       # F-48 (aidant)
        d = self.s.devis[devis_id]
        if d.statut not in ("demande", "devisé"):
            raise ValueError(f"Refus impossible : devis « {d.statut} ».")
        d.statut = "refusé"
        d.motif_refus = d.motif_refus or "Refusé par l'assuré-aidant"
        pro = self.s.pros[d.pro_id]
        self.s.email(pro.email or f"{pro.nom} (adresse du catalogue aidance-pro)",
                     f"[MPA] Demande close — {d.id}",
                     "L'assuré-aidant n'a pas donné suite à votre devis. "
                     "Aucune action attendue de votre part.")
        return d

    # — RG-45 : la réception de la facture (gestionnaire) VAUT VALIDATION —
    def facture_recue(self, devis_id, date_facture: str = "") -> Devis:
        d = self.s.devis[devis_id]
        if d.statut != "engagé":
            raise ValueError(f"Réception de facture impossible : devis « {d.statut} ».")
        d.statut = "facturée"
        d.date_facture = date_facture or _today()
        return d

    # — F-22 / RG-52 / RG-53 : paiement MANUEL, partiel possible, e-mail (F-24) —
    def payer(self, devis_id, montant=None, commentaire="", bordereau="") -> Devis:
        d = self.s.devis[devis_id]
        if d.statut != "facturée":
            raise ValueError("Paiement impossible : facture non reçue (RG-52).")
        engage = d.montant_engage if d.montant_engage is not None else d.total
        m = D(montant) if montant not in (None, "") else engage
        if m > engage:
            raise IntegriteError(f"Paiement {eur(m)} > montant engagé {eur(engage)} (RG-53).")
        p = self.s.prestations[d.prestation_id]
        env = self.s.pmv(d.assure_id)
        env.payer(m, f"Paiement pro — {p.nom}", d.id, commentaire)
        reliquat = (engage - m).quantize(Decimal("0.01"))
        if reliquat > 0:
            env.desengager(reliquat, f"Reliquat (paiement partiel) — {p.nom}", d.id, commentaire)
        d.statut = "payé"
        d.montant_paye = m
        d.date_paiement = _today()
        d.commentaire_paiement = (commentaire or "").strip()
        d.bordereau_id = bordereau
        a = self.s.assures[d.assure_id]
        self.s.email(a.email, f"[MPA] Paiement effectué — {d.id}",
                     f"Votre dépense « {p.nom} » a été acceptée : un virement de {eur(m)} "
                     f"est adressé au professionnel {self.s.pros[d.pro_id].nom} ({d.date_paiement})."
                     + (f"\nRéférence de virement : {bordereau}." if bordereau else "")
                     + (f"\nCommentaire du gestionnaire : {d.commentaire_paiement}" if d.commentaire_paiement else "")
                     + (f"\nReliquat recrédité sur votre disponible : {eur(reliquat)}." if reliquat > 0 else ""))
        return d

    # — F-25 : annulation par le gestionnaire → désengagement intégral —
    def annuler(self, devis_id, motif) -> Devis:
        d = self.s.devis[devis_id]
        if d.statut not in ("engagé", "facturée"):
            raise ValueError(f"Annulation impossible : devis « {d.statut} ».")
        if not (motif or "").strip():
            raise ValueError("Motif obligatoire pour annuler (F-25).")
        p = self.s.prestations[d.prestation_id]
        engage = d.montant_engage if d.montant_engage is not None else d.total
        if engage and engage > 0:
            env = self.s.pmv(d.assure_id)
            env.desengager(engage, f"Annulation — {p.nom}", d.id, motif.strip())
        d.statut = "annulé"
        d.motif_annulation = motif.strip()
        return d


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Moteur 3 — Remboursements (§7.2) : Assuré-aidant ↔ Gestionnaire       ║
# ╚══════════════════════════════════════════════════════════════════════╝
class MoteurRemboursement:
    def __init__(self, store: Store):
        self.s = store

    def _ref(self, a: Assure) -> str:
        a.seq_remb += 1
        return f"{a.id}-R{a.seq_remb:02d}"

    # — F-51 : soumission avec justificatif déposé —
    def soumettre(self, assure_id, libelle, motif, montant,
                  justificatif_nom, justificatif_data="") -> Remboursement:
        a = self.s.assures.get(assure_id)
        if a is None:
            raise KeyError(f"Dossier introuvable : {assure_id}")
        _b = pmv_blocage(self.s, assure_id)
        if _b:
            raise ValueError(_b)
        if not (justificatif_nom or "").strip():
            raise ValueError("Justificatif obligatoire (PDF ou image) — F-51.")
        m = D(montant)
        if m <= 0:
            raise ValueError("Montant positif requis.")
        r = Remboursement(self._ref(a), assure_id, (libelle or "").strip(),
                          (motif or "").strip(), m, "soumise",
                          justificatif_nom.strip(), justificatif_data or "")
        self.s.remboursements[r.id] = r
        return r

    # — F-23 : validation (partiel automatique — RG-44) ; « validée » ENGAGE le PMV —
    def valider(self, rid) -> Remboursement:
        r = self.s.remboursements[rid]
        if r.statut not in ("soumise", "piece_demandee"):
            raise ValueError(f"Validation impossible : demande « {r.statut} ».")
        env = self.s.pmv(r.assure_id)
        r.montant_valide = min(r.montant, env.disponible)
        if r.montant_valide <= 0:
            raise IntegriteError("Validation impossible : disponible nul (RG-44).")
        r.partiel = r.montant_valide < r.montant
        env.engager(r.montant_valide, f"Engagement — remboursement {r.libelle}", r.id, "gestionnaire")
        r.statut = "validée"
        a = self.s.assures[r.assure_id]
        self.s.email(a.email, f"[MPA] Remboursement validé — {r.id}",
                     f"Votre demande « {r.libelle} » est validée pour {eur(r.montant_valide)}"
                     + (f" (partiel, demandé {eur(r.montant)} — à hauteur du disponible)." if r.partiel else ".")
                     + " Le virement vous sera adressé prochainement.")
        return r

    def refuser(self, rid, motif="") -> Remboursement:
        r = self.s.remboursements[rid]
        if r.statut not in ("soumise", "piece_demandee"):
            raise ValueError(f"Refus impossible : demande « {r.statut} ».")
        r.statut = "refusée"
        r.motif_refus = (motif or "").strip()
        a = self.s.assures[r.assure_id]
        self.s.email(a.email, f"[MPA] Remboursement refusé — {r.id}",
                     f"Votre demande « {r.libelle} » a été refusée."
                     + (f" Motif : {r.motif_refus}" if r.motif_refus else ""))
        return r

    def demander_piece(self, rid) -> Remboursement:
        r = self.s.remboursements[rid]
        if r.statut != "soumise":
            raise ValueError(f"Demande de pièce impossible : demande « {r.statut} ».")
        r.statut = "piece_demandee"
        return r

    # — §7.2 : retour à « soumise » sur nouveau dépôt —
    def redeposer(self, rid, justificatif_nom, justificatif_data="") -> Remboursement:
        r = self.s.remboursements[rid]
        if r.statut != "piece_demandee":
            raise ValueError(f"Nouveau dépôt impossible : demande « {r.statut} ».")
        if not (justificatif_nom or "").strip():
            raise ValueError("Justificatif obligatoire.")
        r.justificatif_nom = justificatif_nom.strip()
        r.justificatif_data = justificatif_data or ""
        r.statut = "soumise"
        return r

    # — F-23 : marquer payée → ligne du bordereau de virement (RG-52) —
    def marquer_payee(self, rid, commentaire="", bordereau="") -> Remboursement:
        r = self.s.remboursements[rid]
        if r.statut != "validée":
            raise ValueError(f"Marquage impossible : demande « {r.statut} ».")
        env = self.s.pmv(r.assure_id)
        env.payer(r.montant_valide, f"Paiement remboursement — {r.libelle}", r.id, commentaire)
        r.statut = "payée"
        r.date_paiement = _today()
        r.bordereau_id = bordereau
        a = self.s.assures[r.assure_id]
        self.s.email(a.email, f"[MPA] Remboursement payé — {r.id}",
                     f"Votre dépense « {r.libelle} » a été acceptée : un virement de "
                     f"{eur(r.montant_valide)} vous est adressé ({r.date_paiement})."
                     + (f"\nRéférence de virement : {bordereau}." if bordereau else ""))
        return r


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Bordereaux de virement (RG-52) — générés au marquage « payé »         ║
# ╚══════════════════════════════════════════════════════════════════════╝
def payer_lot(store: Store, devis_items=None, remb_refs=None, commentaire="") -> dict:
    """Marque payés les éléments donnés et génère LE bordereau de virement.

    devis_items : réfs, ou {ref, montant} pour un paiement partiel (RG-53).
    Les lignes sont groupées par bénéficiaire : le pro (devis — coordonnées
    bancaires sur sa facture, F-62), l'assuré-aidant (remboursement — IBAN du
    dossier). Le bordereau n'est créé que si au moins un élément est payé."""
    md, mr = MoteurDevis(store), MoteurRemboursement(store)
    bid = store.numero_bordereau()
    lignes, payes, erreurs = [], [], []
    for item in (devis_items or []):
        ref = item["ref"] if isinstance(item, dict) else item
        montant = item.get("montant") if isinstance(item, dict) else None
        try:
            d = md.payer(ref, montant, commentaire, bordereau=bid)
            pro = store.pros[d.pro_id]
            lignes.append({"type": "devis", "ref": d.id, "dossier": d.assure_id,
                           "beneficiaire": pro.nom,
                           "iban": "Coordonnées bancaires : sur facture (F-62)",
                           "montant": d.montant_paye})
            payes.append(ref)
        except Exception as e:
            erreurs.append({"ref": ref, "erreur": str(e)})
    for ref in (remb_refs or []):
        try:
            r = mr.marquer_payee(ref, commentaire, bordereau=bid)
            a = store.assures[r.assure_id]
            lignes.append({"type": "remboursement", "ref": r.id, "dossier": r.assure_id,
                           "beneficiaire": f"{a.prenom} {a.nom} (assuré-aidant)",
                           "iban": store.pmv(r.assure_id).iban or "IBAN manquant",
                           "montant": r.montant_valide})
            payes.append(ref)
        except Exception as e:
            erreurs.append({"ref": ref, "erreur": str(e)})
    if not lignes:
        store._seq_bordereau[datetime.date.today().year] -= 1   # numéro rendu : rien payé
        return {"payes": [], "erreurs": erreurs, "bordereau": None}
    lignes.sort(key=lambda l: (l["beneficiaire"], l["ref"]))     # groupé par bénéficiaire
    b = Bordereau(bid, _today(), lignes,
                  sum((l["montant"] for l in lignes), Decimal("0")).quantize(Decimal("0.01")),
                  commentaire=(commentaire or "").strip())
    store.bordereaux[b.id] = b
    return {"payes": payes, "erreurs": erreurs, "bordereau": b}


def executer_bordereau(store: Store, bid: str, commentaire="") -> Bordereau:
    """Trace l'exécution bancaire (hors outil) du bordereau."""
    b = store.bordereaux.get(bid)
    if b is None:
        raise KeyError(f"Bordereau introuvable : {bid}")
    if b.statut == "exécuté":
        raise ValueError(f"Bordereau {bid} déjà exécuté le {b.date_execution}.")
    b.statut = "exécuté"
    b.date_execution = _today()
    if (commentaire or "").strip():
        b.commentaire = (b.commentaire + " · " if b.commentaire else "") + commentaire.strip()
    return b


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Alertes (F-25) & tâche quotidienne (F-70) — aucune libération auto    ║
# ╚══════════════════════════════════════════════════════════════════════╝
def alertes(store: Store) -> List[dict]:
    """F-70 — deux files de vigilance du gestionnaire, AUCUNE action automatique :
    • facture attendue : devis engagé sans facture depuis plus de
      DELAI_FACTURE_JOURS (A-3) — relancer le pro, ou annuler (litige, F-25) ;
    • bordereau non exécuté depuis plus de DELAI_BORDEREAU_JOURS (A-7) —
      réconciliation bancaire."""
    out = []
    today = datetime.date.today()
    for d in store.devis.values():
        if d.statut == "engagé" and d.date_engagement:
            attente = (today - datetime.date.fromisoformat(d.date_engagement)).days
            if attente > DELAI_FACTURE_JOURS:
                out.append({"type": "facture_attendue", "devis_id": d.id, "assure_id": d.assure_id,
                            "detail": f"Engagé le {d.date_engagement} — aucune facture reçue "
                                      f"depuis {attente} jours (délai A-3 : {DELAI_FACTURE_JOURS} j)"})
    for e in echeances(store):
        if e["statut"] == "a_traiter":
            j = e["jours"]
            out.append({"type": "echeance", "assure_id": e["assure_id"],
                        "detail": f"Échéance du PMV le {e['date_echeance']} "
                                  f"({'dans ' + str(j) + ' jour(s)' if j >= 0 else 'dépassée de ' + str(-j) + ' jour(s)'}) — "
                                  "renouveler (demande de renouvellement reçue et valide) ou "
                                  "tracer le non-renouvellement (RG-54)"})
    for b in store.bordereaux.values():
        if b.statut == "à exécuter":
            attente = (today - datetime.date.fromisoformat(b.date)).days
            if attente > DELAI_BORDEREAU_JOURS:
                out.append({"type": "bordereau", "bordereau_id": b.id,
                            "detail": f"Bordereau {b.id} ({eur(b.total)}) généré le {b.date} — "
                                      f"non exécuté depuis {attente} jours (A-7)"})
    return out


def tache_quotidienne(store: Store) -> dict:
    """F-70 — en production : tâche planifiée quotidienne qui alerte le
    gestionnaire. Dans la maquette : même calcul, déclenchable à la demande."""
    al = alertes(store)
    return {"date": _now(), "alertes": al,
            "message": f"{len(al)} alerte(s) : {sum(1 for a in al if a['type']=='facture_attendue')} facture(s) "
                       f"attendue(s), {sum(1 for a in al if a['type']=='bordereau')} bordereau(x) non exécuté(s), "
                       f"{sum(1 for a in al if a['type']=='echeance')} échéance(s) de PMV. "
                       "Aucune action automatique (F-70)."}


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Exports CSV (F-28)                                                    ║
# ╚══════════════════════════════════════════════════════════════════════╝
def _csv(rows: List[List]) -> str:
    def cell(v):
        s = "" if v is None else str(v)
        return '"' + s.replace('"', '""') + '"' if any(c in s for c in ';"\n') else s
    return "﻿" + "\n".join(";".join(cell(v) for v in row) for row in rows)


def exporter(store: Store, quoi: str) -> str:
    if quoi == "dossiers":
        rows = [["N_dossier", "Nom", "Prenom", "Email", "Contrat_ref", "NDD", "Etat",
                 "Date_preinscription", "Date_echeance", "Non_renouvele",
                 "Credit_cumule", "Disponible", "Engage", "Paye", "Solde"]]
        for a in store.assures.values():
            e = store.pmv(a.id)
            rows.append([a.id, a.nom, a.prenom, a.email, a.contrat_ref, a.ndd,
                         etat_dossier(store, a.id), a.date_preinscription,
                         a.date_echeance,
                         "oui" if a.non_renouvellement.get("echeance") == a.date_echeance else "non",
                         e.credit_cumule, e.disponible, e.engage, e.paye, e.solde])
    elif quoi == "mouvements":
        rows = [["N_dossier", "Date", "Type", "Montant", "Libelle", "Reference", "Auteur", "Commentaire"]]
        for a in store.assures.values():
            for m in store.pmv(a.id).mouvements:
                rows.append([a.id, m.date, m.type, m.montant, m.libelle, m.ref, m.auteur, m.commentaire])
    elif quoi == "devis":
        rows = [["Reference", "N_dossier", "Prestation", "Professionnel", "Statut",
                 "Quantite", "Total", "Montant_engage", "Reste_a_charge",
                 "Date_engagement", "Date_facture",
                 "Montant_paye", "Date_paiement", "Bordereau"]]
        for d in store.devis.values():
            p = store.prestations.get(d.prestation_id)
            rows.append([d.id, d.assure_id, p.nom if p else d.prestation_id,
                         store.pros[d.pro_id].nom, d.statut,
                         d.quantite, d.total, d.montant_engage, d.reste_a_charge,
                         d.date_engagement, d.date_facture,
                         d.montant_paye, d.date_paiement, d.bordereau_id])
    elif quoi == "remboursements":
        rows = [["Reference", "N_dossier", "Libelle", "Motif", "Montant_demande",
                 "Montant_valide", "Partiel", "Statut", "Date_paiement", "Justificatif"]]
        for r in store.remboursements.values():
            rows.append([r.id, r.assure_id, r.libelle, r.motif, r.montant, r.montant_valide,
                         "oui" if r.partiel else "non", r.statut, r.date_paiement, r.justificatif_nom])
    elif quoi == "bordereaux":
        rows = [["N_bordereau", "Date", "Statut", "Date_execution", "Beneficiaire",
                 "Type", "Reference", "N_dossier", "IBAN", "Montant", "Total_bordereau"]]
        for b in store.bordereaux.values():
            for l in b.lignes:
                rows.append([b.id, b.date, b.statut, b.date_execution, l["beneficiaire"],
                             l["type"], l["ref"], l["dossier"], l["iban"], l["montant"], b.total])
    else:
        raise ValueError("Export inconnu : dossiers, mouvements, devis, remboursements ou bordereaux.")
    return _csv(rows)



# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Mon baromètre aidant — repère visuel par dimension                   ║
# ║  3 zones d'action (Se renseigner · Demander de l'aide · Me protéger), ║
# ║  global + 6 dimensions, calcul DÉTERMINISTE et transparent sur les    ║
# ║  profils déjà saisis (aucune nouvelle question) ; lecture             ║
# ║  personnalisée par l'assistant. Repère indicatif — jamais un          ║
# ║  diagnostic (RG-62). Chaque ligne du barème est explicite ci-dessous. ║
# ╚══════════════════════════════════════════════════════════════════════╝
def _zone(score):
    if score < 30:
        return "vert"
    return "orange" if score < 60 else "rouge"


ZONES_BAROMETRE = {
    "vert": ("Équilibre préservé", "Se renseigner et anticiper : c'est le bon moment pour préparer la suite."),
    "orange": ("Vigilance", "Il y a un risque pour votre santé : c'est le moment de demander de l'aide."),
    "rouge": ("Protégez-vous", "Demandez de l'aide sans attendre — vous compter aussi fait partie de l'aide."),
}


def barometre(store: Store, assure_id: str) -> Optional[dict]:
    a = store.assures.get(assure_id)
    if a is None or not a.profil:
        return None
    p = a.profil or {}
    princ = next((x for x in a.aides if x.principal), None)
    q = (princ.profil if princ else {}) or {}
    g = lambda k: str(p.get(k) or "")
    gq = lambda k: str(q.get(k) or "")
    taches = p.get("taches") or []
    avq = q.get("avq") or []
    risques = q.get("risques") or []

    class Dim:
        def __init__(self, id_, libelle, maxi):
            self.id, self.libelle, self.maxi = id_, libelle, maxi
            self.pts = 0
            self.pese, self.appuis = [], []
            self.na = False
        def agg(self, pts, lib):
            self.pts += pts
            self.pese.append((pts, lib))
        def pro(self, pts, lib):
            self.pts -= pts
            self.appuis.append((pts, lib))
        def out(self):
            if self.na:
                return {"id": self.id, "libelle": self.libelle, "na": True,
                        "score": None, "zone": None, "pese": [], "appuis": []}
            sc = max(0, min(100, round(100 * self.pts / self.maxi)))
            self.pese.sort(key=lambda x: -x[0]); self.appuis.sort(key=lambda x: -x[0])
            return {"id": self.id, "libelle": self.libelle, "na": False,
                    "score": sc, "zone": _zone(sc),
                    "pese": [l for _, l in self.pese[:4]],
                    "appuis": [l for _, l in self.appuis[:3]]}

    # ── D1 · Charge d'aide (volume et intensité de l'aide apportée) ──
    d1 = Dim("charge", "Charge d'aide", 40)
    h = g("heures")
    if "Plus de 40" in h: d1.agg(16, "Plus de 40 h d'aide par semaine")
    elif "20 à 40" in h: d1.agg(12, "20 à 40 h d'aide par semaine")
    elif "10 à 20" in h: d1.agg(8, "10 à 20 h d'aide par semaine")
    elif "4 à 10" in h: d1.agg(4, "4 à 10 h d'aide par semaine")
    n = g("nuit")
    if "régulièrement" in n: d1.agg(8, "Aide la nuit, régulièrement")
    elif "ponctuellement" in n: d1.agg(4, "Aide la nuit, ponctuellement")
    if g("cohabite").startswith("Oui"): d1.agg(3, "Vous vivez avec votre proche")
    if "Plus d'1 h" in g("distance"): d1.agg(3, "Plus d'une heure de trajet")
    if len(taches) >= 4: d1.agg(6, f"{len(taches)} types de tâches assumés")
    elif len(taches) >= 2: d1.agg(3, f"{len(taches)} types de tâches assumés")
    if len(avq) >= 5: d1.agg(8, f"{len(avq)} actes du quotidien à soutenir")
    elif len(avq) >= 3: d1.agg(5, f"{len(avq)} actes du quotidien à soutenir")
    elif len(avq) >= 1: d1.agg(2, f"{len(avq)} acte(s) du quotidien à soutenir")
    mo = gq("mobilite")
    if "Alité" in mo: d1.agg(6, "Proche alité la majeure partie du temps")
    elif "Fauteuil" in mo: d1.agg(4, "Proche en fauteuil roulant")
    elif "Aide technique" in mo: d1.agg(2, "Proche aidé dans ses déplacements")
    if "Plus de 5" in g("anciennete"): d1.agg(3, "Aidant depuis plus de 5 ans")
    if p.get("aidesh"): d1.pro(3, "Des aides humaines interviennent déjà")

    # ── D2 · Charge mentale (vigilance, coordination, « y penser pour deux ») ──
    d2 = Dim("mentale", "Charge mentale", 35)
    cg = gq("cognitif")
    if "importants" in cg: d2.agg(8, "Troubles cognitifs importants : vigilance constante")
    elif "légers" in cg: d2.agg(4, "Troubles cognitifs légers du proche")
    if "Errance / désorientation" in risques: d2.agg(5, "Risque d'errance : l'esprit jamais tranquille")
    if "Sécurité du domicile" in risques: d2.agg(3, "Inquiétude sur la sécurité du domicile")
    autres = [x for x in risques if x not in ("Épuisement de l'aidant", "Errance / désorientation", "Sécurité du domicile")]
    if autres: d2.agg(min(len(autres), 3), "Autres risques à surveiller : " + ", ".join(autres[:2]))
    if "Démarches administratives" in taches: d2.agg(4, "Vous portez les démarches administratives")
    if "Soins / surveillance" in taches: d2.agg(4, "Vous assurez soins et surveillance")
    if g("role") == "Aidant principal": d2.agg(3, "Vous êtes l'aidant principal")
    if "seul aidant" in g("coaidants"): d2.agg(4, "Personne avec qui partager les décisions")
    if "régulièrement" in n: d2.agg(4, "Nuits fractionnées par l'aide")
    elif "ponctuellement" in n: d2.agg(2, "Sommeil parfois interrompu par l'aide")
    iso = gq("isolement")
    if iso == "Fort": d2.agg(4, "Proche très isolé : tout repose sur vous")
    elif iso == "Modéré": d2.agg(2, "Proche plutôt isolé")
    if q.get("aidesh"): d2.pro(2, "Des professionnels partagent la surveillance")

    # ── D3 · Santé & répit (impact sur votre santé, capacité à souffler) ──
    d3 = Dim("sante", "Santé & répit", 35)
    f = g("fatigue")
    if f == "Élevée": d3.agg(14, "Fatigue élevée")
    elif f == "Modérée": d3.agg(6, "Fatigue modérée")
    s_ = g("sante")
    if s_ == "Altérée": d3.agg(8, "Votre santé est altérée")
    elif s_ == "Moyenne": d3.agg(4, "Votre santé est moyenne")
    r = g("relais")
    if "Aucun relais" in r: d3.agg(8, "Aucun relais pour souffler")
    elif "parfois" in r: d3.agg(4, "Relais seulement occasionnel")
    elif "facilement" in r: d3.pro(3, "Un relais est possible facilement")
    if "Épuisement de l'aidant" in risques: d3.agg(5, "Risque d'épuisement identifié")
    if "régulièrement" in n: d3.agg(4, "Sommeil amputé régulièrement")
    elif "ponctuellement" in n: d3.agg(2, "Sommeil parfois amputé")
    if p.get("aidesh"): d3.pro(2, "Des aides humaines allègent le quotidien")

    # ── D4 · Vie professionnelle (concilier travail et aide) ──
    d4 = Dim("pro", "Vie professionnelle", 25)
    statut = g("statutpro")
    if statut in ("Retraité(e)", "Au foyer", "Demandeur d'emploi", ""):
        d4.na = True
    else:
        fx = g("flex")
        if fx == "Aucune flexibilité": d4.agg(6, "Aucune flexibilité d'horaires")
        elif fx == "Faible": d4.agg(5, "Faible flexibilité d'horaires")
        po = g("poste")
        if any(k in po for k in ("posté", "nuit", "variables")): d4.agg(4, "Horaires contraignants (" + po.lower() + ")")
        if g("temps") == "Temps plein" and any(k in h for k in ("10 à 20", "20 à 40", "Plus de 40")):
            d4.agg(4, "Temps plein + " + h.lower() + " d'aide")
        if g("temps") == "Temps partiel": d4.agg(2, "Activité réduite (temps partiel)")
        if g("contrat") in ("CDD", "Intérim"): d4.agg(2, "Contrat " + g("contrat"))
        if p.get("amenage"): d4.pro(3, "Aménagements obtenus : " + ", ".join(p.get("amenage")[:2]))
        else: d4.agg(3, "Aucun aménagement professionnel en place")

    # ── D5 · Entourage & relais (êtes-vous seul·e à porter ?) ──
    d5 = Dim("entourage", "Entourage & relais", 25)
    c = g("coaidants")
    if "seul aidant" in c: d5.agg(8, "Vous êtes seul(e) à aider")
    elif "un autre" in c: d5.agg(2, "Un seul co-aidant"); d5.pro(2, "Un co-aidant à vos côtés")
    elif "plusieurs" in c: d5.pro(3, "Plusieurs co-aidants à vos côtés")
    if "Aucun relais" in r: d5.agg(8, "Aucun relais possible")
    elif "parfois" in r: d5.agg(4, "Relais seulement occasionnel")
    elif "facilement" in r: d5.pro(3, "Relais facile à organiser")
    if iso == "Fort": d5.agg(4, "Le proche n'a que vous")
    elif iso == "Modéré": d5.agg(2, "Entourage du proche limité")
    if gq("entourage"): d5.pro(2, "D'autres proches présents : " + gq("entourage")[:40])
    if q.get("aidesh"): d5.pro(2, "Des professionnels interviennent auprès du proche")

    # ── D6 · Budget & droits (les dispositifs sont-ils mobilisés ?) ──
    #    NB maquette : sans donnée de reste à charge ni de perte de revenus,
    #    on mesure la MOBILISATION DES DROITS, pas l'impact financier réel.
    d6 = Dim("budget", "Budget & droits", 20)
    if not p.get("aidesf") and not p.get("aidesf_autre"):
        d6.agg(5, "Aucune aide financière d'aidant mobilisée (AJPA, CESU…)")
    else:
        d6.pro(2, "Aides d'aidant mobilisées : " + ", ".join((p.get("aidesf") or [])[:2]))
    if not q.get("aidesf") and not q.get("aidesf_autre"):
        d6.agg(5, "Aucune aide financière du proche mobilisée (APA, PCH…)")
    else:
        d6.pro(2, "Droits du proche activés : " + ", ".join((q.get("aidesf") or [])[:2]))
    if not q.get("aidest"): d6.agg(2, "Aucune aide technique installée")
    ad = gq("adapte")
    if ad == "Non": d6.agg(3, "Logement non adapté : des financements existent")
    elif ad == "En projet": d6.agg(1, "Adaptation du logement en projet")
    if g("temps") == "Temps partiel": d6.agg(2, "Temps partiel : revenus possiblement réduits")

    dims = [d.out() for d in (d1, d2, d3, d4, d5, d6)]

    # ── Signaux d'usage : le baromètre S'AFFINE avec la vie du dossier ──
    #    (services consommés, remboursements, contacts). Bornés à ±10 points
    #    de score par dimension : le déclaratif reste dominant, et chaque
    #    signal est AFFICHÉ en clair — jamais de scoring opaque.
    usage = _signaux_usage(store, assure_id)
    by_id = {d["id"]: d for d in dims}
    for dim_id, delta, lib in usage["signaux"]:
        d = by_id.get(dim_id)
        if d is None or d["na"]:
            continue
        d.setdefault("_u", 0)
        borne = max(-10 - d["_u"], min(10 - d["_u"], delta))
        if borne == 0:
            continue
        d["_u"] += borne
        d["score"] = max(0, min(100, d["score"] + borne))
        cible = d["pese"] if borne > 0 else d["appuis"]
        if sum(1 for x in cible if x.startswith(("Vous avez mobilisé", "Vos ", "Le PMV", "Votre PMV")) or "conseiller" in x or "30 jours" in x) < 2:
            cible.append(lib)
        d["zone"] = _zone(d["score"])
    for d in dims:
        d.pop("_u", None)

    actifs = [d for d in dims if not d["na"]]
    score = round(sum(d["score"] for d in actifs) / max(1, len(actifs)))
    zone = _zone(score)
    titre, action = ZONES_BAROMETRE[zone]
    return {"score": score, "zone": zone, "titre": titre, "action": action,
            "dimensions": dims, "pfd_profil": bool(q), "usage": usage["resume"]}


# Famille de prestation consommée -> dimension soulagée
_FAMILLE_DIM = {
    "Aide administrative": ("mentale", "démarches prises en charge"),
    "Aide psycho-affective": ("sante", "soutien psychologique en place"),
    "Aide humaine": ("charge", "renfort humain à domicile"),
    "Aide au parcours de soin": ("sante", "parcours de soin accompagné"),
    "Aide au parcours de vie": ("mentale", "coordination assurée par un pro"),
    "Aide matérielle": ("budget", "équipement financé"),
}


def _famille_dominante(p: "Prestation") -> Optional[str]:
    """Famille la plus représentative d'une prestation. Certains pros du
    catalogue cochent toutes les familles : on tranche alors par le nom."""
    fams = p.familles or []
    if not fams:
        return None
    if len(fams) <= 3:
        return fams[0]
    nom = (p.nom or "").lower()
    for mots, fam in (
        (("administrat", "démarche"), "Aide administrative"),
        (("coordination", "parcours de vie", "projet de vie"), "Aide au parcours de vie"),
        (("psycholog", "écoute", "soutien moral"), "Aide psycho-affective"),
        (("soin", "infirmi", "médic"), "Aide au parcours de soin"),
        (("matériel", "équipement", "aménagement", "téléassistance"), "Aide matérielle"),
        (("garde", "nuit", "domicile", "ménage", "répit", "accompagnement"), "Aide humaine"),
    ):
        if any(m in nom for m in mots) and fam in fams:
            return fam
    return fams[0]


def _signaux_usage(store: Store, assure_id: str) -> dict:
    """Signaux comportementaux du dossier (liste de (dimension, ±points, libellé))."""
    a = store.assures[assure_id]
    devis = [d for d in store.devis.values() if d.assure_id == assure_id]
    rembs = [r for r in store.remboursements.values() if r.assure_id == assure_id]
    sig = []

    # 1 · familles de services réellement mobilisées (engagé / facturée / payé)
    familles = []
    for d in reversed(devis):               # consommations récentes d'abord
        if d.statut not in ("engagé", "facturée", "payé"):
            continue
        p = store.prestations.get(d.prestation_id)
        fam = _famille_dominante(p) if p else None
        if fam and fam not in familles:
            familles.append(fam)
    for fam in familles[:4]:
        dim, lib = _FAMILLE_DIM.get(fam, ("charge", "service mobilisé"))
        sig.append((dim, -3, f"Vous avez mobilisé votre PMV : {lib}"))

    # 2 · remboursements validés ou payés : le PMV couvre les avances
    couverts = [r for r in rembs if r.statut in ("validée", "payée")]
    if couverts:
        mots = (couverts[0].motif or couverts[0].libelle or "").lower()
        if any(k in mots for k in ("transport", "taxi")):
            sig.append(("charge", -2, "Vos transports liés à l'aide sont couverts"))
        elif any(k in mots for k in ("repas", "portage")):
            sig.append(("charge", -2, "Le portage de repas est couvert"))
        else:
            sig.append(("budget", -2, "Le PMV rembourse vos avances"))

    # 3 · demandes rapprochées : la situation s'intensifie ?
    import datetime as _dt
    seuil = (_dt.date.today() - _dt.timedelta(days=30)).isoformat()
    recentes = [d for d in devis if (d.date_demande or "") >= seuil]
    if len(recentes) >= 3:
        sig.append(("mentale", 3, f"{len(recentes)} demandes en 30 jours : besoin qui s'intensifie"))


    # 5 · contact conseiller : vous n'êtes pas seul
    if any(c.assure_id == assure_id for c in store.contacts):
        sig.append(("entourage", -2, "Vous avez sollicité un conseiller"))

    # 6 · non-recours doux : forte charge déclarée et PMV jamais mobilisé
    p = a.profil or {}
    if not familles and not couverts and (p.get("fatigue") == "Élevée" or p.get("sante") == "Altérée"):
        sig.append(("sante", 4, "Votre PMV n'a pas encore servi — il est là pour vous soulager"))

    return {"signaux": sig,
            "resume": {"familles": familles, "nb_services": len([d for d in devis if d.statut in ("engagé", "facturée", "payé")]),
                       "nb_rembourses": len(couverts)}}


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Assistant IA — bilan (F-44) & évaluation des besoins (F-45, RG-60–63)║
# ╚══════════════════════════════════════════════════════════════════════╝
FAMILLES = [
    "Aide administrative",
    "Aide au parcours de soin",
    "Aide au parcours de vie",
    "Aide humaine",
    "Aide matérielle",
    "Aide psycho-affective",
]

_BESOIN_PAR_FAMILLE = {
    "Aide administrative": "Accompagnement administratif (dossiers, droits, démarches)",
    "Aide au parcours de soin": "Coordination du parcours de soin",
    "Aide au parcours de vie": "Accompagnement du parcours de vie (logement, orientation)",
    "Aide humaine": "Aide humaine à domicile (actes de la vie quotidienne)",
    "Aide matérielle": "Aide matérielle et adaptation du domicile",
    "Aide psycho-affective": "Soutien psycho-affectif et répit de l'aidant",
}

_MOTS = {
    "Aide administrative": ["dossier", "apa", "mdph", "papier", "administratif",
                            "caisse", "retraite", "impôt", "succession", "tutelle", "droits"],
    "Aide au parcours de soin": ["médecin", "soin", "hôpital", "kiné", "ergo",
                                 "traitement", "rééducation", "infirmier", "consultation"],
    "Aide au parcours de vie": ["ehpad", "logement", "déménage", "adaptation", "domicile",
                                "maintien", "orientation", "projet de vie", "établissement"],
    "Aide humaine": ["toilette", "repas", "ménage", "courses", "présence", "auxiliaire",
                     "lever", "coucher", "habillage", "quotidien"],
    "Aide matérielle": ["fauteuil", "lit médicalisé", "barre", "matériel", "équipement",
                        "monte-escalier", "déambulateur", "perte d'autonomie"],
    "Aide psycho-affective": ["épuisement", "fatigue", "moral", "isolement", "psychologique",
                              "stress", "angoisse", "répit", "seul", "soutien", "débordé"],
}


def _anticiper_fallback(socle, recit):
    txt = (json.dumps(socle, ensure_ascii=False) + " " + (recit or "")).lower()
    out = []
    for fam in FAMILLES:
        hits = [m for m in _MOTS[fam] if m in txt]
        if hits:
            out.append({"famille": fam, "besoin": _BESOIN_PAR_FAMILLE[fam],
                        "raison": f"Évoqué dans la situation : {', '.join(hits[:3])}."})
    if not out:
        out = [{"famille": "Aide psycho-affective",
                "besoin": _BESOIN_PAR_FAMILLE["Aide psycho-affective"],
                "raison": "Besoin de premier niveau pour tout aidant ; à confirmer avec lui."}]
    return out


def _anticiper_llm(socle, recit, key):
    sys_prompt = (
        "Tu assistes un gestionnaire d'indemnisation d'une garantie de soutien aux aidants. "
        "À partir de la situation, propose 2 à 5 besoins anticipés pour l'aidant et son proche. "
        "Chaque besoin DOIT être rattaché à exactement une de ces familles : "
        + " | ".join(FAMILLES) + ". "
        "Réponds UNIQUEMENT en JSON, sans texte autour, sous la forme "
        '{"besoins":[{"famille":"...","besoin":"...","raison":"..."}]}. '
        "Le champ famille est copié mot pour mot depuis la liste."
    )
    user = ("Situation structurée : " + json.dumps(socle, ensure_ascii=False)
            + "\n\nRécit libre de l'aidant : " + (recit or "(aucun)"))
    body = json.dumps({
        "model": "claude-sonnet-4-6",
        "max_tokens": 1024,
        "system": sys_prompt,
        "messages": [{"role": "user", "content": user}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    txt = "".join(b.get("text", "") for b in data.get("content", [])
                  if b.get("type") == "text").strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        if txt.lower().startswith("json"):
            txt = txt[4:]
    parsed = json.loads(txt)
    besoins = parsed.get("besoins", parsed) if isinstance(parsed, dict) else parsed
    out = [b for b in besoins if isinstance(b, dict) and b.get("famille") in FAMILLES]
    return out or _anticiper_fallback(socle, recit)


def anticiper_besoins(socle, recit):
    """Renvoie {moteur, besoins}. Utilise le LLM si ANTHROPIC_API_KEY est posée,
    sinon un repli heuristique — dans les deux cas contraint aux 6 familles."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        try:
            return {"moteur": "llm", "besoins": _anticiper_llm(socle, recit, key)}
        except Exception:
            pass
    return {"moteur": "repli", "besoins": _anticiper_fallback(socle, recit)}


def anticiper_prompt(prompt: str, system: str = None, max_tokens: int = 1100) -> str:
    """Proxy LLM générique. Le prompt utilisateur est construit côté client ; on
    relaie tel quel et on renvoie le texte du modèle. `system` permet de cadrer la
    tâche (ex. analyse situationnelle). Lève si la clé est absente ou en cas
    d'erreur, pour que le client bascule sur son repli."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY absente")
    payload = {
        "model": "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages", data=body, method="POST",
        headers={"content-type": "application/json", "x-api-key": key,
                 "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return "".join(b.get("text", "") for b in data.get("content", [])
                   if b.get("type") == "text").strip()


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Catalogue aidance-pro (F-72, A-2) — snapshot + endpoint optionnel    ║
# ╚══════════════════════════════════════════════════════════════════════╝
CATALOGUE_RAW = r'''{"rows": [{"pid": "18.0", "pro": "Julie Capitrel", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["distanciel", "presentiel_aidant", "presentiel_pro"], "nat": true, "deps": [], "prix": 570.0, "unite": "Prestation complète", "nom": "Retrouver mon énergie", "desc": "Un accompagnement puissant pour les aidant-es en surcharge, qui ont besoin de souffler, de se recentrer et de remettre du sens dans leur vie. Reprendr"}, {"pid": "19.0", "pro": "Julie Capitrel", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["presentiel_pro"], "nat": true, "deps": [], "prix": 580.0, "unite": "Prestation complète", "nom": "GAME OF RSE - comprendre et intégrer l'aidance en entreprise", "desc": "Une masterclass interactive et percutante pour comprendre les réalités des salariés aidants grâce à un jeu de cartes original. Idéal pour les équipes "}, {"pid": "20.0", "pro": "Julie Capitrel", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 147.0, "unite": "Prestation complète", "nom": "Programme d'accompagnement digital : Les Capsules de la Vigie - spécial Salariés-aidants", "desc": "Un programme d'accompagnement digital avec des capsules vidéos spécialement conçu par et pour les aidants. Pour vous accompagner et vous informer sur "}, {"pid": "2.0", "pro": "PREV & CARE", "rank": 2, "metiers": ["Conseiller(e) en économie sociale et familiale"], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 390.0, "unite": "Prestation complète", "nom": "Care Management", "desc": "Le Care Management, c’est un accompagnement personnalisé pour vous aider à mieux vivre votre rôle d’aidant. Un expert vous est dédié : il prend le tem"}, {"pid": "3.0", "pro": "Famirelay", "rank": 0, "metiers": [], "familles": ["Aide au parcours de vie"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 10.0, "unite": "Prestation complète", "nom": "Abonnement à Famirelay", "desc": "Famirelay propose une application mobile qui aide les aidants et leur entourage au quotidien. Famirelay optimise la coordination et la communication e"}, {"pid": "4.0", "pro": "Agnès PETIT PEREL", "rank": 0, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 60.0, "unite": "Prestation complète", "nom": "Soutien, clarté, action : votre coaching sur-mesure", "desc": "Coaching pour prendre du recul, décider et avancer sereinement Dans les moments de doute ou de tension liés à votre rôle d’aidant, il est essentiel de"}, {"pid": "5.0", "pro": "Agnès PETIT PEREL", "rank": 0, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 1620.0, "unite": "Prestation complète", "nom": "Bilan de Compétences Aidant : Valorisez votre parcours, révélez vos talents", "desc": "Vous accompagnez un proche au quotidien et vous vous interrogez sur votre parcours professionnel, vos compétences ou vos envies d’évolution ? Le bilan"}, {"pid": "6.0", "pro": "Agnès PETIT PEREL", "rank": 0, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 1300.0, "unite": "Prestation complète", "nom": "Entreprendre en tant qu’Aidant : Créez votre activité à votre rythme", "desc": "Vous êtes aidant et vous souhaitez vous lancer dans l’aventure entrepreneuriale, créer votre propre activité ou développer un projet professionnel qui"}, {"pid": "7.0", "pro": "Céline VIRISSEL", "rank": 2, "metiers": ["Assistant de service social (ASS)"], "familles": ["Aide administrative", "Aide au parcours de vie"], "mod": ["presentiel_aidant", "distanciel"], "nat": true, "deps": [], "prix": 50.0, "unite": "Par heure", "nom": "Accompagnement administratif", "desc": "Evaluation globale de la situation familiale et sociale Accompagnement dans les demandes MDPH ou APA. Soutien dans le quotidien : répit, ouverture de "}, {"pid": "8.0", "pro": "CFDP ASSURANCE", "rank": 0, "metiers": ["Conseiller(e) en économie sociale et familiale"], "familles": ["Aide administrative"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 50.0, "unite": "Prestation complète", "nom": "Renseignement Juridique tout domaine du droit", "desc": "Renseigner les aidants sur tous les domaines du droit"}, {"pid": "9.0", "pro": "Mieux zen huiles", "rank": 2, "metiers": ["Coach"], "familles": ["Aide psycho-affective"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 10.0, "unite": "Par heure", "nom": "Bilan bien être", "desc": "Je propose des bilans bien être pour évaluer vos besoins physiques et émotionnels, et créer du lien. À la suite de ce bilan je vous propose un accompa"}, {"pid": "10.0", "pro": "ADAPTIA", "rank": 0, "metiers": ["Ergothérapeute"], "familles": ["Aide au parcours de vie", "Aide matérielle"], "mod": ["presentiel_aidant"], "nat": true, "deps": [], "prix": 275.0, "unite": "Prestation complète", "nom": "Evaluation au domicile", "desc": "Evaluation par un ergothérapeute au domicile afin d'aménager le logement via des aides techniques et/ou des travaux."}, {"pid": "11.0", "pro": "Frédérique GUIBOUT", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide psycho-affective"], "mod": ["presentiel_pro"], "nat": true, "deps": [], "prix": 70.0, "unite": "Par heure", "nom": "Sophrologie - Relaxation", "desc": "Séance de sophrologie ou de relaxation afin de permettre une profonde récupération physique et mentale. Des séances tout en douceur, basées sur la res"}, {"pid": "30.0", "pro": "CREE SAS", "rank": 2, "metiers": ["Ergothérapeute"], "familles": ["Aide matérielle"], "mod": ["presentiel_aidant"], "nat": true, "deps": [], "prix": 50.0, "unite": "Prestation complète", "nom": "Essai poussette sur site", "desc": "Démonstration et essai d'une poussette"}, {"pid": "12.0", "pro": "Anne-Claire KUBALA", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide psycho-affective"], "mod": ["distanciel", "presentiel_pro"], "nat": true, "deps": [], "prix": 60.0, "unite": "Prestation complète", "nom": "séance soprologie bien-être", "desc": "un accompagnement personnalisé et adapté pour apprendre à gérer le stress : * des examens * au quotidien * pression au travail. Durée de la séance ent"}, {"pid": "13.0", "pro": "Anne-Claire KUBALA", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide psycho-affective"], "mod": ["distanciel", "presentiel_pro"], "nat": true, "deps": [], "prix": 270.0, "unite": "Prestation complète", "nom": "forfait 5 séances sophrologie", "desc": "Ce forfait comprend : • une première séance d'1h30 • 4 séances d'1h Ce forfait est idéal pour apprendre * à gérer les émotions de la prise de parole ("}, {"pid": "14.0", "pro": "Anne-Claire KUBALA", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide psycho-affective"], "mod": ["distanciel", "presentiel_pro"], "nat": true, "deps": [], "prix": 420.0, "unite": "Prestation complète", "nom": "forfait 8 séances sophrologie", "desc": "Ce forfait comprend : • 1 première séance d'1h30 • 7 séances d'1h. Ce forfait est idéal pour travailler des sujets plus complexes comme * la confiance"}, {"pid": "69.0", "pro": "Anne-Claire KUBALA", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide psycho-affective"], "mod": ["presentiel_pro"], "nat": true, "deps": [], "prix": 18.0, "unite": "Prestation complète", "nom": "Atelier : être bien au quotidien - tous les 2ème lundi du mois", "desc": "Spécialiste du \"Bien vivre son travail et se reconnecter au quotidien\", je vous propose : 🗓️ Tous les 2ème lundis du mois : lundi 13 avril 2026 - Lund"}, {"pid": "70.0", "pro": "Anne-Claire KUBALA", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide psycho-affective"], "mod": ["presentiel_pro", "distanciel"], "nat": true, "deps": [], "prix": 420.0, "unite": "Prestation complète", "nom": "Protocole Acouphène - Hyperacousie - vertiges", "desc": "Depuis mars 2026, j'ai obtenu la certification sophrologue spécialisé Acouphène. C'est un protocole en 7 séances qui permet de ✅ \"mettre à distance\" l"}, {"pid": "21.0", "pro": "Marie Tessier", "rank": 0, "metiers": [], "familles": ["Aide au parcours de soin", "Aide au parcours de vie", "Aide psycho-affective"], "mod": ["distanciel", "presentiel_pro", "presentiel_aidant"], "nat": true, "deps": [], "prix": 70.0, "unite": "Prestation complète", "nom": "Consultation allaitement maternel", "desc": "Un accompagnement pour préparer l'arrivée de bébé, puis la mise en place de la lactation et de l'allaitement, son soutien au fil des mois, lors de la "}, {"pid": "22.0", "pro": "Marie Tessier", "rank": 0, "metiers": [], "familles": ["Aide au parcours de soin", "Aide au parcours de vie", "Aide psycho-affective"], "mod": ["presentiel_pro", "distanciel"], "nat": true, "deps": [], "prix": 70.0, "unite": "Prestation complète", "nom": "Consultation sommeil", "desc": "Consultation permettant de mieux comprendre la physiologie du sommeil et les rythmes de l'enfant, puis ensuite de reprendre avec la famille les diffic"}, {"pid": "15.0", "pro": "LAURE WINTERBONE", "rank": 0, "metiers": ["Assistant de service social (ASS)"], "familles": ["Aide administrative", "Aide au parcours de vie"], "mod": ["presentiel_aidant", "distanciel"], "nat": true, "deps": [], "prix": 60.0, "unite": "Par heure", "nom": "Accompagnement aux démarches liées au handicap", "desc": "Dossier MDPH, conseils sur orientations, sur les prestations liées au handicap, aide au respect des droits... Tarif indicatif / Forfait possible"}, {"pid": "16.0", "pro": "Anne JUVANTENY", "rank": 0, "metiers": [], "familles": ["Aide au parcours de vie", "Aide psycho-affective"], "mod": ["presentiel_pro", "distanciel"], "nat": true, "deps": [], "prix": 77.0, "unite": "Par heure", "nom": "Thérapie familiale", "desc": "Le travail du thérapeute consiste à développer les échanges entre les membres de la famille, à faire en sorte que chacun puisse s’exprimer de façon au"}, {"pid": "17.0", "pro": "Anne JUVANTENY", "rank": 0, "metiers": [], "familles": ["Aide au parcours de vie", "Aide psycho-affective"], "mod": ["presentiel_pro", "distanciel"], "nat": true, "deps": [], "prix": 62.0, "unite": "Par heure", "nom": "Accompagnement individuel de l'aidant", "desc": "Accompagnement des aidants dans leur cheminement personnel. Approche intégrative (approche systémique, approche humaniste et orientations solutions) c"}, {"pid": "nan", "pro": "HMS devient VyV équipement médical", "rank": 0, "metiers": [], "familles": ["Aide matérielle"], "mod": [], "nat": false, "deps": [], "prix": null, "unite": "", "nom": "", "desc": ""}, {"pid": "24.0", "pro": "LIFE&MOBILITY", "rank": 0, "metiers": [], "familles": ["Aide matérielle"], "mod": ["presentiel_aidant"], "nat": true, "deps": [], "prix": 1.0, "unite": "Prestation complète", "nom": "Essai de matériel et contact revendeur médical", "desc": "Conseils et essai de matériel dans le cadre d'un besoin d'une solution de mobilité ou de verticalisation. Conseil sur le choix d'un prestataire medica"}, {"pid": "23.0", "pro": "Youne", "rank": 0, "metiers": ["Accompagnant éducatif et social (AES)", "Assistant de service social (ASS)", "Conseiller(e) en économie sociale et familiale", "Technicien de l'Intervention Sociale et Familiale (TISF)"], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 65.0, "unite": "Par heure", "nom": "Accompagnement social", "desc": "Un rendez-vous social à distance pour les aidants familiaux avec YOUNE Être aidant familial, c’est accompagner au quotidien un proche en situation de "}, {"pid": "29.0", "pro": "Payelo", "rank": 1, "metiers": ["Aide à domicile", "Assistant(e) familial(e)", "Assistant(e) maternel(le) (AM)", "Ergothérapeute"], "familles": ["Aide administrative", "Aide au parcours de vie"], "mod": ["distanciel", "presentiel_aidant", "presentiel_pro"], "nat": true, "deps": [], "prix": 10.99, "unite": "Prestation complète", "nom": "Payelo", "desc": "Payelo est une carte de paiement destinée aux personnes vulnérables et à leurs aidants, pilotée par une application mobile pour une utilisation en tou"}, {"pid": "25.0", "pro": "Coralie MONNET", "rank": 1, "metiers": [], "familles": ["Aide au parcours de vie", "Aide psycho-affective"], "mod": ["distanciel", "presentiel_aidant"], "nat": true, "deps": [], "prix": 60.0, "unite": "Par heure", "nom": "Accompagnement des parents d'enfant porteur de handicap dans leur cheminement et leur parentalité", "desc": "Dossier MDPH, conseils dans les démarches administratives & le projet de vie, accompagnement de l'impact du diagnostic au sein de la famille Aide ponc"}, {"pid": "26.0", "pro": "Auxi'Life", "rank": 2, "metiers": ["Aide à domicile", "Psychologue"], "familles": ["Aide administrative", "Aide au parcours de vie", "Aide humaine"], "mod": ["presentiel_aidant"], "nat": false, "deps": ["14", "28", "35", "42", "45", "47", "62", "76", "93", "19", "24", "27", "58", "60", "75", "78", "87", "33", "38", "77", "13", "18", "26", "31", "34", "44", "50", "59", "72", "80", "91", "95", "41"], "prix": 25.0, "unite": "Par heure", "nom": "Aide ménagère", "desc": "AUXI'life propose un accompagnement sur mesure pour les personnes fragilisées par l'âge, la maladie, le handicap ou en sortie d'hospitalisation, ainsi"}, {"pid": "33.0", "pro": "Auxi'Life", "rank": 2, "metiers": ["Aide à domicile", "Psychologue"], "familles": ["Aide administrative", "Aide au parcours de vie", "Aide humaine"], "mod": ["presentiel_pro", "presentiel_aidant"], "nat": true, "deps": [], "prix": 25.0, "unite": "Par heure", "nom": "Aide humaine", "desc": "Assistance dans les actes quotidiens de la vie ou l'aide à l'insertion sociale aux personnes âgées, handicapées ou atteintes de pathologies chroniques"}, {"pid": "27.0", "pro": "Le Lien Psy", "rank": 0, "metiers": ["Psychologue"], "familles": ["Aide psycho-affective"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 65.0, "unite": "Prestation complète", "nom": "Consultations psychologiques", "desc": "Consultation avec un psychologue clinicien psychothérapeute formé à l'impact de l'aidance"}, {"pid": "nan", "pro": "Association LÉA", "rank": 2, "metiers": ["Assistant de service social (ASS)", "Psychologue"], "familles": ["Aide administrative", "Aide matérielle"], "mod": [], "nat": false, "deps": [], "prix": null, "unite": "", "nom": "", "desc": ""}, {"pid": "28.0", "pro": "Gaelle DORADO", "rank": 2, "metiers": ["Accompagnant éducatif et social (AES)"], "familles": ["Aide psycho-affective"], "mod": ["presentiel_pro", "presentiel_aidant"], "nat": true, "deps": [], "prix": 50.0, "unite": "Prestation complète", "nom": "SOPHROLOGIE et GUIDANCE PARENTALE BARKLEY", "desc": "Séance de sophrologie adulte ou enfant (sophrologie ludique) 1h15 Programme de guidance parentale Barkley (2h, 65 €)"}, {"pid": "31.0", "pro": "Auger Katleen", "rank": 2, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 49.0, "unite": "Prestation complète", "nom": "BOX \"Une pause s'impose\"", "desc": "Parce qu’il y a des journées où tout déborde. Cette box est un kit de secours pour aider le corps à relâcher, le mental à souffler. En 30 minutes, ret"}, {"pid": "45.0", "pro": "INSPIRE by", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["presentiel_pro"], "nat": true, "deps": [], "prix": 550.0, "unite": "Prestation complète", "nom": "SEJOUR DE REPIT & DE RESSOURCEMENT pour les aidants dont le proche souffre d'un trouble psychique.", "desc": "3 jours / 2 nuits ou 5 jours / 4 nuits NOUER DES LIENS Les personnes présentes vivent la même réalité que vous. Seul ou à deux, venez partager vos cha"}, {"pid": "46.0", "pro": "INSPIRE by", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["distanciel", "presentiel_aidant"], "nat": true, "deps": [], "prix": 80.0, "unite": "Par heure", "nom": "ACCOMPAGNEMENT SUITE A UN DEUIL OU UNE TENTATIVE DE SUICIDE", "desc": ". Se sentir légitime dans sa souffrance et accompagné dans sa singularité . Recevoir un soutien émotionnel et une validation pour normaliser des émoti"}, {"pid": "47.0", "pro": "INSPIRE by", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["distanciel", "presentiel_aidant"], "nat": true, "deps": [], "prix": 80.0, "unite": "Par heure", "nom": "ACCOMPAGNEMENT INDIVIDUEL", "desc": "• Vous libérer de ce qui pèse • Exprimer et apprivoiser votre vulnérabilité • Obtenir des éclairages et des pistes concrètes pour cheminer • Recevoir "}, {"pid": "32.0", "pro": "Eliane DEQUIEDT", "rank": 2, "metiers": ["Psychologue"], "familles": ["Aide au parcours de soin", "Aide psycho-affective"], "mod": ["presentiel_pro", "distanciel", "presentiel_aidant"], "nat": true, "deps": [], "prix": 60.0, "unite": "Par heure", "nom": "Consultations de soutien psychologique", "desc": "Consultations avec un psychologue clinicien afin de parler de ses difficultés et de ce qui peut faire souffrir. C'est un espace confidentiel qui perme"}, {"pid": "34.0", "pro": "MARGUERITE SERVICES", "rank": 2, "metiers": ["Assistant de service social (ASS)", "Conseiller(e) en économie sociale et familiale", "Technicien de l'Intervention Sociale et Familiale (TISF)"], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 430.0, "unite": "Prestation complète", "nom": "Évaluation, diagnostic et préconisations", "desc": "215€ après crédit d'impôt (L’obtention de cette aide est soumise à conditions) Entretien d’évaluation approfondie d’une durée de 60 minutes, mené par "}, {"pid": "35.0", "pro": "MARGUERITE SERVICES", "rank": 2, "metiers": ["Assistant de service social (ASS)", "Conseiller(e) en économie sociale et familiale", "Technicien de l'Intervention Sociale et Familiale (TISF)"], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 840.0, "unite": "Prestation complète", "nom": "Évaluation, diagnostic et mise en oeuvre", "desc": "420€ après crédit d'impôt (L’obtention de cette aide est soumise à conditions) Entretien d’évaluation approfondie (60 minutes) - Réalisé par un care m"}, {"pid": "36.0", "pro": "MARGUERITE SERVICES", "rank": 2, "metiers": ["Assistant de service social (ASS)", "Conseiller(e) en économie sociale et familiale", "Technicien de l'Intervention Sociale et Familiale (TISF)"], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 290.0, "unite": "Prestation complète", "nom": "Sortie d'hospitalisation", "desc": "Accompagnement personnalisé – 3 formules adaptées à vos besoins (Prix après crédit d’impôt – obtention soumise à conditions) Offre Essentielle – 145€ "}, {"pid": "37.0", "pro": "MARGUERITE SERVICES", "rank": 2, "metiers": ["Assistant de service social (ASS)", "Conseiller(e) en économie sociale et familiale", "Technicien de l'Intervention Sociale et Familiale (TISF)"], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 570.0, "unite": "Prestation complète", "nom": "Accompagnement au deuil", "desc": "285€ après crédit d'impôt (L’obtention de cette aide est soumise à conditions) Soutien dans l’organisation des obsèques - Le care manager accompagne l"}, {"pid": "38.0", "pro": "MARGUERITE SERVICES", "rank": 2, "metiers": ["Assistant de service social (ASS)", "Conseiller(e) en économie sociale et familiale", "Technicien de l'Intervention Sociale et Familiale (TISF)"], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 190.0, "unite": "Prestation complète", "nom": "Coordination de services à domicile", "desc": "95€ après crédit d'impôt (L’obtention de cette aide est soumise à conditions) À la manière d’une conciergerie médico-sociale, le care manager identifi"}, {"pid": "39.0", "pro": "MARGUERITE SERVICES", "rank": 2, "metiers": ["Assistant de service social (ASS)", "Conseiller(e) en économie sociale et familiale", "Technicien de l'Intervention Sociale et Familiale (TISF)"], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 190.0, "unite": "Prestation complète", "nom": "Accompagnement administratif", "desc": "95€ après crédit d'impôt (L’obtention de cette aide est soumise à conditions) Prise de contact avec les organismes concernés (caisses de retraite, mut"}, {"pid": "40.0", "pro": "MARGUERITE SERVICES", "rank": 2, "metiers": ["Assistant de service social (ASS)", "Conseiller(e) en économie sociale et familiale", "Technicien de l'Intervention Sociale et Familiale (TISF)"], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 290.0, "unite": "Prestation complète", "nom": "Habitat adapté", "desc": "145€ après crédit d'impôt(L’obtention de cette aide est soumise à conditions) À la demande du Client, le care manager l’accompagne pour clarifier ses "}, {"pid": "41.0", "pro": "MARGUERITE SERVICES", "rank": 2, "metiers": ["Assistant de service social (ASS)", "Conseiller(e) en économie sociale et familiale", "Technicien de l'Intervention Sociale et Familiale (TISF)"], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 380.0, "unite": "Prestation complète", "nom": "Montage de dossier", "desc": "90€ après crédit d'impôt (L’obtention de cette aide est soumise à conditions) Constitution complète du dossier, à partir des pièces justificatives fou"}, {"pid": "42.0", "pro": "MARGUERITE SERVICES", "rank": 2, "metiers": ["Assistant de service social (ASS)", "Conseiller(e) en économie sociale et familiale", "Technicien de l'Intervention Sociale et Familiale (TISF)"], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 380.0, "unite": "Prestation complète", "nom": "L’aménagement du domicile", "desc": "190€ après crédit d'impôt (L’obtention de cette aide est soumise à conditions) Adapter son logement peut changer la vie… à condition de trouver les bo"}, {"pid": "48.0", "pro": "La bulle de Jade", "rank": 2, "metiers": ["Coach"], "familles": ["Aide administrative", "Aide au parcours de vie", "Aide humaine"], "mod": ["presentiel_pro"], "nat": true, "deps": [], "prix": 200.0, "unite": "Prestation complète", "nom": "Le Dojo des Héros - 2ème Saison", "desc": "Chaque samedi de 14h30 à 15h30 & de 15h30 à 16h30 (hors vacances scolaires) / 2 créneaux de 1h (à choisir) ​🎨 Activités proposées 🎨 ​🛝 Parcours de mot"}, {"pid": "49.0", "pro": "La bulle de Jade", "rank": 2, "metiers": ["Coach"], "familles": ["Aide administrative", "Aide au parcours de vie", "Aide humaine"], "mod": ["presentiel_aidant"], "nat": true, "deps": [], "prix": 1.0, "unite": "Prestation complète", "nom": "Dispositif 1h - J'accompagne un enfant en situation de handicap", "desc": "J'accompagne une enfant pendant 1h apres l'ecole. Vous avez 1h à offrir ? Rejoignez le dispositif \"1h de répit, 1h d'activité pour un enfant\" et perme"}, {"pid": "43.0", "pro": "A2DOM", "rank": 2, "metiers": ["Ergothérapeute", "Kiné"], "familles": ["Aide au parcours de soin", "Aide humaine", "Aide matérielle"], "mod": ["presentiel_aidant"], "nat": false, "deps": ["22", "35"], "prix": 1.0, "unite": "Prestation complète", "nom": "Evaluation et Installation de Matériel médical à domicile", "desc": "A2DOM vous accompagne à domicile dans l'installation du matériel médical dont vous avez besoin. Une visite préalable gratuite, permet à nos intervenan"}, {"pid": "50.0", "pro": "PDA pour Tous - Mes Médocs du jour", "rank": 2, "metiers": ["Aide à domicile", "Assistant(e) familial(e)"], "familles": ["Aide au parcours de soin"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 16.9, "unite": "Prestation complète", "nom": "PDA - Préparation des doses à Administer", "desc": "Préparation du traitement médicamenteux sous forme de sachets-doses par moment de prise"}, {"pid": "51.0", "pro": "Nathalie Pommier", "rank": 2, "metiers": [], "familles": ["Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["presentiel_pro", "distanciel", "presentiel_aidant"], "nat": true, "deps": [], "prix": 65.0, "unite": "Par heure", "nom": "Première séance de sophrologie : \"découverte de la sophrologie\"", "desc": "Premier rdv de contact d'1h30, qui permet d'analyser le besoin de la personne, d'effectuer un bilan (anamnèse) de la personne sur l'histoire d'une mal"}, {"pid": "53.0", "pro": "Nathalie Pommier", "rank": 2, "metiers": [], "familles": ["Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["presentiel_pro", "presentiel_aidant", "distanciel"], "nat": true, "deps": [], "prix": 60.0, "unite": "Par heure", "nom": "Consultation de suivi de sophrologie", "desc": "Suivi de sophrologie après la première consultation qui a permis de définir votre besoin, et plus spécifiquement votre objectif, une séance commence t"}, {"pid": "52.0", "pro": "SAME Service d'accompagnement au Mieux Etre", "rank": 2, "metiers": ["Assistant de service social (ASS)"], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["presentiel_pro", "presentiel_aidant", "distanciel"], "nat": false, "deps": ["974", "02", "10", "14", "15", "28", "35", "39", "40", "42", "45", "47", "55", "61", "62", "63", "67", "68", "76", "89", "93", "04", "05", "07", "08", "09", "17", "19", "24", "27", "37", "48", "58", "60", "64", "69", "71", "75", "78", "81", "82", "83", "85", "87", "88", "92", "03", "06", "11", "22", "23", "25", "29", "30", "33", "36", "38", "51", "52", "57", "65", "66", "73", "74", "77", "84", "86", "94", "01", "12", "13", "16", "18", "21", "26", "31", "32", "34", "43", "44", "46", "49", "50", "56", "59", "70", "72", "80", "91", "95", "41", "53", "54", "79", "90", "971", "972", "973", "976", "975", "977", "978", "986", "987", "988"], "prix": 60.0, "unite": "Par heure", "nom": "Accompagnement individuel", "desc": "Intervention en présentiel sur la Réunion ou en distanciel (visio) sur la France métropolitaine Assistante sociale experte dans l'accompagnement des a"}, {"pid": "54.0", "pro": "Ernesti", "rank": 2, "metiers": [], "familles": ["Aide humaine"], "mod": ["presentiel_aidant"], "nat": true, "deps": [], "prix": 22.9, "unite": "Par heure", "nom": "Garde de nuit et accompagnement en journée par des étudiants en santé", "desc": "Notre service de soins à domicile est assuré par des étudiants en santé soigneusement sélectionnés pour leur expertise et leur dévouement. Ils ont pou"}, {"pid": "56.0", "pro": "Emilie Record", "rank": 2, "metiers": ["Coach"], "familles": ["Aide psycho-affective"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 70.0, "unite": "Par heure", "nom": "Accompagnement individuel", "desc": "Cet accompagnement s’adresse à vous si : - vous accompagnez un proche malade, en situation de handicap ou de fragilité, - vous vous sentez épuisé, tir"}, {"pid": "57.0", "pro": "Emilie Record", "rank": 2, "metiers": ["Coach"], "familles": ["Aide psycho-affective"], "mod": ["presentiel_pro"], "nat": true, "deps": [], "prix": 1000.0, "unite": "Par jour", "nom": "Animation de table(s) ronde(s) \"Le cercle des aidants\"", "desc": "Un espace collectif pour libérer la parole, sensibiliser et soutenir les collaborateurs aidants. Ce temps d’échange permet de briser l’isolement, de m"}, {"pid": "55.0", "pro": "Younify", "rank": 2, "metiers": [], "familles": ["Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 1.0, "unite": "Prestation complète", "nom": "Création d'une bulle de soutien pour soi ou pour un proche", "desc": "Younify permet de créer une bulle de soutien autour d’une personne fragilisée, réunissant trois rôles : l’aidé, ses aidants et ses soutiens (famille, "}, {"pid": "58.0", "pro": "Cécile PASCUAL", "rank": 2, "metiers": [], "familles": ["Aide psycho-affective"], "mod": ["presentiel_pro", "presentiel_aidant", "distanciel"], "nat": true, "deps": [], "prix": 60.0, "unite": "Par heure", "nom": "Accompagnement bien être des aidants", "desc": "Accompagnement en consultation individuelle soit au cabinet, à domicile ou en visioconférence. - Accueil et écoute de vos difficultés et besoins -expl"}, {"pid": "60.0", "pro": "Les Voisins Beaucemaine", "rank": 2, "metiers": [], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["presentiel_pro"], "nat": true, "deps": [], "prix": 150.0, "unite": "Prestation complète", "nom": "Séjour aidant-aidé à la carte", "desc": "Découvrez nos séjours spécialement conçus pour ceux qui accompagnent un proche fragilisé au quotidien : un moment pour vous ressourcer, partager et pr"}, {"pid": "61.0", "pro": "Les Voisins Beaucemaine", "rank": 2, "metiers": [], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["presentiel_pro"], "nat": true, "deps": [], "prix": 70.0, "unite": "Par jour", "nom": "Nuit à l'hôtel", "desc": "Plongez au cœur de la campagne bretonne dans notre hôtel entièrement adapté et accessible PMR, un havre de sérénité pensé pour tous les voyageurs, mai"}, {"pid": "62.0", "pro": "Cyndia TON", "rank": 2, "metiers": ["Coach"], "familles": [], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 1800.0, "unite": "Prestation complète", "nom": "Bilan de compétences", "desc": "Le bilan de compétences est un accompagnement structuré et réglementé permettant de faire le point sur ses compétences, ses motivations et ses priorit"}, {"pid": "63.0", "pro": "Edwige Cochaux", "rank": 2, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["presentiel_aidant", "distanciel"], "nat": true, "deps": [], "prix": 1000.0, "unite": "Prestation complète", "nom": "Coaching individuel", "desc": "En 8 séances individuelles sur 4 mois en moyenne : Vous aider à retrouver votre juste positionnement, transformé par votre parcours , retrouver votre "}, {"pid": "64.0", "pro": "Edwige Cochaux", "rank": 2, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["presentiel_pro"], "nat": true, "deps": [], "prix": 50.0, "unite": "Prestation complète", "nom": "Atelier inspiré de l'art ancestral japonais Kintsugi", "desc": "Atelier en petit groupe qui permet d'honorer les vulnérabilités et les blessures intérieures, et ainsi comprendre comment elles renforcent l'être huma"}, {"pid": "65.0", "pro": "Nelly BEKHEDDA", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["presentiel_pro", "presentiel_aidant", "distanciel"], "nat": true, "deps": [], "prix": 80.0, "unite": "Par heure", "nom": "Accompagnement Ressources", "desc": "Que vous ressentiez du découragement, un manque d’estime, des doutes sur vos capacités ou l’impression de subir plutôt que de décider, notamment si vo"}, {"pid": "66.0", "pro": "Nelly BEKHEDDA", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["presentiel_pro", "distanciel"], "nat": true, "deps": [], "prix": 1600.0, "unite": "Prestation complète", "nom": "Bilan de compétences", "desc": "Le bilan de compétences est une étape précieuse dans tout parcours professionnel. Il est accessible à tout moment de la vie active et sans limite d’âg"}, {"pid": "67.0", "pro": "Nelly BEKHEDDA", "rank": 1, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["distanciel", "presentiel_pro"], "nat": true, "deps": [], "prix": 80.0, "unite": "Par heure", "nom": "Accompagnement Ressources Pro", "desc": "Vos évènements de vie ont pu impacter votre parcours, créer une pause, un questionnement, une perte de confiance ou le besoin de réorganiser vos prior"}, {"pid": "68.0", "pro": "Association Toliss'all", "rank": 2, "metiers": [], "familles": ["Aide administrative", "Aide au parcours de vie", "Aide humaine"], "mod": ["presentiel_pro"], "nat": true, "deps": [], "prix": 5.0, "unite": "Prestation complète", "nom": "Séance adaptée de loisirs", "desc": "Toliss’All propose des temps de répit pensés pour les aidants et leurs aidés, où chacun peut profiter d’une activité adaptée à ses besoins. Les séance"}, {"pid": "71.0", "pro": "Éclat De Vie", "rank": 2, "metiers": ["Accompagnant éducatif et social (AES)"], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["presentiel_aidant"], "nat": true, "deps": [], "prix": 40.0, "unite": "Par heure", "nom": "Développer l’autonomie", "desc": "Accompagnement à l'hygiène, organisation quotidienne, gestion du budget, repères et stabilité quotidienne"}, {"pid": "72.0", "pro": "Éclat De Vie", "rank": 2, "metiers": ["Accompagnant éducatif et social (AES)"], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["presentiel_aidant"], "nat": true, "deps": [], "prix": 40.0, "unite": "Par heure", "nom": "Favoriser la sociabilisation et vie relationnelle", "desc": "Activités collectives, ludiques, communication, gestion des émotions, apprentissage des règles sociales"}, {"pid": "73.0", "pro": "Éclat De Vie", "rank": 2, "metiers": ["Accompagnant éducatif et social (AES)"], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["presentiel_aidant"], "nat": true, "deps": [], "prix": 40.0, "unite": "Par heure", "nom": "Participer à la vie culturelle et sociale", "desc": "S'intégrer à son environnement, découvertes, sorties, développer la curiosité"}, {"pid": "74.0", "pro": "Swan VERSTREPEN", "rank": 2, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide psycho-affective"], "mod": ["distanciel", "presentiel_pro"], "nat": true, "deps": [], "prix": 70.0, "unite": "Prestation complète", "nom": "Accompagnement en coaching et/ou gestalt thérapie", "desc": "Difficultés relationnelles - Burn out - Perte de repères - Transition de vie - Séparation - Guidance parentale Je vous accompagne avec bienveillance p"}, {"pid": "75.0", "pro": "Swan VERSTREPEN", "rank": 2, "metiers": ["Coach"], "familles": ["Aide au parcours de vie", "Aide psycho-affective"], "mod": ["presentiel_pro", "distanciel"], "nat": true, "deps": [], "prix": 70.0, "unite": "Prestation complète", "nom": "Accompagnement en évolution ou reconversion professionnelle", "desc": "Je vous accompagne pour clarifier votre situation, évaluer vos possibilités et vous orienter vers de nouveaux possibles. Séance de 45 mn ou bien bilan"}, {"pid": "76.0", "pro": "ELODIE ONEXAYVIENG", "rank": 2, "metiers": [], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 80.0, "unite": "Par heure", "nom": "Gestion du stress et des émotions", "desc": "Vous vous sentez submergé(e) par la charge émotionnelle de l'aidance ? Je vous accompagne pour identifier vos sources de stress, comprendre vos émotio"}, {"pid": "77.0", "pro": "ELODIE ONEXAYVIENG", "rank": 2, "metiers": [], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 100.0, "unite": "Par heure", "nom": "Accompagnement au changement et transformation personnel", "desc": "Grâce aux techniques de Programmation Neuro-Linguistique, je vous aide à dépasser vos blocages, clarifier vos objectifs et activer vos ressources inte"}, {"pid": "78.0", "pro": "ELODIE ONEXAYVIENG", "rank": 2, "metiers": [], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["presentiel_pro", "distanciel"], "nat": true, "deps": [], "prix": 750.0, "unite": "Par jour", "nom": "Conseil en entreprise – Accompagnement des salariés aidants", "desc": "J'accompagne les entreprises dans la mise en place de dispositifs de soutien aux salariés aidants : sensibilisation des équipes, ateliers collectifs, "}, {"pid": "79.0", "pro": "ELODIE ONEXAYVIENG", "rank": 2, "metiers": [], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 80.0, "unite": "Par heure", "nom": "Accompagnement à la reconversion et définition de projet professionnel - Bilan / Coaching carrière", "desc": "Vous souhaitez donner un nouveau sens à votre parcours professionnel ? Je vous guide dans l'exploration de vos compétences, valeurs et aspirations pou"}, {"pid": "80.0", "pro": "ELODIE ONEXAYVIENG", "rank": 2, "metiers": [], "familles": ["Aide au parcours de vie", "Aide humaine"], "mod": ["presentiel_pro"], "nat": true, "deps": [], "prix": 250.0, "unite": "Par heure", "nom": "Conseil et stratégie d'inclusion des aidants", "desc": "J'accompagne les entreprises et organisations dans la construction d'une politique d'inclusion adaptée aux salariés aidants. Mon approche combine diag"}, {"pid": "81.0", "pro": "Chloé FLOSI", "rank": 2, "metiers": [], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["distanciel", "presentiel_aidant"], "nat": true, "deps": [], "prix": 60.0, "unite": "Prestation complète", "nom": "Accompagnement administratif", "desc": "Élaboration et suivi des dossiers administratifs (dossier MDPH, Emploi, Scolarité, demande de logement social, loisirs) Ouverture de droit : CAF, CMU"}, {"pid": "82.0", "pro": "Chloé FLOSI", "rank": 2, "metiers": [], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["presentiel_aidant", "distanciel"], "nat": true, "deps": [], "prix": 25.0, "unite": "Prestation complète", "nom": "Conseils et orientations", "desc": "Conseil et orientation sur une situation précise Piste d’accompagnement. Analyse de situation"}, {"pid": "83.0", "pro": "Chloé FLOSI", "rank": 2, "metiers": [], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["distanciel", "presentiel_aidant"], "nat": true, "deps": [], "prix": 35.0, "unite": "Par heure", "nom": "Espace d’écoute", "desc": "Cet espace est un lieu d’écoute et de parole où vous pouvez évoquer les difficultés de votre quotidien, partager vos émotions, vos doutes et vos resse"}, {"pid": "84.0", "pro": "Chloé FLOSI", "rank": 2, "metiers": [], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide psycho-affective"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 145.0, "unite": "Prestation complète", "nom": "Accompagnement logistique de voyage", "desc": "Nous avons tous envie de partir en vacances, mais les contraintes logistiques peuvent parfois rendre l’organisation complexe, notamment lorsqu’une sit"}, {"pid": "85.0", "pro": "AKKUM", "rank": 2, "metiers": ["Assistant(e) familial(e)", "Coach", "Conseiller(e) en économie sociale et familiale"], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie"], "mod": ["distanciel"], "nat": true, "deps": [], "prix": 60.0, "unite": "Prestation complète", "nom": "AKKUM 4 GOOD", "desc": "AKKUM est la plateforme collaborative tout-en-un, propulsée par l'IA, qui centralise en un seul espace tout ce dont les familles aidantes ont besoin p"}, {"pid": "86.0", "pro": "AÎNÉS CONSEILS", "rank": 2, "metiers": [], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide matérielle", "Aide psycho-affective"], "mod": ["presentiel_aidant"], "nat": true, "deps": [], "prix": 28.0, "unite": "Par heure", "nom": "ASSISTANCE ADMINISTRATIVE", "desc": "Assistance administrative courante et experte : - Gestion courante, correspondance, formulaire, tri, classement et archivage ; - Aide à la création et"}, {"pid": "87.0", "pro": "AÎNÉS CONSEILS", "rank": 2, "metiers": [], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide matérielle", "Aide psycho-affective"], "mod": ["presentiel_aidant"], "nat": true, "deps": [], "prix": 45.0, "unite": "Par heure", "nom": "COORDINATION DU PARCOURS DE VIE ET SOUTIEN AUX AIDANTS", "desc": "Accompagnement de proximité pour coordonner le parcours de vie de votre proche au quotidien : - Évaluation et bilan de la situation au domicile, - Pro"}, {"pid": "88.0", "pro": "AÎNÉS CONSEILS", "rank": 2, "metiers": [], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide matérielle", "Aide psycho-affective"], "mod": ["presentiel_aidant"], "nat": true, "deps": [], "prix": 878.0, "unite": "Prestation complète", "nom": "ENTRÉE EN EHPAD OU STRUCTURE MÉDICO-SOCIALE", "desc": "Accompagnement à l’entrée en structure médico-sociale adaptée à vos besoins et envies - Entretien d’évaluation, recueil des besoins et attentes, - Rec"}, {"pid": "89.0", "pro": "AÎNÉS CONSEILS", "rank": 2, "metiers": [], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide matérielle", "Aide psycho-affective"], "mod": ["presentiel_aidant"], "nat": true, "deps": [], "prix": 38.0, "unite": "Par heure", "nom": "FORMALITÉS APRÈS DÉCÈS", "desc": "Perdre un proche est un moment difficile à vivre humainement et malheureusement administrativement parlant également. Pour vous alléger de cette charg"}, {"pid": "90.0", "pro": "AÎNÉS CONSEILS", "rank": 2, "metiers": [], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide matérielle", "Aide psycho-affective"], "mod": ["presentiel_aidant"], "nat": true, "deps": [], "prix": 220.0, "unite": "Prestation complète", "nom": "DEMANDE DE PENSION DE RÉVERSION", "desc": "votre proche est décédé et vous étiez mariés, vous pouvez sûrement bénéficier de sa pension de réversion. Je vous accompagne pour la constitution la g"}, {"pid": "91.0", "pro": "AÎNÉS CONSEILS", "rank": 2, "metiers": [], "familles": ["Aide administrative", "Aide au parcours de soin", "Aide au parcours de vie", "Aide humaine", "Aide matérielle", "Aide psycho-affective"], "mod": ["presentiel_pro", "distanciel"], "nat": true, "deps": [], "prix": 1.0, "unite": "Prestation complète", "nom": "SENSIBILISATION À L’AIDANCE EN ENTREPRISE", "desc": "Cet atelier peut être décliné sous différents formats : - À destination de salariés aidants - À destination des manager et RH, - En présentiel comme e"}], "depts": [{"c": "01", "n": "Ain"}, {"c": "02", "n": "Aisne"}, {"c": "03", "n": "Allier"}, {"c": "04", "n": "Alpes-de-Haute-Provence"}, {"c": "05", "n": "Hautes-Alpes"}, {"c": "06", "n": "Alpes-Maritimes"}, {"c": "07", "n": "Ardèche"}, {"c": "08", "n": "Ardennes"}, {"c": "09", "n": "Ariège"}, {"c": "10", "n": "Aube"}, {"c": "11", "n": "Aude"}, {"c": "12", "n": "Aveyron"}, {"c": "13", "n": "Bouches-du-Rhône"}, {"c": "14", "n": "Calvados"}, {"c": "15", "n": "Cantal"}, {"c": "16", "n": "Charente"}, {"c": "17", "n": "Charente-Maritime"}, {"c": "18", "n": "Cher"}, {"c": "19", "n": "Corrèze"}, {"c": "21", "n": "Côte-d'Or"}, {"c": "22", "n": "Côtes-d'Armor"}, {"c": "23", "n": "Creuse"}, {"c": "24", "n": "Dordogne"}, {"c": "25", "n": "Doubs"}, {"c": "26", "n": "Drôme"}, {"c": "27", "n": "Eure"}, {"c": "28", "n": "Eure-et-Loir"}, {"c": "29", "n": "Finistère"}, {"c": "30", "n": "Gard"}, {"c": "31", "n": "Haute-Garonne"}, {"c": "32", "n": "Gers"}, {"c": "33", "n": "Gironde"}, {"c": "34", "n": "Hérault"}, {"c": "35", "n": "Ille-et-Vilaine"}, {"c": "36", "n": "Indre"}, {"c": "37", "n": "Indre-et-Loire"}, {"c": "38", "n": "Isère"}, {"c": "39", "n": "Jura"}, {"c": "40", "n": "Landes"}, {"c": "41", "n": "Loir-et-Cher"}, {"c": "42", "n": "Loire"}, {"c": "43", "n": "Haute-Loire"}, {"c": "44", "n": "Loire-Atlantique"}, {"c": "45", "n": "Loiret"}, {"c": "46", "n": "Lot"}, {"c": "47", "n": "Lot-et-Garonne"}, {"c": "48", "n": "Lozère"}, {"c": "49", "n": "Maine-et-Loire"}, {"c": "50", "n": "Manche"}, {"c": "51", "n": "Marne"}, {"c": "52", "n": "Haute-Marne"}, {"c": "53", "n": "Mayenne"}, {"c": "54", "n": "Meurthe-et-Moselle"}, {"c": "55", "n": "Meuse"}, {"c": "56", "n": "Morbihan"}, {"c": "57", "n": "Moselle"}, {"c": "58", "n": "Nièvre"}, {"c": "59", "n": "Nord"}, {"c": "60", "n": "Oise"}, {"c": "61", "n": "Orne"}, {"c": "62", "n": "Pas-de-Calais"}, {"c": "63", "n": "Puy-de-Dôme"}, {"c": "64", "n": "Pyrénées-Atlantiques"}, {"c": "65", "n": "Hautes-Pyrénées"}, {"c": "66", "n": "Pyrénées-Orientales"}, {"c": "67", "n": "Bas-Rhin"}, {"c": "68", "n": "Haut-Rhin"}, {"c": "69", "n": "Rhône"}, {"c": "70", "n": "Haute-Saône"}, {"c": "71", "n": "Saône-et-Loire"}, {"c": "72", "n": "Sarthe"}, {"c": "73", "n": "Savoie"}, {"c": "74", "n": "Haute-Savoie"}, {"c": "75", "n": "Paris"}, {"c": "76", "n": "Seine-Maritime"}, {"c": "77", "n": "Seine-et-Marne"}, {"c": "78", "n": "Yvelines"}, {"c": "79", "n": "Deux-Sèvres"}, {"c": "80", "n": "Somme"}, {"c": "81", "n": "Tarn"}, {"c": "82", "n": "Tarn-et-Garonne"}, {"c": "83", "n": "Var"}, {"c": "84", "n": "Vaucluse"}, {"c": "85", "n": "Vendée"}, {"c": "86", "n": "Vienne"}, {"c": "87", "n": "Haute-Vienne"}, {"c": "88", "n": "Vosges"}, {"c": "89", "n": "Yonne"}, {"c": "90", "n": "Territoire de Belfort"}, {"c": "91", "n": "Essonne"}, {"c": "92", "n": "Hauts-de-Seine"}, {"c": "93", "n": "Seine-Saint-Denis"}, {"c": "94", "n": "Val-de-Marne"}, {"c": "95", "n": "Val-d'Oise"}, {"c": "971", "n": "Guadeloupe"}, {"c": "972", "n": "Martinique"}, {"c": "973", "n": "Guyane"}, {"c": "974", "n": "La Réunion"}, {"c": "975", "n": "Saint-Pierre-et-Miquelon"}, {"c": "976", "n": "Mayotte"}, {"c": "977", "n": "Saint-Barthélemy"}, {"c": "978", "n": "Saint-Martin"}, {"c": "986", "n": "Wallis-et-Futuna"}, {"c": "987", "n": "Polynésie française"}, {"c": "988", "n": "Nouvelle-Calédonie"}]}'''
CATALOGUE_SOURCE = "snapshot"   # "aidance-pro" une fois branché sur l'endpoint distant

def _charger_catalogue():
    """Le catalogue est la source de vérité aidance-pro. Par défaut : snapshot
    embarqué (l'export téléchargé pour le maquettage). Si AIDANCE_PRO_CATALOGUE_URL
    est défini — un endpoint JSON exposé par aidance-pro / Pilot Systems, de même
    structure {"rows": [...], "depts": [...]} — on le charge à chaud, avec repli
    automatique sur le snapshot en cas d'indisponibilité ou de format invalide."""
    global CATALOGUE_SOURCE
    url = os.environ.get("AIDANCE_PRO_CATALOGUE_URL", "").strip()
    if url:
        try:
            req = urllib.request.Request(url, headers={"accept": "application/json"})
            token = os.environ.get("AIDANCE_PRO_CATALOGUE_TOKEN", "").strip()
            if token:
                req.add_header("authorization", "Bearer " + token)
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            if isinstance(data, dict) and data.get("rows") and data.get("depts"):
                CATALOGUE_SOURCE = "aidance-pro"
                print(f"[catalogue] chargé depuis aidance-pro ({len(data['rows'])} lignes)", flush=True)
                return data
            print("[catalogue] réponse distante invalide — repli sur le snapshot", flush=True)
        except Exception as e:
            print(f"[catalogue] distant indisponible ({e.__class__.__name__}) — repli sur le snapshot", flush=True)
    CATALOGUE_SOURCE = "snapshot"
    return json.loads(CATALOGUE_RAW)


_CAT = _charger_catalogue()
CATALOGUE_ROWS = _CAT["rows"]
DEPTS = _CAT["depts"]


def _pro_slug(nom: str) -> str:
    import re as _re
    s = _re.sub(r"[^A-Za-z0-9]+", "-", nom).strip("-").upper()[:24]
    return "PRO-" + (s or "X")


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Jeu d'essai (seed) — illustre chaque file et chaque alerte V1         ║
# ╚══════════════════════════════════════════════════════════════════════╝
def seed() -> Store:
    s = Store()

    # ── Catalogue réel aidance-pro (A-2 : snapshot, ou endpoint via env) ──
    pros_by_nom: Dict[str, str] = {}
    for row in CATALOGUE_ROWS:
        nom_pro = (row.get("pro") or "").strip()
        if not nom_pro:
            continue
        if nom_pro not in pros_by_nom:
            pid_pro = _pro_slug(nom_pro)
            base, k = pid_pro, 2
            while pid_pro in s.pros:
                pid_pro = f"{base}-{k}"; k += 1
            s.pros[pid_pro] = Pro(pid_pro, nom_pro, email=str(row.get("email") or ""))
            pros_by_nom[nom_pro] = pid_pro
        pro_id = pros_by_nom[nom_pro]
        if row.get("prix") is None or not row.get("nom"):
            continue
        pid = str(row.get("pid", "")).split(".")[0]
        prid = f"PR-{pid}" if pid and pid != "nan" else _uid("PR")
        if prid in s.prestations:
            prid = _uid("PR")
        s.prestations[prid] = Prestation(
            prid, pro_id, row["nom"], row["unite"], D(str(row["prix"])),
            pid=pid, familles=row.get("familles", []), metiers=row.get("metiers", []),
            mod=row.get("mod", []), nat=bool(row.get("nat", True)),
            deps=row.get("deps", []), rank=int(row.get("rank", 2)),
            desc=row.get("desc", ""))

    md_, mv_, mr_ = MoteurDossiers(s), MoteurDevis(s), MoteurRemboursement(s)

    # ── Dossier 1 · Léa : pré-inscrite, PMV « Verrouillé RIB » ──
    lea = md_.preinscrire("Léa", "Garnier", "l.garnier@exemple.com",
                          REFERENCES_CONTRAT[0], ndd=3, credit_initial=900,
                          pfd={"prenom": "Marie", "lien": "Mère", "naissance": "1948", "ndd": 3},
                          commentaire="Ouverture de droits — décision du 02/11")

    # ── Dossier 2 · Claire : active, files et alertes illustrées ──
    claire = md_.preinscrire("Claire", "Dubois", "c.dubois@exemple.com",
                             REFERENCES_CONTRAT[0], ndd=1, credit_initial=1500,
                             pfd={"prenom": "Hugo", "lien": "Enfant", "naissance": "2014", "ndd": 1})
    md_.completer_profil(claire.id, "FR7630006000011234567890189", "0612345678", {
        "adresse": "12 rue des Lilas", "cp": "69003", "ville": "Lyon",
        "marital": "Marié(e) / Pacsé(e)", "foyer": "Avec enfant(s) à charge", "enfants": "2",
        "cohabite": "Non", "distance": "15 à 30 min", "anciennete": "2 à 5 ans",
        "heures": "10 à 20 h/sem", "nuit": "Oui, ponctuellement",
        "taches": ["Démarches administratives", "Accompagnement / transport", "Soutien moral"],
        "statutpro": "Salarié(e)", "contrat": "CDI", "temps": "Temps plein",
        "poste": "Travail posté / décalé", "flex": "Faible", "amenage": ["Télétravail"],
        "coaidants": "Oui, un autre aidant", "role": "Aidant principal",
        "relais": "Relais possible parfois",
        "aidesh": ["Aide à domicile"], "aidesf": ["AJPA (congé proche aidant)"],
        "sante": "Moyenne", "fatigue": "Élevée",
        "dispo": ["Soir", "Week-end"], "besoins": ["Répit", "Aide administrative"],
    })
    claire.aides[0].profil = {
        "lieu": "Domicile, avec l'aidant", "logement": "Appartement",
        "adapte": "En projet", "environ": "Urbain",
        "nature": "Mixte (physique & cognitive)", "patho": "Handicap de naissance",
        "mobilite": "Aide technique (canne, déambulateur)", "cognitif": "Troubles importants",
        "avq": ["Toilette / habillage", "Alimentation", "Déplacements", "Cohérence / orientation"],
        "isolement": "Modéré",
        "aidesh": ["Aide à domicile"], "aidesf": ["PCH", "AEEH"], "aidest": ["Aménagement salle de bain"],
        "risques": ["Chutes", "Épuisement de l'aidant"],
        "besoins": ["Aide à domicile", "Répit de l'aidant", "Stimulation / lien social"],
    }

    j = lambda n: (datetime.date.today() - datetime.timedelta(days=n)).isoformat()

    # D01 — payé (historique complet : engagement, facture reçue, bordereau exécuté)
    d1 = mv_.demander(claire.id, "PR-86", "Mise à jour du dossier MDPH de Hugo.")
    mv_.etablir(d1.id, 4, "4 h réparties sur deux mercredis après-midi.")
    mv_.accepter(d1.id); d1.date_engagement = j(12)
    mv_.facture_recue(d1.id, j(4))
    _lot = payer_lot(s, [d1.id], [], commentaire="Virement CERA du " + j(2))
    executer_bordereau(s, _lot["bordereau"].id)

    # F-30 — échéances de démonstration, COHÉRENTES avec RG-54 : la date de
    # préinscription est reculée pour que échéance = préinscription + 1 an,
    # crédit initial et e-mail d'activation datés du jour de la préinscription.
    #   Claire : préinscrite il y a 360 j → échéance à J+5 (fenêtre de préavis) ;
    #   Léa    : préinscrite il y a 25 j  → échéance à J+340.
    for _a, _jrest in ((claire, 5), (lea, 340)):
        _pre = datetime.date.today() + datetime.timedelta(days=_jrest - DUREE_GARANTIE_JOURS)
        _a.date_preinscription = _pre.isoformat()
        _a.date_echeance = (_pre + datetime.timedelta(days=DUREE_GARANTIE_JOURS)).isoformat()
        s.enveloppes[_a.id].mouvements[0].date = f"{_pre.isoformat()} 09:00"
        for _m in s.emails:
            if _m.objet == f"[MPA] Activez votre espace — dossier {_a.id}":
                _m.date = f"{_pre.isoformat()} 09:00"

    # D02 — FACTURE REÇUE (= validation, RG-45) → FILE DES PAIEMENTS (F-22)
    d2 = mv_.demander(claire.id, "PR-87", "Coordonner les intervenants autour de Hugo.")
    mv_.etablir(d2.id, 2, "Deux rendez-vous de coordination.")
    mv_.accepter(d2.id); d2.date_engagement = j(9)
    mv_.facture_recue(d2.id, j(1))

    # D03 — engagé SANS facture depuis 35 j → ALERTE « facture attendue » (F-70)
    d3 = mv_.demander(claire.id, "PR-54", "Garde de nuit ponctuelle pour souffler.")
    mv_.etablir(d3.id, 6, "6 h de garde de nuit par un étudiant en santé.")
    mv_.accepter(d3.id); d3.date_engagement = j(DELAI_FACTURE_JOURS + 5)

    # D04 — forfait à prix fixe : « devisé » immédiatement (F-47), à accepter
    mv_.demander(claire.id, "PR-27", "Besoin de parler de mon épuisement.")

    # D05 — devisé AU-DELÀ du disponible : démontre le RESTE À CHARGE (RG-43).
    #       L'acceptation ouvrira la confirmation chiffrée côté assuré-aidant.
    d5 = mv_.demander(claire.id, "PR-54",
                      "Garde de nuit récurrente : 3 nuits par semaine pendant un mois.",
                      quantite=60)
    mv_.etablir(d5.id, 60, "60 h sur 4 semaines, planning à caler ensemble.")

    # R01 — validée (engagée) → à marquer payée ; R02 — soumise à instruire.
    # Justificatifs de démonstration réellement consultables (F-51).
    def _piece(titre, montant, date):
        import base64
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="560" height="320">'
               f'<rect width="100%" height="100%" fill="#FBF9F6"/>'
               f'<rect x="20" y="20" width="520" height="280" fill="#fff" stroke="#CBC2BA"/>'
               f'<text x="40" y="70" font-family="sans-serif" font-size="22" font-weight="bold" fill="#2A2433">{titre}</text>'
               f'<text x="40" y="105" font-family="sans-serif" font-size="14" fill="#6B6470">Justificatif de démonstration — MPA V1</text>'
               f'<text x="40" y="170" font-family="sans-serif" font-size="16" fill="#2A2433">Date : {date}</text>'
               f'<text x="40" y="200" font-family="sans-serif" font-size="16" fill="#2A2433">Montant TTC : {montant} EUR</text>'
               f'<text x="40" y="265" font-family="sans-serif" font-size="12" fill="#8C8492">Document fictif genere pour la maquette.</text></svg>')
        return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode()
    r1 = mr_.soumettre(claire.id, "Taxi RDV médical", "Transport", 30,
                       "facture_taxi_0411.svg", _piece("FACTURE TAXI", "30,00", j(2)))
    mr_.valider(r1.id)
    mr_.soumettre(claire.id, "Repas portage — semaine 44", "Portage de repas", 42,
                  "recu_portage_s44.svg", _piece("RECU PORTAGE DE REPAS", "42,00", j(1)))

    # Contact conseiller en attente (F-52)
    md_.contacter(claire.id, "rappel", "Je voudrais comprendre le délai de confirmation du service fait.")

    return s


# ╔══════════════════════════════════════════════════════════════════════╗
# ║  Démonstration console — le cycle V1 complet, règles à l'appui         ║
# ╚══════════════════════════════════════════════════════════════════════╝
def _pmv(env, t=""):
    print(f"      PMV{(' ' + t) if t else ''} : crédit cumulé {eur(env.credit_cumule)} − payé {eur(env.paye)}"
          f" = solde {eur(env.solde)} ; − engagé {eur(env.engage)} = disponible {eur(env.disponible)}")


def _role(r):
    print("\n" + "─" * 72 + f"\n  [{r}]\n" + "─" * 72)


def main():
    s = seed()
    md_, mv_, mr_ = MoteurDossiers(s), MoteurDevis(s), MoteurRemboursement(s)
    print("═" * 72)
    print("  MPA V1 — spécifications fonctionnelles V1.1 : cycle complet")
    print("═" * 72)

    _role("Gestionnaire — pré-inscription (F-20 : PFD obligatoire, crédit libre)")
    paul = md_.preinscrire("Paul", "Martin", "p.martin@exemple.com", REFERENCES_CONTRAT[1],
                           ndd=2, credit_initial=1200,
                           pfd={"prenom": "Jeanne", "lien": "Mère", "naissance": "1945", "ndd": 2})
    env = s.pmv(paul.id)
    print(f"  Dossier {paul.id} ouvert — lien d'activation adressé (e-mail simulé).")
    _pmv(env)

    _role("Assuré-aidant — activation : RIB (verrou 1) puis profil PFD (verrou 2)")
    try:
        mv_.demander(paul.id, "PR-86")
    except ValueError as e:
        print(f"  Devis refusé tant que verrouillé : {e}")
    md_.completer_profil(paul.id, "FR7630006000011234567890189", "0600000000")
    md_.completer_profil_pfd(paul.id, paul.aides[0].id, {"lieu": "Domicile, seul(e)",
                                                         "mobilite": "Marche avec aide"})
    print(f"  PMV : {pmv_etat(s, paul.id)} — dossier « {etat_dossier(s, paul.id)} ».")

    _role("Cycle devis (RG-45, RG-51) — acceptation = engagement automatique")
    d = mv_.demander(paul.id, "PR-86", "Dossier MDPH, de préférence le mercredi.")
    mv_.etablir(d.id, 4, "OK pour deux mercredis.")
    mv_.accepter(d.id)
    print(f"  {d.id} engagé : {eur(d.total)} (aucune intervention du gestionnaire).")
    _pmv(env)

    _role("Facture reçue (RG-45) — vaut validation, AUCUN paiement automatique")
    mv_.facture_recue(d.id)
    print(f"  {d.id} facturé par le pro → file des paiements du gestionnaire.")
    _pmv(env)

    _role("Gestionnaire — paiement MANUEL partiel (F-22, RG-52/53)")
    mv_.payer(d.id, montant=84, commentaire="2 h non assurées — accord téléphonique")
    print(f"  {d.id} payé {eur(D(84))} sur {eur(D(112))} ; reliquat recrédité. E-mail adressé (F-24).")
    _pmv(env)

    _role("Remboursement (F-51, F-23) — validée engage, payée après virement")
    r = mr_.soumettre(paul.id, "Taxi", "Transport", 30, "taxi.pdf")
    mr_.valider(r.id)
    mr_.marquer_payee(r.id)
    _pmv(env)

    _role("Blocage (F-27, RG-50)")
    md_.bloquer(paul.id, "Suspicion d'usage hors objet (RG-49) — vérification en cours")
    try:
        mv_.demander(paul.id, "PR-86")
    except ValueError as e:
        print(f"  Nouvelle dépense refusée : {e}")
    md_.debloquer(paul.id, "Vérification levée")

    _role("Tâche quotidienne (F-70) & exports (F-28)")
    t = tache_quotidienne(s)
    print("  " + t["message"])
    for quoi in ("dossiers", "mouvements", "devis", "remboursements"):
        print(f"  export {quoi}.csv : {len(exporter(s, quoi).splitlines())} lignes")

    print("\n" + "═" * 72)
    print(f"  JOURNAL DU PMV {paul.id} (F-43, F-26)")
    print("═" * 72)
    for m in env.mouvements:
        print(f"  {m.date}  {m.type:14} {eur(m.montant):>12}  {m.libelle}"
              + (f"  [{m.ref}]" if m.ref else "") + (f"  · {m.commentaire}" if m.commentaire else ""))
    print(f"\n  E-mails simulés émis : {len(s.emails)}")


if __name__ == "__main__":
    main()
    try:
        if sys.stdin.isatty():
            input("\nAppuyez sur Entrée pour fermer…")
    except Exception:
        pass
