# MPA — Maquette opérationnelle V1

Implémentation exécutable des **spécifications fonctionnelles V1.1 du 6 novembre 2026**
(« a minima »). Un état partagé, un **PMV** par dossier, **deux espaces**
(Assuré-aidant · Gestionnaire indemnisation) — **le professionnel n'a pas de
compte MPA** : à chaque demande de devis il reçoit un e-mail (adresse du
catalogue) avec le n° de dossier, le besoin exprimé et un **lien sécurisé à
usage limité** (`?pro=<jeton>`) vers un formulaire mono-demande (A-1a).
La gestion des contrats, la détermination du NDD, la facture du pro, les virements
bancaires, les rejets, le renouvellement et le reporting assureur sont **hors outil** (§1).

## Ce qui change par rapport à la maquette précédente

| Avant | V1 (specs V1.1) |
|---|---|
| 4 rôles (dont console contrats + reporting) | **3 rôles** — contrats/barèmes hors outil ; la pré-inscription porte une simple *référence contrat* et un **crédit initial en saisie libre** (F-20) |
| Paiement automatique à la double validation + bordereau SEPA pain.001 | **Paiement = acte manuel du gestionnaire** (RG-52), **en deux temps** : il marque payé — unitaire, **partiel** (RG-53, reliquat → disponible) ou **en lot** — ce qui notifie l'assuré-aidant (F-24, avec la référence de virement) et **génère un bordereau de virement groupé par bénéficiaire** (BRD-AA-NNN : pro → coordonnées sur facture F-62 ; assuré → IBAN du dossier) ; il **exécute ensuite le bordereau à sa banque** (hors outil) et le marque **exécuté** (réconciliation) |
| Onglet « Remboursements » mêlant instruction et paiement | **« Demandes de remboursement »** : l'instruction seule, **groupée par dossier** (nom de l'assuré + solde / engagé / disponible du PMV en tête de groupe) ; une demande **validée bascule dans « Paiements à effectuer »**, file **groupée par bénéficiaire** |
| Déclaration de réalisation (pro) puis confirmation du service fait (assuré-aidant), libération à J+7 | **Ni l'une ni l'autre** : à l'acceptation, le pro reçoit les informations à porter sur sa facture ; **la réception de la facture, enregistrée par le gestionnaire (« Facture reçue »), vaut validation de la prestation** (RG-45, confiance dans le réseau) et met la ligne en file de paiement. Litiges réglés par le gestionnaire : annulation motivée (désengagement intégral) ou paiement partiel (F-25). Vigilances F-70 : **facture attendue** au-delà de 30 j (A-3 recyclé) et **bordereau non exécuté** au-delà de 3 j (A-7) |
| PMV 3 compartiments | **5 chiffres + 2 équations** affichées : crédit cumulé − payé = solde ; solde − engagé = disponible (F-43) |
| Écran « Pro » permanent (3e rôle dans l'en-tête) | **Pas de compte pro** : un **jeton par demande** dans l'e-mail simulé ouvre un **formulaire mono-demande** (`/?pro=<jeton>` → `GET /api/pro/<jeton>`, **minimisé** : n° de dossier + besoin exprimé + prestation — jamais l'identité de l'aidant ni le PMV) ; chiffrer/décliner puis déclarer la réalisation ; plafond d'ouvertures, lien consultatif après clôture |
| — | **Blocage/déblocage** du PMV (F-27, RG-50), **n° de dossier GSA-AA-NNNNN** (§9) avec références dérivées -Dnn/-Rnn, **contact conseiller** (F-52), **commentaires du gestionnaire** sur chaque mouvement (F-26), **justificatif réellement déposé et consultable** (F-51), **exports CSV** (F-28), **e-mails simulés** journalisés |

## Fichiers

```
mpa_core.py     Cœur de domaine V1 : dossiers numérotés, PMV (5 chiffres,
                intégrité F-71), cycles devis/remboursement (§7), alertes,
                exports, e-mails simulés, assistant IA, catalogue aidance-pro.
                Les RG-xx et les arbitrages A-1 à A-5 sont en tête de fichier.
mpa_api.py      API HTTP (stdlib) — table des routes en tête ; sert le shell
                sur / ; routes /api/pro/<jeton> (vue minimisée) pour le pro.
mpa_demo.html   Shell (HTML/JS sans dépendance) : 2 espaces + formulaire pro
                par lien, sommaire §1–§9.
nonreg_v1.py    LA SPÉCIFICATION EXÉCUTABLE : 83 vérifications rejouant chaque
                exigence F-xx/RG-xx de bout en bout.  python3 nonreg_v1.py
render_v1.py    Harness de rendu : 39 vues des 3 profils d'usage sur le jeu
                d'essai réel + replis IA (requiert node).
Procfile, render.yaml, requirements.txt : inchangés.
```

## Traçabilité exigences → implémentation (vérifiée par `nonreg_v1.py`)

| Réf. | Où | Vérifié |
|---|---|---|
| F-20/RG-41/RG-13 | `MoteurDossiers.preinscrire` (PFD **obligatoire**, NDD 5–6 refusés, crédit libre, n° §9, e-mail d'activation avec lien) | 01–10 |
| **A-1a (pro sans compte)** | jeton par demande (`Devis.jeton`), `GET/POST /api/pro/<jeton>` **minimisés**, 404 jeton inconnu, anciennes routes pro supprimées, plafond d'ouvertures → 410, lien consultatif après clôture, acceptation notifiée au pro | 17–20, 23, 26–29 |
| F-40 | Lien `?dossier=GSA-AA-NNNNN` ouvre le portail sur le dossier ; n° affiché en permanence (bandeau) | smoke test |
| F-41/F-42/RG-42 | `pmv_etat` : Verrouillé RIB → Verrouillé PFD → Utilisable ; IBAN mod-97 | 11–15 |
| F-43/RG-43 | `Enveloppe` 5 chiffres, équations affichées, `_verifier()` (F-71) | 03, 19, 32, 39 |
| F-44/RG-61-62 | `/api/analyse/generer` (≤40 lignes, factuel, sans diagnostic) ; **seule la version validée est stockée** ; repli local | 75, 77 |
| F-45/RG-60/63 | `/api/anticiper2`, taxonomie fermée 9 catégories, retenir/écarter → « Mon parcours » ; repli déterministe | 76 + harness |
| F-46 | Catégories retenues → liste **complète** filtrée (tri premium→labellisé→autre, 3 facettes) ; catalogue libre | harness |
| F-47/F-48/RG-51 | `demander` (message, **e-mail au pro avec `?pro=<jeton>`**, forfait→devisé, verrous), `accepter` = **engagement automatique**, garde disponible | 16–17, 21–25 |
| RG-45 (remplace F-49/F-61) | `facture_recue` (gestionnaire) : **la réception de la facture vaut validation** → file des paiements ; e-mail d'acceptation = infos de facturation ; étapes réalisation/service fait **supprimées** (404) ; alerte « facture attendue » (A-3) | 30–37 |
| F-50 | Fil d'avancement par devis (demandé→devisé→engagé→réalisé→payé) + délai + actions prioritaires à l'accueil | harness |
| F-51 | Dépôt **réel** du justificatif (PDF/image, dataURL) ; consultable par le gestionnaire (`GET …/justificatif`) | 43–45 |
| F-52 | `contacter` (appel/rappel/message/rendez-vous, aucun chatbot) — bouton permanent, visible au dossier gestionnaire | 72–73 |
| F-60/F-62/F-63 | `etablir` (message pro) / `refuser_pro` (motif) — **exclusivement via `/api/pro/<jeton>`** ; consignes de facturation affichées ; paiement ≤ engagé | 21, 26–27, 38 |
| F-21 | `crediter` (Crédit initial · Correction), journalisé, irréversible, correction négative tracée | 60–63 |
| F-22/RG-52/RG-53 | `payer_lot` : tout passage en payé (unitaire, partiel → reliquat recrédité, ou lot `/api/paiements`) **génère un bordereau par bénéficiaire** ; `executer_bordereau` trace le passage en banque ; file **groupée par bénéficiaire** | 32, 38–41, 51–59 |
| F-23/RG-44 | `valider` (**partiel automatique** = min(demandé, disponible), **engage**, bascule en file des paiements), `refuser` (motif), `demander_piece`/`redeposer`, `marquer_payee` via bordereau | 47–50 |
| F-24 | E-mails automatiques (demande au pro, acceptation, paiement **avec référence du bordereau**, validation partielle, refus) — **simulés**, journal consultable, **liens cliquables** | 40–41 + onglet E-mails |
| F-25 | Règlement des litiges par le gestionnaire : **annuler** (motif, désengagement intégral) un devis engagé ou facturé ; **paiement partiel** (RG-53) ; actions directes sur les alertes | 39, 42 |
| F-26 | `commenter_mouvement` — visible par l'assuré-aidant dans son historique | 69 |
| F-27/RG-50 | `bloquer`/`debloquer` (motif) ; engagements en cours honorés ; consultation/orientation accessibles | 64–68 |
| F-28 | `GET /api/exports/{dossiers,mouvements,devis,remboursements,bordereaux}.csv` | 59, 74 |
| F-70 | `alertes()` + `POST /api/tache-quotidienne` — **aucune libération automatique** | 70–71 |
| F-71 | Gardes serveur : engagement ≤ disponible, paiement ≤ engagé, validé ≤ disponible, aucun compartiment négatif (`IntegriteError`) | 24, 38, 49 |
| F-72/A-2 | Snapshot aidance-pro embarqué + `AIDANCE_PRO_CATALOGUE_URL` (+`_TOKEN`), repli auto ; source affichée dans `/api/diag` | 83 |
| §9 | `GSA-AA-NNNNN`, séquence annuelle ; devis `-Dnn`, remboursements `-Rnn`, bordereaux `BRD-AA-NNN` (sans clé de contrôle — A-4) | 01–02, 16, 44 |

**Arbitrages appliqués (§10)** — A-1 : **(a)** lien sécurisé par e-mail, réellement
outillé : **un jeton aléatoire par demande** (`?pro=<jeton>`), plafond d'ouvertures
(`PRO_LIEN_MAX_OUVERTURES`), consultatif dès la clôture — en production : ajouter
une expiration temporelle · A-2 : snapshot + variable d'environnement ·
A-3 (recyclé) : `DELAI_FACTURE_JOURS = 30` (alerte facture attendue) · A-7 : `DELAI_BORDEREAU_JOURS = 3` (alerte bordereau non exécuté) · A-4 : sans clé de contrôle ·
A-5 : paiement partiel décidé par le gestionnaire (F-25).

## Mon baromètre aidant (tableau de bord de l'assuré-aidant)

Repère visuel à **3 zones d'action** (vert *Se renseigner* · orange *Demander de
l'aide* · rouge *Me protéger*) : un positionnement **global** (thermomètre) décliné
en **6 dimensions** cliquables — **Charge d'aide · Charge mentale · Santé & répit ·
Vie professionnelle** (« non concerné » si sans activité) **· Entourage & relais ·
Budget & droits**. Nom et formulations propres à MPA (concept des zones d'action
inspiré des auto-diagnostics associatifs, sans reprise de leurs contenus).

- **Calcul déterministe et transparent** (`barometre()` dans `mpa_core.py`) sur les
  profils déjà saisis — aucune nouvelle question ; chaque dimension affiche « ce qui
  pèse ▲ / vos appuis ▽ ».
- **Il s'affine avec l'usage du PMV** : services réellement mobilisés (famille
  dominante de chaque prestation engagée/facturée/payée), remboursements couverts,
  demandes rapprochées, contestation en cours, contact conseiller, et non-recours
  (forte charge déclarée sans aucun service). Ces signaux sont **bornés à ±10 points
  par dimension** (le déclaratif domine) et **toujours affichés en clair** — un outil
  au bénéfice de l'aidant, jamais un scoring opaque (ligne à tenir aussi en
  production : finalité, transparence, RGPD).
- **Lecture personnalisée par l'assistant** (`POST /api/barometre`, 4 phrases, cite
  la dimension la plus en tension, jamais de diagnostic — RG-62/63 ; repli type sans
  clé). En zone orange/rouge : bouton direct « En parler à un conseiller » (F-52).
