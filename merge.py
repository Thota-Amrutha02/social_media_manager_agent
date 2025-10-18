#!/usr/bin/env python3
import re
import os, sys, time, base64, traceback, json, shutil, uuid
from tempfile import NamedTemporaryFile
import requests
from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from PIL import Image
from dotenv import load_dotenv
from openai import OpenAI
from datetime import datetime


# ---- Load environment ----
load_dotenv()
app = Flask(__name__)
CORS(app)

PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
STABILITY_API_KEY = os.getenv("STABILITY_API_KEY")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
IG_USER_ID = os.getenv("IG_USER_ID")
GRAPH_BASE = "https://graph.facebook.com/v21.0"
DEFAULT_IMAGE = os.path.join(os.path.dirname(__file__), "output.png")
SAVED_FILE = "savedprojects.json"
_served_image_path = None

# ---- New: persistent images directory ----
IMAGES_DIR = os.path.join(os.path.dirname(__file__), "served_images")
os.makedirs(IMAGES_DIR, exist_ok=True)

print(f"[env] ACCESS_TOKEN={'SET' if ACCESS_TOKEN else 'MISSING'}, IG_USER_ID={'SET' if IG_USER_ID else 'MISSING'}", flush=True)

# ---- Clients ----
# Perplexity client (OpenAI-like wrapper)
perplexity = OpenAI(api_key=PERPLEXITY_API_KEY, base_url="https://api.perplexity.ai")

# ---------- Helpers ----------

def shrink_and_convert_image(path, max_size=(1080,1080), quality=85):
    try:
        with Image.open(path) as im:
            im.thumbnail(max_size)
            tmp = NamedTemporaryFile(delete=False, suffix=".jpg")
            tmp.close()
            out_path = tmp.name
            im.convert("RGB").save(out_path, "JPEG", quality=quality)
            print(f"[resize] {path} -> {out_path} ({im.size[0]}x{im.size[1]})", flush=True)
            return out_path
    except Exception as e:
        print("[WARN] conversion failed:", e, flush=True)
        return path

# ---- New helper: persist image and return stable URL ----
def persist_image_and_get_url(src_path):
    """
    Copy the processed image to a persistent filename in IMAGES_DIR and
    return a public URL to access it (using PUBLIC_URL if available).
    Returns empty string on failure.
    """
    try:
        if not src_path or not os.path.exists(src_path):
            return ""
        filename = f"img_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
        dst = os.path.join(IMAGES_DIR, filename)
        shutil.copy2(src_path, dst)
        public_url = app.config.get("PUBLIC_URL")
        if public_url:
            return f"{public_url}/images/{filename}"
        else:
            return f"http://127.0.0.1:5000/images/{filename}"
    except Exception as e:
        print("[WARN] persist_image failed:", e, flush=True)
        return ""

def create_and_publish_instagram(image_url, caption, access_token, ig_user_id):
    if not access_token or not ig_user_id:
        raise ValueError("ACCESS_TOKEN or IG_USER_ID missing")

    print("[insta] creating media container...", flush=True)
    create_url = f"{GRAPH_BASE}/{ig_user_id}/media"
    resp = requests.post(create_url, data={
        "image_url": image_url,
        "caption": caption,
        "access_token": access_token
    }, timeout=(10,60))
    print("[insta] response:", resp.text, flush=True)
    resp.raise_for_status()

    media_id = resp.json().get("id")
    if not media_id:
        raise RuntimeError(f"No media ID returned: {resp.json()}")

    print(f"[insta] media id: {media_id}", flush=True)
    publish_url = f"{GRAPH_BASE}/{ig_user_id}/media_publish"
    resp2 = requests.post(publish_url, data={
        "creation_id": media_id,
        "access_token": access_token
    }, timeout=(10,60))
    print("[insta] publish response:", resp2.text, flush=True)
    resp2.raise_for_status()
    print("[insta] published OK!", flush=True)
    return resp2.json()


