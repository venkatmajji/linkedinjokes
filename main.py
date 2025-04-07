import os
import json
from datetime import datetime
import gspread
import requests
from oauth2client.service_account import ServiceAccountCredentials

# === 0. DEBUG: Verify service account JSON is properly loaded ===
print("🔍 Checking SERVICE_ACCOUNT_JSON...")
service_account_json = os.getenv("SERVICE_ACCOUNT_JSON")

if not service_account_json:
    raise Exception("❌ SERVICE_ACCOUNT_JSON not found in environment.")

try:
    credentials_dict = json.loads(service_account_json)
    print("✅ SERVICE_ACCOUNT_JSON successfully parsed!")
    print("🔐 Service Account Email:", credentials_dict.get("client_email"))
except json.JSONDecodeError as e:
    raise Exception("❌ Failed to decode SERVICE_ACCOUNT_JSON. Check if \\n are escaped correctly.") from e

# === 1. Authenticate with Google Sheets ===
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
client = gspread.authorize(creds)
sheet = client.open("Majjis-jokes").sheet1
rows = sheet.get_all_records()

# === 2. Joke style rotation ===
styles = ["Corporate Wit", "Playful Nerd", "Dad-Joke"]
last_posted = next((row["Style"] for row in reversed(rows) if str(row["Posted?"]).upper() == "TRUE"), None)
next_style = styles[(styles.index(last_posted) + 1) % len(styles)] if last_posted else styles[0]

# === 3. Select next joke ===
joke_row = next((r for r in rows if r["Style"] == next_style and str(r["Posted?"]).upper() != "TRUE"), None)
if not joke_row:
    print(f"❌ No unposted jokes found for style: {next_style}")
    exit()

joke = joke_row["Joke"]
row_index = rows.index(joke_row) + 2
print(f"📝 Selected joke ({next_style}): {joke}")

# === 4. LinkedIn Auth ===
access_token = os.getenv("LINKEDIN_ACCESS_TOKEN")
if not access_token:
    raise Exception("❌ Missing LINKEDIN_ACCESS_TOKEN in environment.")

headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
    "X-Restli-Protocol-Version": "2.0.0"
}

# === 5. Get LinkedIn profile ID ===
profile_res = requests.get("https://api.linkedin.com/v2/me", headers=headers)
if profile_res.status_code != 200:
    raise Exception(f"❌ Failed to get LinkedIn profile: {profile_res.text}")

profile_id = profile_res.json()["id"]

# === 6. Optional: Generate Doodle with OpenAI ===
image_url = None
openai_key = os.getenv("OPENAI_API_KEY")
if openai_key:
    try:
        print("🎨 Generating doodle via OpenAI...")
        image_prompt = f"A hand-drawn doodle cartoon representing: {joke}"
        gen = requests.post("https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
            json={"model": "dall-e-3", "prompt": image_prompt, "n": 1, "size": "1024x1024"})
        if gen.ok:
            image_url = gen.json()["data"][0]["url"]
    except Exception as e:
        print(f"⚠️ Doodle generation failed: {e}")

# === 7. Prepare LinkedIn post ===
if image_url:
    print("📤 Uploading image to LinkedIn...")
    reg = requests.post("https://api.linkedin.com/v2/assets?action=registerUpload", headers=headers, json={
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": f"urn:li:person:{profile_id}",
            "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}]
        }
    })

    upload_info = reg.json()
    upload_url = upload_info["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
    asset_urn = upload_info["value"]["asset"]

    img_data = requests.get(image_url).content
    requests.put(upload_url, headers={"Content-Type": "image/png"}, data=img_data)

    post_payload = {
        "author": f"urn:li:person:{profile_id}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": joke},
                "shareMediaCategory": "IMAGE",
                "media": [{"status": "READY", "media": asset_urn, "title": {"text": "Majji's Weekly Joke"}}]
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }
else:
    print("📎 Posting text-only joke to LinkedIn...")
    post_payload = {
        "author": f"urn:li:person:{profile_id}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": joke},
                "shareMediaCategory": "NONE"
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }

# === 8. Post to LinkedIn ===
post_res = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=post_payload)

if post_res.status_code == 201:
    print("✅ Joke posted to LinkedIn!")
    sheet.update(f"D{row_index}", "TRUE")
    sheet.update(f"E{row_index}", datetime.now().strftime("%Y-%m-%d"))
    sheet.update(f"F{row_index}", post_res.json().get("id", ""))
else:
    print("❌ Failed to post to LinkedIn:", post_res.text)
