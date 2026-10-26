import functions_framework
import json
import base64
from datetime import datetime, timezone
from shared.supabase_client import get_supabase
from shared.gcp_env import get_project_id
from shared.coverage_quality import assess_leaning
from supabase import Client
from google.cloud import pubsub_v1

from nlp_analysis import analyze_frequencies
from shared.tracing import get_tracer
from opentelemetry import context as otel_context
from opentelemetry import trace as otel_trace

tracer = get_tracer("scorer")


PROJECT_ID = get_project_id()
FINALIZER_TOPIC_ID = "topic-finalize-run"
STAGE_NAME = "scorer"


def get_publisher() -> pubsub_v1.PublisherClient:
    return pubsub_v1.PublisherClient()

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_stage_attempts(supabase: Client, run_date: str, region: str, stage: str) -> int:
    response = (
        supabase.table("region_runs")
        .select(f"{stage}_attempts")
        .eq("run_date", run_date)
        .eq("region", region)
        .limit(1)
        .execute()
    )
    if response.data:
        return int(response.data[0].get(f"{stage}_attempts") or 0)
    return 0


def update_stage_state(
    run_date: str,
    region: str,
    stage: str,
    status: str,
    *,
    error_message: str | None = None,
    increment_attempt: bool = False,
):
    supabase = get_supabase()
    now_iso = _utc_now_iso()
    payload: dict[str, object] = {
        "run_date": run_date,
        "region": region,
        f"{stage}_status": status,
        "last_event_at": now_iso,
    }
    if increment_attempt:
        payload[f"{stage}_attempts"] = _fetch_stage_attempts(supabase, run_date, region, stage) + 1
        payload[f"{stage}_started_at"] = now_iso
    if status == "completed":
        payload[f"{stage}_completed_at"] = now_iso
        payload[f"{stage}_last_error"] = None
        payload["next_retry_at"] = None
    elif status == "failed":
        payload[f"{stage}_last_error"] = error_message
    elif status == "running":
        payload[f"{stage}_last_error"] = None
    supabase.table("region_runs").upsert(payload, on_conflict="run_date,region").execute()


def publish_completion_event(region: str, date: str, stage: str):
    publisher = get_publisher()
    topic_path = publisher.topic_path(PROJECT_ID, FINALIZER_TOPIC_ID)
    payload = json.dumps({"region": region, "date": date, "stage": stage, "status": "completed"}).encode("utf-8")
    future = publisher.publish(topic_path, data=payload)
    print(f"Published completion event {future.result()} for {region} {date} ({stage}).")


def publish_failure_event(region: str, date: str, stage: str):
    publisher = get_publisher()
    topic_path = publisher.topic_path(PROJECT_ID, FINALIZER_TOPIC_ID)
    payload = json.dumps({"region": region, "date": date, "stage": stage, "status": "failed"}).encode("utf-8")
    future = publisher.publish(topic_path, data=payload)
    print(f"Published failure event {future.result()} for {region} {date} ({stage}).")


# ---------------------------------------------------------------------------
# Sentiment Lexicon — AFINN-inspired, scored -5 (very negative) to +5 (very positive)
# Score formula: raw = sum(freq[w] * score[w]) / sum(freq[w] for matched words)
# Scaled to 0–10 via: sentiment = clamp(raw + 5, 0, 10)
# ---------------------------------------------------------------------------
SENTIMENT_LEXICON: dict[str, float] = {
    # Strongly positive
    "excellent": 5, "outstanding": 5, "wonderful": 5, "spectacular": 5, "brilliant": 5,
    "amazing": 4, "fantastic": 4, "superb": 4, "triumph": 4, "victory": 4,
    "celebrate": 4, "peace": 4, "rescue": 4, "freed": 4, "acquitted": 4,
    # Positive
    "good": 3, "great": 3, "success": 3, "win": 3, "won": 3, "award": 3,
    "benefit": 2, "improve": 2, "improved": 2, "safe": 2, "help": 2, "hope": 2,
    "positive": 2, "strong": 2, "progress": 2, "opportunity": 2, "boost": 2,
    "growth": 3, "recovery": 3, "agreement": 2, "approved": 2, "saved": 2,
    "historic": 2, "milestone": 2, "breakthrough": 3, "relief": 2, "support": 1,
    # Mildly negative
    "concern": -1, "difficult": -1, "fall": -1, "cut": -1, "drop": -1,
    "delay": -1, "slow": -1, "struggle": -2, "challenge": -1, "risk": -2,
    "loss": -2, "fail": -2, "failed": -2, "hurt": -2, "decline": -2,
    "problem": -2, "threat": -2, "layoff": -3, "layoffs": -3, "strike": -2,
    "arrested": -3, "charged": -2, "charges": -2, "lawsuit": -2, "trial": -1,
    # Strongly negative
    "bad": -3, "poor": -2, "disaster": -5, "crisis": -4, "tragedy": -5,
    "catastrophe": -5, "collapse": -4, "attack": -3, "murder": -5, "murdered": -5,
    "killed": -4, "dead": -4, "death": -4, "deaths": -4, "fatal": -4,
    "war": -4, "violence": -4, "shooting": -4, "crash": -3, "explosion": -4,
    "scandal": -4, "corruption": -4, "fraud": -4, "abuse": -4,
    "fire": -2, "flood": -3, "earthquake": -3, "storm": -2, "drought": -3,
    "recession": -4, "deficit": -3, "debt": -2, "bankruptcy": -4, "inflation": -3,
    "riot": -4, "protest": -2, "clash": -3, "siege": -4, "hostage": -4,
    "guilty": -3, "convicted": -4, "sentenced": -3, "indicted": -3,
}

