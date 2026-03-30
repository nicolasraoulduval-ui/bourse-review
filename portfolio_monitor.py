"""
Portfolio Monitor — Automation post-clôture US
Exécute le workflow portfolio-monitor via l'API Anthropic et envoie l'email.

Dépendances : pip install anthropic yfinance schedule python-dotenv
Configuration : fichier .env dans le même dossier (voir README)
"""

import os
import smtplib
import logging
import schedule
import time
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

import anthropic
from dotenv import load_dotenv

load_dotenv()

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("portfolio_monitor.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ── Config depuis .env ─────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
EMAIL_SENDER      = os.getenv("EMAIL_SENDER")       # ex: moncompte@gmail.com
EMAIL_PASSWORD    = os.getenv("EMAIL_PASSWORD")      # mot de passe app Gmail
EMAIL_RECIPIENT   = os.getenv("EMAIL_RECIPIENT")     # ex: nicolas@email.com
SMTP_HOST         = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT         = int(os.getenv("SMTP_PORT", "587"))

# ── Portefeuille ───────────────────────────────────────────────────────────────
PORTFOLIO = """
| Ticker | Nom                   | Nombre | Bourse       | Secteur                    |
|--------|-----------------------|--------|--------------|----------------------------|
| AAPL   | Apple Inc.            | 5,01   | NASDAQ (USD) | Technology                 |
| UNH    | UnitedHealth Group    | 1,43   | NYSE (USD)   | Healthcare                 |
| V      | Visa Inc.             | 3,38   | NYSE (USD)   | Financial Services         |
| PG     | Procter & Gamble      | 2,97   | NYSE (USD)   | Consumer Staples           |
| AVGO   | Broadcom Inc.         | 5,9    | NASDAQ (USD) | Semiconductors             |
| KO     | Coca-Cola             | 7,7    | NYSE (USD)   | Consumer Staples           |
| MSFT   | Microsoft             | 3,45   | NASDAQ (USD) | Technology                 |
| BLK    | BlackRock             | 0,35   | NYSE (USD)   | Financial Services         |
| DLR    | Digital Realty Trust  | 5,45   | NYSE (USD)   | REIT                       |
| HD     | Home Depot            | 0,78   | NYSE (USD)   | Retail                     |
| MC     | LVMH                  | 5      | Euronext (€) | Luxury                     |
| TTE    | TotalEnergies         | 35     | Euronext (€) | Oil & Gas                  |
| AXA    | AXA SA                | 20     | Euronext (€) | Insurance                  |
| ENX    | Euronext NV           | 5      | Euronext (€) | Financial Services         |
| SU     | Schneider Electric    | 4      | Euronext (€) | Industrials                |
| NVO    | Novo Nordisk          | 9      | NYSE (USD)   | Pharmaceuticals            |
| AI     | Air Liquide           | 10     | Euronext (€) | Chemicals                  |
"""

# ── Prompt système ─────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Tu es un assistant d'analyse de portefeuille boursier. Tu appliques rigoureusement le workflow suivant à chaque exécution.

## Portefeuille à analyser

{portfolio}

## Workflow obligatoire

### Étape 1 — Données de marché
Pour chaque position :
- Récupère le cours de clôture du jour et le cours de clôture précédent via web search
- Calcule la variation : ((clôture - clôture_préc) / clôture_préc) × 100
- Calcule la performance pondérée du portfolio par valeur de marché (prix × quantité)
- Les positions européennes (MC, TTE, AXA, ENX, SU, AI) sont en EUR sur Euronext Paris

### Étape 2 — Identification des mouvements > ±1%
Pour chaque position avec |variation| > 1%, recherche les informations récentes (24–72h) dans cet ordre de priorité :
1. Résultats financiers (EPS, CA vs consensus, guidance)
2. Actions d'analystes (upgrade, downgrade, révision de cible)
3. Actualité produit/business (lancements, contrats, partenariats, régulation)
4. Événements macro (Fed, CPI, emploi, taux)
5. Rotation sectorielle
6. Actualité réglementaire ou judiciaire
7. Sentiment / positionnement (short squeeze, flux retail confirmés)
8. Réajustement de valorisation

Si aucun catalyseur solide n'est identifié : écrire "Aucun catalyseur clair identifié."
Ne jamais inventer une cause. Si incertain, le dire explicitement.
Si plusieurs causes existent, les classer par probabilité décroissante.

### Étape 3 — Classification
Pour chaque mouvement > ±1%, classer le moteur principal :
- Fondamentaux — résultats, guidance, révision analyste, news produit
- Macro — taux, inflation, géopolitique, devise
- Sentiment — positionnement, short squeeze, flux retail
- Aucun catalyseur clair

### Étape 4 — Rédaction de l'email

Produire l'email EN FRANÇAIS avec cette structure exacte :

---
Objet : Performance quotidienne du portfolio – {date}

1. Performance du portfolio
[2–3 phrases. Performance totale pondérée du jour en %. Le marché large est-il en hausse ou en baisse ? Surperformance ou sous-performance ?]

2. Principaux mouvements
Tableau de toutes les positions triées par variation absolue décroissante.
| Ticker | Nom | Variation |

3. Mouvements supérieurs à 1%
Pour chaque position au-dessus de ±1% :

**[TICKER] – [Nom]**
Variation : [+/-X.XX%]
Catalyseur probable : [explication concise, 4 phrases max. Séparer faits ("Selon [source]...") et interprétation ("Il est probable que...")]
Classé comme : [Fondamentaux / Macro / Sentiment / Aucun catalyseur clair]

4. Note de discipline
[Une phrase. Rappeler de ne pas réagir émotionnellement sauf si la thèse d'investissement a fondamentalement changé.]
---

## Règles de sortie
- Français uniquement
- Dense et court. Chaque explication de catalyseur ≤ 4 phrases
- Pas de conseil d'achat/vente
- Pas de récapitulatif macro générique sauf si ça explique directement une position
- Si le mouvement est macro : "Mouvement macro généralisé, pas de catalyseur spécifique à la valeur."
- Si les données d'un ticker sont indisponibles : le noter explicitement
""".strip()


def is_us_market_open_today() -> bool:
    """Vérifie si c'est un jour de marché US (lundi–vendredi, hors jours fériés approximatifs)."""
    today = date.today()
    if today.weekday() >= 5:  # samedi=5, dimanche=6
        return False
    # Jours fériés US fixes les plus courants (approximation)
    us_holidays = {
        date(today.year, 1, 1),   # Nouvel An
        date(today.year, 7, 4),   # Fête nationale
        date(today.year, 12, 25), # Noël
    }
    return today not in us_holidays


def build_prompt(today_str: str) -> str:
    return (
        f"Nous sommes le {today_str}. Les marchés US viennent de clôturer.\n\n"
        "Applique le workflow portfolio-monitor complet sur le portefeuille défini dans le prompt système. "
        "Utilise la recherche web pour récupérer les cours du jour et les actualités récentes. "
        "Génère l'email complet en français, prêt à être envoyé."
    )


def call_claude(today_str: str) -> str:
    """Appelle l'API Anthropic avec web search activé."""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    system = SYSTEM_PROMPT.replace("{portfolio}", PORTFOLIO).replace("{date}", today_str)

    log.info("Appel API Anthropic (claude-sonnet-4-20250514 + web search)...")

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content": build_prompt(today_str)}],
    )

    # Extraire le texte de la réponse (peut contenir des blocs tool_use intermédiaires)
    full_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            full_text += block.text

    if not full_text.strip():
        raise ValueError("Réponse vide reçue de l'API Anthropic.")

    return full_text.strip()


def send_email(subject: str, body: str) -> None:
    """Envoie l'email via SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECIPIENT

    # Version texte brut
    msg.attach(MIMEText(body, "plain", "utf-8"))

    log.info(f"Envoi email à {EMAIL_RECIPIENT}...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
    log.info("Email envoyé.")


def extract_subject(email_body: str, fallback_date: str) -> str:
    """Extrait la ligne Objet du corps généré par Claude."""
    for line in email_body.splitlines():
        if "objet" in line.lower() or "subject" in line.lower():
            # Prend ce qui suit le ":" sur la même ligne
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    return f"Performance quotidienne du portfolio – {fallback_date}"


def run_daily_job() -> None:
    """Job principal : générer + envoyer le rapport portfolio."""
    paris_tz  = ZoneInfo("Europe/Paris")
    today     = datetime.now(paris_tz)
    today_str = today.strftime("%d/%m/%Y")

    log.info(f"=== Démarrage du job portfolio — {today_str} ===")

    if not is_us_market_open_today():
        log.info("Marché US fermé aujourd'hui. Job ignoré.")
        return

    try:
        email_body = call_claude(today_str)
        subject    = extract_subject(email_body, today_str)
        send_email(subject, email_body)
        log.info("Job terminé avec succès.")
    except Exception as e:
        log.error(f"Erreur durant le job : {e}", exc_info=True)


# ── Planification ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Exécution immédiate si argument --now (pour test)
    import sys
    if "--now" in sys.argv:
        log.info("Mode test : exécution immédiate.")
        run_daily_job()
        sys.exit(0)

    # Planifié à 22h30 heure de Paris (30 min après la clôture US à 22h00)
    schedule.every().day.at("22:30").do(run_daily_job)
    log.info("Scheduler démarré. Job planifié à 22h30 (heure de Paris) chaque jour de marché.")

    while True:
        schedule.run_pending()
        time.sleep(60)