def save_project(data):
    """Save successfully posted project data into savedprojects.json"""
    try:
        if os.path.exists(SAVED_FILE):
            with open(SAVED_FILE, "r") as f:
                projects = json.load(f)
        else:
            projects = []
    except Exception:
        projects = []

    projects.append(data)

    try:
        with open(SAVED_FILE, "w") as f:
            json.dump(projects, f, indent=4)
    except Exception as e:
        print("[WARN] failed to save project:", e, flush=True)


def strip_instagram_heading(text: str) -> str:
    """
    Remove common heading labels at the start of the text, including:
      - **Instagram-Style Caption**
      - Instagram-Style Caption:
      - Instagram Caption
      - Markdown headings like # Caption, ## Caption, ### Caption
    Only removes heading at the start of the text (or the first line).
    """
    if not text:
        return text

    cleaned = text

    # Remove IG-style headings (existing logic)
    cleaned = re.sub(
        r'(?i)^\s*\*{0,}\s*(?:instagram(?:[-\s]*style)?\s*caption)\s*\*{0,}\s*[:\-]?\s*',
        '',
        cleaned,
        count=1
    )

    # Remove a line that consists only of that heading
    cleaned = re.sub(
        r'(?im)^\s*\*{0,}\s*(?:instagram(?:[-\s]*style)?\s*caption)\s*\*{0,}\s*[:\-]?\s*$\n?',
        '',
        cleaned,
        count=1
    )

    # --- New: Remove Markdown headings like # Caption, ## Caption, ### Caption ---
    cleaned = re.sub(
        r'(?im)^\s*#{1,6}\s*(Instagram(?:[-\s]*Style)?\s*Caption|Caption)\s*[:\-]?\s*$\n?',
        '',
        cleaned,
        count=1
    )

    return cleaned.lstrip()



def format_generated_output(generated_text: str):
    """
    Return (post_text, display_text, image_prompt)
      - display_text: original generated_text (unchanged) - for UI
      - post_text: cleaned caption + hashtags (no headings, no image prompt) - for Instagram
      - image_prompt: extracted image prompt
    """
    if not generated_text:
        return "", "", ""

    original = generated_text.strip()

    # 1) Extract labeled sections
    sections = re.split(r'(?im)(?=^\s*\**\s*(?:Instagram Caption|Instagram-Style Caption|Hashtags|Image Prompt)\s*\**\s*[:\-]?)', original, flags=re.M)
    found = {}
    for sec in sections:
        m = re.match(r'(?im)^\s*\**\s*(Instagram Caption|Instagram-Style Caption|Hashtags|Image Prompt)\s*\**\s*[:\-]?\s*(.*)', sec, re.S)
        if m:
            key = m.group(1).strip().lower()
            content = m.group(2).strip()
            found[key] = content

    caption = found.get('instagram caption', "") or found.get('instagram-style caption', "")
    hashtags = found.get('hashtags', "")
    image_prompt = found.get('image prompt', "")

    # 2) Fallback caption
    if not caption:
        temp = re.sub(r'(?is)\*\*?\s*Image Prompt\s*\*{0,2}\s*[:\-]?\s*.*$', '', original).strip()
        temp = re.sub(r'(?im)^\s*(Hashtags|Instagram Caption|Instagram-Style Caption)\s*[:\-]?\s*', '', temp)
        parts = re.split(r'\n\s*\n', temp)
        caption_candidate = parts[0].strip() if parts and parts[0].strip() else temp.strip()
        caption_candidate_clean = re.sub(r'(#\w[\w-]*)', '', caption_candidate).strip()
        caption = caption_candidate_clean

    # 3) Extract inline hashtags if missing
    if not hashtags:
        hashtags_list = re.findall(r"#\w[\w-]*", original)
        hashtags = " ".join(dict.fromkeys(hashtags_list))

    # 4) Extract image prompt if missing
    if not image_prompt:
        m3 = re.search(r'(?is)(?:\*\*?\s*Image Prompt\s*\*{0,2}\s*[:\-]?\s*)(.*)$', original)
        if m3:
            image_prompt = m3.group(1).strip()
        else:
            m4 = re.search(r'(?im)^(?:Prompt|Image Prompt|Image)\s*[:\-]?\s*(.+)$', original)
            if m4:
                image_prompt = m4.group(1).strip()

    # 5) Clean caption heading
    caption = strip_instagram_heading(caption)

    # 6) 🧹 Clean unwanted ** around hashtags
    hashtags = re.sub(r'\*\*+(?=#)', '', hashtags)   # remove ** before hashtags
    hashtags = re.sub(r'\*\*+', '', hashtags)        # remove any leftover **
    hashtags = hashtags.strip()

    # 7) Final post_text
    post_text = caption.strip()
    if hashtags:
        post_text = f"{post_text}\n\n{hashtags}".strip()

    return post_text, original, image_prompt