# ---------------------------------------------------------------------------
# Political Leaning Lexicons — 0.0 (far left) to 5.0 (far right), 2.5 = neutral
# Score formula: left_mass = sum(freq[w] * weight[w]) for left words
#                right_mass = sum(freq[w] * weight[w]) for right words
#                leaning = right_mass / (left_mass + right_mass) * 5.0
# Defaults to 2.5 if neither side has signal.
# ---------------------------------------------------------------------------
LEFT_LEXICON: dict[str, float] = {
    "climate": 4, "inequality": 4, "progressive": 5, "welfare": 3,
    "union": 4, "unions": 4, "medicare": 4, "medicaid": 4,
    "diversity": 4, "inclusion": 4, "equity": 4, "inclusive": 3,
    "immigrants": 3, "immigration": 2, "refugees": 3, "asylum": 3,
    "renewable": 4, "abortion": 3, "reproductive": 4, "planned": 2,
    "lgbt": 5, "lgbtq": 5, "transgender": 4, "nonbinary": 5,
    "minimum": 3, "redistribution": 5, "taxing": 3, "healthcare": 2,
    "environment": 3, "emissions": 4, "regulation": 2, "regulations": 2,
    "socialist": 5, "socialism": 5, "democratic": 2, "democrat": 3,
    "protest": 2, "activism": 4, "defund": 5, "reparations": 5,
    "racism": 3, "systemic": 4, "gender": 3, "pronoun": 5, "woke": 3,
    "unhoused": 4, "housing": 2, "poverty": 3, "workers": 2, "labour": 3,
    "labor": 3, "striking": 3, "universal": 3, "free": 1,
}

RIGHT_LEXICON: dict[str, float] = {
    "border": 4, "wall": 4, "patriot": 4, "patriots": 4,
    "freedom": 3, "liberty": 3, "conservative": 5, "conservatives": 5,
    "military": 3, "guns": 4, "firearms": 4, "secondamendment": 5,
    "deregulation": 5, "tariff": 4, "tariffs": 4, "taxes": 3,
    "tradition": 3, "sovereign": 4, "sovereignty": 4,
    "deportation": 5, "illegal": 3, "maga": 5,
    "republican": 3, "republicans": 3, "gop": 4,
    "religion": 2, "faith": 2, "church": 2, "prolife": 5, "capitalism": 4,
    "voter": 1, "fraud": 2, "mandate": 3, "censorship": 4,
    "woke": 3, "globalist": 5, "establishment": 2, "deep": 2,
    "sanctuary": 3, "cartel": 4, "fentanyl": 3, "crime": 2, "criminals": 3,
    "militia": 5, "patriotism": 4, "constitution": 3, "amendment": 2,
    "homeschool": 4, "parental": 3, "parents": 2, "inflation": 2,
}

LEANING_PRIOR_MASS = 8.0
LEANING_CONFIDENCE_DISTINCT_TERMS = 3.0
LEANING_CONFIDENCE_TOTAL_MASS = 60.0


def compute_sentiment(frequencies: dict) -> tuple[float, list, list]:
    """
    Returns (sentiment_score 0-10, top_positive, top_negative).
    """
    matched_positive = []
    matched_negative = []
    weighted_sum = 0.0
    total_matched_count = 0

    for word, count in frequencies.items():
        word_lower = word.lower()
        if word_lower in SENTIMENT_LEXICON:
            score = SENTIMENT_LEXICON[word_lower]
            weighted_sum += score * count
            total_matched_count += count
            entry = {"word": word_lower, "score": score, "count": count}
            if score > 0:
                matched_positive.append(entry)
            else:
                matched_negative.append(entry)

    if total_matched_count == 0:
        return 5.0, [], []

    raw_avg = weighted_sum / total_matched_count  # in range [-5, +5]
    scaled = raw_avg + 5.0  # shift to [0, 10]
    sentiment_score = max(0.0, min(10.0, scaled))

    top_positive = sorted(matched_positive, key=lambda x: x["score"] * x["count"], reverse=True)[:5]
    top_negative = sorted(matched_negative, key=lambda x: x["score"] * x["count"])[:5]

    return round(sentiment_score, 2), top_positive, top_negative


