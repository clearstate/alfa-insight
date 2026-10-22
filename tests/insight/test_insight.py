from __future__ import annotations

import json

from services.insight.llm import LLMClient, LLMUnavailable, model_allowed
from services.insight.server import ApiError, App
from services.insight.settings import Settings
from services.insight.textkit import key_rate_values, rate_stance, significant_numbers

from .fixtures import find, svc, user


def _titles(company: str, role: str, n: int = 4) -> list[str]:
    return [c["news_title"] for c in svc().feed(user(), company, role)["cards"][:n]]


def test_all_bank_anchors_verified_against_page_text():
    st = svc().kb.stats()
    assert st["anchors_rejected"] == [], st["anchors_rejected"]
    assert st["anchors_ok"] >= 19


def test_forecast_conflicts_resolved_to_latest_with_history():
    k = svc().kb.indicator("key_rate_eoy", "2026")
    assert k["value"] == 14.0 and k["published_at"].startswith("2026-09-11")
    assert {s["value"] for s in k["superseded"]} == {13.5}
    assert svc().kb.indicator("usd_rub_eoy", "2027")["value"] == 93.0


def test_ranking_is_personalised_by_company():
    assert any("утилизацион" in t.lower() for t in _titles("U_25835", "cfo", 2))      # импортёр автозапчастей
    assert any("общепит" in t.lower() or "зарплат" in t.lower() for t in _titles("U_212593", "ceo", 2))   # ресторан
    assert any("Татарстан" in t or "Стройматериалы" in t for t in _titles("U_51606", "cfo", 2))            # строительство
    assert any("Аренда складов" in t for t in _titles("U_99802", "treasury", 2))                           # аренда недвижимости
    assert any("Макулатура" in t for t in _titles("U_150736", "ceo", 3))                                    # гофрокартон


def test_role_changes_ranking():
    a = [c["news_title"] for c in svc().feed(user(), "U_212593", "chief_accountant")["cards"][:6]]
    b = [c["news_title"] for c in svc().feed(user(), "U_212593", "treasury")["cards"][:6]]
    assert a != b


def test_prompt_injection_item_is_not_in_feed_and_blocked():
    it = find("Срочно: ставка по кредитам")
    assert it["injection"]
    assert it["id"] not in [c["id"] for c in svc().feed(user(), "U_25835", "cfo")["cards"]]
    ins = svc().insight(user(), "U_25835", "cfo", it["id"])
    assert ins["status"] == "blocked"


def test_rumor_is_labelled_unconfirmed_and_contradicts_bank():
    it = find("Инсайд")
    ins = svc().insight(user(), "U_25835", "cfo", it["id"])
    assert ins["headline"].startswith("Не подтверждено")
    assert all(k["status"] == "unconfirmed" for k in ins["what_happened"]["key_facts"])
    assert any("17" in n and "14,0" in n for n in ins["what_happened"]["status_notes"]), ins["what_happened"]["status_notes"]
    assert ins["confidence"] == "low"


def test_duplicate_publications_clustered_and_conflict_not_averaged():
    cl = [c for c in svc().kb.clusters.values() if len(c["members"]) > 1]
    assert cl and cl[0]["conflict"] and set(cl[0]["conflict"]["values"]) == {"8–12%", "10–15%"}
    cards = [c for c in svc().feed(user(), "U_25835", "cfo")["cards"] if "утилизацион" in c["news_title"].lower()]
    assert len(cards) == 1 and cards[0]["also_reported"] == 1


def test_every_insight_passes_self_checks():
    s, u = svc(), user()
    for cid in ("U_25835", "U_99802", "U_212593", "U_58207", "U_51606", "U_150736"):
        for role in ("ceo", "cfo", "chief_accountant", "treasury"):
            for c in s.feed(u, cid, role)["cards"]:
                ins = s.insight(u, cid, role, c["id"])
                bad = [x for x in ins["checks"]["items"] if x["status"] == "fail"]
                assert not bad, (cid, role, c["title"], bad)


def test_origin_labels_separate_bank_from_ai():
    ins = svc().insight(user(), "U_25835", "cfo", find("Ключевая ставка ЦБ РФ")["id"])
    assert ins["bank_view"]["has_position"]
    for b in ins["bank_view"]["items"]:
        assert b["origin"] in ("bank_view", "bank_data") and b["page"]
    for f in ins["consequences"]["risks"]:
        assert f["origin"] == "ai"
    assert "не является инвестиционной рекомендацией" in ins["disclaimer"]
    assert ins["trace"]["steps"] and any(s["kind"] == "check" for s in ins["trace"]["steps"])


def test_unseen_news_goes_through_pipeline_and_is_ranked():
    s, u = svc(), user()
    r = s.ingest(u, "Минпромторг ввёл временный запрет на ввоз автозапчастей из ряда стран. Импортёры автокомпонентов и оптовые торговцы запчастями готовятся к росту цен и срыву поставок.", "Запрет на ввоз запчастей")
    assert r["outcome"] == "created" and "auto_market" in r["item"]["topics"]
    ranked = s.feed(u, "U_25835", "cfo")["cards"]
    assert any(c["id"] == r["item"]["id"] for c in ranked[:5])
    ins = s.insight(u, "U_25835", "cfo", r["item"]["id"])
    assert ins["checks"]["passed"] and ins["consequences"]["risks"]


