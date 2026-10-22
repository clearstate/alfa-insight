"""Агент подготовки персонализированного инсайта: план → инструменты → единый контекст → анализ → синтез → самопроверка → адаптация.

Один агент с набором инструментов (разделение на несколько агентов не требуется: шаги зависят от общего контекста).
Планировщик выбирает шаги по теме события и признакам компании; каждый вызов инструмента попадает в трассировку.
Режимы синтеза: «rules» (детерминированно) и «llm» (переписывание текстов, если настроен шлюз); проверка общая.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

import yaml

from . import SCHEMA_VERSION
from .evidence import EvidenceBook
from .lenses import Ctx, Finding, PRODUCT_RU, SEV_ORDER, run_lenses
from .llm import LLMClient, LLMUnavailable, SYSTEM_REWRITE
from .settings import Settings
from .textkit import (key_rate_values, numbers, ru_date, ru_num, short, significant_numbers, topics_ru)

log = logging.getLogger("insight.agent")
DISCLAIMER = ("Материал носит информационно-аналитический характер и не является инвестиционной рекомендацией или офертой. "
              "Сценарии и выводы AI — оценка на основе данных и не отражают официальную позицию банка, если не помечены как позиция Альфа-Банка.")
TOOLS_ALLOWED = ("get_company_profile", "get_news_item", "get_cluster", "get_bank_positions", "get_indicators", "match_supply_chain",
                 "get_related_companies", "cross_check_numbers", "search_bank_corpus", "get_product_catalog")


class Trace:
    def __init__(self) -> None:
        self.steps: list[dict] = []

    def add(self, kind: str, name: str, summary: str, *, args: dict | None = None, ms: float = 0.0, status: str = "ok", evidence: int | None = None) -> None:
        self.steps.append({"n": len(self.steps) + 1, "kind": kind, "name": name, "summary": summary, "args": args or {}, "ms": round(ms, 1), "status": status,
                           "evidence_added": evidence})


class InsightAgent:
    def __init__(self, kb, directory, ranker, llm: LLMClient, settings: Settings):
        self.kb, self.dir, self.ranker, self.llm, self.s = kb, directory, ranker, llm, settings
        self.products = yaml.safe_load((__import__("pathlib").Path(__file__).parent / "config" / "products.yaml").read_text(encoding="utf-8"))["products"]
        self.cache: dict[tuple, dict] = {}
        self.audit: list[dict] = []

    # ------------------------------------------------------------------ инструменты (только чтение)
    def _tool(self, tr: Trace, name: str, fn, args: dict, summarize) -> Any:
        assert name in TOOLS_ALLOWED, f"инструмент {name} не разрешён"
        t0 = time.time()
        try:
            res = fn()
        except Exception as exc:  # noqa: BLE001
            tr.add("tool", name, f"ошибка: {exc}", args=args, ms=(time.time() - t0) * 1000, status="error")
            raise
        tr.add("tool", name, summarize(res), args=args, ms=(time.time() - t0) * 1000)
        return res

    # ------------------------------------------------------------------ основной сценарий
    def run(self, company_id: str, role: str, item_id: str, *, user_id: str | None = None, force: bool = False, use_llm: bool = True) -> dict:
        use_llm = bool(use_llm and self.llm.available)
        key = (company_id, role, item_id, self.kb.version, "llm" if use_llm else "rules")
        if key in self.cache and not force:
            return self.cache[key]
        tr = Trace()
        t_start = time.time()
        item = self.kb.get(item_id)
        if item is None:
            raise KeyError(item_id)
        if item.get("injection"):
            out = self._blocked(company_id, role, item, tr)
            self.cache[key] = out
            return out
        ev = EvidenceBook()
        profile = self._tool(tr, "get_company_profile", lambda: self.dir.profile(company_id), {"company": "client"},
                             lambda p: f"ОКВЭД {p['industry']['okved_code']['value']}, регион {p['geography']['region']['value']}, признаков: {len(p['sensitivity_factors'])}")
        role_info = self.dir.role_info(role)
        score = self.ranker.score(item, profile, role_info)
        topics = dict(item.get("topic_scores") or {})
        plan = self._plan(item, profile, score)
        tr.add("plan", "plan", "; ".join(f"{i + 1}) {s['tool']} — {s['why']}" for i, s in enumerate(plan)), args={"steps": [s["tool"] for s in plan]})
        # --- выполнение плана с общим контекстом
        supply, related, cluster = [], None, None
        for st in plan:
            if st["tool"] == "match_supply_chain":
                supply = self._tool(tr, "match_supply_chain", lambda: self.dir.supply_matches(item["industries"]["okved_prefixes"], profile),
                                    {"okved_prefixes": item["industries"]["okved_prefixes"]},
                                    lambda r: f"совпадений: {len(r)}" + (f"; крупнейшее — ОКВЭД {r[0]['okved_code']} ({r[0]['direction']}, {r[0]['share_of_known']:.0%})" if r else ""))
            elif st["tool"] == "get_cluster":
                cluster = self._tool(tr, "get_cluster", lambda: self.kb.clusters.get(item.get("cluster_id")), {"cluster": item.get("cluster_id")},
                                     lambda r: f"публикаций в кластере: {len(r['members']) if r else 1}" + ("; расхождение оценок" if r and r.get("conflict") else ""))
            elif st["tool"] == "get_related_companies":
                related = self._tool(tr, "get_related_companies", lambda: self.dir.related(company_id, 20), {"limit": 20},
                                     lambda r: f"связанных компаний: {r.get('total')}")
        ctx = Ctx(self.kb, self.dir, company_id, role, item, profile, ev, topics, supply)
        facts = self._what_happened(item, profile, ev, ctx)
        tr.add("analysis", "extract_facts", f"ключевых фактов: {len(facts['key_facts'])}; статус: {facts['reliability']}", evidence=len(ev.items))
        findings = self._tool(tr, "get_indicators", lambda: run_lenses(ctx), {"topics": list(topics)[:6]},
                              lambda r: f"линз сработало: {len({f.lens.split(':')[0] for f in r})}; выводов: {len(r)}")
        tr.add("analysis", "context", f"в едином контексте: {len(ev.items)} доказательств, использовано позиций банка: {len({a['id'] for a in ctx.used_anchors})}", evidence=len(ev.items))
        cross = self._tool(tr, "cross_check_numbers", lambda: self._cross_check(item, ctx, ev), {},
                           lambda r: ("расхождение с позицией банка: " + r["statement"]) if r else "расхождений с прогнозами банка не найдено")
        insight = self._compose(item, profile, role, role_info, score, facts, findings, ctx, ev, cross, cluster, related)
        # --- синтез (LLM опционально) и самопроверка с адаптацией
        insight["mode"] = "rules"
        if use_llm:
            self._llm_rewrite(insight, findings, ev, item, profile, tr)
        for attempt in range(3):
            checks = self.verify(insight, ev, item, profile)
            failed = [c for c in checks if c["status"] == "fail"]
            tr.add("check", "verify", f"проверок: {len(checks)}, не пройдено: {len(failed)}" + (f" ({', '.join(c['code'] for c in failed)})" if failed else ""), status="ok" if not failed else "warn")
            if not failed or attempt == 2:
                break
            self._adapt(insight, failed, ctx, ev, item, tr)
        insight["checks"] = {"passed": all(c["status"] != "fail" for c in checks), "items": checks}
        insight.pop("_adapted", None)
        insight.pop("_findings", None)
        insight["evidence"] = ev.items
        insight["id"] = f"ins_{uuid.uuid4().hex[:12]}"
        insight["trace"] = {"id": insight["id"], "steps": tr.steps, "total_ms": round((time.time() - t_start) * 1000, 1),
                            "llm": self.llm.status() if self.llm.available else {"configured": False}}
        self.audit.append({"user": user_id, "company": company_id, "item": item_id, "role": role, "mode": insight["mode"], "ms": insight["trace"]["total_ms"]})
        self.cache[key] = insight
        return insight

    # ------------------------------------------------------------------ планировщик
    def _plan(self, item: dict, profile: dict, score) -> list[dict]:
        steps = [{"tool": "get_company_profile", "why": "контекст компании: отрасль, регион, признаки чувствительности"}]
        steps.append({"tool": "get_cluster", "why": "проверить другие публикации о событии и расхождения оценок"})
        if item["industries"]["okved_prefixes"]:
            steps.append({"tool": "match_supply_chain", "why": "в событии названы отрасли — сопоставить с отраслями контрагентов по платежам"})
        if (profile.get("group") or {}).get("size", 1) > 1:
            steps.append({"tool": "get_related_companies", "why": "компания входит в группу — событие может быть значимо для других участников"})
        steps.append({"tool": "get_bank_positions", "why": "найти позиции и прогнозы банка по темам: " + ", ".join(list(item.get("topic_scores") or {})[:4])})
        steps.append({"tool": "get_indicators", "why": "рассчитать влияние по линзам (ставка, курс, ФОТ, спрос, отрасль) с прогнозами банка"})
        steps.append({"tool": "cross_check_numbers", "why": "сверить цифры события с актуальными прогнозами банка"})
        return steps

    # ------------------------------------------------------------------ факты
    def _what_happened(self, item: dict, profile: dict, ev: EvidenceBook, ctx: Ctx) -> dict:
        unconf = bool(item.get("unconfirmed"))
        prof_topics = {t["topic"] for t in profile["topics"]}
        cands = []
        for kf in item.get("key_facts") or []:
            tp = set(kf.get("topics") or [])
            cands.append((len(tp & prof_topics) + (0.5 if kf.get("claim_type") == "fact" else 0), kf))
        cands.sort(key=lambda x: -x[0])
        facts, seen = [], set()
        ordered = ([kf for _, kf in cands[:3]] if item["kind"] == "bank" else (item.get("key_facts") or [])[:3]) or []
        for kf in ordered:
            t = kf["text"]
            if t in seen:
                continue
            seen.add(t)
            page = (kf.get("span") or {}).get("page") or (kf.get("provenance") or {}).get("page")
            claim_unknown = kf.get("claim_type") == "unknown" or unconf
            if item["kind"] == "bank":
                eid = ev.bank_fact(item, t, page, "fact")
            else:
                eid = ev.news(item, t, key_suffix=t[:40], unconfirmed=claim_unknown)
            facts.append({"text": short(t, 360), "evidence": [eid], "status": "unconfirmed" if claim_unknown else "confirmed"})
            ctx.facts.append(eid)
        if not facts:
            eid = ev.news(item, item.get("summary") or item["title"], key_suffix="summary", unconfirmed=unconf)
            facts.append({"text": short(item.get("summary") or item["title"], 360), "evidence": [eid], "status": "unconfirmed" if unconf else "confirmed"})
            ctx.facts.append(eid)
        return {"summary": short(item.get("summary") or item["title"], 420), "key_facts": facts,
                "publisher": item.get("display_source"), "published_at": item.get("published_at"), "title": item["title"],
                "kind": item["kind"], "synthetic": item.get("synthetic", False), "page": None,
                "reliability": "слух / не подтверждено" if unconf else ("материал банка" if item["kind"] == "bank" else "сообщение издания" + (" (синтетическое, демо)" if item.get("synthetic") else "")),
                "status_notes": []}

    def _cross_check(self, item: dict, ctx: Ctx, ev: EvidenceBook) -> dict | None:
        mentioned = key_rate_values(item["title"] + ". " + item["text"]) if item["kind"] == "news" else []
        kr, e = ctx.ind("key_rate_eoy", "2026")
        if not mentioned or not kr:
            return None
        far = [v for v in mentioned if abs(v - kr["value"]) > 0.3]
        if not far:
            return None
        return {"mentioned": far[0], "bank": kr["value"], "evidence": [e], "statement":
                f"в сообщении названа ставка {ru_num(far[0], 0, strip=True)}%, а позиция банка (от {ru_date(kr['published_at'])}) — {ru_num(kr['value'])}% до конца 2026 г."}

    # ------------------------------------------------------------------ сборка инсайта
    def _compose(self, item, profile, role, role_info, score, facts, findings: list[Finding], ctx: Ctx, ev: EvidenceBook, cross, cluster, related) -> dict:
        topics = list((item.get("topic_scores") or {}).keys())
        anchors_used = {a["id"]: a for a in self.kb.anchors_for(topics, 3)}
        for a in ctx.used_anchors:
            anchors_used.setdefault(a["id"], a)
        bank_items = []
        for a in list(anchors_used.values())[:5]:
            eid = ev.anchor(a)
            bank_items.append({"statement": a["summary"], "kind": a["kind"], "origin": "bank_view" if a["claim_type"] == "bank_view" else "bank_data", "evidence": [eid],
                               "quote": a["quote"], "doc_title": a["doc_title"], "page": a["page"], "published_at": a["published_at"], "item_id": a["item_id"]})
        if item["kind"] == "bank":
            for v in sorted(item.get("bank_views") or [], key=lambda x: -len(set(x.get("topics") or []) & {t["topic"] for t in profile["topics"]}))[:2]:
                if all(v["text"][:60] not in b["quote"] for b in bank_items):
                    eid = ev.bank_fact(item, v["text"], v.get("page"), "bank_view")
                    bank_items.append({"statement": short(v["text"], 260), "kind": v.get("kind"), "origin": "bank_view", "evidence": [eid], "quote": short(v["text"], 420),
                                       "doc_title": item.get("doc_title"), "page": v.get("page"), "published_at": item.get("published_at"), "item_id": item["id"]})
        inds = []
        seen = set()
        for e in ev.items:
            if e["kind"] == "indicator" and e["id"] not in seen:
                seen.add(e["id"])
                s = e["source"]
                i = self.kb.indicator(s["indicator"], s["period"])
                inds.append({"indicator": s["indicator"], "label": i["label"], "period": s["period"], "value": i["value"], "unit": i.get("unit"), "published_at": i["published_at"],
                             "page": i.get("page"), "doc_title": i.get("doc_title"), "item_id": i["item_id"], "evidence": [e["id"]],
                             "superseded": i.get("superseded", [])})
        notes = []
        if cluster and len(cluster["members"]) > 1:
            others = [self.kb.items[m]["display_source"] for m in cluster["members"] if m != item["id"]]
            notes.append(f"О событии сообщили ещё {len(others)} издание(й); дубли объединены в одну карточку.")
            if cluster.get("conflict"):
                notes.append(cluster["conflict"]["note"])
        if item.get("stale"):
            notes.append("Материал устарел (старше года): не использовать как текущую позицию.")
        if item.get("unconfirmed"):
            notes.append("Сообщение не подтверждено официальными источниками: это не факт, а предположение.")
        if cross:
            notes.append("Расхождение с позицией банка: " + cross["statement"] + ".")
        facts["status_notes"] = notes
        # почему важно: связь с компанией
        why = self._why(item, profile, score, ctx, ev)
        risks = [self._fmt_finding(f, i) for i, f in enumerate(findings) if f.direction in ("risk", "mixed")]
        opps = [self._fmt_finding(f, i) for i, f in enumerate(findings) if f.direction in ("opportunity", "mixed")]
        neutral = [self._fmt_finding(f, i) for i, f in enumerate(findings) if f.direction == "neutral"]
        top = next((f for f in findings if f.company_specific), findings[0] if findings else None)
        typ = "event"
        if top:
            typ = "risk" if top.direction in ("risk",) else "opportunity" if top.direction == "opportunity" else "event"
            if top.direction == "mixed":
                typ = "risk" if top.severity == "high" else "event"
        headline = (("Не подтверждено: " if item.get("unconfirmed") else "") + (top.title if top else item["title"]))
        sev = top.severity if top else "low"
        conf = "low" if (item.get("unconfirmed") or (top and top.hypothesis)) else (top.confidence if top else "low")
        actions = self._actions(findings, topics)
        offer = self._offer(findings)
        gaps = self._gaps(profile, findings)
        if not bank_items:
            gaps.append("В доступных материалах банка нет позиции по этой теме: выводы сформированы AI на основе данных компании и события.")
        summary = self._summary(item, top, bank_items, cross)
        return {
            "schema_version": SCHEMA_VERSION, "company_id": ctx.company_id, "role": role, "role_title": role_info.get("title"),
            "news_item_id": item["id"], "cluster_id": item.get("cluster_id"), "status": "ok", "type": typ, "severity": sev, "confidence": conf, "headline": headline,
            "summary": summary, "relevance": score.as_dict(),
            "what_happened": facts, "why_it_matters": why,
            "consequences": {"risks": risks, "opportunities": opps, "notes": neutral, "scenarios": [s for f in findings for s in f.scenarios][:4]},
            "bank_view": {"has_position": bool(bank_items), "items": bank_items, "indicators": inds,
                          "note": None if bank_items else "Позиции банка по теме в доступных материалах нет."},
            "actions": actions, "offer": offer, "questions": self._questions(topics, findings), "data_gaps": gaps,
            "metric": self._metric(top, ctx), "disclaimer": DISCLAIMER, "created_at": self.s.as_of,
            "_findings": findings,
        }

    def _fmt_finding(self, f: Finding, i: int) -> dict:
        return {"index": i, "lens": f.lens, "title": f.title, "text": f.text, "severity": f.severity, "confidence": f.confidence, "horizon": f.horizon,
                "direction": f.direction, "hypothesis": f.hypothesis, "origin": "ai", "method": "rules", "evidence": f.evidence, "features": f.features}

    def _why(self, item, profile, score, ctx: Ctx, ev: EvidenceBook) -> list[dict]:
        out = []
        for comp in score.components:
            if comp.code == "bank_doc":
                continue
            eids = []
            txt = ""
            if comp.code == "industry":
                txt = f"Событие напрямую касается вашей отрасли: основной ОКВЭД компании — {ctx.okved} ({short(profile['industry']['okved_name']['value'], 90)})."
                eids = [ev.company_fact("okved", f"ОКВЭД {ctx.okved}: {profile['industry']['okved_name']['value']}", {"field": "MAINOKVED_CODE", "source_file": profile["industry"]["okved_code"]["source_file"], "row": profile["industry"]["okved_code"]["source_row_id"]})]
            elif comp.code == "topic":
                srcs = [f for f in ctx.factors.values() if f["level"] not in ("none",) and set(f.get("topics") or []) & set(ctx.topics)]
                txt = "Темы события совпадают с чувствительными для компании признаками: " + (", ".join(f"{f['code']} ({f['level']})" for f in srcs[:3]) or "отраслевые темы профиля") + "."
                eids = [ev.company(f["code"], f) for f in srcs[:3]]
            elif comp.code == "supply_chain":
                txt = f"Событие касается отрасли контрагентов: {comp.detail}."
                f = ctx.factors.get("supply_chain_industries")
                eids = [ev.company("supply_chain_industries", f)] if f else []
            elif comp.code == "region":
                txt = f"Событие связано с регионом компании — {ctx.region}."
                eids = [ev.company_fact("region", f"Регион компании: {ctx.region}", {"field": "REGION", "source_file": profile["geography"]["region"]["source_file"], "row": profile["geography"]["region"]["source_row_id"]})]
            elif comp.code == "country":
                txt = f"В событии упомянуты страны внешней торговли компании ({comp.detail.replace('страны: ', '')})."
                f = ctx.factors.get("fx_and_trade_exposure")
                eids = [ev.company("fx_and_trade_exposure", f)] if f else []
            elif comp.code == "role":
                txt = f"Тема входит в приоритеты роли «{ctx.dir.role_info(ctx.role)['title']}»: {topics_ru(comp.detail.split(': ', 1)[-1].split(', '))}."
                eids = [ev.company_fact("role:" + ctx.role, f"Приоритетные темы роли: {topics_ru(ctx.dir.role_info(ctx.role)['priority_topics'])}", {"config": "roles.yaml", "role": ctx.role})]
            elif comp.code == "group":
                txt = f"Событие затрагивает другую компанию вашей группы: {comp.detail}."
                eids = [ev.company_fact("group", "Состав группы компаний (GROUP_ID)", {"field": "GROUP_ID"})]
            if txt:
                out.append({"statement": txt, "origin": "company_data" if comp.code in ("industry", "region") else "rule", "evidence": eids, "component": comp.code, "strength": round(comp.value, 2)})
        return out

    def _actions(self, findings: list[Finding], topics: list[str]) -> list[dict]:
        out, seen = [], set()
        for f in findings:
            for a in f.actions:
                if a["title"] in seen or f.severity == "low" and a["kind"] == "product":
                    continue
                seen.add(a["title"])
                out.append({**a, "severity": f.severity, "origin": "ai"})
        if any(t in topics for t in ("key_rate", "bond_market", "deposit_rates")):
            out.append({"title": "Отследить заседание Банка России 23 октября", "text": "Банк ожидает паузы; в случае иного решения пересмотреть расчёты по ставке.", "kind": "monitor", "product": None, "severity": "low", "origin": "ai"})
        out.sort(key=lambda a: (-SEV_ORDER.get(a.get("severity", "low"), 1), a["kind"] == "product"))
        return out[:5]

    def _offer(self, findings: list[Finding]) -> dict | None:
        for f in findings:
            if f.severity == "low" or not f.company_specific:
                continue
            for tag in f.tags:
                for p in self.products:
                    if tag in p["for"]:
                        return {"id": p["id"], "title": p["title"], "text": p["text"], "sponsored": True, "label": "Предложение банка — не аналитика"}
        return None

    def _gaps(self, profile: dict, findings: list[Finding]) -> list[str]:
        used = {f.lens.split(":")[0] for f in findings}
        out = []
        for g in profile["data_gaps"]:
            if g["code"] == "trade_direction_unknown" and "fx" in used or g["code"] == "revenue_unit_unknown" or g["code"] == "no_dates":
                out.append(g["message"])
        if "rate" in used:
            out.append("Объём и тип ставки по долгу компании в данных банка неизвестны.")
        return out

    def _questions(self, topics: list[str], findings: list[Finding]) -> list[str]:
        q = ["Какие платежи и контрагенты влияют?", "Как снизить риск?", "Показать расчёт релевантности"]
        if any(t in topics for t in ("key_rate", "credit_conditions", "bond_market")):
            q.append("Что банк ждёт по ставке на 2027 год?")
        if any(t in topics for t in ("fx_rates", "foreign_trade")):
            q.append("Какой прогноз банка по курсу?")
        return q[:4]

    def _metric(self, top: Finding | None, ctx: Ctx) -> dict | None:
        mapping = {"rate": ("key_rate_eoy", "2026", "%", "прогноз банка на конец 2026 г."), "deposit": ("key_rate_eoy", "2026", "%", "прогноз банка на конец 2026 г."),
                   "fx": ("usd_rub_eoy", "2026", " ₽/$", "прогноз банка на конец 2026 г."), "payroll": ("wages_nominal", "2026", "%", "рост зарплат, прогноз банка 2026"),
                   "demand": ("retail_turnover", "2026", "%", "рост розницы, прогноз банка 2026"), "macro": ("gdp_growth", "2026", "%", "рост ВВП, прогноз банка 2026")}
        if top and top.lens.split(":")[0] in mapping:
            code, per, unit, label = mapping[top.lens.split(":")[0]]
            i = self.kb.indicator(code, per)
            if i:
                return {"value": f"{ru_num(i['value'], 1)}{unit}", "label": label}
        return None

    def _summary(self, item, top: Finding | None, bank_items, cross) -> str:
        parts = []
        if top:
            parts.append(short(top.text.split(". ")[0] + ".", 260))
        if bank_items:
            b = bank_items[0]
            parts.append(("Позиция банка: " if b["origin"] == "bank_view" else "Данные банка: ") + b["statement"])
        if cross:
            parts.append("Внимание: " + cross["statement"] + ".")
        return " ".join(parts)

    # ------------------------------------------------------------------ LLM-переписывание (опционально)
    def _llm_rewrite(self, insight: dict, findings: list[Finding], ev: EvidenceBook, item: dict, profile: dict, tr: Trace) -> None:
        import json
        pack = {"company": self.dir.prompt_view(profile), "role": insight["role_title"], "headline": insight["headline"],
                "evidence": [{"id": e["id"], "origin": e["origin"], "text": e["text"]} for e in ev.items],
                "findings": [{"index": i, "title": f.title, "draft": f.text, "evidence": f.evidence, "hypothesis": f.hypothesis} for i, f in enumerate(findings[:6])]}
        user = "Контекст в JSON. Новость передана внутри <document>.\n<document>" + short(item["title"] + ". " + item["text"], 1500) + "</document>\n" + json.dumps(pack, ensure_ascii=False)
        t0 = time.time()
        try:
            raw = self.llm.chat("reason", SYSTEM_REWRITE, user, max_tokens=1400)
            data = self.llm.parse_json(raw)
            if not data:
                raise LLMUnavailable("ответ не JSON")
        except LLMUnavailable as exc:
            tr.add("synthesis", "llm_rewrite", f"LLM недоступен, остаёмся в режиме правил: {exc}", ms=(time.time() - t0) * 1000, status="fallback")
            return
        allowed_item = set(numbers(item["title"] + " " + item["text"]))
        applied = 0
        for fx in data.get("findings", []):
            try:
                idx, txt = int(fx["index"]), str(fx["text"])
            except (KeyError, ValueError, TypeError):
                continue
            if idx >= len(findings):
                continue
            allowed = ev.all_numbers() | allowed_item | set(numbers(findings[idx].text))
            bad = [n for n in significant_numbers(txt) if n not in allowed]
            claims_bank = re.search(r"банк\w*\s+(ожида|прогнозир|полага|считает)", txt.lower())
            has_bank = any((ev.get(e) or {}).get("origin") in ("bank_view", "bank_data") for e in findings[idx].evidence)
            if bad or (claims_bank and not has_bank):
                self.llm.calls["rejected"] += 1
                continue
            for lst in ("risks", "opportunities", "notes"):
                for r in insight["consequences"][lst]:
                    if r["index"] == idx:
                        r["text"], r["method"] = txt, "llm"
            applied += 1
        if data.get("summary") and not [n for n in significant_numbers(str(data["summary"])) if n not in (ev.all_numbers() | allowed_item)]:
            insight["summary"] = str(data["summary"])
        insight["mode"] = "llm" if applied else "rules"
        tr.add("synthesis", "llm_rewrite", f"принято переписанных выводов: {applied} из {len(data.get('findings', []))}", ms=(time.time() - t0) * 1000)

    # ------------------------------------------------------------------ самопроверка
    def verify(self, ins: dict, ev: EvidenceBook, item: dict, profile: dict) -> list[dict]:
        ids = {e["id"] for e in ev.items}
        checks: list[dict] = []

        def add(code: str, ok: bool, detail: str, warn: bool = False) -> None:
            checks.append({"code": code, "status": "pass" if ok else ("warn" if warn else "fail"), "detail": detail})

        all_f = ins["consequences"]["risks"] + ins["consequences"]["opportunities"] + ins["consequences"]["notes"]
        missing = [e for f in all_f for e in f["evidence"] if e not in ids]
        add("evidence_exist", not missing, "все ссылки на доказательства существуют" if not missing else f"нет доказательств: {missing}")
        add("grounded", all(f["evidence"] for f in all_f), "каждый вывод связан с источником" if all(f["evidence"] for f in all_f) else "есть выводы без источников")
        allowed = ev.all_numbers() | set(numbers(item["title"] + " " + item["text"])) | set(numbers(str(profile["size"]["workers_fns"]["value"] or "")))
        badnums = []
        for f in all_f:
            clean = re.sub(r"(ОКВЭД\s*|входит в\s*)[\d.]+", " ", f["text"])      # коды ОКВЭД — не «числа» вывода
            for n in significant_numbers(clean):
                if n not in allowed:
                    badnums.append((f["index"], n))
        add("numbers_grounded", not badnums, "числа в выводах найдены в источниках" if not badnums else f"числа без источника: {badnums[:3]}")
        bank_no_page = [e["id"] for e in ev.items if e["kind"] in ("bank", "indicator") and not (e["source"] or {}).get("page")]
        add("bank_page_refs", not bank_no_page, "каждая позиция банка имеет страницу первоисточника" if not bank_no_page else f"нет страницы: {bank_no_page}")
        bad_label = []
        for f in all_f:
            if re.search(r"банк\w*\s+(ожида|прогнозир|полага|считает)", f["text"].lower()) and not any((ev.get(e) or {}).get("origin") in ("bank_view", "bank_data") for e in f["evidence"]):
                bad_label.append(f["index"])
        add("bank_attribution", not bad_label, "позиции банка приписаны только при наличии источника" if not bad_label else f"приписана позиция банка без источника: {bad_label}")
        spec = any(not f["hypothesis"] for f in all_f) or any(f.get("lens") not in ("macro", "generic") for f in all_f)
        if "coverage" in ins.get("_adapted", set()) and not spec:
            add("coverage", False, "после расширения поиска прямая связь с компанией не найдена: вывод общий, уверенность низкая", warn=True)
        else:
            add("coverage", bool(all_f) and spec, "есть вывод, привязанный к признакам компании" if spec else "вывод общий — связь с компанией не найдена")
        unconf_bad = item.get("unconfirmed") and any(k["status"] == "confirmed" for k in ins["what_happened"]["key_facts"])
        add("rumor_not_fact", not unconf_bad, "неподтверждённые сведения не поданы как факт" if not unconf_bad else "слух отмечен как факт")
        sup = [i for i in ins["bank_view"]["indicators"] if i["superseded"]]
        add("forecast_versions", True, ("использованы актуальные версии прогнозов; заменённые значения показаны: " + ", ".join(i["label"] for i in sup)) if sup else "конфликтов версий прогнозов нет")
        add("source_fresh", not item.get("stale"), "источник актуален" if not item.get("stale") else "источник устарел", warn=True)
        add("injection_clean", not item.get("injection"), "признаков prompt-injection нет")
        return checks

    def _adapt(self, ins: dict, failed: list[dict], ctx: Ctx, ev: EvidenceBook, item: dict, tr: Trace) -> None:
        for fc in failed:
            code = fc["code"]
            if code == "numbers_grounded":
                for lst in ("risks", "opportunities", "notes"):
                    for r in ins["consequences"][lst]:
                        orig = next((f for f in ins["_findings"] if f.title == r["title"]), None)
                        if orig and r["text"] != orig.text and r.get("method") == "llm":
                            r["text"], r["method"] = orig.text, "rules"
                tr.add("adapt", "revert_to_template", "тексты с непроверяемыми числами заменены шаблонными")
            elif code in ("evidence_exist", "grounded"):
                ids = {e["id"] for e in ev.items}
                for lst in ("risks", "opportunities", "notes"):
                    for r in ins["consequences"][lst]:
                        r["evidence"] = [e for e in r["evidence"] if e in ids] or ctx.news_ev()
                tr.add("adapt", "repair_evidence", "ссылки на доказательства исправлены")
            elif code == "coverage":
                hits = self._tool(tr, "search_bank_corpus", lambda: self.kb.search(item["title"] + " " + ctx.pv["industry"]["okved_name"], 3, kinds={"bank"}),
                                  {"query": "title + okved"}, lambda r: f"найдено фрагментов: {len(r)}")
                for h in hits[:2]:
                    ch = self.kb.chunks.get(h["id"])
                    if ch:
                        eid = ev.bank_chunk(ch, self.kb.items[h["item_id"]])
                        ins["bank_view"]["items"].append({"statement": short(ch["text"], 240), "kind": "assessment", "origin": "bank_view" if ch.get("claim_type") == "bank_view" else "bank_data",
                                                          "evidence": [eid], "quote": short(ch["text"], 420), "doc_title": self.kb.items[h["item_id"]].get("doc_title"), "page": ch.get("page"),
                                                          "published_at": self.kb.items[h["item_id"]].get("published_at"), "item_id": h["item_id"]})
                ins.setdefault("_adapted", set()).add("coverage")
                ins["confidence"] = "low"
                ins["data_gaps"].append("Прямую связь события с признаками компании установить не удалось: вывод общий, уверенность низкая.")
                tr.add("adapt", "broaden_search", "расширен поиск по материалам банка, уверенность снижена до «низкой»")
                for c in ins.get("checks", {}).get("items", []):
                    pass
            elif code == "bank_attribution":
                for lst in ("risks", "opportunities", "notes"):
                    for r in ins["consequences"][lst]:
                        if r["index"] in [int(x) for x in re.findall(r"\d+", fc["detail"])]:
                            orig = next((f for f in ins["_findings"] if f.title == r["title"]), None)
                            if orig:
                                r["text"], r["method"] = orig.text, "rules"
                tr.add("adapt", "revert_to_template", "убрана неподтверждённая атрибуция позиции банка")

    def _blocked(self, company_id: str, role: str, item: dict, tr: Trace) -> dict:
        tr.add("check", "injection_guard", "в тексте обнаружены инструкции для модели (prompt injection): материал не используется для анализа", status="blocked")
        return {"schema_version": SCHEMA_VERSION, "id": f"ins_{uuid.uuid4().hex[:12]}", "status": "blocked", "company_id": company_id, "role": role, "news_item_id": item["id"],
                "headline": "Материал заблокирован проверкой безопасности", "type": "event", "severity": "low", "confidence": "low",
                "summary": "В тексте обнаружены инструкции для AI-модели. Материал не анализируется и не попадает в ленту.", "evidence": [], "trace": {"steps": tr.steps},
                "checks": {"passed": False, "items": [{"code": "injection_clean", "status": "fail", "detail": "prompt_injection_suspected"}]}, "disclaimer": DISCLAIMER}
