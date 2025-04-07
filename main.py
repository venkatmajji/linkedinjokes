import os
import json
from datetime import datetime
import gspread
import requests
from oauth2client.service_account import ServiceAccountCredentials

# === 1. Load Google Service Account from ENV ===
print("⏳ Loading SERVICE_ACCOUNT_JSON...")
service_account_json = os.getenv("SERVICE_ACCOUNT_JSON")

if not service_account_json:
    raise Exception("❌ SERVICE_ACCOUNT_JSON not loaded from environment. Check your Azure Key Vault or app settings.")

try:
    credentials_dict = json.loads(service_account_json)
except json.JSONDecodeError:
    raise Exception("❌ Failed to decode SERVICE_ACCOUNT_JSON. Make sure it's valid JSON.")

# === 2. Authenticate with Google Sheets ===
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
client = gspread.authorize(creds)

sheet = client.open("Majjis-jokes").sheet1
rows = sheet.get_all_records()

# === 3. Determine Next Joke Style ===
styles = ["Corporate Wit", "Playful Nerd", "Dad-Joke"]
last_posted = next((row["Style"] for row in reversed(rows) if str(row["Posted?"]).upper() == "TRUE"), None)
next_style = styles[(styles.index(last_posted) + 1) % len(styles)] if last_posted else styles[0]

# === 4. Select the Next Joke ===
joke_row = next((r for r in rows if r["Style"] == next_style and str(r["Posted?"]).upper() != "TRUE"), None)
if not joke_row:
    print(f"❌ No unposted jokes found for style: {next_style}")
    exit()

joke = joke_row["Joke"]
row_index = rows.index(joke_row) + 2  # account for 1-based indexing in Sheets

print(f"✅ Selected joke (style: {next_style}): {joke}")

# === 5. Prepare LinkedIn Auth ===
access_token = os.getenv("LINKEDIN_ACCESS_TOKEN")
if not access_token:
    raise Exception("❌ Missing LINKEDIN_ACCESS_TOKEN in environment variables.")

headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
    "X-Restli-Protocol-Version": "2.0.0"
}

# === 6. Get LinkedIn Profile ID ===
profile_res = requests.get("https://api.linkedin.com/v2/me", headers=headers)
if profile_res.status_code != 200:
    raise Exception(f"❌ Failed to get LinkedIn profile: {profile_res.text}")

profile_id = profile_res.json()["id"]

# === 7. Optional: Generate Doodle via OpenAI ===
image_url = None
openai_key = os.getenv("OPENAI_API_KEY")
if openai_key:
    try:
        print("🎨 Generating doodle with OpenAI...")
        image_prompt = f"A hand-drawn black and white doodle cartoon representing: {joke}"
        gen = requests.post("https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
            json={"model": "dall-e-3", "prompt": image_prompt, "n": 1, "size": "1024x1024"})
        if gen.ok:
            image_url = gen.json()["data"][0]["url"]
    except Exception as e:
        print(f"⚠️ Failed to generate image: {e}")

# === 8. Post to LinkedIn ===
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
    print("📝 Posting text-only joke to LinkedIn...")
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

post_res = requests.post("https://api.linkedin.com/v2/ugcPosts", headers=headers, json=post_payload)

if post_res.status_code == 201:
    print("✅ Joke posted successfully!")
    sheet.update(f"D{row_index}", "TRUE")
    sheet.update(f"E{row_index}", datetime.now().strftime("%Y-%m-%d"))
    sheet.update(f"F{row_index}", post_res.json().get("id", ""))
else:
    print("❌ Failed to post to LinkedIn:", post_res.text)
