import os
import requests

META_ACCESS_TOKEN = os.environ["META_ACCESS_TOKEN"]
GRAPH_API_VERSION = "v19.0"

TARGET_ACCOUNT = os.environ.get("VIDEO_REPORT_ACCOUNT", "cz").strip().lower()
ACCOUNT_ID = os.environ["META_AD_ACCOUNT_ID_HU"] if TARGET_ACCOUNT == "hu" else os.environ["META_AD_ACCOUNT_ID_CZ"]


def fetch_campaigns(account_id: str) -> list[dict]:
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/act_{account_id}/campaigns"
    params = {
        "access_token": META_ACCESS_TOKEN,
        "fields": "id,name,objective,effective_status,status",
        "limit": 500,
    }
    campaigns = []
    while url:
        response = requests.get(url, params=params, timeout=30)
        if not response.ok:
            print(f"Meta API error fetching campaigns: {response.text}")
            response.raise_for_status()
        payload = response.json()
        campaigns.extend(payload.get("data", []))
        url = payload.get("paging", {}).get("next")
        params = {}
    return campaigns


def main():
    campaigns = fetch_campaigns(ACCOUNT_ID)
    print(f"Account {TARGET_ACCOUNT}: {len(campaigns)} campaigns total")
    for c in campaigns:
        print(
            f"id={c.get('id')} | name={c.get('name')} | "
            f"status={c.get('status')} | effective_status={c.get('effective_status')} | "
            f"objective={c.get('objective')}"
        )


if __name__ == "__main__":
    main()
