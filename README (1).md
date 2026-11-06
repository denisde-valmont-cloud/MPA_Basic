# MPA — Maquette opérationnelle V1

Implémentation exécutable des **spécifications fonctionnelles V1.1 du 6 novembre 2026**
(« a minima »). Un état partagé, un **PMV** par dossier, **trois rôles** :
Assuré-aidant · Professionnel de l'aidance · Gestionnaire indemnisation.
La gestion des contrats, la détermination du NDD, la facture du pro, les virements
bancaires, les rejets, le renouvellement et le reporting assureur sont **hors outil** (§1).

## Ce qui change par rapport à la maquette précédente

| Avant | V1 (specs V1.1) |
|---|---|
| 4 rôles (dont console contrats + reporting) | **3 rôles** — contrats/barèmes hors outil ; la pré-inscription porte une simple *référence contrat* et un **crédit initial en saisie libre** (F-20) |
| Paiement automatique à la double validation + bordereau SEPA pain.001 | **Paiement = acte manuel du gestionnaire** (RG-52) : virement à la banque hors outil, puis saisie — unitaire, **partielle** (RG-53, reliquat → disponible) ou **en lot** — avec **e-mail automatique** à l'assuré-aidant (F-24) |
| Libération automatique J+7 | **Aucune libération automatique** : à l'échéance du délai (A-3), **alerte** au gestionnaire (F-70), qui confirme pour le compte / paie partiellement / annule, motif obligatoire (F-25) |
| PMV 3 compartiments | **5 chiffres + 2 équations** affichées : crédit cumulé − payé = solde ; solde − engagé = disponible (F-43) |
| — | **Contestation** du service fait (F-49), **blocage/déblocage** du PMV (F-27, RG-50), **n° de dossier GSA-AA-NNNNN** (§9) avec références dérivées -Dnn/-Rnn, **contact conseiller** (F-52), **commentaires du gestionnaire** sur chaque mouvement (F-26), **justificatif réellement déposé et consultable** (F-51), **exports CSV** (F-28), **e-mails simulés** journalisés |

## Fichiers

```
mpa_core.py     Cœur de domaine V1 : dossiers numérotés, PMV (5 chiffres,
                intégrité F-71), cycles devis/remboursement (§7), alertes,
                exports, e-mails simulés, assistant IA, catalogue aidance-pro.
                Les RG-xx et les arbitrages A-1 à A-5 sont en tête de fichier.
mpa_api.py      API HTTP (stdlib) — table des routes en tête ; sert le shell sur /.
mpa_demo.html   Shell 3 rôles (HTML/JS sans dépendance), sommaire §1–§9.
nonreg_v1.py    LA SPÉCIFICATION EXÉCUTABLE : 62 vérifications rejouant chaque
                exigence F-xx/RG-xx de bout en bout.  python3 nonreg_v1.py
render_v1.py    Harness de rendu : exécute 39 vues des 3 rôles sur le jeu
                d'essai réel + replis IA (requiert node).
Procfile, render.yaml, requirements.txt : inchangés.
```

## Traçabilité exigences → implémentation (vérifiée par `nonreg_v1.py`)

