"""Report / chart texts in Ukrainian and English. Findings are generated from numbers, not by the LLM."""
from __future__ import annotations

LANG_NAMES = {
    "uk": {
        "en": "англійська", "uk": "українська", "pl": "польська", "cs": "чеська", "sk": "словацька",
        "de": "німецька", "fr": "французька", "es": "іспанська", "it": "італійська", "pt": "португальська",
        "ro": "румунська", "hu": "угорська", "bg": "болгарська", "hr": "хорватська", "sr": "сербська",
        "sl": "словенська", "lt": "литовська", "lv": "латиська", "et": "естонська", "fi": "фінська",
        "sv": "шведська", "no": "норвезька", "da": "данська", "nl": "нідерландська", "el": "грецька",
        "tr": "турецька", "ru": "російська", "be": "білоруська", "ka": "грузинська", "hy": "вірменська",
        "az": "азербайджанська", "kk": "казахська", "uz": "узбецька", "ar": "арабська", "he": "іврит",
        "fa": "перська", "hi": "гінді", "bn": "бенгальська", "id": "індонезійська", "ms": "малайська",
        "vi": "вʼєтнамська", "th": "тайська", "ja": "японська", "ko": "корейська", "zh": "китайська",
        "simple": "проста англійська", "ca": "каталанська", "eu": "баскська", "gl": "галісійська",
    },
    "en": {
        "en": "English", "uk": "Ukrainian", "pl": "Polish", "cs": "Czech", "sk": "Slovak", "de": "German",
        "fr": "French", "es": "Spanish", "it": "Italian", "pt": "Portuguese", "ro": "Romanian",
        "hu": "Hungarian", "bg": "Bulgarian", "hr": "Croatian", "sr": "Serbian", "sl": "Slovenian",
        "lt": "Lithuanian", "lv": "Latvian", "et": "Estonian", "fi": "Finnish", "sv": "Swedish",
        "no": "Norwegian", "da": "Danish", "nl": "Dutch", "el": "Greek", "tr": "Turkish", "ru": "Russian",
        "be": "Belarusian", "ka": "Georgian", "hy": "Armenian", "az": "Azerbaijani", "kk": "Kazakh",
        "uz": "Uzbek", "ar": "Arabic", "he": "Hebrew", "fa": "Persian", "hi": "Hindi", "bn": "Bengali",
        "id": "Indonesian", "ms": "Malay", "vi": "Vietnamese", "th": "Thai", "ja": "Japanese",
        "ko": "Korean", "zh": "Chinese", "simple": "Simple English", "ca": "Catalan", "eu": "Basque",
        "gl": "Galician",
    },
}

