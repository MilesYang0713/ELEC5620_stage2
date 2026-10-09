from datetime import date, timedelta

DATA_MODE = "demo"
PRODUCTS = [
    {"id": "P-001", "name": "Harbour Blend Coffee", "category": "Pantry", "price": 18.5, "stock": 12, "units_sold_7d": 21, "units_sold_prev_7d": 34},
    {"id": "P-002", "name": "Coastal Oat Biscuits", "category": "Pantry", "price": 8.0, "stock": 86, "units_sold_7d": 5, "units_sold_prev_7d": 7},
    {"id": "P-003", "name": "Wattle Hand Balm", "category": "Wellness", "price": 14.0, "stock": 9, "units_sold_7d": 27, "units_sold_prev_7d": 12},
]
FEEDBACK = [
    {"id": "F-001", "product_id": "P-001", "category": "product", "content": "Love the flavour, but it was out of stock twice this month.", "submitted_at": date.today() - timedelta(days=2)},
    {"id": "F-002", "product_id": "P-002", "category": "product", "content": "The pack size feels small for the price.", "submitted_at": date.today() - timedelta(days=5)},
]
