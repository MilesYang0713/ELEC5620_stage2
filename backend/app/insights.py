"""Transparent, deterministic retail indicators used by the prototype dashboard."""

from collections import Counter
from typing import Any


THEMES = {
    "availability": ("out of stock", "stock", "available", "shelf", "缺货", "库存"),
    "value": ("price", "value", "expensive", "discount", "价格", "优惠"),
    "quality": ("quality", "flavour", "broken", "damaged", "质量", "口味"),
    "service": ("service", "staff", "delivery", "店员", "服务", "配送"),
}
POSITIVE_TERMS = ("love", "great", "good", "helpful", "excellent", "喜欢", "很好")
NEGATIVE_TERMS = ("out of stock", "complaint", "bad", "poor", "small", "expensive", "缺货", "投诉", "不好")


def product_indicators(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return explainable metrics without implying a forecast or supplier recommendation."""
    indicators = []
    for product in products:
        current = int(product.get("units_sold_7d", 0))
        previous = int(product.get("units_sold_prev_7d", 0))
        stock = int(product.get("stock", 0))
        velocity = current / 7
        change_percent = round((current - previous) / max(previous, 1) * 100, 1)
        cover_days = round(stock / velocity, 1) if velocity else None
        risk = "normal"
        if stock == 0 or (cover_days is not None and cover_days < 4):
            risk = "stock_out"
        elif current < previous or (cover_days is not None and cover_days > 90):
            risk = "overstock_or_decline"
        indicators.append({
            "product_id": product["id"], "product_name": product["name"],
            "weekly_change_percent": change_percent, "estimated_cover_days": cover_days,
            "latest_week_revenue": round(current * float(product["price"]), 2), "risk": risk,
        })
    return indicators


def feedback_insights(feedback_records: list[dict[str, Any]]) -> dict[str, Any]:
    themes: Counter[str] = Counter()
    sentiment: Counter[str] = Counter()
    for feedback in feedback_records:
        text = str(feedback.get("content", "")).casefold()
        matched = [theme for theme, terms in THEMES.items() if any(term in text for term in terms)]
        themes.update(matched or ["other"])
        if any(term in text for term in NEGATIVE_TERMS):
            sentiment["negative"] += 1
        elif any(term in text for term in POSITIVE_TERMS):
            sentiment["positive"] += 1
        else:
            sentiment["neutral"] += 1
    return {"theme_counts": dict(themes), "sentiment_counts": dict(sentiment), "record_count": len(feedback_records)}