# ---------- Flask Endpoints ----------

@app.route("/generate", methods=["POST"])
def generate_content():
    try:
        data = request.json or {}
        topic = data.get("topic", "travel to paris")

        query = f"Generate a short Instagram-style caption, 5-7 hashtags, and an image prompt about {topic}."
        response = perplexity.chat.completions.create(
            model="sonar-pro",
            messages=[
                {"role": "system", "content": "You are a social media content generator."},
                {"role": "user", "content": query}
            ],
        )

        # Perplexity client returns choices similar to OpenAI-style; adapt defensively
        try:
            text_output = response.choices[0].message.content
        except Exception:
            # Try alternative shape
            text_output = getattr(response.choices[0], "text", "") if getattr(response, "choices", None) else ""

        if not text_output:
            # As fallback, convert entire response to string
            text_output = str(response)

        # Extract cleaned caption/hashtags and image prompt
        post_text, display_text, image_prompt = format_generated_output(text_output)
        image_prompt_for_gen = image_prompt or (display_text or topic)

        # Generate image via Stability API
        engine_id = "stable-diffusion-xl-1024-v1-0"
        url = f"https://api.stability.ai/v1/generation/{engine_id}/text-to-image"
        headers = {
            "Authorization": f"Bearer {STABILITY_API_KEY}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        payload = {
            "text_prompts": [{"text": image_prompt_for_gen}],
            "cfg_scale": 7,
            "height": 1024,
            "width": 1024,
            "samples": 1,
            "steps": 30,
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=(10,120))
        if resp.status_code != 200:
            # log and return a response with no image but with text
            print("[stability] non-200:", resp.status_code, resp.text, flush=True)
            return jsonify({
                "success": True,
                "display_text": display_text,
                "post_text": post_text,
                "caption_hashtags": post_text,
                "image_prompt": image_prompt_for_gen,
                "image_url": ""  # no image available
            })

        result = resp.json()
        # result["artifacts"][0]["base64"] as in your original code
        try:
            image_base64 = result["artifacts"][0]["base64"]
            image_url = f"data:image/png;base64,{image_base64}"
        except Exception as e:
            print("[stability] missing artifacts:", e, flush=True)
            image_url = ""

        # Return both post_text and caption_hashtags for compatibility
        return jsonify({
            "success": True,
            "display_text": display_text,
            "post_text": post_text,
            "caption_hashtags": post_text,   # alias for older frontend
            "image_prompt": image_prompt_for_gen,
            "image_url": image_url
        })

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/image.jpg")
def serve_image():
    if not _served_image_path or not os.path.exists(_served_image_path):
        return "No image served", 404
    return send_file(_served_image_path, mimetype="image/jpeg")


# ---- New route for persisted images ----
@app.route("/images/<path:filename>")
def serve_persisted_image(filename):
    # Serve from served_images/ directory
    return send_from_directory(IMAGES_DIR, filename)


