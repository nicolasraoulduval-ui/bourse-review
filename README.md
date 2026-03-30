# Portfolio Monitor — Automation post-clôture US

Script Python qui génère et envoie chaque soir un email de suivi de portefeuille en français,
en appelant Claude via l'API Anthropic avec web search activé.

---

## Prérequis

- Python 3.11+
- Un compte Anthropic avec clé API (https://console.anthropic.com)
- Un compte Gmail avec un mot de passe d'application (pas ton mot de passe principal)

---

## Installation

```bash
# 1. Cloner ou copier ce dossier
cd portfolio_monitor

# 2. Installer les dépendances
pip install -r requirements.txt

# 3. Configurer les variables d'environnement
cp .env.template .env
# Éditer .env avec tes vraies valeurs
```

---

## Configuration du .env

```
ANTHROPIC_API_KEY=sk-ant-...       # Clé API Anthropic
EMAIL_SENDER=ton.email@gmail.com   # Expéditeur (compte Gmail)
EMAIL_PASSWORD=xxxx xxxx xxxx xxxx # Mot de passe d'application Gmail (16 caractères)
EMAIL_RECIPIENT=nicolas@email.com  # Destinataire
```

### Obtenir un mot de passe d'application Gmail

1. Aller sur https://myaccount.google.com/security
2. Activer la validation en deux étapes
3. Aller sur https://myaccount.google.com/apppasswords
4. Créer un mot de passe pour "Mail" → copier les 16 caractères dans `.env`

---

## Utilisation

### Test immédiat (recommandé avant de laisser tourner)

```bash
python portfolio_monitor.py --now
```

Cela exécute le job immédiatement sans attendre 22h30. Vérifie que :
- L'API Anthropic répond
- L'email arrive bien dans ta boîte
- Le contenu est correct

### Démarrage en mode daemon (tourne en continu, s'exécute chaque soir)

```bash
python portfolio_monitor.py
```

Le script planifie le job à **22h30 heure de Paris** chaque jour de marché (lundi–vendredi hors jours fériés principaux).

---

## Déploiement continu (optionnel)

Pour que le script tourne sans que ton ordinateur reste allumé, tu peux le déployer sur :

### Option A — GitHub Actions (gratuit, recommandé)

Crée `.github/workflows/portfolio.yml` :

```yaml
name: Portfolio Monitor

on:
  schedule:
    # 22h30 Paris = 21h30 UTC (hiver) / 20h30 UTC (été)
    - cron: '30 21 * * 1-5'
  workflow_dispatch:  # Déclenchement manuel possible

jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r requirements.txt
      - run: python portfolio_monitor.py --now
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          EMAIL_SENDER: ${{ secrets.EMAIL_SENDER }}
          EMAIL_PASSWORD: ${{ secrets.EMAIL_PASSWORD }}
          EMAIL_RECIPIENT: ${{ secrets.EMAIL_RECIPIENT }}
```

Ajouter les secrets dans GitHub → Settings → Secrets and variables → Actions.

### Option B — Serveur VPS / Raspberry Pi

```bash
# Lancer en arrière-plan avec nohup
nohup python portfolio_monitor.py > portfolio_monitor.log 2>&1 &

# Ou avec systemd (plus robuste)
# Créer /etc/systemd/system/portfolio-monitor.service
```

---

## Logs

Le script écrit dans `portfolio_monitor.log`. En cas d'erreur, consulter ce fichier en premier.

---

## Structure des fichiers

```
portfolio_monitor/
├── portfolio_monitor.py   # Script principal
├── requirements.txt       # Dépendances Python
├── .env.template          # Template de configuration
├── .env                   # Configuration réelle (ne pas committer)
└── README.md              # Ce fichier
```

---

## Sécurité

- Ne jamais committer `.env` dans Git
- Ajouter `.env` dans `.gitignore`
- Utiliser des secrets GitHub pour le déploiement CI/CD
