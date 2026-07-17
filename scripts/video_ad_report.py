import os
import re
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

# Below this video-view/impression ratio, treat the row as a banner/static
# asset (video fields present but effectively unwatched), not a real video ad.
MIN_VIDEO_VIEW_RATIO = 0.05

EXCLUDE_NAME_PATTERN = re.compile(r"\bSK\b")


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

        ad_name = r.get("ad_name") or ""
        adset_name = r.get("adset_name") or ""
        campaign_name = r.get("campaign_name") or ""
        if any(EXCLUDE_NAME_PATTERN.search(n) for n in (ad_name, adset_name, campaign_name)):
            continue

        spend = float(r.get("spend", 0))
        actions = r.get("actions", [])
        video_views = extract_value(actions, "video_view")
        p100 = sum_values(r.get("video_p100_watched_actions", []))
        thruplay = sum_values(r.get("video_thruplay_watched_actions", []))

        if video_views == 0 and p100 == 0 and thruplay == 0:
            continue  # not a video ad
        if video_views / impressions < MIN_VIDEO_VIEW_RATIO:
            continue  # video field present but effectively unwatched -> banner/static asset

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

    print(f"Found {len(video_ads)} real (non-banner, non-SK, non-sales) video ad rows over {DATE_PRESET} for account {TARGET_ACCOUNT}")
    print(json.dumps(video_ads, indent=2, ensure_ascii=False))

    if not video_ads:
        return

    # Same ad_name = same creative running in multiple adsets. Combine raw
    # counts before recomputing rates, rather than averaging pre-computed
    # per-adset rates.
    creatives = {}
    for a in video_ads:
        c = creatives.setdefault(a["ad_name"], {
            "ad_name": a["ad_name"],
            "campaigns": set(),
            "adsets": set(),
            "impressions": 0,
            "spend": 0.0,
            "video_views": 0.0,
            "p100_completions": 0.0,
            "thruplays": 0.0,
            "engagement": 0.0,
        })
        c["campaigns"].add(a["campaign_name"])
        c["adsets"].add(a["adset_name"])
        c["impressions"] += a["impressions"]
        c["spend"] += a["spend"]
        c["video_views"] += a["video_views"]
        c["p100_completions"] += a["p100_completions"]
        c["thruplays"] += a["thruplays"]
        c["engagement"] += a["engagement"]

    combined = []
    for c in creatives.values():
        impressions = c["impressions"]
        spend = c["spend"]
        view_through = c["thruplays"] or c["p100_completions"]
        combined.append({
            "ad_name": c["ad_name"],
            "campaigns": ", ".join(sorted(c["campaigns"])),
            "adset_count": len(c["adsets"]),
            "impressions": impressions,
            "spend": round(spend, 2),
            "cpm": round(spend / impressions * 1000, 2),
            "video_views": c["video_views"],
            "p100_completions": c["p100_completions"],
            "thruplays": c["thruplays"],
            "view_through_rate_pct": round(view_through / impressions * 100, 2) if view_through else 0.0,
            "engagement": c["engagement"],
            "engagement_rate_pct": round(c["engagement"] / impressions * 100, 3) if c["engagement"] else 0.0,
            "cost_per_thruplay": round(spend / c["thruplays"], 3) if c["thruplays"] else None,
        })

    print(f"\nCombined into {len(combined)} distinct creatives")
    print(json.dumps(combined, indent=2, ensure_ascii=False))

    # Composite score: average rank across CPM (lower better), view-through
    # rate, impressions, and engagement rate (all higher better). Lower score
    # wins.
    def ranks(key, reverse):
        ordered = sorted(combined, key=lambda a: a[key], reverse=reverse)
        return {id(a): i for i, a in enumerate(ordered)}

    cpm_ranks = ranks("cpm", reverse=False)
    vtr_ranks = ranks("view_through_rate_pct", reverse=True)
    impr_ranks = ranks("impressions", reverse=True)
    eng_ranks = ranks("engagement_rate_pct", reverse=True)

    for a in combined:
        a["composite_rank_score"] = (
            cpm_ranks[id(a)] + vtr_ranks[id(a)] + impr_ranks[id(a)] + eng_ranks[id(a)]
        ) / 4

    top10 = sorted(combined, key=lambda a: a["composite_rank_score"])[:10]

    print("\n--- TOP 10 NON-SALES VIDEO CREATIVES, COMBINED ACROSS ADSETS (composite of CPM, view-through rate, impressions, engagement rate) ---")
    for i, a in enumerate(top10, 1):
        print(
            f"{i}. {a['ad_name']} | {a['campaigns']} ({a['adset_count']} adsets) | "
            f"CPM {a['cpm']} | VTR {a['view_through_rate_pct']}% | "
            f"impressions {a['impressions']} | eng rate {a['engagement_rate_pct']}% | "
            f"spend {a['spend']} | cost/thruplay {a['cost_per_thruplay']}"
        )


if __name__ == "__main__":
    main()
