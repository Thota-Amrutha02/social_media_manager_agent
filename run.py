"""import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

PPLX_KEY = os.getenv("PERPLEXITY_API_KEY")
if not PPLX_KEY:
    raise RuntimeError("Set PERPLEXITY_API_KEY in your .env file")

# Connect to Perplexity API
client = OpenAI(api_key=PPLX_KEY, base_url="https://api.perplexity.ai")

# Choose one of the supported models: "sonar", "sonar-pro", "sonar-reasoning"
model = "sonar-pro"

response = client.chat.completions.create(
    model=model,
    messages=[
        {"role": "system", "content": "You are a creative assistant."},
        {"role": "user", "content": "Generate a caption, hashtags, and an image prompt for travel to paris."}
    ],
    temperature=0.7
)

print("Response:", response.choices[0].message.content)"""



"""
import os
import requests, base64
from openai import OpenAI   
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()

# ---- Load Keys ----
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
STABILITY_API_KEY = os.getenv("STABILITY_API_KEY")

# ---- Perplexity client ----
perplexity = OpenAI(
    api_key=PERPLEXITY_API_KEY,
    base_url="https://api.perplexity.ai"
)

# ---- Step 1: Generate caption + hashtags + image prompt ----
query = "Generate a short Instagram-style caption, 5-7 hashtags, and an image prompt about travel to paris."

response = perplexity.chat.completions.create(
    model="sonar-pro",
    messages=[
        {"role": "system", "content": "You are a social media content generator."},
        {"role": "user", "content": query}
    ],
)

text_output = response.choices[0].message.content
print("\n---- GENERATED TEXT ----")
print(text_output)

# Extract image prompt
image_prompt = text_output.split("Image prompt:")[-1].strip()

# ---- Step 2: Generate image using Stability AI ----
engine_id = "stable-diffusion-xl-1024-v1-0"
url = f"https://api.stability.ai/v1/generation/{engine_id}/text-to-image"

headers = {
    "Authorization": f"Bearer {STABILITY_API_KEY}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

data = {
    "text_prompts": [{"text": image_prompt}],
    "cfg_scale": 7,
    "height": 1024,
    "width": 1024,
    "samples": 1,
    "steps": 30,
}

resp = requests.post(url, headers=headers, json=data)

if resp.status_code == 200:
    result = resp.json()
    image_base64 = result["artifacts"][0]["base64"]

    # Save + show image
    with open("output.png", "wb") as f:
        f.write(base64.b64decode(image_base64))

    image = Image.open(BytesIO(base64.b64decode(image_base64)))
    image.show()

    print("\n✅ Caption + hashtags + prompt printed above")
    print("✅ Image saved as output.png and opened")
else:
    print("\n❌ Image generation error:", resp.text)"""




import re

from flask import Flask, request, jsonify
import os, requests, base64
from openai import OpenAI
from PIL import Image
from io import BytesIO
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
from flask_cors import CORS
CORS(app)

# ---- Load Keys ----
PERPLEXITY_API_KEY = os.getenv("PERPLEXITY_API_KEY")
STABILITY_API_KEY = os.getenv("STABILITY_API_KEY")

# ---- Perplexity client ----
perplexity = OpenAI(
    api_key=PERPLEXITY_API_KEY,
    base_url="https://api.perplexity.ai"
)

@app.route("/generate", methods=["POST"])
def generate_content():
    try:
        data = request.json
        topic = data.get("topic", "travel to paris")

        # Step 1: Generate caption + hashtags + image prompt
        query = f"Generate a short Instagram-style caption, 5-7 hashtags, and an image prompt about {topic}."

        response = perplexity.chat.completions.create(
            model="sonar-pro",
            messages=[
                {"role": "system", "content": "You are a social media content generator."},
                {"role": "user", "content": query}
            ],
        )

        text_output = response.choices[0].message.content

        # Extract image prompt
        match = re.search(r"image prompt[:\-]*\s*(.*)", text_output, re.IGNORECASE | re.DOTALL)
        if match:
            image_prompt = match.group(1).strip()
        else:
    # fallback: use the whole text if no prompt is found
            image_prompt = text_output.strip()
        # Step 2: Generate image
        engine_id = "stable-diffusion-xl-1024-v1-0"
        url = f"https://api.stability.ai/v1/generation/{engine_id}/text-to-image"

        headers = {
            "Authorization": f"Bearer {STABILITY_API_KEY}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        data = {
            "text_prompts": [{"text": image_prompt}],
            "cfg_scale": 7,
            "height": 1024,
            "width": 1024,
            "samples": 1,
            "steps": 30,
        }


        resp = requests.post(url, headers=headers, json=data)

        if resp.status_code == 200:
            result = resp.json()
            image_base64 = result["artifacts"][0]["base64"]
            image_url = f"data:image/png;base64,{image_base64}"

            return jsonify({
                "success": True,
                "caption_hashtags": text_output,
                "image_url": image_url
            })
        else:
            return jsonify({"success": False, "error": resp.text}), 500


    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
















