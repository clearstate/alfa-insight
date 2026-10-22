"""Обогащение правилами и словарями (без LLM): темы, отрасли (стык с участником 1), сущности, ключевые факты,
позиции банка (bank_view), числовые утверждения. LLM вызывается только поверх (см. llm.py)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from contracts.news_vocab import TOPICS_V1
from services.company_profile.industry_terms import load_industry_terms, sections_for
from services.company_profile.okved import OkvedDirectory

from .models import BankView, KeyFact, NumericClaim
from .textutil import fold, split_sentences

CONFIG = Path(__file__).resolve().parent / "config"
FEATURE_RULES = Path(__file__).resolve().parents[1] / "company_profile" / "config" / "feature_rules.yaml"

_BANK_MARK = re.compile(
    r"(?<![а-я])(мы\s+(ожида|полага|счита|ждем|повыша|понижа|меня|перестав|смеща|вид|рекоменд|отдаем|сохраня|ориентир|не\s+ожида|"
    r"не\s+исключа|не\s+вид|не\s+счита|оцениваем|прогнозируем)|на\s+наш\s+взгляд|по\s+нашему\s+мнению|наш\w*\s+(прогноз|оценк|взгляд|мнени|ожидани|стратег)|"
    r"наше\s+мнение|рекоменду(?:ем|ю)(?![а-я])|ожидаем(?![а-я])|полагаем(?![а-я])|считаем(?![а-я])|ждем(?![а-я]))", re.I)
_BANK_SOFT = re.compile(
    r"(может\s+(стать|продолжить|оказать|привести|быть|ограничи)|вероятност\w*\s+(такого|повышен|снижен)|(?<!не)благоприятн|"
    r"негативн\w*\s+фактор|ключев\w*\s+фактор|остается\s+опорой|важн\w*\s+будет|для\s+(золота|рынка|ставки)\s+(это|важн)|"
    r"сигнал\s+(для|о)|выглядит\s+(избыточн|неожиданн|рискован|обоснован)|подталкива|оказа\w+\s+давлени|давление\s+на)", re.I)
_REC = re.compile(r"рекоменду|предпочтени|отдаем\s+предпочт|стоит\s+(использовать|избегать)|избегать", re.I)
_FCST = re.compile(r"ожида|прогноз|ждем|ориентируемся|не\s+исключа|ожидаем|на\s+горизонте|к\s+концу\s+(года|20)", re.I)
_HEDGE = re.compile(r"возможно|может\s+быть|вероятно|предположительно|по\s+слухам|не\s+исключ|якобы|по\s+неподтвержден|могут\s+", re.I)
_SKIP_LINE = re.compile(r"^(рис\.|табл|таблица|источник|график|\*)", re.I)
_NUM = re.compile(r"\d")
_PCT = re.compile(r"\d\s*%|б\.\s*п\.|п\.\s*п\.")
_INJECTION = re.compile(
    r"(ignore\s+(all\s+)?(previous|prior|above)\s+instructions|disregard\s+(the\s+)?(system|previous)|you\s+are\s+now\b|system\s+prompt|"
    r"игнорируй\w*\s+(все\s+)?(предыдущ|прежн|выше)\w*\s+(инструкц|указан)|забудь\w*\s+(все\s+)?инструкц|ты\s+теперь\b|новые\s+инструкции\s*:)", re.I)

_NUMBER = r"(\d{1,3}(?:[.,]\d{1,2})?)"
_RE_KEY_RATE = [
    re.compile(r"ставк\w*\s+[^.%\n]{0,50}?на\s+уровне\s+" + _NUMBER + r"\s*%"),
    re.compile(r"ставк\w*\s+без\s+изменени\w*\s+на\s+" + _NUMBER + r"\s*%"),
    re.compile(r"ключев\w*\s+ставк\w*[^.%\n]{0,120}?" + _NUMBER + r"\s*%"),
    re.compile(r"(?:сохранил|снизил|повысил|оставил)\w*\s+[^.%\n]{0,60}?ставк\w*[^.%\n]{0,60}?" + _NUMBER + r"\s*%"),
]
_RE_INFL = re.compile(r"(?:в\s+годовом\s+выражении\s+инфляц\w*|годов\w+\s+инфляц\w*)[^.%\n]{0,40}?" + _NUMBER + r"\s*%")
_RE_USD = re.compile(r"(?:курс\w*[^.\n]{0,60}?|на\s+уровне\s+)" + _NUMBER + r"\s*руб\.?\s*/\s*\$")


def _f(x: str) -> float:
    return float(x.replace(",", "."))


class Enricher:
    def __init__(self) -> None:
        tr = yaml.safe_load((CONFIG / "topic_rules.yaml").read_text(encoding="utf-8"))
        self.min_score = tr["min_score"]
        self.max_topics = tr["max_topics"]
        extra_path = CONFIG / "topic_rules_extra.yaml"          # insight-слой: дополнительные шаблоны, не ломающие базовые правила
        if extra_path.exists():
            extra = yaml.safe_load(extra_path.read_text(encoding="utf-8")) or {}
            for t, pats in (extra.get("topics") or {}).items():
                tr["topics"][t] = list(tr["topics"].get(t, [])) + list(pats)
        unknown = set(tr["topics"]) - set(TOPICS_V1)
        if unknown:
            raise ValueError(f"в topic_rules.yaml темы вне словаря v1: {sorted(unknown)}")
        self.topic_re = {t: [re.compile(p) for p in pats] for t, pats in tr["topics"].items()}
        ent = yaml.safe_load((CONFIG / "entities.yaml").read_text(encoding="utf-8"))
        self.entities = [(e["name"], e["type"], [re.compile(p) for p in e["patterns"]]) for e in ent["entities"]]
        gc = yaml.safe_load((CONFIG / "geo_countries.yaml").read_text(encoding="utf-8"))
        gr = yaml.safe_load((CONFIG / "geo_regions.yaml").read_text(encoding="utf-8"))
        # названия — РОВНО как в данных кейса (FTS_COUNTRY_NAME, REGION): совпадают с profile.foreign_trade.countries и geography.region
        self.countries = [(c["name"], [re.compile(p) for p in c["patterns"]]) for c in gc["countries"]]
        self.regions = [(c["name"], [re.compile(p) for p in c["patterns"]]) for c in gr["regions"]]
        self.region_groups = [([re.compile(p) for p in g["patterns"]], g["regions"]) for g in gr["groups"]]
        self.terms = load_industry_terms()
        rules = yaml.safe_load(FEATURE_RULES.read_text(encoding="utf-8"))
        self.okved_dir = OkvedDirectory(rules["okved_sections"])
        ov = yaml.safe_load((CONFIG / "industry_overrides.yaml").read_text(encoding="utf-8"))
        self._neutralize = [re.compile(p) for p in ov.get("neutralize", [])]
        self._ind_min_score = ov.get("min_score", {})
        self._term_re: dict[str, tuple[list[re.Pattern], list[re.Pattern]]] = {}
        for eid, e in self.terms.items():
            mk = lambda ts: [re.compile(r"(?<![а-яa-z0-9])" + re.escape(t)) for t in ts]
            self._term_re[eid] = (mk(e["terms"]), mk(e.get("ambiguous_terms", [])))

    # ---- темы ----
    def topics(self, title: str, text: str) -> tuple[list[str], dict[str, float], dict[str, list[str]]]:
        ft, fx = fold(title or ""), fold(text or "")
        scores: dict[str, float] = {}
        evidence: dict[str, list[str]] = {}
        for t, pats in self.topic_re.items():
            sc, ev, in_title = 0.0, [], False
            for p in pats:
                n_title, n_text = len(p.findall(ft)), len(p.findall(fx))
                if n_title:
                    in_title = True
                sc += 3 * n_title + n_text
                if n_title or n_text:
                    ev.append(p.pattern)
            if sc >= self.min_score or in_title:
                scores[t] = round(min(1.0, sc / 10.0), 3)
                evidence[t] = ev
        ranked = sorted(scores, key=lambda k: (-scores[k], k))[: self.max_topics]
        return ranked, {k: scores[k] for k in ranked}, {k: evidence[k] for k in ranked}

    # ---- отрасли (стык с company_profile.industry_terms) ----
    def industries(self, title: str, text: str, min_hits: int = 2) -> dict[str, Any]:
        ft, fx = fold(title or ""), fold(text or "")
        for rx in self._neutralize:
            ft, fx = rx.sub(" ", ft), rx.sub(" ", fx)
        matches, prefixes = [], []
        for eid, (main, amb) in self._term_re.items():
            hits: list[str] = []
            n = 0
            for rx in main:
                a, b = len(rx.findall(ft)), len(rx.findall(fx))
                if a or b:
                    hits.append(rx.pattern.split("]")[-1].replace("\\", ""))
                n += 3 * a + b
            if hits and amb:
                for rx in amb:
                    c = len(rx.findall(fx)) + len(rx.findall(ft))
                    if c:
                        hits.append(rx.pattern.split("]")[-1].replace("\\", ""))
                        n += c
            title_hit = any(rx.search(ft) for rx in main)
            if hits and ((n >= max(min_hits, self._ind_min_score.get(eid, 0))) or (title_hit and eid not in self._ind_min_score)):
                ps = [p["prefix"] for p in self.terms[eid]["okved_prefixes"]]
                matches.append({"entry_id": eid, "terms": sorted(set(hits)), "score": n, "okved_prefixes": ps,
                                "industry_rule": self.terms[eid].get("industry_rule")})
                for p in ps:
                    if p not in prefixes:
                        prefixes.append(p)
        matches.sort(key=lambda m: (-m["score"], m["entry_id"]))
        return {"okved_prefixes": prefixes, "okved_sections": sections_for(prefixes, self.okved_dir), "matches": matches}

    # ---- сущности, страны, регионы ----
    def entities_geo(self, text: str) -> tuple[list[dict[str, str]], list[str], list[str]]:
        fx = fold(text or "")
        ents = [{"name": n, "type": ty} for n, ty, pats in self.entities if any(p.search(fx) for p in pats)]
        for m in re.finditer(r"(?:\b(?:ПАО|АО|ООО|МКПАО)\s+)([«\"]?[А-ЯЁA-Z][\w\-]+(?:\s+[А-ЯЁA-Z][\w\-]+)?[»\"]?)", text or ""):
            nm = m.group(1).strip("«»\"")
            if nm and not any(e["name"] == nm for e in ents):
                ents.append({"name": nm, "type": "org"})
        countries = [n for n, pats in self.countries if any(p.search(fx) for p in pats)]
        regions = [n for n, pats in self.regions if any(p.search(fx) for p in pats)]
        for pats, members in self.region_groups:            # «Дальний Восток», «Сибирь» … -> официальные регионы из данных
            if any(p.search(fx) for p in pats):
                regions += [m for m in members if m not in regions]
        return ents, countries, regions

    # ---- предложения: ключевые факты / позиции банка / числа ----
    def _candidate_sentences(self, pages: list[tuple[int | None, str, int]]):
        """pages: (page, text, offset_in_item_text). Возвращает (sentence, abs_start, abs_end, page)."""
        for page, text, off in pages:
            for para_m in re.finditer(r"[^\n]+", text):
                line = para_m.group(0)
                if _SKIP_LINE.match(line.strip()) or line.count("|") >= 2:
                    continue
                for s, a, b in split_sentences(line):
                    if 35 <= len(s) <= 700:
                        yield s, off + para_m.start() + a, off + para_m.start() + b, page

    def analyse_sentences(self, pages: list[tuple[int | None, str, int]], is_bank: bool, max_facts: int, topic_pool: list[str]):
        facts_c, views = [], []
        for s, a, b, page in self._candidate_sentences(pages):
            fs = fold(s)
            sent_topics = [t for t in topic_pool if any(p.search(fs) for p in self.topic_re[t])]
            has_num, has_pct = bool(_NUM.search(s)), bool(_PCT.search(s))
            bank_mark = is_bank and bool(_BANK_MARK.search(fs) or _BANK_SOFT.search(fs))
            if bank_mark:
                kind = "recommendation" if _REC.search(fs) else ("forecast" if _FCST.search(fs) else "assessment")
                views.append(BankView(text=s, kind=kind, topics=sent_topics, page=page,
                                      span={"field": "text", "start": a, "end": b, "page": page}))
            score = 2.0 * has_pct + 1.0 * has_num + 1.2 * len(sent_topics) + (1.5 if bank_mark else 0.0)
            if score >= 2.0:
                if is_bank:
                    ct = "bank_view" if bank_mark else "fact"
                else:
                    ct = "unknown" if _HEDGE.search(fs) else "fact"
                facts_c.append((score, a, KeyFact(text=s, claim_type=ct, method="rule", topics=sent_topics,
                                                  span={"field": "text", "start": a, "end": b, "page": page})))
        top = sorted(facts_c, key=lambda x: (-x[0], x[1]))[:max_facts]
        facts = [f for _, _, f in sorted(top, key=lambda x: x[1])]
        return facts, views

    def numeric_claims(self, pages: list[tuple[int | None, str, int]], is_bank: bool) -> list[NumericClaim]:
        out: list[NumericClaim] = []
        seen: set[tuple[str, float, str]] = set()
        for s, a, b, page in self._candidate_sentences(pages):
            fs = fold(s)
            ct = "bank_view" if (is_bank and (_BANK_MARK.search(fs) or _BANK_SOFT.search(fs))) else "fact"
            cands: list[tuple[str, float, str]] = []
            for rx in _RE_KEY_RATE:
                for m in rx.finditer(fs):
                    cands.append(("key_rate_pct", _f(m.group(1)), "%"))
            for m in _RE_INFL.finditer(fs):
                cands.append(("inflation_yoy_pct", _f(m.group(1)), "%"))
            for m in _RE_USD.finditer(fs):
                cands.append(("usd_rub", _f(m.group(1)), "руб./$"))
            for kind, val, unit in cands:
                if kind == "key_rate_pct" and not (1.0 <= val <= 40.0):
                    continue
                key = (kind, val, s[:40])
                if key not in seen:
                    seen.add(key)
                    out.append(NumericClaim(kind=kind, value=val, text=s, claim_type=ct, page=page))
        return out

    @staticmethod
    def injection_flags(text: str) -> list[str]:
        return ["prompt_injection_suspected"] if _INJECTION.search(text or "") else []

    @staticmethod
    def summary(text: str, limit: int = 420) -> str | None:
        for para in text.split("\n\n"):
            if len(para) >= 80 and max(len(l) for l in para.split("\n")) >= 100 and not _SKIP_LINE.match(para.strip()):
                sents = [s for s, _, _ in split_sentences(para) if len(s) >= 30]
                out = ""
                for s in sents[:3]:
                    if len(out) + len(s) > limit and out:
                        break
                    out = (out + " " + s).strip()
                return out[:limit].rstrip() + ("…" if len(out) > limit else "")
        return text[:limit].strip() or None