T = {
    "uk": {
        "direction": {"growing": "зростає", "declining": "спадає", "stable": "стабільний",
                      "insufficient_data": "мало даних"},
        "confidence": {"high": "висока", "medium": "середня", "low": "низька"},
        "subtitle": "Wikipedia · перегляди людьми (без ботів), усі пристрої, редиректи враховано · {start} — {end} ({n} міс.)",
        "question": "Питання",
        "table": ["Мова", "Медіана/міс", "Перегляди, 12 міс", "Скориг. зміна", "Міс. > торік", "Тренд/рік", "Довіра · напрям"],
        "chart_trend_multi": "Динаміка інтересу (індекс, перші 12 міс = 100; ковзне 3 міс)",
        "chart_trend_single": "Перегляди на місяць (ковзне 3 міс; тонка лінія — фактичні)",
        "chart_share": "Інтенсивність: переглядів на 1 млн переглядів розділу",
        "findings": "Ключові знахідки (згенеровано з даних)",
        "conclusion": "Висновок і рекомендація",
        "confidence_head": "Чому такий рівень довіри:",
        "method": "Методологія й обмеження",
        "method_text": (
            "Джерело: Wikimedia Pageviews API (agent=user — без відомих ботів, усі пристрої); статті зіставлено через "
            "Wikidata, перегляди редиректів додано. Головний показник — «скоригована зміна»: як змінилася частка теми "
            "в усіх переглядах мовного розділу (останні 12 міс проти попередніх 12, сезонно-нейтрально). Це відділяє "
            "інтерес до теми від зміни трафіку самої Wikipedia (частина читачів іде до AI-асистентів). «Перегляди, 12 міс» "
            "— сира зміна для контексту. «Міс. > торік» — у скількох з останніх 12 міс частка вища, ніж роком раніше. "
            "Тренд — Theil–Sen на десезоналізованому ряді частки, значущість — тест Манна–Кендалла. Довіра — частка "
            "пройдених перевірок (послідовність, стійкість до піків, узгодженість із сирими переглядами, значущість "
            "тренду), обмежена обсягом і якістю даних. Обмеження: інтерес до статті ≠ попит на продукт чи готовність "
            "платити; мовний розділ ≠ країна; частина ботів лишається; одна стаття — лише проксі теми."
        ),
        "footer": "Run {run} · дані завантажено {date} · wiki-interest-research",
        "no_article": "статті немає",
        "f_lang": "{name}: інтерес {direction}: {adj} з поправкою на трафік розділу (сирі перегляди {raw}); у {up} з 12 міс. частка вища, ніж торік; довіра {conf}.",
        "f_lang_short": "{name}: інтерес {direction}: {adj} з поправкою на трафік розділу (сирі перегляди {raw}); період < 24 міс., довіра {conf}.",
        "f_context": "Трафік самої Wikipedia змінився ({items}), тому сирі перегляди {bias}; орієнтуйтеся на скориговану зміну.",
        "f_bias_down": "занижують інтерес",
        "f_bias_up": "завищують інтерес",
        "f_spike": "{name}: сплеск у {month} ({x}× медіани) — ймовірно, новинний привід; без 2 найбільших місяців скориг. зміна {ex}.",
        "f_seasonal": "{name}: виражена сезонність (піки в місяцях {months}) — порівнюйте рік до року, а не сусідні місяці.",
        "f_missing": "{name}: статті про тему немає — це може означати низький інтерес або незайняту нішу; потрібна інша перевірка.",
        "f_low_volume": "{name}: лише ~{median} переглядів на місяць — абсолютна аудиторія мала, висновки попередні.",
        "f_rank": "Відносний рейтинг за вашими критеріями ({weights}): {order}.",
        "f_size": "Розмір аудиторії (медіана переглядів на місяць): {order}.",
        "f_ambiguous": "Проаналізовано «{label}» ({desc}), а не інші значення цієї назви: {alts}.",
        "limitations": "Обмеження: інтерес до статті у Wikipedia ≠ попит на продукт чи готовність платити; мовний розділ ≠ країна.",
        "draft_head": "DRAFT FACTS ({lang}) — use these sentences as the factual part of your answer (you may shorten them), then add your recommendation:",
        "f_long": "{name}: за весь період ({n} міс.) скориг. зміна {long} (≈{cagr} на рік), сирі перегляди {raw}.",
        "check": {
            "consistency": "у {up} з {n} міс. частка вища, ніж торік",
            "robust_to_spikes": "без 2 найбільших місяців: {value}",
            "raw_agrees": "сирі перегляди {value} (розділ {project})",
            "significant_trend": "тренд {trend}/рік, p={p}",
            "no_consistent_shift": "у {up} з {n} міс. частка вища, ніж торік",
            "stable_without_spikes": "без 2 найбільших місяців: {value}",
            "no_significant_trend": "тренд {trend}/рік, p={p}",
            "cap_low": "обмеження до «низька»: {flags}",
            "cap_medium": "обмеження до «середня»: {flags}",
            "insufficient_data": "недостатньо даних",
        },
        "flag": {
            "low_volume": "малий обсяг", "modest_volume": "помірний обсяг", "short_period": "період < 24 міс.",
            "too_short": "період < 6 міс.", "high_automated": "висока частка ботів",
            "article_new_or_renamed": "стаття нова/перейменована в періоді", "gaps": "місяці без переглядів",
            "news_spikes": "новинні сплески", "seasonal_peaks": "сезонні піки",
            "incomplete_basket": "не всі статті теми є в цій мові", "disambiguation": "сторінка неоднозначності",
        },
    },
    "en": {
        "direction": {"growing": "growing", "declining": "declining", "stable": "stable",
                      "insufficient_data": "insufficient data"},
        "confidence": {"high": "high", "medium": "medium", "low": "low"},
        "subtitle": "Wikipedia · human pageviews (agent=user), all devices, redirects included · {start} — {end} ({n} mo.)",
        "question": "Question",
        "table": ["Language", "Median/mo", "Views, 12 mo", "Adjusted chg", "Mo. > last yr", "Trend/yr", "Confidence · direction"],
        "chart_trend_multi": "Interest over time (index, first 12 mo = 100; 3-mo rolling)",
        "chart_trend_single": "Monthly views (3-mo rolling; thin line = actual)",
        "chart_share": "Intensity: views per 1M views of the language edition",
        "findings": "Key findings (generated from data)",
        "conclusion": "Conclusion and recommendation",
        "confidence_head": "Why this confidence level:",
        "method": "Method and limitations",
        "method_text": (
            "Source: Wikimedia Pageviews API (agent=user, i.e. known bots excluded; all devices); articles matched via "
            "Wikidata; redirect views added. Primary metric = 'adjusted change': how the topic's share of all views "
            "of that language edition changed (last 12 months vs previous 12, season-neutral). This separates interest "
            "in the topic from shifts in Wikipedia's own traffic (some readers move to AI assistants). 'Views, 12 mo' "
            "= raw change, for context. 'Mo. > last yr' = how many of the last 12 months had a higher share than a "
            "year earlier. Trend = Theil-Sen on the deseasonalised share, significance = Mann-Kendall. Confidence = "
            "share of passed checks (consistency, robustness to spikes, agreement with raw views, trend significance), "
            "capped by volume and data quality. Limitations: article interest is not product demand or willingness to "
            "pay; a language edition is not a country; some bots remain; one article is only a proxy for a topic."
        ),
        "footer": "Run {run} · data fetched {date} · wiki-interest-research",
        "no_article": "no article",
        "f_lang": "{name}: interest {direction}: {adj} adjusted for edition traffic (raw views {raw}); share above last year in {up} of 12 months; confidence {conf}.",
        "f_lang_short": "{name}: interest {direction}: {adj} adjusted for edition traffic (raw views {raw}); period < 24 mo., confidence {conf}.",
        "f_context": "Wikipedia's own traffic changed ({items}), so raw views {bias}; rely on the adjusted change.",
        "f_bias_down": "understate interest",
        "f_bias_up": "overstate interest",
        "f_spike": "{name}: spike in {month} ({x}× median), likely news-driven; without the 2 largest months the adjusted change is {ex}.",
        "f_seasonal": "{name}: strong seasonality (peaks in months {months}); compare year over year, not adjacent months.",
        "f_missing": "{name}: no article on this topic; either low interest or an unserved niche, needs another check.",
        "f_low_volume": "{name}: only ~{median} views per month; the absolute audience is small, conclusions are tentative.",
        "f_rank": "Relative ranking by your criteria ({weights}): {order}.",
        "f_size": "Audience size (median views per month): {order}.",
        "f_ambiguous": "Analysed '{label}' ({desc}), not other meanings of this name: {alts}.",
        "limitations": "Limitations: interest in a Wikipedia article ≠ product demand or willingness to pay; a language edition ≠ a country.",
        "draft_head": "DRAFT FACTS ({lang}) — use these sentences as the factual part of your answer (you may shorten them), then add your recommendation:",
        "f_long": "{name}: over the whole period ({n} mo.) adjusted change {long} (≈{cagr} per year), raw views {raw}.",
        "check": {
            "consistency": "share above last year in {up} of {n} months",
            "robust_to_spikes": "without the 2 largest months: {value}",
            "raw_agrees": "raw views {value} (edition {project})",
            "significant_trend": "trend {trend}/yr, p={p}",
            "no_consistent_shift": "share above last year in {up} of {n} months",
            "stable_without_spikes": "without the 2 largest months: {value}",
            "no_significant_trend": "trend {trend}/yr, p={p}",
            "cap_low": "capped at low: {flags}",
            "cap_medium": "capped at medium: {flags}",
            "insufficient_data": "insufficient data",
        },
        "flag": {
            "low_volume": "low volume", "modest_volume": "modest volume", "short_period": "period < 24 mo.",
            "too_short": "period < 6 mo.", "high_automated": "high bot share",
            "article_new_or_renamed": "article new/renamed within period", "gaps": "months without views",
            "news_spikes": "news spikes", "seasonal_peaks": "seasonal peaks",
            "incomplete_basket": "not all topic articles exist in this language",
            "disambiguation": "disambiguation page",
        },
    },
}


def t(lang: str) -> dict:
    return T.get(lang, T["en"])


def lang_name(code: str, ui: str = "en") -> str:
    return LANG_NAMES.get(ui, LANG_NAMES["en"]).get(code, code)


def pct(x: float | None, digits: int = 0) -> str:
    if x is None:
        return "—"
    return f"{x * 100:+.{digits}f}%"


def render_check(check: dict, ui: str) -> str:
    tmpl = t(ui)["check"].get(check["code"], check["code"])
    params = dict(check)
    for key in ("value", "project", "trend"):
        if key in params:
            params[key] = pct(params[key])
    if "p" in params:
        params["p"] = f"{params['p']:.3f}"
    if "flags" in params:
        params["flags"] = ", ".join(t(ui)["flag"].get(f, f) for f in params["flags"])
    try:
        text = tmpl.format(**params)
    except (KeyError, IndexError):
        text = tmpl
    return ("✓ " if check["ok"] else "✗ ") + text