# TT and UK are collected for sentiment and wordcloud only. The leaning
# lexicons below are US-specific (MAGA, medicare, deportation, GOP), so
# scoring a non-U.S. region with them yields a confident wrong answer rather
# than a weak one: the UK reads as far left because "labour" is the party's
# name, and TT's score is decided by whether "free" appears in a headline.
# Kept local rather than imported from shared/regions.py because each Cloud
# Function deploys from its own directory.
NON_US_REGIONS = frozenset({"TT", "UK"})


def scores_political_leaning(region: str) -> bool:
    """False for TT and UK, which get sentiment and wordcloud output only."""
    return region not in NON_US_REGIONS


def compute_leaning(frequencies: dict) -> tuple[float, list, list]:
    """
    Returns (leaning_score 0-5, left_indicators, right_indicators).
    0.0 = far left, 5.0 = far right, 2.5 = neutral.
    """
    left_mass = 0.0
    right_mass = 0.0
    left_indicators = []
    right_indicators = []
    distinct_indicator_terms = set()

    for word, count in frequencies.items():
        word_lower = word.lower()
        if word_lower in LEFT_LEXICON:
            weight = LEFT_LEXICON[word_lower] * count
            left_mass += weight
            left_indicators.append({"word": word_lower, "count": count, "weight": round(weight, 2)})
            distinct_indicator_terms.add(word_lower)
        if word_lower in RIGHT_LEXICON:
            weight = RIGHT_LEXICON[word_lower] * count
            right_mass += weight
            right_indicators.append({"word": word_lower, "count": count, "weight": round(weight, 2)})
            distinct_indicator_terms.add(word_lower)

    total_mass = left_mass + right_mass
    if total_mass == 0:
        return 2.5, [], []

    # Add a neutral prior and confidence shrinkage so sparse one-sided hits
    # do not collapse to misleading 0.0 or 5.0 scores.
    smoothed_score = (
        (right_mass + LEANING_PRIOR_MASS)
        / (total_mass + (2 * LEANING_PRIOR_MASS))
    ) * 5.0
    confidence_from_mass = min(1.0, total_mass / LEANING_CONFIDENCE_TOTAL_MASS)
    confidence_from_terms = min(1.0, len(distinct_indicator_terms) / LEANING_CONFIDENCE_DISTINCT_TERMS)
    confidence = confidence_from_mass * confidence_from_terms
    leaning_score = 2.5 + ((smoothed_score - 2.5) * confidence)

    left_indicators = sorted(left_indicators, key=lambda x: x["weight"], reverse=True)[:5]
    right_indicators = sorted(right_indicators, key=lambda x: x["weight"], reverse=True)[:5]

    return round(leaning_score, 2), left_indicators, right_indicators


