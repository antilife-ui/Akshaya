"""AI Space: deterministic, template-based assistant over the computed inventory data."""
from __future__ import annotations

import uuid

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import now_ist, to_ist_iso
from app.database import new_id
from app.errors import ApiError
from app.models import ChatMessage
from app.services import intents as I
from app.services.analytics import active_materials
from app.services.intents import Intent
from app.services.pipeline import forecast_data, get_as_of, get_series, latest_forecast
from app.services.recommendations import all_items


def _db_now():
    return now_ist().replace(tzinfo=None)


def _core_data(it: dict) -> dict:
    return {
        "current_stock": it["current_stock"], "average_daily_demand": it["average_daily_demand"],
        "forecasted_demand_next_30_days": it["forecasted_demand_next_30_days"],
        "days_of_cover": it["days_of_cover"], "predicted_depletion_date": it["predicted_depletion_date"],
        "recommended_order_quantity": it["recommended_order_quantity"], "stock_status": it["stock_status"],
    }


def _pack(targets: list[dict], per_item) -> dict:
    """Flat data for one material, keyed by material_id when several are answered."""
    if len(targets) == 1:
        return per_item(targets[0])
    return {t["material_id"]: per_item(t) for t in targets}


def _consumption(db: Session, it: dict, days: int, as_of) -> dict:
    s = get_series(db, it["material_id"], as_of)["quantity"]
    cur = s.tail(days)
    prev = s.iloc[-2 * days : -days] if len(s) >= 2 * days else None
    out = {
        "period_days": days, "total_consumption": round(float(cur.sum()), 2),
        "average_daily_consumption": round(float(cur.mean()), 2) if len(cur) else 0.0,
        "peak_date": cur.idxmax().date().isoformat() if len(cur) else None,
        "peak_quantity": round(float(cur.max()), 2) if len(cur) else 0.0,
        "change_vs_previous_period_pct": None,
    }
    if prev is not None and prev.sum() > 0:
        out["change_vs_previous_period_pct"] = round((cur.sum() / prev.sum() - 1) * 100, 1)
    return out


def _period_label(days: int) -> str:
    if days % 365 == 0:
        k = days // 365
        return f"{k} year{'s' if k > 1 else ''}"
    if days % 30 == 0 and days >= 30:
        k = days // 30
        return f"{k} month{'s' if k > 1 else ''}"
    return f"{days} days"


