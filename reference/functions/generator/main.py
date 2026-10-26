import functions_framework
import json
import base64
from datetime import datetime, timezone
from wordcloud import WordCloud
from PIL import ImageDraw, ImageFont
from shared.supabase_client import get_supabase
from shared.gcp_env import get_project_id
from supabase import Client
from google.cloud import pubsub_v1
from generator_object_store import put_bytes, storage_provider

from shared.tracing import get_tracer
from opentelemetry import context as otel_context
from opentelemetry import trace as otel_trace

tracer = get_tracer("generator")


PROJECT_ID = get_project_id()
FINALIZER_TOPIC_ID = "topic-finalize-run"
STAGE_NAME = "generator"


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

def save_to_db(region: str, date: str, frequencies: dict, image_path: str):
    """
    Connects to Supabase to save frequencies and upload the generated image.
    """
    supabase = get_supabase()
    bucket_name = "newspics"
    storage_path = f"{region}/wordcloud_{region}_{date}.png"
    
    # 1. Save frequencies
    print(f"Saving frequencies for {region} on {date} to Supabase...")
    supabase.table("word_frequencies").upsert({
        "region": region,
        "date": date,
        "frequencies": frequencies
    }, on_conflict="region,date").execute()
    
    # 2. Upload image to the configured object store.
    provider = storage_provider()
    print(f"Uploading wordcloud to {provider} storage at {storage_path}...")
    if provider == "r2":
        with open(image_path, "rb") as image_file:
            put_bytes(
                bucket_role=bucket_name,
                key=storage_path,
                body=image_file.read(),
                content_type="image/png",
            )
    else:
        with open(image_path, "rb") as image_file:
            # The Supabase Python SDK uses string "true" for its upsert option.
            supabase.storage.from_(bucket_name).upload(
                file=image_file,
                path=storage_path,
                file_options={"content-type": "image/png", "x-upsert": "true"},
            )
        
    # 3. Save image metadata
    print(f"Saving image metadata for {region} on {date} to Supabase...")
    supabase.table("generated_images").upsert({
        "region": region,
        "date": date,
        "storage_url": storage_path
    }, on_conflict="region,date").execute()
    
    print("Database sync complete.")


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

@functions_framework.cloud_event
def generate_wordcloud(cloud_event):
    """Cloud Event Function triggered by Pub/Sub to generate a wordcloud from frequencies."""
    
    # Parse the incoming base64 Pub/Sub message
    if 'message' in cloud_event.data and 'data' in cloud_event.data['message']:
        payload = base64.b64decode(cloud_event.data['message']['data']).decode('utf-8')
        try:
            event_json = json.loads(payload)
            region = event_json.get('region')
            date = event_json.get('date', 'unknown-date')
            frequencies = event_json.get('frequencies')
        except json.JSONDecodeError:
            print("Error: Invalid JSON payload in Pub/Sub message")
            return
    else:
        print("Error: Message data missing from Cloud Event")
        return
        
    if not region or not frequencies:
        print("Error: Invalid payload. 'frequencies' and 'region' are required.")
        return

    update_stage_state(date, region, STAGE_NAME, "running", increment_attempt=True)

    generate_span = tracer.start_span("generate_wordcloud", attributes={"region": region, "run_date": date})
    generate_span_token = otel_context.attach(otel_trace.set_span_in_context(generate_span))

    try:
        # Generate word cloud
        wordcloud = WordCloud(width=800, height=400, background_color='white').generate_from_frequencies(frequencies)
        
        # Convert to PIL Image to allow drawing
        img = wordcloud.to_image()
        
        # Draw text on the bottom right
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("arial.ttf", 20)
        except IOError:
            font = ImageFont.load_default()
            
        text = f"{region} | {date}"
        
        # Calculate text position (bottom right with 15px padding)
        if hasattr(font, 'getbbox'):
            bbox = font.getbbox(text)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
        else:
            text_width, text_height = draw.textsize(text, font=font)
            
        x = img.width - text_width - 15
        y = img.height - text_height - 15
        
        # Draw text (with a slight drop shadow for readability against random words)
        draw.text((x+1, y+1), text, font=font, fill="black")
        draw.text((x, y), text, font=font, fill="gray")
        
        # Save to a temporary file
        tmp_path = f"/tmp/wordcloud_{region}_{date}.png"
        img.save(tmp_path)
        
        # Save to Supabase (DB + Storage)
        with tracer.start_as_current_span("supabase.save_to_db", attributes={"region": region, "run_date": date}):
            save_to_db(region, date, frequencies, tmp_path)
        update_stage_state(date, region, STAGE_NAME, "completed")
        publish_completion_event(region, date, "generated")
        
        print(f"Successfully generated wordcloud for {region} and logged to DB.")
        
    except Exception as e:
        update_stage_state(date, region, STAGE_NAME, "failed", error_message=str(e))
        publish_failure_event(region, date, STAGE_NAME)
        print(f"Failed to generate wordcloud: {e!s}")
        generate_span.record_exception(e)
    finally:
        otel_context.detach(generate_span_token)
        generate_span.end()

# gen2 python313 - final
# deployment marker: workflow rebuild requested
