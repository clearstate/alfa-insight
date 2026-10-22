"""Фасад сервиса: лента, инсайты, контекст компании, аналитика банка, вопросы, ввод новой новости."""
from __future__ import annotations

import logging
from datetime import datetime

from services.company_profile.access import AccessDenied
from services.company_profile.service import CompanyNotFound, CompanyQuarantined

from .agent import DISCLAIMER, InsightAgent
from .kb import KnowledgeBase
from .llm import LLMClient
from .people import Directory
from .qa import Answerer
from .ranking import Ranker
from .runtime import Journal
from .settings import Settings, load_settings
from .textkit import ru_date, ru_date_short, ru_num, short

log = logging.getLogger("insight.service")
TYPE_LABEL = {"risk": "Требует внимания", "opportunity": "Возможность", "event": "Событие"}
CONF_LABEL = {"high": "Высокая уверенность", "medium": "Средняя уверенность", "low": "Низкая уверенность"}
FACTOR_TITLES = {"rate_sensitivity": "Чувствительность к ставке", "deposit_income": "Доход от размещения средств", "fx_and_trade_exposure": "Валюта и внешняя торговля",
                 "payroll_exposure": "Фонд оплаты труда", "consumer_exposure": "Зависимость от потребительского спроса", "counterparty_concentration": "Концентрация контрагентов",
                 "supply_chain_industries": "Отрасли поставщиков и покупателей"}
LEVEL_RU = {"high": "высокая", "medium": "средняя", "low": "низкая", "none": "нет", "info": "справочно"}