def respond(db: Session, message: str) -> dict:
    items = all_items(db)
    by_id = {i["material_id"]: i for i in items}
    mats = [(m.material_id, m.name) for m in active_materials(db)]
    name_of = dict(mats)
    mentioned = I.find_materials(message, mats)
    intent = I.detect_intent(message, bool(mentioned))
    targets = [by_id[m] for m in mentioned if m in by_id]
    missing = [name_of[m] for m in mentioned if m not in by_id]
    note = (" I don't have consumption data for " + ", ".join(missing) + " yet.") if missing else ""
    first_name = (targets[0]["material_name"] if targets else None) or (items[0]["material_name"] if items else None)

    def done(answer, data=None, ids=None):
        ids = ids if ids is not None else [t["material_id"] for t in targets]
        return {
            "answer": answer + note, "material_id": ids[0] if ids else None, "material_ids": ids,
            "intent": intent.value, "data_used": data or {}, "suggestions": I.suggestions_for(first_name),
        }

    if intent == Intent.GENERAL_HELP:
        return done(I.HELP_TEXT, ids=[])
    if not items:
        return done(I.NO_DATA_TEXT, ids=[])
    if mentioned and not targets:  # asked about materials that have no data
        return done("I can't answer that yet.", ids=[])

    if intent == Intent.CRITICAL_MATERIALS:
        if targets:
            return done(" ".join(I.answer_status(t) for t in targets), _pack(targets, _core_data))
        top = items[0]
        if top["stock_status"] not in I.NEEDS_ACTION:
            return done(
                f"No material is currently at risk. {top['material_name']} has the lowest cover at "
                f"{I.n(top['days_of_cover'])} days.", _core_data(top), [top["material_id"]],
            )
        text = I.answer_critical(top)
        others = [i for i in items[1:] if i["stock_status"] in I.NEEDS_ACTION][:3]
        if others:
            text += " Also at risk: " + "; ".join(
                f"{o['material_name']} ({I.n(o['days_of_cover'])} days of cover)" for o in others
            ) + "."
        ids = [top["material_id"]] + [o["material_id"] for o in others]
        return done(text, {i: _core_data(by_id[i]) for i in ids} if len(ids) > 1 else _core_data(top), ids)

    if intent == Intent.MATERIAL_DEPLETION:
        ts = targets or [items[0]]  # no material named -> the most critical one
        return done(" ".join(I.answer_depletion(t) for t in ts), _pack(ts, _core_data), [t["material_id"] for t in ts])

    if intent == Intent.REORDER_RECOMMENDATION:
        if targets:
            return done(" ".join(I.answer_reorder(t) for t in targets), _pack(targets, _core_data))
        need = [i for i in items if i["stock_status"] in I.NEEDS_ACTION]
        if need:
            text = "Materials to reorder: " + "; ".join(
                f"{i['material_name']} - {I.n(i['recommended_order_quantity'])} {i['unit']} "
                f"({I.n(i['days_of_cover'])} days of cover)" for i in need
            ) + "."
            return done(text, {i["material_id"]: _core_data(i) for i in need}, [i["material_id"] for i in need])
        nxt = items[0]
        return done(
            f"No material needs reordering right now. The closest to its reorder point is {nxt['material_name']} "
            f"({I.n(nxt['current_stock'])} {nxt['unit']} vs reorder point {I.n(nxt['reorder_point'])}).",
            {}, [],
        )

    if intent == Intent.MATERIAL_FORECAST:
        h = I.parse_horizon(message, 30)
        ts = targets or items
        parts, data = [], {}
        for t in ts:
            row = latest_forecast(db, t["material_id"])
            if row is None:
                continue
            fd = forecast_data(row)
            total = float(np.sum(fd.predicted[:h]))
            parts.append(I.answer_forecast(t, min(h, len(fd.predicted)), total))
            data[t["material_id"]] = {
                "horizon_days": h, "forecasted_demand": round(total, 2), "average_daily_demand": round(total / h, 2),
                "model_name": fd.model_name,
            }
        if not parts:
            return done("No forecast is available yet. Upload data first.", ids=[])
        ids = list(data)
        return done(" ".join(parts), data[ids[0]] if len(ids) == 1 else data, ids)

    if intent == Intent.INVENTORY_STATUS:
        ts = targets or items
        if targets:
            return done(" ".join(I.answer_status(t) for t in ts), _pack(ts, _core_data))
        lines = [
            f"{t['material_name']}: {I.n(t['current_stock'])} {t['unit']} ({I.n(t['days_of_cover'])} days, "
            f"{t['stock_status'].replace('_', ' ').lower()})" for t in ts
        ]
        return done("Current inventory - " + "; ".join(lines) + ".", {t["material_id"]: _core_data(t) for t in ts},
                    [t["material_id"] for t in ts])

    # CONSUMPTION_ANALYSIS
    as_of = get_as_of(db)
    if targets:
        days = I.parse_days(message, 180)
        parts, data = [], {}
        for t in targets:
            c = _consumption(db, t, days, as_of)
            data[t["material_id"]] = c
            s = (
                f"Over the last {_period_label(days)}, {t['material_name']} consumption was "
                f"{I.n(c['total_consumption'])} {t['unit']} (average {I.n(c['average_daily_consumption'])} "
                f"{t['unit']}/day), peaking on {c['peak_date']} at {I.n(c['peak_quantity'])} {t['unit']}."
            )
            if c["change_vs_previous_period_pct"] is not None:
                ch = c["change_vs_previous_period_pct"]
                s += f" That is {'up' if ch >= 0 else 'down'} {abs(ch):.1f}% versus the previous period."
            parts.append(s)
        ids = list(data)
        return done(" ".join(parts), data[ids[0]] if len(ids) == 1 else data, ids)
    days = I.parse_days(message, 30)
    ranked = sorted(((_consumption(db, i, days, as_of), i) for i in items), key=lambda p: -p[0]["total_consumption"])
    top, topi = ranked[0]
    rest = ", ".join(f"{i['material_name']} ({I.n(c['total_consumption'])})" for c, i in ranked[1:3])
    text = (
        f"Over the last {_period_label(days)}, {topi['material_name']} was consumed the most at "
        f"{I.n(top['total_consumption'])} {topi['unit']}" + (f", followed by {rest}." if rest else ".")
    )
    return done(text, {i["material_id"]: c for c, i in ranked}, [topi["material_id"]])


def chat(db: Session, session_id: str | None, message: str) -> dict:
    sid = session_id or f"SES-{uuid.uuid4().hex[:8].upper()}"
    result = respond(db, message)
    db.add(ChatMessage(message_id=new_id("MSG"), session_id=sid, role="user", message=message, created_at=_db_now()))
    db.add(ChatMessage(message_id=new_id("MSG"), session_id=sid, role="assistant", message=result["answer"],
                       created_at=_db_now()))
    db.commit()
    return {"session_id": sid, **result}


def history(db: Session, session_id: str) -> dict:
    rows = db.scalars(
        select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at, ChatMessage.role.desc())
    ).all()
    if not rows:
        raise ApiError(404, f"Chat session '{session_id}' not found")
    return {
        "session_id": session_id,
        "messages": [
            {"message_id": r.message_id, "role": r.role, "message": r.message, "created_at": to_ist_iso(r.created_at)}
            for r in rows
        ],
    }