@app.route("/post", methods=["POST"])
def post_to_instagram():
    global _served_image_path
    try:
        caption = ""
        image_url = None
        display_text = ""

        # 1) If frontend sent a file via form-data
        if request.files.get("image"):
            f = request.files["image"]
            tmp_path = NamedTemporaryFile(delete=False, suffix=".jpg").name
            f.save(tmp_path)
            processed_path = shrink_and_convert_image(tmp_path)
            _served_image_path = processed_path
            raw_caption = request.form.get("caption", "") or ""
            # If client provided raw caption, use it, otherwise try to parse
            caption, display_text, _ = format_generated_output(raw_caption)
            # Strip heading if client accidentally included it
            caption = strip_instagram_heading(caption)

        # 2) If frontend sent JSON with base64 image or data URL
        elif request.is_json:
            data = request.get_json()
            generated_text = data.get("caption", "") or data.get("post_text", "") or ""
            img_data_url = data.get("image_url") or data.get("imageData") or ""
            display_text = data.get("display_text", generated_text)
            caption, _, _ = format_generated_output(generated_text)
            # ensure we remove heading from whatever client passed
            caption = strip_instagram_heading(caption)

            if not img_data_url:
                return jsonify({"success": False, "error": "No image_url provided"}), 400

            if img_data_url.startswith("data:image"):
                header, base64_data = img_data_url.split(",", 1)
                tmp_path = NamedTemporaryFile(delete=False, suffix=".jpg").name
                with open(tmp_path, "wb") as f:
                    f.write(base64.b64decode(base64_data))
                processed_path = shrink_and_convert_image(tmp_path)
                _served_image_path = processed_path
            else:
                # If it's a remote URL, accept it (IG API accepts remote images); set image_url directly
                _served_image_path = None
                image_url = img_data_url
        else:
            return jsonify({"success": False, "error": "No image provided"}), 400

        # If we don't already have an image_url (external or data-url earlier), persist the current local image
        public_url = app.config.get("PUBLIC_URL")
        if not image_url:
            if _served_image_path:
                # persist the processed image to a stable file and get a URL
                persisted_url = persist_image_and_get_url(_served_image_path)
                if persisted_url:
                    image_url = persisted_url
                else:
                    # fallback to old behaviour if persistence failed
                    if public_url:
                        image_url = f"{public_url}/image.jpg"
                    else:
                        image_url = "http://127.0.0.1:5000/image.jpg"
            else:
                return jsonify({"success": False, "error": "No image available to post"}), 400

                # Ensure caption is clean, valid, and not None
        if not caption:
            caption = ""

        # Safety: strip any stray newlines or unicode control chars that IG rejects
        caption = caption.replace("\r", "").replace("\u2028", "").replace("\u2029", "").strip()

        # Debugging log — safe to leave
        print(f"[insta-debug] Final caption being posted ({len(caption)} chars): {repr(caption[:300])}", flush=True)

        # Instagram caption limit = 2200 characters
        if len(caption) > 2200:
            print(f"[warn] caption too long ({len(caption)}). Trimming to 2200 chars.", flush=True)
            caption = caption[:2200]

        # Now create and publish as before
        publish = create_and_publish_instagram(image_url, caption, ACCESS_TOKEN, IG_USER_ID)

        # ✅ Save posted project
        save_project({
            "caption_display": display_text or caption,
            "image_url": image_url,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "publish_response": publish
        })

        return jsonify({"success": True, "publish": publish})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/savedprojects", methods=["GET"])
def get_saved_projects():
    if os.path.exists(SAVED_FILE):
        with open(SAVED_FILE, "r") as f:
            data = json.load(f)
        return jsonify(data)
    return jsonify([])


# ---------- Main ----------
if __name__ == "__main__":
    print("[server] Starting Flask on 127.0.0.1:5000")
    from pyngrok import ngrok
    ngrok.set_auth_token(os.getenv("NGROK_AUTH_TOKEN", ""))  # optional

    try:
        public_url = ngrok.connect(5000).public_url
        print(f"[ngrok] Public URL: {public_url}")
        app.config["PUBLIC_URL"] = public_url
    except Exception as e:
        print("[ngrok] failed to start (continuing without tunnel):", e, flush=True)
        app.config["PUBLIC_URL"] = None

    app.run(port=5000, debug=False, use_reloader=False)
