"""Small server-side Supabase REST adapter for the local prototype."""

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class SupabaseError(Exception):
    """A safe, user-facing Supabase connectivity or query error."""


def configured() -> bool:
    return bool(os.getenv("SUPABASE_URL", "").strip() and _api_key())


def _api_key() -> str:
    # The secret/service-role key must stay in this backend-only module.
    return (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or "").strip()


def _uses_legacy_bearer(key: str) -> bool:
    # Current opaque secret keys must be sent only as `apikey`; legacy JWT keys
    # still need the Authorization header used by PostgREST clients.
    return not key.startswith("sb_secret_")


def _request(table: str, *, method: str = "GET", query: dict[str, str] | None = None,
             payload: Any = None, prefer: str | None = None) -> Any:
    base_url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = _api_key()
    if not base_url or not key:
        raise SupabaseError("Supabase is not configured. Set SUPABASE_URL and a backend secret key.")
    url = f"{base_url}/rest/v1/{table}"
    if query:
        url += "?" + urlencode(query, safe=".*(),")
    headers = {"apikey": key, "Content-Type": "application/json"}
    if _uses_legacy_bearer(key):
        headers["Authorization"] = f"Bearer {key}"
    if prefer:
        headers["Prefer"] = prefer
    data = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8") if payload is not None else None
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=12) as response:
            body = response.read()
    except HTTPError as exc:
        # Do not echo request headers, URLs, or keys into application logs/UI.
        raise SupabaseError(f"Supabase returned HTTP {exc.code} for the {table} table. Check migrations and database permissions.") from None
    except (URLError, TimeoutError, OSError):
        raise SupabaseError("Could not reach Supabase. Check the project URL and network connection.") from None
    if not body:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SupabaseError("Supabase returned an unreadable response.") from None


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise TypeError(f"Unsupported value type: {type(value).__name__}")


def _rows(table: str, select: str, *, filters: dict[str, str] | None = None,
          order: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
    query = {"select": select, **(filters or {})}
    if order:
        query["order"] = order
    if limit:
        query["limit"] = str(limit)
    result = _request(table, query=query)
    if not isinstance(result, list):
        raise SupabaseError(f"Supabase returned an invalid list for the {table} table.")
    return result


def load_business_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    products = _rows("products", "id,name,category,price", order="name.asc")
    inventory = {row["product_id"]: int(row["quantity"]) for row in _rows("inventory_levels", "product_id,quantity")}
    since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    sales = _rows("sales_records", "product_id,sold_at,quantity", filters={"sold_at": f"gte.{since}"})
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)
    computed = []
    for product in products:
        current = previous = 0
        for sale in sales:
            if sale.get("product_id") != product["id"]:
                continue
            sold_at = datetime.fromisoformat(str(sale["sold_at"]).replace("Z", "+00:00"))
            if sold_at >= week_start:
                current += int(sale["quantity"])
            else:
                previous += int(sale["quantity"])
        computed.append({
            "id": product["id"], "name": product["name"], "category": product["category"],
            "price": float(product["price"]), "stock": inventory.get(product["id"], 0),
            "units_sold_7d": current, "units_sold_prev_7d": previous,
        })
    feedback = _rows("customer_feedback", "id,product_id,category,content,submitted_at", order="submitted_at.desc", limit=100)
    return computed, feedback


def load_active_promotions() -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc).isoformat()
    return _rows("promotions", "id,product_id,title,starts_at,ends_at,discount_percent",
                 filters={"starts_at": f"lte.{now}", "ends_at": f"gte.{now}"},
                 order="ends_at.asc", limit=50)


def create_feedback(record: dict[str, Any]) -> dict[str, Any]:
    rows = _request("customer_feedback", method="POST", payload={
        "product_id": record["product_id"], "category": record["category"], "content": record["content"],
    }, prefer="return=representation")
    if not isinstance(rows, list) or not rows:
        raise SupabaseError("Supabase did not confirm that the feedback was saved.")
    return rows[0]


def save_run(run: Any, *, audit_summary: str) -> None:
    _request("analysis_runs", method="POST", payload={
        "id": run.id, "question": run.question, "workflow": run.workflow, "status": run.status,
        "data_mode": run.data_mode, "created_at": run.created_at, "result": run.model_dump(mode="json"),
    })
    for agent in run.agents:
        _request("agent_results", method="POST", payload={
            "run_id": run.id, "agent_name": agent.agent, "status": agent.status,
            "result": agent.model_dump(mode="json"), "created_at": agent.completed_at,
        })
    for recommendation in run.recommendations:
        _request("recommendations", method="POST", payload={
            "id": recommendation.id, "run_id": run.id, "title": recommendation.title,
            "action": recommendation.action, "priority": recommendation.priority,
            "high_risk": recommendation.high_risk, "status": recommendation.status,
            "evidence": recommendation.evidence, "result": recommendation.model_dump(mode="json"),
        })
    write_audit("analysis_created", audit_summary, run_id=run.id)


def load_runs(limit: int = 100) -> list[dict[str, Any]]:
    rows = _rows("analysis_runs", "result", order="created_at.desc", limit=limit)
    return [row["result"] for row in rows if isinstance(row.get("result"), dict)]


def write_audit(event: str, summary: str, *, run_id: str | None = None,
                recommendation_id: str | None = None, feedback_id: str | None = None) -> None:
    details: dict[str, Any] = {"summary": summary}
    if recommendation_id:
        details["recommendation_id"] = recommendation_id
    if feedback_id:
        details["feedback_id"] = feedback_id
    _request("audit_logs", method="POST", payload={"run_id": run_id, "event": event, "details": details})


def load_audit(limit: int = 50) -> list[dict[str, Any]]:
    rows = _rows("audit_logs", "id,run_id,event,details,created_at", order="created_at.desc", limit=limit)
    return [{"id": row["id"], "run_id": row.get("run_id"), "event": row["event"],
             "recommendation_id": row.get("details", {}).get("recommendation_id"),
             "summary": row.get("details", {}).get("summary", row["event"]),
             "created_at": row["created_at"]} for row in rows]


def decide(recommendation_id: str, decision: str, note: str) -> tuple[dict[str, Any], str]:
    rows = _rows("recommendations", "id,run_id,status,high_risk,result", filters={"id": f"eq.{recommendation_id}"}, limit=1)
    if not rows:
        raise KeyError("Recommendation not found.")
    row = rows[0]
    recommendation = row.get("result") or {}
    if not row.get("high_risk") or row.get("status") != "pending_approval":
        raise ValueError("This recommendation is not awaiting a high-risk approval.")
    status = "approved" if decision == "approve" else "rejected"
    recommendation["status"] = status
    _request("recommendations", method="PATCH", query={"id": f"eq.{recommendation_id}"},
             payload={"status": status, "result": recommendation})
    _request("approval_decisions", method="POST", payload={
        "recommendation_id": recommendation_id, "decision": status, "note": note,
    })
    run_rows = _rows("analysis_runs", "id,result", filters={"id": f"eq.{row['run_id']}"}, limit=1)
    if run_rows and isinstance(run_rows[0].get("result"), dict):
        run_result = run_rows[0]["result"]
        for item in run_result.get("recommendations", []):
            if item.get("id") == recommendation_id:
                item["status"] = status
        _request("analysis_runs", method="PATCH", query={"id": f"eq.{row['run_id']}"}, payload={"result": run_result})
    write_audit(f"recommendation_{status}", note or f"Owner {status} recommendation",
                run_id=row["run_id"], recommendation_id=recommendation_id)
    return recommendation, row["run_id"]
