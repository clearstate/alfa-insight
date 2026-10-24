"""Фасад сервиса: лента, инсайты, контекст компании, аналитика банка, вопросы, ввод новой новости."""
from __future__ import annotations

import logging
import queue
import threading

from services.company_profile.features import country_title

from . import APP_VERSION
from .agent import DISCLAIMER, InsightAgent, ItemNotFound
from .kb import KnowledgeBase
from .labels import FACTOR_TITLES, LEVEL_RU, PRODUCT_TITLES
from .llm import LLMClient
from .people import Directory
from .qa import Answerer
from .ranking import Ranker
from .runtime import Journal
from .settings import Settings, load_settings
from .textkit import TOPIC_RU, fold, ru_date, ru_date_short, ru_num, short

log = logging.getLogger("insight.service")
TYPE_LABEL = {"risk": "Требует внимания", "opportunity": "Возможность", "event": "Событие"}
CONF_LABEL = {"high": "Высокая уверенность", "medium": "Средняя уверенность", "low": "Низкая уверенность"}


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
        # скрытые пользователем события: (user_id, company_id) -> {item_id}; восстанавливаются из журнала при старте
        self.hidden: dict[tuple[str, str], set[str]] = {}
        for rec in self.journal.read("hidden", limit=100000):
            self._set_hidden((rec.get("user"), rec.get("company")), rec.get("item"), bool(rec.get("hidden")))
        if self.s.live_feeds:
            self.kb.start_live_feeds()
        # фоновая подготовка разборов моделью для верхних карточек ленты (LLM_PREWARM): разбор потом открывается сразу
        # с текстом модели, а карточка ленты показывает его краткий текст. Один поток — вызовы шлюза идут по очереди.
        self._prewarm_q: queue.Queue[tuple[str, str, str]] = queue.Queue(maxsize=200)
        self._prewarm_pending: set[tuple[str, str, str]] = set()
        self._prewarm_thread: threading.Thread | None = None

    # ---- фоновая подготовка разборов моделью
    def _prewarm(self, company_id: str, role: str, item_ids: list[str]) -> int:
        """Ставит в очередь разборы, ещё не переписанные моделью; возвращает число ожидающих для этой компании и роли."""
        if not (self.llm.available and self.s.llm_prewarm > 0):
            return 0
        if self._prewarm_thread is None:
            self._prewarm_thread = threading.Thread(target=self._prewarm_worker, name="llm-prewarm", daemon=True)
            self._prewarm_thread.start()
        for iid in item_ids[: self.s.llm_prewarm]:
            key = (company_id, role, iid)
            if key in self._prewarm_pending or self.agent.cached(company_id, role, iid, "llm"):
                continue
            try:
                self._prewarm_q.put_nowait(key)
                self._prewarm_pending.add(key)
            except queue.Full:
                break
        return sum(1 for k in list(self._prewarm_pending) if k[:2] == (company_id, role))

    def _prewarm_worker(self) -> None:
        while True:
            key = self._prewarm_q.get()
            try:
                if not self.llm.blocked:                    # бюджет шлюза исчерпан — до сброса не тратим вызовы
                    self.agent.run(*key, use_llm=True)
            except Exception:  # noqa: BLE001 — фоновая подготовка не должна останавливаться из-за одного разбора
                log.exception("фоновый разбор моделью %s", key)
            finally:
                self._prewarm_pending.discard(key)

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
        cards, seen_clusters, seen_titles, hidden = [], {}, {}, 0
        by_user = self.hidden.get((user.user_id, company_id), set())
        hidden_clusters = {(self.kb.get(i) or {}).get("cluster_id") for i in by_user} - {None}
        for item, sc in ranked:
            if sc.excluded:
                continue
            if item["id"] in by_user or item.get("cluster_id") in hidden_clusters:
                continue                  # скрыто пользователем: событие целиком (все публикации кластера)
            if sc.relevance < min_rel:
                hidden += 1
                continue
            cid = item.get("cluster_id")
            if cid in seen_clusters:
                seen_clusters[cid]["also_reported"] += 1
                continue
            same = seen_titles.get(fold(item.get("doc_title") or item["title"]))
            if same is not None:          # тот же регулярный материал за другую неделю (мониторинг ставок ЦБ) — показан самый свежий
                same["also_reported"] += 1
                continue
            ins = self.agent.run(company_id, role, item["id"], user_id=user.user_id, use_llm=False)
            if not self.feed_worthy(item, ins):
                hidden += 1
                continue
            card = self._card(item, sc, ins, self.agent.cached(company_id, role, item["id"], "llm"), profile)
            seen_clusters[cid] = card
            seen_titles[fold(item.get("doc_title") or item["title"])] = card
            cards.append(card)
        for c in cards:
            c["final"] = round((0.8 * c["relevance"] + 0.2 * {"high": 100, "medium": 65, "low": 35}[c["severity"]]) * (0.88 if c["is_bank"] else 1.0), 1)
        cards.sort(key=lambda c: -c["final"])
        # Повтор одного и того же вывода (например, «деньги остаются дорогими» из 4 материалов про ставку):
        # тревогой остаётся только первая карточка, остальные — «событие, подкрепляющее вывод» и ниже в ленте.
        seen_head: dict[str, str] = {}
        for c in cards:
            h = c["headline"]
            if (c.get("top_lens") or "").startswith("sector:"):
                continue        # отраслевой сценарий по разным событиям — не повтор (разные факты), не понижаем
            if h in seen_head:
                c["repeat_of"] = seen_head[h]
                if c["type"] == "risk":
                    c["type"], c["label"] = "event", TYPE_LABEL["event"]
                c["final"] = round(c["final"] * 0.85, 1)
            else:
                seen_head[h] = c["title"]
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
                  "event": sum(c["type"] == "event" and not c["is_bank"] for c in cards), "bank": sum(c["is_bank"] for c in cards),
                  "important": sum(c["type"] == "risk" and c["severity"] == "high" for c in cards)}
        if tab == "bank":
            cards = [c for c in cards if c["is_bank"]]
        elif tab in ("risk", "opportunity", "event"):
            cards = [c for c in cards if c["type"] == tab and (tab != "event" or not c["is_bank"])]
        self.journal.audit(user.user_id, "feed", company=company_id, role=role, tab=tab, shown=len(cards[:limit]))
        pending = self._prewarm(company_id, role, [c["id"] for c in cards if c["mode"] != "llm"])
        return {"company_id": company_id, "role": role, "as_of": self.s.as_of, "as_of_ru": ru_date(self.s.as_of), "counts": counts, "cards": cards[:limit], "hidden_low_relevance": hidden,
                "llm_pending": pending,
                "hidden_by_user": [{"item_id": i, "title": (self.kb.get(i) or {}).get("doc_title") or (self.kb.get(i) or {}).get("title")} for i in sorted(by_user) if self.kb.get(i)],
                "updated": self.s.as_of, "disclaimer": DISCLAIMER}

    @staticmethod
    def feed_worthy(item: dict, ins: dict) -> bool:
        """Попадает ли внешняя новость в ленту. Нужны экономическая суть (не военная сводка, политика, происшествие, спорт) и
        конкретный вывод именно для компании: «макрофон», «тема важна, оценка общая» и пересказ — не инсайт (кейс: не новостная
        лента, а интерпретация). Такие события доступны через вопросы ассистенту. Материалы банка показываются по релевантности."""
        if item["kind"] != "news":
            return True
        return bool(item.get("econ")) and not item.get("offtopic") and ins.get("top_lens") not in (None, "generic") and ins.get("top_company_specific", True)

    @staticmethod
    def _reasons(item: dict, sc, ins: dict, profile: dict | None) -> list[str]:
        """«Почему вы это видите» — до трёх коротких причин: признак компании, на котором держится главный вывод, и совпадения
        события с её данными («ваш долг: кредиты, лизинг», «отрасль покупателей · 52%», «страны ВЭД: Китай»)."""
        if item["kind"] == "bank":
            out = ["аналитика Альфа-Банка"]
        else:
            out = []
        base = (ins.get("top_lens") or "").split(":")[0]
        owned = {k for k, v in ((profile or {}).get("bank_relationship") or {}).get("products", {}).items() if v.get("value") is True}
        debt = [PRODUCT_TITLES[k].lower() for k in ("loans", "leasing", "guarantees", "factoring") if k in owned]
        countries = [country_title(c) for c in ((profile or {}).get("foreign_trade") or {}).get("countries", {}).get("value") or []]
        workers = (((profile or {}).get("size") or {}).get("workers_fns") or {}).get("value")
        lens_reason = {"rate": "ваш долг: " + ", ".join(debt) if debt else None, "deposit": "депозиты в банке" if "deposits" in owned else None,
                       "fx": "ВЭД: " + ", ".join(countries[:3]) if countries else "валютные расчёты",
                       "fx_payments": "ВЭД: " + ", ".join(countries[:3]) if countries else None,
                       "payroll": f"численность: {workers[:1].lower() + workers[1:]}" if workers else "фонд оплаты труда",
                       "demand": "потребительский сектор", "sector": "ваша отрасль", "industry": "ваша отрасль"}.get(base)
        if lens_reason:
            out.append(lens_reason)
        # совпадения события с данными компании — только те, на которых держится главный вывод: у вывода о ставке по обзору ВВП
        # «отрасль покупателей · 52%» — не причина
        for c in sc.components:
            if c.code == "supply_chain" and base in ("supply_chain", "sector", "industry"):
                who = "поставщиков" if "поставщиков" in c.detail else "покупателей"
                share = c.detail.split("—")[-1].strip().split("%")[0] if "%" in c.detail else ""
                out.append(f"отрасль {who}" + (f" · {share}%" if share else ""))
            elif c.code == "region":
                out.append("ваш регион")
            elif c.code == "country" and base in ("fx", "fx_payments", "sector"):
                out.append("страны ВЭД в событии")
            elif c.code == "group":
                out.append("компания вашей группы")
        return list(dict.fromkeys(out))[:3]

    def _card(self, item: dict, sc, ins: dict, llm_ins: dict | None = None, profile: dict | None = None) -> dict:
        """Карточка ленты. Тип, значимость и релевантность — из разбора по правилам (стабильны); краткий текст — из разбора
        моделью, если он уже готов (открывали разбор или фоновая подготовка)."""
        use_llm_text = bool(llm_ins and llm_ins.get("mode") == "llm")
        title, text = item.get("doc_title") or item["title"], short((llm_ins if use_llm_text else ins)["summary"], 260)
        return {"id": item["id"], "type": ins["type"], "label": TYPE_LABEL[ins["type"]], "severity": ins["severity"], "title": title, "headline": ins["headline"],
                "text": text, "metric": ins.get("metric"), "confidence": ins["confidence"], "confidence_label": CONF_LABEL[ins["confidence"]],
                "relevance": sc.relevance, "published_at": item.get("published_at"), "time": ru_date_short(item.get("published_at")),
                "source": item.get("display_source"), "news_title": item["title"], "is_bank": item["kind"] == "bank", "synthetic": item.get("synthetic", False),
                "unconfirmed": item.get("unconfirmed", False), "has_bank_view": ins["bank_view"]["has_position"], "also_reported": 0, "repeat_of": None, "top_lens": ins.get("top_lens"),
                "why": [w["statement"] for w in ins["why_it_matters"][:2]], "checks_passed": ins["checks"]["passed"],
                "mode": "llm" if use_llm_text else "rules", "reasons": self._reasons(item, sc, ins, profile),
                "action": (ins.get("actions") or [{}])[0].get("title")}

    def insight(self, user, company_id: str, role: str | None, item_id: str, mode: str = "auto") -> dict:
        """mode: rules — сразу, без модели (интерфейс показывает его первым); llm/auto — с переписыванием моделью, если шлюз настроен."""
        role = self.check(user, company_id, role)
        ins = self.agent.run(company_id, role, item_id, user_id=user.user_id, use_llm=mode != "rules")
        self.journal.audit(user.user_id, "insight", company=company_id, role=role, item=item_id, mode=ins.get("mode"))
        src = self.kb.page_text(item_id, None)
        return {**ins, "news_source": {k: v for k, v in src.items() if k != "text"} if src else None}

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
        for code, per, unit, label in (("key_rate_eoy", "2026", "%", "Ключевая ставка, прогноз банка на конец 2026 г."), ("usd_rub_eoy", "2026", " ₽", "USD/RUB, прогноз банка на конец 2026 г."),
                                       ("inflation_dec_yoy", "2026", "%", "Инфляция за 2026 г., прогноз банка"), ("gdp_growth", "2026", "%", "Рост ВВП за 2026 г., прогноз банка")):
            i = self.kb.indicator(code, per)
            if i:
                stats.append({"label": label, "value": ru_num(i["value"], 1) + unit, "updated": ru_date_short(i["published_at"]), "item_id": i["item_id"], "page": i["page"],
                              "changed": bool(i.get("superseded")), "was": ru_num(i["superseded"][0]["value"], 1) + unit if i.get("superseded") else None})
        pv = self.dir.prompt_view(p)
        return {"company": self.dir.card(company_id), "role": self.dir.role_info(role), "factors": factors, "stats": stats, "products": pv["products"],
                "countries": [country_title(c) for c in pv["foreign_trade"]["countries"]], "group_size": pv["group"]["size"], "data_gaps": [g["message"] for g in p["data_gaps"]],
                "reliability_notes": p["reliability_notes"], "calendar": self.kb.calendar()}

    def payments(self, user, company_id: str) -> dict:
        """Платёжные потоки и продукты компании по данным кейса (без выдуманных остатков: их в данных нет)."""
        self.check(user, company_id, None)
        p = self.dir.profile(company_id)
        cp = p["counterparties"]

        def side(d: dict) -> dict:
            rows = []
            for t in d["top"][:8]:
                name = None
                if t["known"]:
                    try:
                        name = self.dir.svc.company_summary(t["company_id"]).get("okved_name")
                    except Exception:  # noqa: BLE001
                        name = None
                rows.append({"counterparty": "Контрагент •••" + t["company_id"].split("_")[-1][-4:], "okved_code": t["okved_code"], "okved_name": name,
                             "region": t["region"], "amount": t["pay_amt"], "count": t["pay_cnt"], "share": t["share"], "known": t["known"]})
            return {"total_amt": d["total_amt"], "total_cnt": d["total_cnt"], "n_counterparties": d["n_counterparties"],
                    "known_coverage": d["known_coverage"], "top": rows}

        prods = [{"code": k, "title": PRODUCT_TITLES.get(k, k), "active": v["value"] is True} for k, v in p["bank_relationship"]["products"].items()]
        rev = p["size"]["revenue"]["value"]
        return {"company": self.dir.card(company_id), "incoming": side(cp["incoming"]), "outgoing": side(cp["outgoing"]),
                "self_transfers": cp.get("self_payments_excluded"), "products": prods,
                "countries": [country_title(c) for c in p["foreign_trade"]["countries"]["value"] or []], "revenue": rev,
                "workers": p["size"]["workers_fns"]["value"], "group_size": (p.get("group") or {}).get("size"),
                "note": "Платежи, видимые банку, с 1 января (по разъяснению организаторов). Самопереводы между своими счетами исключены. "
                        "Идентификаторы контрагентов обезличены; характер отношений по платежам определить нельзя. Остатков по счетам в данных кейса нет."}

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
            d["pdf_url"] = f"/files/{d['source_file']}" + (f"#page={d['page']}" if d.get("page") else "")
        return d

    def hide(self, user, company_id: str, role: str | None, item_id: str, hidden: bool = True) -> dict:
        """Скрыть событие из ленты пользователя по компании (или вернуть). Решение пишется в журнал hidden."""
        self.check(user, company_id, role)
        if self.kb.get(item_id) is None:
            raise ItemNotFound(item_id)
        ids = self._set_hidden((user.user_id, company_id), item_id, hidden)
        self.journal.write("hidden", {"user": user.user_id, "company": company_id, "item": item_id, "hidden": bool(hidden)})
        return {"ok": True, "item_id": item_id, "hidden": bool(hidden), "hidden_count": len(ids)}

    def _set_hidden(self, key: tuple[str, str], item_id: str, hidden: bool) -> set[str]:
        ids = self.hidden.setdefault(key, set())
        if hidden:
            ids.add(item_id)
        else:
            ids.discard(item_id)
        return ids

    def ingest(self, user, text: str, title: str | None) -> dict:
        text = (text or "").strip()
        if len(text) < 40 or len(text) > 20000:
            raise ValueError("текст новости: от 40 до 20000 символов")
        r = self.kb.ingest_user_text(text, title)
        self.journal.audit(user.user_id, "news_ingest", outcome=r["outcome"], item=r.get("item_id"))
        item = self.kb.get(r["item_id"]) if r.get("item_id") else None
        # темы и страны — подписями для интерфейса; коды тем — в topic_codes
        r["item"] = {"id": item["id"], "title": item["title"], "topics": [TOPIC_RU.get(t, t) for t in item["topics"]], "topic_codes": item["topics"],
                     "okved_prefixes": item["industries"]["okved_prefixes"], "regions": item["regions"],
                     "countries": [country_title(c) for c in item["countries"]],
                     "injection": item["injection"], "unconfirmed": item["unconfirmed"]} if item else None
        return r

    def health(self) -> dict:
        kb = self.kb.stats()
        feeds = kb.get("feeds") or {}
        status = "degraded" if feeds.get("enabled") and feeds.get("status") != "ok" else "ok"   # просрочено обновление лент
        return {"status": status, "version": APP_VERSION, "as_of": self.s.as_of, "data_dir": str(self.s.data_dir.name), "profiles": self.dir.health(), "kb": kb, "llm": self.llm.status(),
                "mode": "llm" if self.llm.available else "rules"}