@functions_framework.cloud_event
def score_region(cloud_event):
    """
    Cloud Event Function triggered by Pub/Sub (topic-generate-wordcloud).
    Consumes region/date/frequencies from the payload, computes sentiment and
    political leaning scores, and upserts them to the regional_sentiment table.
    """
    if 'message' in cloud_event.data and 'data' in cloud_event.data['message']:
        payload = base64.b64decode(cloud_event.data['message']['data']).decode('utf-8')
        try:
            event_json = json.loads(payload)
            region = event_json.get('region')
            date = event_json.get('date')
            frequencies = event_json.get('frequencies')
        except json.JSONDecodeError:
            print("Error: Invalid JSON payload in Pub/Sub message")
            return
    else:
        print("Error: Message data missing from Cloud Event")
        return

    if not region or not date or not frequencies:
        print("Error: 'region', 'date', and 'frequencies' are all required.")
        return

    update_stage_state(date, region, STAGE_NAME, "running", increment_attempt=True)

    print(f"Scoring region={region} date={date} ({len(frequencies)} terms)...")

    score_span = tracer.start_span("score_region", attributes={"region": region, "run_date": date})
    score_span_token = otel_context.attach(otel_trace.set_span_in_context(score_span))

    try:
        sentiment_score, top_positive, top_negative = compute_sentiment(frequencies)

        if scores_political_leaning(region):
            leaning_score, left_indicators, right_indicators = compute_leaning(frequencies)
            print(f"Results — sentiment: {sentiment_score}/10, leaning: {leaning_score}/5 "
                  f"(0=left, 5=right)")
        else:
            leaning_score, left_indicators, right_indicators = None, [], []
            print(f"Results — sentiment: {sentiment_score}/10, leaning: skipped "
                  f"(non-U.S. region, US leaning lexicons do not apply)")

        # Deeper NLP analysis: emotional profile, entities, topics, lexical stats
        with tracer.start_as_current_span("nlp_analysis.analyze_frequencies"):
            nlp_profile = analyze_frequencies(frequencies)
        print(f"NLP profile — emotions: {list(nlp_profile['emotional_profile'].keys())[:4]}, "
              f"topics: {list(nlp_profile['topic_scores'].keys())[:4]}, "
              f"entities: persons={len(nlp_profile['entity_profile'].get('persons', {}))}, "
              f"places={len(nlp_profile['entity_profile'].get('places', {}))}, "
              f"lexical: TTR={nlp_profile['lexical_stats'].get('ttr', 'n/a')}")

        supabase = get_supabase()
        supabase.table("regional_sentiment").upsert({
            "region": region,
            "date": date,
            "sentiment_score": sentiment_score,
            "leaning_score": leaning_score,
            "top_positive_words": top_positive,
            "top_negative_words": top_negative,
            "left_indicators": left_indicators,
            "right_indicators": right_indicators,
            "emotional_profile": nlp_profile["emotional_profile"],
            "entity_profile": nlp_profile["entity_profile"],
            "topic_scores": nlp_profile["topic_scores"],
            "lexical_stats": nlp_profile["lexical_stats"],
        }, on_conflict="region,date").execute()
        update_stage_state(date, region, STAGE_NAME, "completed")
        publish_completion_event(region, date, "scored")

        print(f"Successfully upserted sentiment scores for {region} on {date}.")
    except Exception as exc:
        update_stage_state(date, region, STAGE_NAME, "failed", error_message=str(exc))
        publish_failure_event(region, date, STAGE_NAME)
        print(f"Failed to score region {region} on {date}: {exc}")
        score_span.record_exception(exc)
    finally:
        otel_context.detach(score_span_token)
        score_span.end()

@functions_framework.cloud_event
def score_district(cloud_event):
    """Score a congressional district's frequencies into regional_sentiment.

    District regions are not part of the daily readiness barrier, so unlike
    ``score_region`` this writes no ``region_runs`` state and publishes no
    finalizer event. It is the district-only entry point, triggered on
    ``topic-score-district``. District regions are U.S., so the U.S. leaning
    lexicons apply.
    """
    if 'message' in cloud_event.data and 'data' in cloud_event.data['message']:
        try:
            event_json = json.loads(
                base64.b64decode(cloud_event.data['message']['data']).decode('utf-8')
            )
        except json.JSONDecodeError:
            print("Error: Invalid JSON payload in Pub/Sub message")
            return
    else:
        print("Error: Message data missing from Cloud Event")
        return

    region = event_json.get('region')
    date = event_json.get('date')
    frequencies = event_json.get('frequencies')
    if not region or not date or not frequencies:
        print("Error: 'region', 'date', and 'frequencies' are all required.")
        return

    try:
        sentiment_score, top_positive, top_negative = compute_sentiment(frequencies)
        leaning_score, left_indicators, right_indicators = compute_leaning(frequencies)
        nlp_profile = analyze_frequencies(frequencies)
        # A leaning at the midpoint contributes exactly 0.0 to the coverage
        # component, so a district can render a band that its evidence does not
        # support. Name it; see shared/coverage_quality.py.
        leaning_quality = assess_leaning(leaning_score)
        if not leaning_quality["ok"]:
            print(json.dumps({
                "event": "district_leaning_neutral",
                "region": region,
                "date": date,
                **leaning_quality,
            }, sort_keys=True, default=str))
        get_supabase().table("regional_sentiment").upsert({
            "region": region,
            "date": date,
            "sentiment_score": sentiment_score,
            "leaning_score": leaning_score,
            "top_positive_words": top_positive,
            "top_negative_words": top_negative,
            "left_indicators": left_indicators,
            "right_indicators": right_indicators,
            "emotional_profile": nlp_profile["emotional_profile"],
            "entity_profile": nlp_profile["entity_profile"],
            "topic_scores": nlp_profile["topic_scores"],
            "lexical_stats": nlp_profile["lexical_stats"],
        }, on_conflict="region,date").execute()
        print(f"Successfully upserted district sentiment for {region} on {date}.")
    except Exception as exc:
        print(f"Failed to score district {region} on {date}: {exc}")

# deployment marker: workflow rebuild requested
