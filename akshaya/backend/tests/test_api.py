"""End-to-end API tests (need fastapi, sqlalchemy, statsmodels installed)."""
from datetime import date, timedelta


def _csv(days=120, extra=""):
    end = date.today() - timedelta(days=1)
    lines = ["material_name,date,quantity_consumed,current_stock,lead_time_days,unit"]
    for i in range(days):
        d = (end - timedelta(days=days - 1 - i)).isoformat()
        q = 800 + (i % 7) * 20
        lines.append(f"Iron Ore,{d},{q},4000,7,tonne")
    return ("\n".join(lines) + "\n" + extra).encode()


def _upload(client, content, name="t.csv"):
    return client.post("/api/v1/upload/csv", files={"file": (name, content, "text/csv")})


def test_health_and_default_materials(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"
    assert len(client.get("/api/v1/materials").json()) == 5


def test_upload_flow_and_duplicate_handling(client):
    r = _upload(client, _csv(extra="Iron Ore,bad-date,5,,,\nScrap,2026-01-01,-1,,,\n"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["valid_rows"] == 120 and body["invalid_rows"] == 2 and body["forecasts_generated"] == 1
    assert {e["row"] for e in body["errors"]} == {122, 123}
    assert client.get(f"/api/v1/upload/{body['upload_id']}").json()["status"] == "COMPLETED"
    assert len(client.get("/api/v1/upload/history").json()) == 1
    # identical re-upload -> 409
    assert _upload(client, _csv()).status_code == 409
    # in-file duplicate row is skipped, not stored twice
    dup = _csv(days=30) + b"Limestone,2026-01-05,100,,,\nLimestone,2026-01-05,100,,,\n"
    r = _upload(client, dup).json()
    assert r["duplicate_rows"] >= 1


def test_upload_validation_errors(client):
    assert _upload(client, b"a,b\n1,2\n").status_code == 400
    assert _upload(client, _csv(), name="data.txt").status_code == 400
    assert _upload(client, b"material_name,date,quantity_consumed\nX,nope,1\n").status_code == 400


def test_new_material_autocreated_and_stock_updated(client):
    _upload(client, _csv(days=40, extra=""))
    names = {m["name"] for m in client.get("/api/v1/materials").json()}
    assert "Iron Ore" in names
    m = client.get("/api/v1/materials/MAT-IRON-ORE").json()
    assert m["current_stock"] == 4000 and m["lead_time_days"] == 7


def test_sample_template(client):
    r = client.get("/api/v1/upload/sample-template")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert len(r.text.strip().splitlines()) == 6


def test_chart_endpoints(seeded):
    c = seeded
    assert len(c.get("/api/v1/analytics/materials").json()) == 5
    d6 = c.get("/api/v1/analytics/consumption", params={"material_id": "MAT-IRON-ORE", "period": "6M"}).json()
    d12 = c.get("/api/v1/analytics/consumption", params={"material_id": "MAT-IRON-ORE", "period": "12M"}).json()
    assert len(d6["data"]) == 180 and len(d12["data"]) == 365 and d6["unit"] == "tonne"
    assert abs(d6["total_consumption"] / 180 - d6["average_daily_consumption"]) < 0.1
    allm = c.get("/api/v1/analytics/consumption", params={"period": "12M", "granularity": "monthly"}).json()
    assert len(allm["materials"]) == 5 and len(allm["stacked"]) >= 12
    f = c.get("/api/v1/analytics/forecast", params={"material_id": "MAT-IRON-ORE", "horizon": 180}).json()
    assert len(f["forecast"]) == 180 and f["forecast"][0]["lower_bound"] >= 0
    s = c.get("/api/v1/analytics/summary").json()
    assert s["highest_consumption"]["material_id"] == "MAT-IRON-ORE" and s["strongest_upward_trend"] and s["most_volatile"]
    assert c.get("/api/v1/analytics/consumption", params={"period": "3M"}).status_code == 400
    assert c.get("/api/v1/analytics/forecast", params={"material_id": "NOPE"}).status_code == 404


def test_recommendations_endpoint(seeded):
    r = seeded.get("/api/v1/recommendations").json()
    assert r["summary"]["total_materials"] == 5
    assert "MAT-IRON-ORE" in [m["material_id"] for m in r["critical_materials"]]
    assert r["overstocked_materials"] and r["healthy_materials"]
    one = seeded.get("/api/v1/recommendations/MAT-IRON-ORE").json()
    assert one["recommended_order_quantity"] > 0 and one["stock_status"] == "CRITICAL_STOCKOUT_RISK"
    assert seeded.post("/api/v1/recommendations/refresh").status_code == 200


def test_ai_chat_depletion_answer_and_history(seeded):
    r = seeded.post("/api/v1/ai/chat", json={"message": "How long will Iron Ore last?"}).json()
    assert r["intent"] == "depletion_prediction" and r["material_id"] == "MAT-IRON-ORE"
    assert "Iron Ore is expected to last approximately" in r["answer"] and r["data_used"]["current_stock"] == 4300
    h = seeded.get(f"/api/v1/ai/chat/{r['session_id']}").json()
    assert [m["role"] for m in h["messages"]] == ["user", "assistant"]
    r2 = seeded.post("/api/v1/ai/chat", json={"session_id": r["session_id"], "message": "Which materials are at risk?"}).json()
    assert r2["intent"] == "critical_materials" and "Iron Ore" in r2["answer"]
    assert seeded.get("/api/v1/ai/chat/SES-NOPE").status_code == 404


def test_forecast_inventory_and_simulation(seeded):
    assert seeded.get("/api/v1/forecast/MAT-SCRAP/accuracy").json()["validation_mae"] is not None
    assert seeded.post("/api/v1/forecast/retrain/MAT-LIMESTONE").status_code == 200
    inv = seeded.get("/api/v1/inventory/MAT-IRON-ORE").json()
    assert len(inv["stock_projection"]) == 90
    assert seeded.post("/api/v1/inventory/MAT-IRON-ORE/recalculate", json={"service_level": 0.99}).status_code == 200
    assert seeded.post("/api/v1/inventory/MAT-IRON-ORE/recalculate", json={"service_level": 0.5}).status_code == 400
    before = seeded.get("/api/v1/materials/MAT-DOLOMITE").json()["current_stock"]
    seeded.post("/api/v1/simulation/receive-delivery", json={"material_id": "MAT-DOLOMITE", "quantity": 100})
    assert seeded.get("/api/v1/materials/MAT-DOLOMITE").json()["current_stock"] == before + 100
    assert seeded.post("/api/v1/simulation/run-day", json={}).status_code == 200
    assert seeded.post("/api/v1/simulation/seed", json={}).status_code == 400  # needs confirm
