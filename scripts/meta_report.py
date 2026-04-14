import os
import html
import requests
from datetime import date, timedelta, datetime, timezone

META_ACCESS_TOKEN = os.environ["META_ACCESS_TOKEN"]
META_AD_ACCOUNT_IDS = {
    "Fermato CZ": os.environ["META_AD_ACCOUNT_ID_CZ"],
    "Fermato HU": os.environ["META_AD_ACCOUNT_ID_HU"],
}
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

GRAPH_API_VERSION = "v19.0"


def fetch_account_currency(account_id: str) -> str:
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/act_{account_id}"
    params = {"access_token": META_ACCESS_TOKEN, "fields": "currency"}
    response = requests.get(url, params=params, timeout=15)
    if response.ok:
        return response.json().get("currency", "EUR")
    return "EUR"


def fetch_active_campaign_ids(account_id: str) -> set[str]:
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/act_{account_id}/campaigns"
    params = {
        "access_token": META_ACCESS_TOKEN,
        "effective_status": '["ACTIVE"]',
        "fields": "id",
        "limit": 200,
    }
    response = requests.get(url, params=params, timeout=30)
    if not response.ok:
        print(f"Meta API error fetching campaigns: {response.text}")
        return set()
    return {c["id"] for c in response.json().get("data", [])}


def fetch_insights(account_id: str, active_ids: set[str], date_preset: str) -> list[dict]:
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/act_{account_id}/insights"
    params = {
        "access_token": META_ACCESS_TOKEN,
        "level": "campaign",
        "fields": "campaign_id,campaign_name,spend,actions,action_values",
        "date_preset": date_preset,
        "limit": 100,
    }
    response = requests.get(url, params=params, timeout=30)
    if not response.ok:
        print(f"Meta API error {response.status_code}: {response.text}")
        response.raise_for_status()
    data = response.json().get("data", [])
    return [c for c in data if c.get("campaign_id") in active_ids]


def extract_value(items: list[dict], action_type: str) -> float:
    for item in items or []:
        if item.get("action_type") == action_type:
            return float(item.get("value", 0))
    return 0.0


def format_spend(amount: float, currency: str) -> str:
    if currency == "CZK":
        return f"Kč{amount:,.0f}"
    if currency == "HUF":
        return f"Ft{amount:,.0f}"
    return f"€{amount:,.2f}"


def build_account_block(account_name: str, currency: str, campaigns: list[dict]) -> tuple[str, str]:
    """Returns (summary_line, full_block) — summary_line goes into the notification preview."""
    if not campaigns:
        summary = f"<b>{account_name}</b>: no data"
        block = f"🏢 <b>{account_name}</b>\nNo active campaigns with data yesterday."
        return summary, block

    total_spend = sum(float(c.get("spend", 0)) for c in campaigns)
    total_revenue = sum(extract_value(c.get("action_values", []), "purchase") for c in campaigns)
    total_roas = round(total_revenue / total_spend, 2) if total_spend > 0 else 0.0

    summary = f"<b>{account_name}</b>: {format_spend(total_spend, currency)} · ROAS {total_roas}x"

    campaign_lines = []
    for c in campaigns:
        name = html.escape(c.get("campaign_name", "Unknown"))
        spend = float(c.get("spend", 0))
        revenue = extract_value(c.get("action_values", []), "purchase")
        roas = round(revenue / spend, 2) if spend > 0 else 0.0
        campaign_lines.append(
            f"  • <b>{name}</b>\n"
            f"    {format_spend(spend, currency)}  |  ROAS {roas}x"
        )

    block = (
        f"🏢 <b>{account_name}</b>\n"
        f"💸 {format_spend(total_spend, currency)}  |  📈 ROAS {total_roas}x\n\n"
        f"<b>Active campaigns:</b>\n\n" + "\n\n".join(campaign_lines)
    )

    return summary, block


def send_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}
    response = requests.post(url, json=payload, timeout=15)
    if not response.ok:
        print(f"Telegram error {response.status_code}: {response.text}")
        response.raise_for_status()


def main():
    utc_hour = datetime.now(timezone.utc).hour
    if utc_hour < 9:
        date_preset = "yesterday"
        label = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
        period = "Yesterday"
    else:
        date_preset = "today"
        label = date.today().strftime("%Y-%m-%d")
        period = "Today so far"

    summaries = []
    blocks = []

    for account_name, account_id in META_AD_ACCOUNT_IDS.items():
        print(f"Fetching {account_name}...")
        currency = fetch_account_currency(account_id)
        active_ids = fetch_active_campaign_ids(account_id)
        campaigns = fetch_insights(account_id, active_ids, date_preset)
        summary, block = build_account_block(account_name, currency, campaigns)
        summaries.append(summary)
        blocks.append(block)

    header = f"📊 {period} · {label}\n" + "\n".join(summaries)
    divider = "─" * 28
    full_message = header + f"\n\n{divider}\n\n" + f"\n\n{divider}\n\n".join(blocks)

    send_telegram(full_message)
    print("Report sent to Telegram.")


if __name__ == "__main__":
    main()