def test_irrelevant_news_gets_low_relevance_and_general_conclusion():
    s, u = svc(), user()
    ins = s.insight(u, "U_212593", "ceo", find("Минсельхоз")["id"])
    assert ins["relevance"]["relevance"] < 40


def test_qa_grounded_and_no_answer_path():
    s, u = svc(), user()
    a = s.ask(u, "U_25835", "cfo", "Что банк ждёт по ставке на 2027 год?", None)
    assert "12,0" in a["answer"] and a["origin"] == "bank_view" and a["refs"][0]["page"]
    b = s.ask(u, "U_25835", "cfo", "Расскажи про квантовые компьютеры и рецепт борща", None)
    assert "нет" in b["answer"].lower()


def test_access_control_and_auth():
    s = svc()
    app = App(s)
    tok = app.issue("u_cfo_demo")
    h = {"Authorization": "Bearer " + tok}
    assert app.handle("GET", "/api/feed", {"company": ["U_25835"]}, {}, h)[0] == 200
    try:
        app.handle("GET", "/api/feed", {"company": ["U_99802"]}, {}, h)
        assert False, "ожидали 403"
    except Exception as e:  # AccessDenied обрабатывается на уровне HTTP-хендлера
        assert e.__class__.__name__ == "AccessDenied"
    try:
        app.handle("GET", "/api/me", {}, {}, {})
        assert False
    except ApiError as e:
        assert e.status == 401
    try:
        app.handle("GET", "/api/me", {}, {}, {"Authorization": "Bearer abc.def"})
        assert False
    except ApiError as e:
        assert e.status == 401


# ---------------------------------------------------------------- LLM (заглушка шлюза)
def _llm(reply):
    s = Settings()
    s.llm_base_url, s.llm_api_key = "http://stub", "k"
    calls = []

    def transport(model, messages, max_tokens, temperature):
        calls.append(model)
        if isinstance(reply, Exception):
            raise reply
        return {"choices": [{"message": {"content": reply(messages)}}], "usage": {"total_tokens": 321}}
    return LLMClient(s, transport), calls


def test_llm_allowed_models_only():
    assert model_allowed("GLM-5.3-Flash") and model_allowed("qwen3.6-35b-a3b") and not model_allowed("gpt-4o")
    s = Settings()
    s.llm_base_url, s.llm_api_key, s.llm_model_reason = "http://stub", "k", "gpt-4o"
    try:
        LLMClient(s, lambda *a: {})
        assert False
    except ValueError:
        pass


def test_llm_rewrite_accepts_grounded_and_rejects_hallucinated_numbers():
    from services.insight.agent import InsightAgent
    base = svc()
    good = lambda m: json.dumps({"summary": "Ставка остаётся 14,0%; нагрузка по кредитам не снизится.", "findings": [{"index": 0, "text": "Ставка 14,0% сохранится до конца 2026 г. — проценты по кредитам не снизятся."},
                                                                                                      {"index": 1, "text": "Рост ставки до 25% разорит компанию."}]})
    llm, calls = _llm(good)
    ag = InsightAgent(base.kb, base.dir, base.ranker, llm, base.s)
    ins = ag.run("U_25835", "cfo", find("Ключевая ставка ЦБ РФ")["id"], use_llm=True)
    assert calls and ins["mode"] == "llm"
    texts = [f["text"] for f in ins["consequences"]["risks"]]
    assert any("сохранится до конца 2026" in t for t in texts) and not any("25%" in t for t in texts)
    assert llm.calls["rejected"] >= 1 and ins["checks"]["passed"]


def test_llm_failure_falls_back_to_rules():
    from services.insight.agent import InsightAgent
    base = svc()
    llm, _ = _llm(LLMUnavailable("down"))
    ag = InsightAgent(base.kb, base.dir, base.ranker, llm, base.s)
    ins = ag.run("U_25835", "cfo", find("Ключевая ставка ЦБ РФ")["id"], use_llm=True, force=True)
    assert ins["mode"] == "rules" and any(s["status"] == "fallback" for s in ins["trace"]["steps"])


def test_text_utils():
    assert rate_stance("ЦБ сохранил ключевую ставку на уровне 14%") == "hold"
    assert rate_stance("Ставки по лизингу выросли") is None
    assert key_rate_values("арендные ставки выросли на 9%") == []
    assert significant_numbers("курс 13,2 и 2026 год, 23 октября") == [13.2]


def test_bank_source_has_pdf_and_page_text():
    s = svc()
    it = find("Ключевая ставка ЦБ РФ")
    d = s.source(it["id"], 1)
    assert d["text"] and d["kind"] == "bank"
    assert d.get("pdf_url", "").startswith("/files/") and "#page=1" in d["pdf_url"]
