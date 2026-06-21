"""
Portfolio Monitor — Automation post-cloture US.

Le calcul quantitatif (cours, variations, poids, performance ponderee,
comparaison au S&P 500, detection des mouvements > 1 %) est fait en Python
de maniere deterministe via yfinance. L'API Anthropic n'intervient ensuite
que pour le commentaire qualitatif des mouvements (recherche de catalyseur,
contexte news), a partir des chiffres deja calcules.

Dependances : pip install -r requirements.txt
Configuration : fichier .env dans le meme dossier (voir README).
"""

import os
import sys
import smtplib
import logging
from datetime import datetime, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from zoneinfo import ZoneInfo

import yfinance as yf
import anthropic
from dotenv import load_dotenv

load_dotenv()

# -- Logging -----------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("portfolio_monitor.log"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)

# -- Config depuis .env ------------------------------------------------------
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
EMAIL_SENDER      = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD    = os.getenv("EMAIL_PASSWORD")
EMAIL_RECIPIENT   = os.getenv("EMAIL_RECIPIENT")
SMTP_HOST         = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT         = int(os.getenv("SMTP_PORT", "587"))

MOVER_THRESHOLD = 0.01  # +/-1 %
BENCHMARK       = "^GSPC"

# -- Portefeuille ------------------------------------------------------------
# symbol = symbole Yahoo Finance (suffixe .PA pour Euronext Paris)
# ccy    = devise de cotation
PORTFOLIO = [
    {"symbol": "AAPL",  "name": "Apple",             "shares": 5.01, "ccy": "USD"},
    {"symbol": "UNH",   "name": "UnitedHealth",      "shares": 1.43, "ccy": "USD"},
    {"symbol": "V",     "name": "Visa",              "shares": 3.38, "ccy": "USD"},
    {"symbol": "PG",    "name": "Procter & Gamble",  "shares": 2.97, "ccy": "USD"},
    {"symbol": "AVGO",  "name": "Broadcom",          "shares": 5.90, "ccy": "USD"},
    {"symbol": "KO",    "name": "Coca-Cola",         "shares": 7.70, "ccy": "USD"},
    {"symbol": "MSFT",  "name": "Microsoft",         "shares": 3.45, "ccy": "USD"},
    {"symbol": "BLK",   "name": "BlackRock",         "shares": 0.35, "ccy": "USD"},
    {"symbol": "DLR",   "name": "Digital Realty",    "shares": 5.45, "ccy": "USD"},
    {"symbol": "HD",    "name": "Home Depot",        "shares": 0.78, "ccy": "USD"},
    {"symbol": "NVO",   "name": "Novo Nordisk",      "shares": 9.00, "ccy": "USD"},
    {"symbol": "MC.PA", "name": "LVMH",              "shares": 5.00, "ccy": "EUR"},
    {"symbol": "TTE.PA","name": "TotalEnergies",     "shares": 35.0, "ccy": "EUR"},
    {"symbol": "CS.PA", "name": "AXA",               "shares": 20.0, "ccy": "EUR"},
    {"symbol": "ENX.PA","name": "Euronext",          "shares": 5.00, "ccy": "EUR"},
    {"symbol": "SU.PA", "name": "Schneider Electric","shares": 4.00, "ccy": "EUR"},
    {"symbol": "AI.PA", "name": "Air Liquide",       "shares": 10.0, "ccy": "EUR"},
]


def fetch_eurusd() -> float:
    """Taux EUR/USD pour convertir les positions USD en base EUR."""
    data = yf.Ticker("EURUSD=X").history(period="5d")
    if data.empty:
        raise ValueError("Taux EUR/USD indisponible.")
    return float(data["Close"].iloc[-1])


def compute_metrics() -> dict:
    """Calcule, en Python, toute la couche quantitative du rapport.

    Retourne un dict avec : les lignes par position (variation, valeur de marche
    en EUR, poids), la performance ponderee du portefeuille, la variation du
    benchmark, et la liste des mouvements > seuil. Aucune de ces valeurs ne
    depend du LLM.
    """
    eurusd = fetch_eurusd()
    log.info(f"EUR/USD = {eurusd:.4f}")

    rows, total_mv_eur = [], 0.0
    for pos in PORTFOLIO:
        hist = yf.Ticker(pos["symbol"]).history(period="5d")
        if len(hist) < 2:
            log.warning(f"Donnees insuffisantes pour {pos['symbol']} — ignore.")
            continue
        prev_close = float(hist["Close"].iloc[-2])
        last_close = float(hist["Close"].iloc[-1])
        change_pct = (last_close - prev_close) / prev_close

        mv_local = last_close * pos["shares"]
        mv_eur   = mv_local if pos["ccy"] == "EUR" else mv_local / eurusd
        total_mv_eur += mv_eur

        rows.append({
            "symbol": pos["symbol"], "name": pos["name"], "ccy": pos["ccy"],
            "last": last_close, "change_pct": change_pct, "mv_eur": mv_eur,
        })

    for r in rows:
        r["weight"] = r["mv_eur"] / total_mv_eur if total_mv_eur else 0.0

    # Performance ponderee = somme(poids * variation locale).
    # Note : variation en devise locale ; l'effet de change n'est pas inclus.
    weighted_return = sum(r["weight"] * r["change_pct"] for r in rows)

    bench = yf.Ticker(BENCHMARK).history(period="5d")
    bench_return = (
        (float(bench["Close"].iloc[-1]) - float(bench["Close"].iloc[-2]))
        / float(bench["Close"].iloc[-2])
    ) if len(bench) >= 2 else None

    rows.sort(key=lambda r: abs(r["change_pct"]), reverse=True)
    movers = [r for r in rows if abs(r["change_pct"]) > MOVER_THRESHOLD]

    return {
        "rows": rows, "movers": movers, "total_mv_eur": total_mv_eur,
        "weighted_return": weighted_return, "bench_return": bench_return,
        "eurusd": eurusd,
    }


