# Revue de portefeuille post-clôture

Un script Python qui tourne chaque soir de bourse après la clôture américaine et envoie par email une revue du portefeuille. Les chiffres sont calculés en Python, l'IA ne fait que le commentaire.

## Le principe : séparer le calcul du commentaire

Un modèle de langage n'est pas fiable pour faire des calculs. Le script fait donc deux étapes distinctes :

1. **Calcul déterministe en Python** (yfinance) : cours, variations du jour, poids de chaque ligne, performance pondérée du portefeuille, comparaison au S&P 500, conversion EUR/USD, détection des mouvements supérieurs à 1 %.
2. **Commentaire qualitatif par Claude** (API Anthropic, avec recherche web) : à partir des chiffres déjà calculés, Claude cherche le catalyseur de chaque mouvement significatif et rédige l'email.

Résultat : les chiffres de l'email sont exacts, et le texte apporte le contexte d'actualité.

## Fonctionnement

```
GitHub Actions (cron, lundi au vendredi, 22h30 heure de Paris)
  └── python portfolio_monitor.py --now
        ├── Jour de bourse US ? sinon arrêt
        ├── Cours et variations (yfinance)
        ├── Métriques du portefeuille et écart au S&P 500
        ├── Appel à Claude avec l'outil de recherche web
        └── Envoi de l'email (SMTP)
```

## Installation

```
git clone https://github.com/nicolasraoulduval-ui/bourse-review.git
cd bourse-review
pip install -r requirements.txt
cp .env.template .env
```

Remplir `.env` :

```
ANTHROPIC_API_KEY=...      # console.anthropic.com
EMAIL_SENDER=...           # adresse Gmail d'envoi
EMAIL_PASSWORD=...         # mot de passe d'application Gmail (16 caractères)
EMAIL_RECIPIENT=...        # destinataire
```

Le portefeuille se configure dans la liste `PORTFOLIO` de `portfolio_monitor.py` (symbole Yahoo Finance, nombre de titres, devise). Suffixe `.PA` pour Euronext Paris.

Test immédiat :

```
python portfolio_monitor.py --now
```

## Déploiement sur GitHub Actions

Le workflow est dans `.github/workflows/portfolio.yml`. Il suffit d'ajouter les quatre variables ci-dessus dans **Settings → Secrets and variables → Actions**. Le déclenchement manuel est aussi possible depuis l'onglet Actions.

## Sécurité

- `.env` est exclu du dépôt par `.gitignore`.
- Les identifiants passent par les secrets GitHub, jamais en dur dans le code.

## Pistes d'évolution

- Synthèse hebdomadaire le lundi
- Archive des revues
- Calendrier complet des jours fériés US

## Licence

MIT
