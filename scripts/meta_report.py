import os
import html
import requests
from datetime import date, timedelta

META_ACCESS_TOKEN = os.environ["META_ACCESS_TOKEN"]
META_AD_ACCOUNT_IDS = {
    "Fermato CZ": os.environ["META_AD_ACCOUNT_ID_CZ"],
    "Fermato HU": os.environ["META_AD_ACCOUNT_ID_HU"],
}
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

GRAPH_API_VERSION = "v19.0"


def fetch_insights(account_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/act_{account_id}/insights"
    params = {
        "access_token": META_ACCESS_TOKEN,
        "level": "campaign",
        "fields": "campaign_name,spend,impressions,clicks,actions,action_values",
        "date_preset": "yesterday",
        "limit": 100,
    }
    response = requests.get(url, params=params, timeout=30)
    if not response.ok:
        print(f"Meta API error {response.status_code}: {response.text}")
        response.raise_for_status()
    return response.json().get("data", [])


def extract_action_value(items: list[dict], action_type: str) -> float:
    for item in items or []:
        if item.get("action_type") == action_type:
            return float(item.get("value", 0))
    return 0.0


def build_account_section(campaigns: list[dict]) -> str:
    total_spend = 0.0
    total_impressions = 0
    total_clicks = 0
    total_conversions = 0.0
    total_revenue = 0.0
    lines = []

    for c in campaigns:
        name = html.escape(c.get("campaign_name", "Unknown"))
        spend = float(c.get("spend", 0))
        impressions = int(c.get("impressions", 0))
        clicks = int(c.get("clicks", 0))
        conversions = extract_action_value(c.get("actions", []), "purchase")
        revenue = extract_action_value(c.get("action_values", []), "purchase")
        roas = round(revenue / spend, 2) if spend > 0 else 0.0
        ctr = round((clicks / impressions * 100), 2) if impressions > 0 else 0.0

        total_spend += spend
        total_impressions += impressions
        total_clicks += clicks
        total_conversions += conversions
        total_revenue += revenue

        lines.append(
            f"  📁 <b>{name}</b>\n"
            f"  Spend: €{spend:,.2f}  |  ROAS: {roas}x\n"
            f"  Impressions: {impressions:,}  |  Clicks: {clicks:,} ({ctr}%)\n"
            f"  Purchases: {int(conversions)}  |  Revenue: €{revenue:,.2f}"
        )

    total_roas = round(total_revenue / total_spend, 2) if total_spend > 0 else 0.0
    total_ctr = round((total_clicks / total_impressions * 100), 2) if total_impressions > 0 else 0.0

    totals = (
        f"💸 Spend: €{total_spend:,.2f}  |  ROAS: {total_roas}x\n"
        f"👁 Impressions: {total_impressions:,}  |  Clicks: {total_clicks:,} ({total_ctr}%)\n"
        f"🛒 Purchases: {int(total_conversions)}  |  Revenue: €{total_revenue:,.2f}"
    )

    return totals + "\n\n" + "\n\n".join(lines)


def send_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
    }
    response = requests.post(url, json=payload, timeout=15)
    if not response.ok:
        print(f"Telegram error {response.status_code}: {response.text}")
        response.raise_for_status()


def main():
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    parts = [f"📊 <b>Meta Ads Report — {yesterday}</b>"]

    for account_name, account_id in META_AD_ACCOUNT_IDS.items():
        print(f"Fetching insights for {account_name} ({account_id})...")
        campaigns = fetch_insights(account_id)

        parts.append(f"{'─' * 28}\n🏢 <b>{account_name}</b>")

        if not campaigns:
            parts.append("No campaign data found.")
        else:
            parts.append(build_account_section(campaigns))

    send_telegram("\n\n".join(parts))
    print("Report sent to Telegram.")


if __name__ == "__main__":
    main()
