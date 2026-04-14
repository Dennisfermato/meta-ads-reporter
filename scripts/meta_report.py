import os
import requests
from datetime import date, timedelta

META_ACCESS_TOKEN = os.environ["META_ACCESS_TOKEN"]
META_AD_ACCOUNT_ID = os.environ["META_AD_ACCOUNT_ID"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

GRAPH_API_VERSION = "v19.0"


def fetch_insights(date_str: str) -> list[dict]:
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/act_{META_AD_ACCOUNT_ID}/insights"
    params = {
        "access_token": META_ACCESS_TOKEN,
        "level": "campaign",
        "fields": "campaign_name,spend,impressions,clicks,actions,action_values",
        "time_range": f'{{"since":"{date_str}","until":"{date_str}"}}',
        "limit": 100,
    }
    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    return response.json().get("data", [])


def extract_action_value(items: list[dict], action_type: str) -> float:
    for item in items or []:
        if item.get("action_type") == action_type:
            return float(item.get("value", 0))
    return 0.0


def build_report(yesterday: str, campaigns: list[dict]) -> str:
    total_spend = 0.0
    total_impressions = 0
    total_clicks = 0
    total_conversions = 0.0
    total_revenue = 0.0

    lines = []

    for c in campaigns:
        name = c.get("campaign_name", "Unknown")
        spend = float(c.get("spend", 0))
        impressions = int(c.get("impressions", 0))
        clicks = int(c.get("clicks", 0))
        actions = c.get("actions", [])
        action_values = c.get("action_values", [])

        conversions = extract_action_value(actions, "purchase")
        revenue = extract_action_value(action_values, "purchase")
        roas = round(revenue / spend, 2) if spend > 0 else 0.0
        ctr = round((clicks / impressions * 100), 2) if impressions > 0 else 0.0

        total_spend += spend
        total_impressions += impressions
        total_clicks += clicks
        total_conversions += conversions
        total_revenue += revenue

        lines.append(
            f"📁 *{name}*\n"
            f"  Spend: €{spend:,.2f}  |  ROAS: {roas}x\n"
            f"  Impressions: {impressions:,}  |  Clicks: {clicks:,} ({ctr}%)\n"
            f"  Purchases: {int(conversions)}  |  Revenue: €{revenue:,.2f}"
        )

    total_roas = round(total_revenue / total_spend, 2) if total_spend > 0 else 0.0
    total_ctr = round((total_clicks / total_impressions * 100), 2) if total_impressions > 0 else 0.0

    header = (
        f"📊 *Meta Ads Report — {yesterday}*\n\n"
        f"*TOTALS*\n"
        f"💸 Spend: €{total_spend:,.2f}\n"
        f"📈 ROAS: {total_roas}x\n"
        f"👁 Impressions: {total_impressions:,}\n"
        f"🖱 Clicks: {total_clicks:,} (CTR {total_ctr}%)\n"
        f"🛒 Purchases: {int(total_conversions)}  |  Revenue: €{total_revenue:,.2f}\n"
    )

    campaign_section = "\n\n*BY CAMPAIGN*\n\n" + "\n\n".join(lines) if lines else ""

    return header + campaign_section


def send_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
    }
    response = requests.post(url, json=payload, timeout=15)
    response.raise_for_status()


def main():
    yesterday = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"Fetching Meta insights for {yesterday}...")

    campaigns = fetch_insights(yesterday)

    if not campaigns:
        message = f"📊 *Meta Ads Report — {yesterday}*\n\nNo campaign data found for this date."
    else:
        message = build_report(yesterday, campaigns)

    send_telegram(message)
    print("Report sent to Telegram.")


if __name__ == "__main__":
    main()