def format_facts(m: dict, today_str: str) -> str:
    """Bloc de faits chiffres passe au LLM. Le LLM ne recalcule rien."""
    def pct(x): return f"{x * 100:+.2f} %" if x is not None else "n/d"

    lines = [
        f"Date : {today_str}",
        f"Performance ponderee du portefeuille (jour) : {pct(m['weighted_return'])}",
        f"Variation S&P 500 (jour) : {pct(m['bench_return'])}",
        f"Valeur de marche totale : {m['total_mv_eur']:,.0f} EUR",
        "",
        "Toutes les positions (triees par |variation|) :",
        "| Ticker | Nom | Variation | Poids |",
        "|---|---|---|---|",
    ]
    for r in m["rows"]:
        lines.append(f"| {r['symbol']} | {r['name']} | {pct(r['change_pct'])} | {r['weight'] * 100:.1f} % |")

    lines += ["", f"Mouvements > +/-1 % a expliquer : {', '.join(r['symbol'] for r in m['movers']) or 'aucun'}"]
    return "\n".join(lines)


SYSTEM_PROMPT = """Tu es analyste de portefeuille. Les chiffres (cours, variations, \
poids, performance, benchmark) sont DEJA calcules et te sont fournis. Tu ne les recalcules \
pas et tu ne les contredis pas. Ton role : expliquer les mouvements > +/-1 %.

Pour chaque mouvement fourni, recherche via web search les informations recentes (24-72h), \
par ordre de priorite : resultats/guidance, actions d'analystes, news produit/business/regulation, \
macro (Fed, CPI, emploi, taux), rotation sectorielle, sentiment, revalorisation.

Regles : ne jamais inventer de catalyseur ; si rien de solide, ecrire "Aucun catalyseur clair \
identifie". Separer les faits ("Selon [source]...") de l'interpretation ("Il est probable que..."). \
Pas de conseil d'achat/vente. Francais uniquement. Chaque explication <= 4 phrases.

Structure de l'email a produire :

Objet : Performance quotidienne du portfolio - {date}

1. Performance du portfolio
[2-3 phrases reprenant la performance ponderee et la comparaison au S&P 500 fournies.]

2. Mouvements superieurs a 1 %
Pour chaque ticker de la liste fournie :
**[TICKER] - [Nom]** ([variation fournie])
Catalyseur probable : [...]
Classe comme : [Fondamentaux / Macro / Sentiment / Aucun catalyseur clair]

3. Note de discipline
[Une phrase : ne pas reagir emotionnellement sauf si la these a fondamentalement change.]
"""


def call_claude(facts: str, today_str: str) -> str:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    log.info("Appel API Anthropic (commentaire qualitatif + web search)...")
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=SYSTEM_PROMPT.replace("{date}", today_str),
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=[{"role": "user", "content":
                   f"Voici les chiffres deja calcules. Produis l'email.\n\n{facts}"}],
    )
    text = "".join(b.text for b in response.content if hasattr(b, "text")).strip()
    if not text:
        raise ValueError("Reponse vide de l'API Anthropic.")
    return text


def send_email(subject: str, body: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"], msg["From"], msg["To"] = subject, EMAIL_SENDER, EMAIL_RECIPIENT
    msg.attach(MIMEText(body, "plain", "utf-8"))
    log.info(f"Envoi email a {EMAIL_RECIPIENT}...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo(); server.starttls(); server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
    log.info("Email envoye.")


def extract_subject(body: str, fallback_date: str) -> str:
    for line in body.splitlines():
        if line.lower().startswith("objet") or line.lower().startswith("subject"):
            parts = line.split(":", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()
    return f"Performance quotidienne du portfolio - {fallback_date}"


def is_us_market_day() -> bool:
    today = date.today()
    if today.weekday() >= 5:
        return False
    holidays = {date(today.year, 1, 1), date(today.year, 7, 4), date(today.year, 12, 25)}
    return today not in holidays


def run_daily_job() -> None:
    today_str = datetime.now(ZoneInfo("Europe/Paris")).strftime("%d/%m/%Y")
    log.info(f"=== Job portfolio - {today_str} ===")
    if not is_us_market_day():
        log.info("Marche US ferme. Job ignore.")
        return
    try:
        metrics = compute_metrics()
        facts   = format_facts(metrics, today_str)
        log.info("Chiffres calcules :\n" + facts)
        body    = call_claude(facts, today_str)
        send_email(extract_subject(body, today_str), body)
        log.info("Job termine.")
    except Exception as e:
        log.error(f"Erreur durant le job : {e}", exc_info=True)


if __name__ == "__main__":
    run_daily_job()