class InsightService:
    def __init__(self, settings: Settings | None = None, llm: LLMClient | None = None):
        self.s = settings or load_settings()
        self.kb = KnowledgeBase(self.s)
        self.boot = self.kb.bootstrap()
        self.dir = Directory(self.s)
        self.ranker = Ranker(self.dir, self.kb)
        self.llm = llm or LLMClient(self.s)
        self.agent = InsightAgent(self.kb, self.dir, self.ranker, self.llm, self.s)
        self.qa = Answerer(self.kb, self.dir, self.ranker, self.agent, self.llm)
        self.journal = Journal(self.s.runtime_dir)

    # ---- доступ
    def check(self, user, company_id: str, role: str | None) -> str:
        self.dir.authorize(user, company_id)
        r = role or user.role
        if r not in self.dir.roles:
            r = user.role
        return r

    # ---- лента
    def feed(self, user, company_id: str, role: str | None, tab: str = "all", limit: int = 14, min_rel: int = 30) -> dict:
        role = self.check(user, company_id, role)
        profile = self.dir.profile(company_id)
        ranked = self.ranker.rank(profile, self.dir.role_info(role))
        cards, seen_clusters, hidden = [], {}, 0
        for item, sc in ranked:
            if sc.excluded:
                continue
            if sc.relevance < min_rel:
                hidden += 1
                continue
            cid = item.get("cluster_id")
            if cid in seen_clusters:
                seen_clusters[cid]["also_reported"] += 1
                continue
            ins = self.agent.run(company_id, role, item["id"], user_id=user.user_id, use_llm=False)
            card = self._card(item, sc, ins)
            seen_clusters[cid] = card
            cards.append(card)
        for c in cards:
            c["final"] = round((0.8 * c["relevance"] + 0.2 * {"high": 100, "medium": 65, "low": 35}[c["severity"]]) * (0.88 if c["is_bank"] else 1.0), 1)
        cards.sort(key=lambda c: -c["final"])
        keep_bank, tmp = 0, []
        for c in cards:                 # аналитика банка заметна, но не вытесняет события: не более 4 материалов в ленте
            if c["is_bank"]:
                keep_bank += 1
                if keep_bank > 4:
                    continue
            tmp.append(c)
        cards = tmp
        counts = {"all": len(cards), "risk": sum(c["type"] == "risk" for c in cards), "opportunity": sum(c["type"] == "opportunity" for c in cards),
                  "event": sum(c["type"] == "event" and not c["is_bank"] for c in cards), "bank": sum(c["is_bank"] for c in cards)}
        if tab == "bank":
            cards = [c for c in cards if c["is_bank"]]
        elif tab in ("risk", "opportunity", "event"):
            cards = [c for c in cards if c["type"] == tab and (tab != "event" or not c["is_bank"])]
        self.journal.audit(user.user_id, "feed", company=company_id, role=role, tab=tab, shown=len(cards[:limit]))
        return {"company_id": company_id, "role": role, "as_of": self.s.as_of, "as_of_ru": ru_date(self.s.as_of), "counts": counts, "cards": cards[:limit], "hidden_low_relevance": hidden,
                "updated": self.s.as_of, "disclaimer": DISCLAIMER}

    def _card(self, item: dict, sc, ins: dict) -> dict:
        title, text = item.get("doc_title") or item["title"], short(ins["summary"], 260)
        return {"id": item["id"], "type": ins["type"], "label": TYPE_LABEL[ins["type"]], "severity": ins["severity"], "title": title, "headline": ins["headline"],
                "text": text, "metric": ins.get("metric"), "confidence": ins["confidence"], "confidence_label": CONF_LABEL[ins["confidence"]],
                "relevance": sc.relevance, "published_at": item.get("published_at"), "time": ru_date_short(item.get("published_at")),
                "source": item.get("display_source"), "news_title": item["title"], "is_bank": item["kind"] == "bank", "synthetic": item.get("synthetic", False),
                "unconfirmed": item.get("unconfirmed", False), "has_bank_view": ins["bank_view"]["has_position"], "also_reported": 0,
                "why": [w["statement"] for w in ins["why_it_matters"][:2]], "checks_passed": ins["checks"]["passed"]}

    def insight(self, user, company_id: str, role: str | None, item_id: str) -> dict:
        role = self.check(user, company_id, role)
        ins = self.agent.run(company_id, role, item_id, user_id=user.user_id)
        self.journal.audit(user.user_id, "insight", company=company_id, role=role, item=item_id, mode=ins.get("mode"))
        out = dict(ins)
        out["news_source"] = self.kb.page_text(item_id, None) and {k: v for k, v in self.kb.page_text(item_id, None).items() if k != "text"}
        return out

    def ask(self, user, company_id: str, role: str | None, question: str, item_id: str | None) -> dict:
        role = self.check(user, company_id, role)
        res = self.qa.ask(company_id, role, question[:500], item_id)
        self.journal.write("questions", {"user": user.user_id, "company": company_id, "item": item_id, "len": len(question)})
        return res

    # ---- контекст компании и аналитика
    def context(self, user, company_id: str, role: str | None) -> dict:
        role = self.check(user, company_id, role)
        p = self.dir.profile(company_id)
        factors = [{"code": f["code"], "title": FACTOR_TITLES.get(f["code"], f["code"]), "level": f["level"], "level_ru": LEVEL_RU.get(f["level"], f["level"]),
                    "confidence": f["confidence"], "rationale": f["rationale"], "rule_id": f["rule_id"], "origin": "rule"} for f in p["sensitivity_factors"]]
        stats = []
        for code, per, unit, label in (("key_rate_eoy", "2026", "%", "Ключевая ставка, прогноз банка на конец 2026"), ("usd_rub_eoy", "2026", " ₽", "USD/RUB, прогноз банка на конец 2026"),
                                       ("inflation_dec_yoy", "2026", "%", "Инфляция 2026, прогноз банка"), ("gdp_growth", "2026", "%", "Рост ВВП 2026, прогноз банка")):
            i = self.kb.indicator(code, per)
            if i:
                stats.append({"label": label, "value": ru_num(i["value"], 1) + unit, "updated": ru_date_short(i["published_at"]), "item_id": i["item_id"], "page": i["page"],
                              "changed": bool(i.get("superseded")), "was": ru_num(i["superseded"][0]["value"], 1) + unit if i.get("superseded") else None})
        pv = self.dir.prompt_view(p)
        return {"company": self.dir.card(company_id), "role": self.dir.role_info(role), "factors": factors, "stats": stats, "products": pv["products"],
                "countries": pv["foreign_trade"]["countries"], "group_size": pv["group"]["size"], "data_gaps": [g["message"] for g in p["data_gaps"]],
                "reliability_notes": p["reliability_notes"], "calendar": self.kb.calendar()}

    def macro(self) -> dict:
        order = ["key_rate_eoy", "key_rate_avg", "usd_rub_eoy", "cny_rub_eoy", "inflation_dec_yoy", "gdp_growth", "wages_nominal", "unemployment", "retail_turnover", "corp_credit_growth"]
        rows = []
        for code in order:
            for per in ("2026", "2027"):
                i = self.kb.indicator(code, per)
                if i:
                    rows.append({"indicator": code, "label": i["label"], "period": per, "value": i["value"], "unit": i.get("unit"), "published_at": i["published_at"], "page": i["page"],
                                 "item_id": i["item_id"], "doc_title": i["doc_title"], "superseded": i.get("superseded", [])})
        path = [{"period": k, "value": v["value"], "published_at": v["published_at"], "superseded": v.get("superseded", []), "item_id": v["item_id"], "page": v["page"]}
                for k, v in sorted((self.kb.forecasts.get("key_rate_path") or {}).items())]
        docs = [{"item_id": i["id"], "title": i["doc_title"], "published_at": i["published_at"], "source_file": i["source_file"], "stale": i["stale"], "page_count": (i.get("extraction") or {}).get("page_count"),
                 "views": len(i.get("bank_views") or [])} for i in sorted((x for x in self.kb.items.values() if x["kind"] == "bank"), key=lambda x: x["published_at"] or "", reverse=True)]
        changed = [r for r in rows if r["superseded"]]
        return {"as_of": self.s.as_of, "rows": rows, "key_rate_path": path, "documents": docs, "changed": len(changed),
                "note": "Если в нескольких документах разные прогнозы, действует самый поздний; прежние значения показаны как заменённые. Данные извлечены из растровых PDF по изображениям — для критичных цифр сверяйте страницу."}

    def source(self, item_id: str, page: int | None) -> dict | None:
        d = self.kb.page_text(item_id, page)
        if d and d.get("source_file") and (self.s.bank_pdf_dir / d["source_file"]).exists():
            d["pdf_url"] = f"/files/{d['source_file']}" + (f"#page={page}" if page else "")
        return d

    def ingest(self, user, text: str, title: str | None) -> dict:
        text = (text or "").strip()
        if len(text) < 40 or len(text) > 20000:
            raise ValueError("текст новости: от 40 до 20000 символов")
        r = self.kb.ingest_user_text(text, title)
        self.journal.audit(user.user_id, "news_ingest", outcome=r["outcome"], item=r.get("item_id"))
        item = self.kb.get(r["item_id"]) if r.get("item_id") else None
        r["item"] = {"id": item["id"], "title": item["title"], "topics": item["topics"], "okved_prefixes": item["industries"]["okved_prefixes"],
                     "regions": item["regions"], "countries": item["countries"], "injection": item["injection"], "unconfirmed": item["unconfirmed"]} if item else None
        return r

    def health(self) -> dict:
        return {"status": "ok", "as_of": self.s.as_of, "data_dir": str(self.s.data_dir.name), "profiles": self.dir.health(), "kb": self.kb.stats(), "llm": self.llm.status(),
                "mode": "llm" if self.llm.available else "rules"}
