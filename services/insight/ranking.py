"""Персонализированное ранжирование: сопоставление материала с бизнес-контекстом компании и ролью пользователя.

Оценка объяснима: итог = взвешенная сумма компонентов (0..1) × поправки на надёжность источника и свежесть.
Каждый компонент возвращает значение и человекочитаемое обоснование со ссылкой на признак профиля (rule_id/источник).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .labels import profile_source_ru
from services.company_profile.features import country_title

from .textkit import clamp, exp_decay, plural, ru_num, topics_ru

# вес роли 0,28: смена роли заметно меняет ленту (у главного бухгалтера наверху налоги и зарплаты, у финдиректора — ставка),
# но профиль компании по-прежнему главный; новости, набравшие баллы только за счёт роли, отсекает feed_worthy (нет вывода для компании)
WEIGHTS = {"topic": 0.34, "industry": 0.32, "supply_chain": 0.08, "region": 0.06, "country": 0.05, "role": 0.28, "group": 0.04, "bank_doc": 0.08}
TRADE_TOPICS = {"foreign_trade", "fx_rates", "sanctions", "logistics", "export", "import_substitution"}
GENERIC_COUNTRIES = {"США"}  # упоминание без торговой связи — не считаем совпадением
SUPPLY_MIN_SHARE = 0.10      # доля известных платежей контрагентов отрасли, с которой связь через цепочку поставок учитывается
# темы, которые касаются любой компании независимо от профиля: изменения налогов и налоговой отчётности
UNIVERSAL_TOPICS = {"taxes": 0.6}


@dataclass
class Component:
    code: str
    label: str
    value: float                      # 0..1
    weight: float
    detail: str
    sources: list[str] = field(default_factory=list)   # industry:<rule>, factor:<code>, profile:<field>

    @property
    def contribution(self) -> float:
        return self.value * self.weight

    def as_dict(self) -> dict:
        return {"code": self.code, "label": self.label, "value": round(self.value, 3), "weight": self.weight,
                "contribution": round(self.contribution, 3), "detail": self.detail, "sources": self.sources}


@dataclass
class Score:
    item_id: str
    base: float
    relevance: int                    # 0..100
    components: list[Component]
    multipliers: dict[str, float]
    excluded: str | None = None
    matched_features: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"relevance": self.relevance, "base": round(self.base, 3),
                "components": [c.as_dict() for c in self.components if c.value > 0],
                "multipliers": {k: round(v, 3) for k, v in self.multipliers.items()},
                "matched_features": self.matched_features, "excluded": self.excluded}


class Ranker:
    def __init__(self, directory, kb):
        self.dir, self.kb = directory, kb
        self._okved: dict[str, str | None] = {}     # ОКВЭД участников групп: score вызывается для каждого материала ленты

    def score(self, item: dict, profile: dict, role_info: dict) -> Score:
        comps: list[Component] = []
        feats: list[dict] = []
        prof_topics = {t["topic"]: t for t in profile["topics"]}
        ns_all = item.get("topic_scores") or {}
        ns = dict(sorted(ns_all.items(), key=lambda x: -x[1])[:5])      # у обзоров много тем: учитываем пять главных
        mx = max(ns.values()) if ns else 0.0

        # 1) темы: пересечение тем материала и профиля, вес = вес темы в профиле × (смесь относительной и абсолютной силы темы в материале)
        total, hit = 0.0, []
        for t, s in ns.items():
            pt = prof_topics.get(t) or ({"topic": t, "weight": UNIVERSAL_TOPICS[t], "sources": [{"source": "universal:" + t}]}
                                        if t in UNIVERSAL_TOPICS else None)
            if not pt:
                continue
            strength = 0.6 * (s / mx if mx else 0) + 0.4 * s
            total += pt["weight"] * strength
            hit.append((t, pt))
        topic_val = clamp(total / 1.25)
        if hit:
            hit.sort(key=lambda x: -x[1]["weight"])
            top = hit[:3]
            detail = "; ".join(f"{topics_ru([t])} (вес {ru_num(pt['weight'], 1)}: " + ", ".join(dict.fromkeys(profile_source_ru(s["source"]) for s in pt["sources"][:2])) + ")"
                               for t, pt in top)
            srcs = sorted({s["source"] for _, pt in top for s in pt["sources"]})
            comps.append(Component("topic", "Темы материала совпали с признаками компании", topic_val, WEIGHTS["topic"], detail, srcs))
            for t, pt in top:
                feats.append({"kind": "topic", "topic": t, "weight": pt["weight"], "sources": [s["source"] for s in pt["sources"]]})

        # 2) отрасль: пересечение префиксов ОКВЭД материала с иерархией ОКВЭД компании
        levels = profile["industry"]["okved_levels"]["value"] or []
        n_pref = item["industries"]["okved_prefixes"]
        direct = [p for p in n_pref if p in levels]
        if direct:
            deepest = max(direct, key=len)
            depth = {1: 0.0, 2: 0.9, 4: 0.97}.get(len(deepest), 1.0)
            val = clamp(depth if len(deepest) >= 2 else 0.5)
            comps.append(Component("industry", "Материал напрямую касается отрасли компании", val, WEIGHTS["industry"],
                                   f"ОКВЭД компании {profile['industry']['okved_code']['value']} входит в {deepest}", [f"profile:okved:{deepest}"]))
            feats.append({"kind": "industry", "okved_prefix": deepest, "source": "profile.industry.okved_levels"})

        # 3) цепочка поставок (поставщики/покупатели по платежам)
        sc = self.dir.supply_matches(n_pref, profile) if not direct or len(n_pref) > len(direct) else []
        sc = [m for m in sc if (m.get("share_of_known") or 0) >= SUPPLY_MIN_SHARE]
        if sc:
            best = sc[0]
            share = best.get("share_of_known") or 0
            val = clamp(0.35 + share * 1.2)
            who = "поставщиков" if best["direction"] == "suppliers" else "покупателей"
            comps.append(Component("supply_chain", "Событие касается отрасли контрагентов", val, WEIGHTS["supply_chain"],
                                   f"ОКВЭД {best['okved_code']} — {share*100:.0f}% известных платежей {who}", ["factor:supply_chain_industries"]))
            feats.append({"kind": "supply_chain", "direction": best["direction"], "okved_code": best["okved_code"], "share": share})

        # 4) регион
        reg = profile["geography"]["region"]["value"]
        if reg and reg in (item.get("regions") or []):
            comps.append(Component("region", "Событие в регионе компании", 1.0, WEIGHTS["region"], f"регион {reg}", ["profile:geography.region"]))
            feats.append({"kind": "region", "region": reg})

        # 5) страны ВЭД — только вместе с торговыми темами (иначе это просто упоминание)
        ctry = set(profile["foreign_trade"]["countries"]["value"] or [])
        n_ctry = set(item.get("countries") or []) - GENERIC_COUNTRIES
        common = ctry & n_ctry
        if common and (set(ns) & TRADE_TOPICS):
            comps.append(Component("country", "Страны внешней торговли компании упомянуты в событии", clamp(0.5 + 0.25 * len(common)), WEIGHTS["country"],
                                   "страны: " + ", ".join(country_title(x) for x in sorted(common)), ["factor:fx_and_trade_exposure"]))
            feats.append({"kind": "country", "countries": sorted(common)})

        # 6) приоритеты роли пользователя
        prio = role_info.get("priority_topics") or []
        rscore = 0.0
        for pos, t in enumerate(prio):
            if t in ns:
                rscore = max(rscore, (1.0 - 0.12 * pos) * (0.5 + 0.5 * (ns[t] / mx if mx else 0)))
        if rscore > 0:
            comps.append(Component("role", f"Приоритет роли «{role_info.get('title')}»", clamp(rscore), WEIGHTS["role"],
                                   "приоритетные темы роли: " + topics_ru(t for t in prio if t in ns), ["role:" + role_info["code"]]))
            feats.append({"kind": "role", "role": role_info["code"], "topics": [t for t in prio if t in ns]})

        # 7) группа компаний: событие, затрагивающее отрасль других участников группы (вопрос 25 вебинара)
        grp = self._group_overlap(profile, n_pref)
        if grp and not direct:
            comps.append(Component("group", "Событие касается другой компании группы", clamp(0.5 + 0.1 * grp["n"]), WEIGHTS["group"],
                                   f"{grp['n']} {plural(grp['n'], ('компания', 'компании', 'компаний'))} группы с ОКВЭД {', '.join(grp['okved'][:3])}", ["profile:group"]))
            feats.append({"kind": "group", **grp})

        # 8) материал банка по теме — небольшой бонус: аналитика банка должна быть заметной частью ценности
        if item["kind"] == "bank" and comps:
            comps.append(Component("bank_doc", "Аналитика банка по темам компании", 1.0, WEIGHTS["bank_doc"], "аналитический материал Альфа-Банка", ["bank:analytics"]))

        base = sum(c.contribution for c in comps)
        mult: dict[str, float] = {}
        rel = (item.get("source_reliability") or {}).get("score", 0.5)
        mult["reliability"] = 0.75 + 0.25 * rel
        half = 60.0 if item["kind"] == "bank" else 18.0
        mult["recency"] = max(0.35, exp_decay(item["age_days"], half)) if item["age_days"] < 9000 else 0.35
        if item.get("unconfirmed"):
            mult["unconfirmed"] = 0.7
        if item.get("stale"):
            mult["stale"] = 0.15
        excluded = None
        if item.get("injection"):
            excluded = "prompt_injection_suspected"
        elif item.get("dup_of"):
            excluded = "duplicate"
        elif not comps:
            excluded = "no_match"
        m = 1.0
        for v in mult.values():
            m *= v
        rel_score = int(round(100 * (1 - math.exp(-(base * m) / 0.28))))   # насыщающая шкала: слабые совпадения различимы, сильные не «упираются» в потолок мгновенно
        return Score(item["id"], base, rel_score, comps, mult, excluded, feats)

    def _group_overlap(self, profile: dict, prefixes: list[str]) -> dict | None:
        members = (profile.get("group") or {}).get("members") or []
        if not members or not prefixes or len(members) > 60:
            return None
        found = []
        for m in members:
            code = self._member_okved(m)
            if code and any(code.startswith(p) for p in prefixes):
                found.append(code)
        return {"n": len(found), "okved": sorted(set(found))} if found else None

    def _member_okved(self, company_id: str) -> str | None:
        if company_id not in self._okved:
            try:
                self._okved[company_id] = self.dir.svc.company_summary(company_id).get("okved_code")
            except Exception:  # noqa: BLE001 — участник группы вне данных/в карантине: просто не учитывается
                self._okved[company_id] = None
        return self._okved[company_id]

    # ------------------------------------------------------------------ лента
    def rank(self, profile: dict, role_info: dict, since_days: int | None = None) -> list[tuple[dict, Score]]:
        out = []
        for item in self.kb.items.values():
            if since_days is not None and item["age_days"] > since_days and item["kind"] == "news":
                continue
            sc = self.score(item, profile, role_info)
            out.append((item, sc))
        out.sort(key=lambda x: (x[1].excluded is not None, -x[1].relevance, x[0]["age_days"]))
        return out
