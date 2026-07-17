import os
import json
import requests

META_ACCESS_TOKEN = os.environ["META_ACCESS_TOKEN"]
GRAPH_API_VERSION = "v19.0"

TARGET_ACCOUNT = os.environ.get("VIDEO_REPORT_ACCOUNT", "cz").strip().lower()
ACCOUNT_ID = os.environ["META_AD_ACCOUNT_ID_HU"] if TARGET_ACCOUNT == "hu" else os.environ["META_AD_ACCOUNT_ID_CZ"]

DATE_PRESET = os.environ.get("VIDEO_REPORT_DATE_PRESET", "last_90d")

# Ads belonging to a sales-objective campaign are excluded; everything else
# (awareness, traffic, engagement, video views, leads) counts as "non sales".
EXCLUDED_OBJECTIVES = {"OUTCOME_SALES"}


def fetch_campaigns(account_id: str) -> dict:
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/act_{account_id}/campaigns"
    params = {
        "access_token": META_ACCESS_TOKEN,
        "fields": "id,name,objective,effective_status",
        "limit": 500,
    }
    campaigns = {}
    while url:
        response = requests.get(url, params=params, timeout=30)
        if not response.ok:
            print(f"Meta API error fetching campaigns: {response.text}")
            response.raise_for_status()
        payload = response.json()
        for c in payload.get("data", []):
            campaigns[c["id"]] = c
        url = payload.get("paging", {}).get("next")
        params = {}
    return campaigns


def fetch_ad_insights(account_id: str, date_preset: str) -> list[dict]:
    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/act_{account_id}/insights"
    fields = (
        "ad_id,ad_name,adset_name,campaign_id,campaign_name,"
        "impressions,spend,clicks,inline_link_clicks,actions,"
        "video_p100_watched_actions,video_thruplay_watched_actions"
    )
    params = {
        "access_token": META_ACCESS_TOKEN,
        "level": "ad",
        "fields": fields,
        "date_preset": date_preset,
        "limit": 500,
    }
    rows = []
    while url:
        response = requests.get(url, params=params, timeout=30)
        if not response.ok:
            print(f"Meta API error fetching ad insights: {response.text}")
            response.raise_for_status()
        payload = response.json()
        rows.extend(payload.get("data", []))
        url = payload.get("paging", {}).get("next")
        params = {}
    return rows


def extract_value(items: list[dict], action_type: str) -> float:
    for item in items or []:
        if item.get("action_type") == action_type:
            return float(item.get("value", 0))
    return 0.0


def sum_values(items: list[dict]) -> float:
    return sum(float(i.get("value", 0)) for i in items or [])


def main():
    campaigns = fetch_campaigns(ACCOUNT_ID)
    non_sales_ids = {
        cid for cid, c in campaigns.items()
        if c.get("objective") not in EXCLUDED_OBJECTIVES
    }

    rows = fetch_ad_insights(ACCOUNT_ID, DATE_PRESET)

    video_ads = []
    for r in rows:
        campaign_id = r.get("campaign_id")
        if campaign_id not in non_sales_ids:
            continue

        impressions = int(r.get("impressions", 0))
        if impressions == 0:
            continue

        spend = float(r.get("spend", 0))
        actions = r.get("actions", [])
        video_views = extract_value(actions, "video_view")
        p100 = sum_values(r.get("video_p100_watched_actions", []))
        thruplay = sum_values(r.get("video_thruplay_watched_actions", []))

        if video_views == 0 and p100 == 0 and thruplay == 0:
            continue  # not a video ad

        post_engagement = extract_value(actions, "post_engagement")
        engagement = post_engagement or (
            extract_value(actions, "link_click")
            + extract_value(actions, "post_reaction")
            + extract_value(actions, "comment")
        )

        view_through = thruplay or p100
        video_ads.append({
            "ad_name": r.get("ad_name"),
            "adset_name": r.get("adset_name"),
            "campaign_name": r.get("campaign_name"),
            "objective": campaigns.get(campaign_id, {}).get("objective"),
            "impressions": impressions,
            "spend": round(spend, 2),
            "cpm": round(spend / impressions * 1000, 2),
            "video_views": video_views,
            "p100_completions": p100,
            "thruplays": thruplay,
            "view_through_rate_pct": round(view_through / impressions * 100, 2) if view_through else 0.0,
            "engagement": engagement,
            "engagement_rate_pct": round(engagement / impressions * 100, 3) if engagement else 0.0,
            "cost_per_thruplay": round(spend / thruplay, 3) if thruplay else None,
        })

    print(f"Found {len(video_ads)} non-sales video ads over {DATE_PRESET} for account {TARGET_ACCOUNT}")
    print(json.dumps(video_ads, indent=2, ensure_ascii=False))

    if not video_ads:
        return

    def top(key, reverse=True, filter_none=True):
        pool = [a for a in video_ads if a[key] is not None] if filter_none else video_ads
        return sorted(pool, key=lambda a: a[key], reverse=reverse)[:5]

    print("\n--- TOP 5 BY LOWEST CPM ---")
    for a in top("cpm", reverse=False):
        print(f"{a['ad_name']} | {a['campaign_name']} | CPM {a['cpm']} | impressions {a['impressions']}")

    print("\n--- TOP 5 BY VIEW-THROUGH RATE ---")
    for a in top("view_through_rate_pct"):
        print(f"{a['ad_name']} | {a['campaign_name']} | VTR {a['view_through_rate_pct']}% | thruplays {a['thruplays']} | p100 {a['p100_completions']}")

    print("\n--- TOP 5 BY IMPRESSIONS ---")
    for a in top("impressions"):
        print(f"{a['ad_name']} | {a['campaign_name']} | impressions {a['impressions']} | spend {a['spend']}")

    print("\n--- TOP 5 BY ENGAGEMENT RATE ---")
    for a in top("engagement_rate_pct"):
        print(f"{a['ad_name']} | {a['campaign_name']} | eng rate {a['engagement_rate_pct']}% | engagement {a['engagement']}")


if __name__ == "__main__":
    main()
