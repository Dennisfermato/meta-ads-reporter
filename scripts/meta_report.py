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
TELEGRAM_CHAT_IDS = [cid.strip() for cid in os.environ["TELEGRAM_CHAT_IDS"].split(",")]

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
        "fields": "campaign_id,campaign_name,spend,impressions,clicks,reach,frequency,actions,action_values",
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


def calc_metrics(spend: float, impressions: int, clicks: int, purchases: float, revenue: float, reach: int, frequency: float):
    roas  = round(revenue / spend, 2)       if spend > 0        else 0.0
    ctr   = round(clicks / impressions * 100, 1) if impressions > 0 else 0.0
    cpm   = round(spend / impressions * 1000, 2) if impressions > 0 else 0.0
    cpc   = round(spend / clicks, 2)        if clicks > 0       else 0.0
    cpp   = round(spend / purchases, 2)     if purchases > 0    else None
    return roas, ctr, cpm, cpc, cpp


def build_account_block(account_name: str, currency: str, campaigns: list[dict]) -> tuple[str, str]:
    if not campaigns:
        return f"<b>{account_name}</b>: no data", f"🏢 <b>{account_name}</b>\nNo active campaigns with data."

    total_spend = total_impressions = total_clicks = total_purchases = total_revenue = total_reach = 0.0

    for c in campaigns:
        total_spend       += float(c.get("spend", 0))
        total_impressions += int(c.get("impressions", 0))
        total_clicks      += int(c.get("clicks", 0))
        total_reach       += int(c.get("reach", 0))
        total_purchases   += extract_value(c.get("actions", []), "purchase")
        total_revenue     += extract_value(c.get("action_values", []), "purchase")

    roas, ctr, cpm, cpc, cpp = calc_metrics(
        total_spend, int(total_impressions), int(total_clicks),
        total_purchases, total_revenue, int(total_reach), 0
    )

    cpp_str = format_spend(cpp, currency) if cpp else "–"
    summary = f"<b>{account_name}</b>: {format_spend(total_spend, currency)} · {roas}x ROAS"

    account_line = (
        f"🏢 <b>{account_name}</b>\n"
        f"💸 {format_spend(total_spend, currency)}  📈 {roas}x  🛒 {cpp_str}/conv\n"
        f"👁 {int(total_reach):,} reach  🔁 {round(total_impressions/total_reach,1) if total_reach else '–'} freq  ↗ {ctr}% CTR\n"
        f"📌 CPM {format_spend(cpm, currency)}  🖱 CPC {format_spend(cpc, currency)}"
    )

    campaign_lines = []
    for c in campaigns:
        name        = html.escape(c.get("campaign_name", "Unknown"))
        spend       = float(c.get("spend", 0))
        impressions = int(c.get("impressions", 0))
        clicks      = int(c.get("clicks", 0))
        reach       = int(c.get("reach", 0))
        purchases   = extract_value(c.get("actions", []), "purchase")
        revenue     = extract_value(c.get("action_values", []), "purchase")
        freq        = round(impressions / reach, 1) if reach > 0 else 0.0

        roas, ctr, cpm, cpc, cpp = calc_metrics(spend, impressions, clicks, purchases, revenue, reach, freq)
        cpp_str = format_spend(cpp, currency) if cpp else "–"

        campaign_lines.append(
            f"▸ <b>{name}</b>\n"
            f"  💸 {format_spend(spend, currency)}  📈 {roas}x  🛒 {cpp_str}\n"
            f"  ↗ {ctr}%  🔁 {freq}  📌 {format_spend(cpm, currency)} CPM"
        )

    block = account_line + "\n" + "\n".join(campaign_lines)
    return summary, block


def send_telegram(message: str) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chat_id in TELEGRAM_CHAT_IDS:
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        response = requests.post(url, json=payload, timeout=15)
        if not response.ok:
            print(f"Telegram error for {chat_id}: {response.status_code}: {response.text}")


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
        currency   = fetch_account_currency(account_id)
        active_ids = fetch_active_campaign_ids(account_id)
        campaigns  = fetch_insights(account_id, active_ids, date_preset)
        summary, block = build_account_block(account_name, currency, campaigns)
        summaries.append(summary)
        blocks.append(block)

    divider = "─" * 26
    header = f"📊 {period} · {label}\n" + "\n".join(summaries)
    full_message = header + f"\n{divider}\n" + f"\n{divider}\n".join(blocks)

    send_telegram(full_message)
    print("Report sent to Telegram.")


if __name__ == "__main__":
    main()