- Limite assumée : « Budget & droits » mesure la **mobilisation des droits** (AJPA,
  APA/PCH, aides techniques, adaptation du logement), pas l'impact financier réel —
  qui exigerait deux questions absentes du profil V1 (reste à charge mensuel,
  réduction d'activité subie).

## Simulations assumées (maquette)

- **E-mails** : journalisés côté serveur, consultables dans le back-office (onglet
  « E-mails ») — pas d'envoi réel. Le lien d'activation et le lien de chiffrage pro y figurent.
- **Accès** : le sélecteur de dossier (aidant) tient lieu de lien personnel ;
  `?dossier=…` démontre le lien d'activation (F-40). **Côté pro, le lien est réel** :
  l'e-mail journalisé (back-office → E-mails) porte `?pro=<jeton>`, cliquable — le
  gestionnaire peut aussi le récupérer au détail du dossier (« formulaire pro ↗ »).
- **Justificatifs** : stockés en mémoire (dataURL, ≤ 3,5 Mo) — stockage fichier en production.
- **Tâche quotidienne (F-70)** : calcul à la volée + bouton de déclenchement — planificateur en production.
- **État en mémoire** : pas de base ; « Réinitialiser » recharge le jeu d'essai. La
  clôture de dossier (état « Clos ») n'est pas outillée : aucune exigence F-xx ne la décrit.

## Variables d'environnement

| Variable | Effet |
|---|---|
| `ANTHROPIC_API_KEY` | Active l'assistant (bilan F-44 + besoins F-45). Sans clé : replis déterministes (RG-63). Vérifier : `/api/diag` (`?ping=1`). |
| `AIDANCE_PRO_CATALOGUE_URL` / `_TOKEN` | Catalogue live aidance-pro (JSON `{rows, depts}` ; prévoir `desc` complète et `email` de contact du pro — F-72), repli automatique sur le snapshot. |

## Lancer / déployer

```bash
python3 mpa_api.py            # http://127.0.0.1:8765/  (shell servi sur /)
python3 mpa_core.py           # scénario console du cycle V1 complet
python3 nonreg_v1.py          # la spécification exécutable (83 vérifications)
```
Render : pousser ces fichiers (racine), Blueprint `render.yaml` — inchangé. Après
déploiement : « Réinitialiser » dans le shell.

## Règle d'or pour toute évolution

Toute modification doit laisser `nonreg_v1.py` (83 vérifications) et `render_v1.py`
(39 vues, 59 assertions) **verts** — c'est ainsi que cette V1 a été validée, en plus
de deux parcours complets en navigateur réel (Playwright) : le circuit pro par
lien (demande → e-mail → chiffrage → acceptation → consigne de facturation →
facture reçue → file de paiement) et le circuit gestionnaire (instruction groupée
par dossier → validation → file par bénéficiaire → bordereau → exécution en banque).
