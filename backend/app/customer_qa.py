"""Deterministic customer answers grounded only in available records."""

from typing import Any


POLICY_TERMS = ("policy", "return", "refund", "exchange", "opening hours", "store hours",
                "delivery", "shipping", "退货", "退款", "换货", "营业时间", "配送", "店铺政策")
PROMOTION_TERMS = ("promotion", "promotions", "discount", "offer", "sale", "deal", "促销", "优惠", "折扣", "特价")
PRICE_TERMS = ("price", "cost", "how much", "多少钱", "价格")
STOCK_TERMS = ("stock", "available", "availability", "inventory", "in stock", "库存", "有货")


def answer_customer_question(question: str, products: list[dict[str, Any]],
                             promotions: list[dict[str, Any]]) -> dict[str, Any]:
    text = question.casefold()

    if any(term in text for term in POLICY_TERMS):
        return {
            "answer": "I can't confirm that policy because no store-policy information is configured. Please contact the store directly.",
            "evidence": [],
            "limitations": ["No store-policy records are available."],
        }

    product = next((item for item in products if item["name"].casefold() in text), None)
    if any(term in text for term in PROMOTION_TERMS):
        active = [item for item in promotions if not product or item.get("product_id") in (None, product["id"])]
        if not active:
            return {"answer": "There is no current promotion in the available store records.",
                    "evidence": [], "limitations": ["Only promotions saved in the store database can be reported."]}
        names = {item["id"]: item["name"] for item in products}
        facts = [f"{item['title']}" + (f" for {names[item['product_id']]}" if item.get("product_id") in names else "")
                 + (f" ({item['discount_percent']}% off)" if item.get("discount_percent") is not None else "")
                 for item in active]
        return {"answer": "Current promotion records: " + "; ".join(facts) + ".",
                "evidence": facts, "limitations": []}

    if not products:
        return {"answer": "I can't answer because no product records are available.",
                "evidence": [], "limitations": ["The product table is empty or unavailable."]}

    if product is None:
        facts = [f"{item['name']}: A${item['price']:.2f}, {item['stock']} units in stock."
                 for item in products]
        return {"answer": "Here is the product information currently available: " + " ".join(facts),
                "evidence": facts, "limitations": ["Only products in the current store records are listed."]}

    facts = [f"{product['name']} is listed at A${product['price']:.2f}.",
             f"{product['name']} has {product['stock']} units in stock.",
             f"{product['name']} is in the {product['category']} category."]
    if any(term in text for term in PRICE_TERMS):
        answer = facts[0]
        evidence = [facts[0]]
    elif any(term in text for term in STOCK_TERMS):
        answer = (f"{product['name']} is currently in stock ({product['stock']} units)."
                  if product["stock"] > 0 else f"{product['name']} is currently out of stock.")
        evidence = [facts[1]]
    else:
        answer = " ".join(facts)
        evidence = facts
    return {"answer": answer, "evidence": evidence,
            "limitations": ["Answers use the current store records and may not reflect live shelf changes."]}
