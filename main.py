# Main bot script goes here (same as earlier main.py with doodle + LinkedIn posting)
# Placeholder comment: paste actual script content here if needed.
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import requests
import json
from datetime import datetime
import os
import random

# --- 1. Load Google Service Account JSON from Azure Key Vault (via env var) ---
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
service_account_json = os.getenv("SERVICE_ACCOUNT_JSON")
if not service_account_json:
    raise Exception("SERVICE_ACCOUNT_JSON not found in environment.")
creds = ServiceAccountCredentials.from_json_keyfile_dict(json.loads(service_account_json), scope)
client = gspread.authorize(creds)

# --- 2. Joke Rotation Logic ---
sheet = client.open("Majjis-jokes").sheet1
rows = sheet.get_all_records()
styles = ["Corporate Wit", "Playful Nerd", "Dad-Joke"]

# Find last posted style
last_posted = next((row["Style"] for row in reversed(rows) if row["Posted?"] == "TRUE"), None)
next_style = styles[(styles.index(last_posted) + 1) % len(styles)] if last_posted else styles[0]

# Pick the next unposted joke in that style
joke_row = next((row for row in rows if row["Style"] == next_style and row["Posted?"] == "FALSE"), None)
if not joke_row:
    print(f"No unposted jokes found in style: {next_style}")
    exit()

joke = joke_row["Joke"]
row_index = rows.index(joke_row) + 2  # for gspread (1-based, +1 for header)

# --- 3. LinkedIn API Setup ---
access_token = os.getenv("LINKEDIN_ACCESS_TOKEN")
if not access_token:
    raise Exception("LINKEDIN_ACCESS_TOKEN is missing.")

# Get LinkedIn Profile ID
headers = {
    "Authorization": f"Bearer {access_token}"
}
profile_res = requests.get("https://api.linkedin.com/v2/me", headers=headers)
if profile_res.status_code != 200:
    raise Exception(f"Failed to get LinkedIn profile ID: {profile_res.text}")

profile_id = profile_res.json()["id"]

# --- 4. Optional: Generate a Doodle Image via OpenAI ---
image_url = None
openai_key = os.getenv("OPENAI_API_KEY")
if openai_key:
    image_prompt = f"A hand-drawn doodle-style black and white cartoon representing: {joke}"
    gen_res = requests.post(
        "https://api.openai.com/v1/images/generations",
        headers={
            "Authorization": f"Bearer {openai_key}",
            "Content-Type": "application/json"
        },
        json={
            "model": "dall-e-3",
            "prompt": image_prompt,
            "size": "1024x1024",
            "n": 1
        }
    )
    if gen_res.status_code == 200:
        image_url = gen_res.json()["data"][0]["url"]

# --- 5. Post to LinkedIn ---
post_headers = {
    "Authorization": f"Bearer {access_token}",
    "X-Restli-Protocol-Version": "2.0.0",
    "Content-Type": "application/json"
}

if image_url:
    # Step 1: Register image upload
    register_upload_url = "https://api.linkedin.com/v2/assets?action=registerUpload"
    upload_request = {
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": f"urn:li:person:{profile_id}",
            "serviceRelationships": [
                {
                    "relationshipType": "OWNER",
                    "identifier": "urn:li:userGeneratedContent"
                }
            ]
        }
    }
    reg_res = requests.post(register_upload_url, headers=post_headers, json=upload_request)
    upload_info = reg_res.json()
    upload_url = upload_info["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
    asset_urn = upload_info["value"]["asset"]

    # Step 2: Upload image
    img_res = requests.get(image_url)
    requests.put(upload_url, headers={"Content-Type": "image/png"}, data=img_res.content)

    # Step 3: Create post with image
    post_data = {
        "author": f"urn:li:person:{profile_id}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": joke},
                "shareMediaCategory": "IMAGE",
                "media": [{
                    "status": "READY",
                    "media": asset_urn,
                    "title": {"text": "Weekly Joke"}
                }]
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }
else:
    # Post text-only joke
    post_data = {
        "author": f"urn:li:person:{profile_id}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": joke},
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {
            "com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"
        }
    }

# Send the post
res = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=post_headers, json=post_data)

if res.status_code == 201:
    print(f"✅ Joke posted: {next_style}")
    sheet.update(f"D{row_index}", "TRUE")
    sheet.update(f"E{row_index}", datetime.now().strftime("%Y-%m-%d"))
    sheet.update(f"F{row_index}", res.json().get("id", ""))
else:
    print(f"❌ Failed to post joke: {res.status_code} - {res.text}")