| Réf. | Où | Vérifié |
|---|---|---|
| F-20/RG-41/RG-13 | `MoteurDossiers.preinscrire` (PFD **obligatoire**, NDD 5–6 refusés, crédit libre, n° §9, e-mail d'activation avec lien) | 01–10 |
| F-40 | Lien `?dossier=GSA-AA-NNNNN` ouvre le portail sur le dossier ; n° affiché en permanence (bandeau) | smoke test |
| F-41/F-42/RG-42 | `pmv_etat` : Verrouillé RIB → Verrouillé PFD → Utilisable ; IBAN mod-97 | 11–15 |
| F-43/RG-43 | `Enveloppe` 5 chiffres, équations affichées, `_verifier()` (F-71) | 03, 19, 32, 39 |
| F-44/RG-61-62 | `/api/analyse/generer` (≤40 lignes, factuel, sans diagnostic) ; **seule la version validée est stockée** ; repli local | 55, 57 |
| F-45/RG-60/63 | `/api/anticiper2`, taxonomie fermée 9 catégories, retenir/écarter → « Mon parcours » ; repli déterministe | 56 + harness |
| F-46 | Catégories retenues → liste **complète** filtrée (tri premium→labellisé→autre, 3 facettes) ; catalogue libre | harness |
| F-47/F-48/RG-51 | `demander` (message, forfait→devisé, verrous), `accepter` = **engagement automatique**, garde disponible | 16–21 |
| F-49/F-61 | `declarer_realisee` → échéance (A-3) ; `confirmer_service_fait` (**aucun paiement auto**) ; `contester` (commentaire) | 24–30 |
| F-50 | Fil d'avancement par devis (demandé→devisé→engagé→réalisé→payé) + délai + actions prioritaires à l'accueil | harness |
| F-51 | Dépôt **réel** du justificatif (PDF/image, dataURL) ; consultable par le gestionnaire (`GET …/justificatif`) | 35–38 |
| F-52 | `contacter` (appel/rappel/message/rendez-vous, aucun chatbot) — bouton permanent, visible au dossier gestionnaire | 52–53 |
| F-60/F-62/F-63 | `etablir` (message pro) / `refuser_pro` (motif) ; consignes de facturation affichées ; paiement ≤ engagé | 18, 22–23, 31 |
| F-21 | `crediter` (Crédit initial · Correction), journalisé, irréversible, correction négative tracée | 44–47 |
| F-22/RG-52/RG-53 | `payer` (manuel, partiel → reliquat recrédité, date+commentaire) ; **file des paiements** ; marquage **en lot** (`/api/paiements`) | 25, 31–33, 43 |
| F-23/RG-44 | `valider` (**partiel automatique** = min(demandé, disponible), **engage**), `refuser` (motif), `demander_piece`/`redeposer`, `marquer_payee` en lot | 39–43 |
| F-24 | E-mails automatiques (paiement, validation partielle, refus) — **simulés**, journal consultable | 33 + onglet E-mails |
| F-25 | Alertes : confirmer pour compte (motif), payer partiellement, annuler (désengagement intégral) | 27–30, 34 |
| F-26 | `commenter_mouvement` — visible par l'assuré-aidant dans son historique | 49 |
| F-27/RG-50 | `bloquer`/`debloquer` (motif) ; engagements en cours honorés ; consultation/orientation accessibles | 48–52 |
| F-28 | `GET /api/exports/{dossiers,mouvements,devis,remboursements}.csv` | 58 |
| F-70 | `alertes()` + `POST /api/tache-quotidienne` — **aucune libération automatique** | 54–55 |
| F-71 | Gardes serveur : engagement ≤ disponible, paiement ≤ engagé, validé ≤ disponible, aucun compartiment négatif (`IntegriteError`) | 20, 31, 41 |
| F-72/A-2 | Snapshot aidance-pro embarqué + `AIDANCE_PRO_CATALOGUE_URL` (+`_TOKEN`), repli auto ; source affichée dans `/api/diag` | 62 |
| §9 | `GSA-AA-NNNNN`, séquence annuelle ; devis `-Dnn`, remboursements `-Rnn` (sans clé de contrôle — A-4) | 01–02, 16, 36 |

**Arbitrages appliqués (§10)** — A-1 : **(a)** lien sécurisé par e-mail (simulé ; l'écran
Pro est le formulaire ouvert par ce lien) · A-2 : snapshot + variable d'environnement ·
A-3 : `DELAI_CONFIRMATION_JOURS = 7` (paramètre) · A-4 : sans clé de contrôle ·
A-5 : paiement partiel décidé par le gestionnaire (F-25).

## Simulations assumées (maquette)

- **E-mails** : journalisés côté serveur, consultables dans le back-office (onglet
  « E-mails ») — pas d'envoi réel. Le lien d'activation et le lien de chiffrage pro y figurent.
- **Accès** : le sélecteur de dossier (aidant) et de professionnel (pro) tient lieu de
  lien personnel/sécurisé ; `?dossier=…` démontre le lien d'activation (F-40).
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
python3 nonreg_v1.py          # la spécification exécutable (62 vérifications)
```
Render : pousser ces fichiers (racine), Blueprint `render.yaml` — inchangé. Après
déploiement : « Réinitialiser » dans le shell.

## Règle d'or pour toute évolution

Toute modification doit laisser `nonreg_v1.py` (62 vérifications) et `render_v1.py`
(39 vues, 38 assertions) **verts** — c'est ainsi que cette V1 a été validée, en plus
d'un parcours complet en navigateur réel (Playwright).
