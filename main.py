import os
import json
from datetime import datetime
import gspread
import requests
from oauth2client.service_account import ServiceAccountCredentials

# === 0. DEBUG: Verify SERVICE_ACCOUNT_JSON ===
print("🔍 Loading SERVICE_ACCOUNT_JSON...")
service_account_json = os.getenv("SERVICE_ACCOUNT_JSON")
if not service_account_json:
    raise Exception("❌ SERVICE_ACCOUNT_JSON not found.")
try:
    credentials_dict = json.loads(service_account_json)
    print("✅ JSON parsed! Email:", credentials_dict.get("client_email"))
except json.JSONDecodeError as e:
    raise Exception("❌ Invalid JSON in SERVICE_ACCOUNT_JSON.") from e

# === 1. Google Sheets Auth ===
scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
creds = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
client = gspread.authorize(creds)
sheet = client.open("Majjis-jokes").sheet1
rows = sheet.get_all_records()

# === 2. Joke Style Rotation ===
styles = ["Corporate Wit", "Playful Nerd", "Dad-Joke"]
last_posted = next((row["Style"] for row in reversed(rows) if str(row["Posted?"]).upper() == "TRUE"), None)
next_style = styles[(styles.index(last_posted) + 1) % len(styles)] if last_posted else styles[0]
joke_row = next((r for r in rows if r["Style"] == next_style and str(r["Posted?"]).upper() != "TRUE"), None)
if not joke_row:
    print(f"❌ No unposted jokes for style: {next_style}")
    exit()

joke = joke_row["Joke"]
row_index = rows.index(joke_row) + 2
print(f"📝 Selected ({next_style}) joke: {joke}")

# === 3. LinkedIn Auth ===
access_token = os.getenv("LINKEDIN_ACCESS_TOKEN")
if not access_token:
    raise Exception("❌ Missing LINKEDIN_ACCESS_TOKEN")
headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
    "X-Restli-Protocol-Version": "2.0.0"
}

# === 4. Get LinkedIn Profile ID ===
profile_res = requests.get("https://api.linkedin.com/v2/userinfo", headers=headers)
if profile_res.status_code != 200:
    raise Exception(f"❌ LinkedIn profile error: {profile_res.text}")
profile_id = profile_res.json()["sub"]

# === 5. OpenAI Doodle (Optional) ===
image_url = None
openai_key = os.getenv("OPENAI_API_KEY")
if openai_key:
    try:
        print("🎨 Generating image...")
        prompt = f"A hand-drawn doodle cartoon representing: {joke}"
        ai_res = requests.post("https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
            json={"model": "dall-e-3", "prompt": prompt, "n": 1, "size": "1024x1024"})
        if ai_res.ok:
            image_url = ai_res.json()["data"][0]["url"]
            print(f"✅ Image URL from OpenAI: {image_url}")
        else:
            print(f"⚠️ OpenAI generation failed: {ai_res.text}")
    except Exception as e:
        print(f"⚠️ OpenAI error: {e}")

# === 6. Upload Image to LinkedIn (if generated) ===
asset_urn = None
if image_url:
    print("📤 Registering image with LinkedIn...")
    reg_res = requests.post("https://api.linkedin.com/v2/assets?action=registerUpload", headers=headers, json={
        "registerUploadRequest": {
            "recipes": ["urn:li:digitalmediaRecipe:feedshare-image"],
            "owner": f"urn:li:person:{profile_id}",
            "serviceRelationships": [{"relationshipType": "OWNER", "identifier": "urn:li:userGeneratedContent"}]
        }
    })

    if reg_res.status_code == 200:
        reg_data = reg_res.json()
        upload_url = reg_data["value"]["uploadMechanism"]["com.linkedin.digitalmedia.uploading.MediaUploadHttpRequest"]["uploadUrl"]
        asset_urn = reg_data["value"]["asset"]

        try:
            print("📡 Uploading image to LinkedIn...")
            img_data = requests.get(image_url).content
            upload_res = requests.put(upload_url, headers={"Content-Type": "image/png"}, data=img_data)
            if upload_res.status_code != 201 and upload_res.status_code != 200:
                print(f"⚠️ Image upload failed: {upload_res.text}")
        except Exception as e:
            print(f"⚠️ Failed to upload image to LinkedIn: {e}")
    else:
        print(f"⚠️ LinkedIn registerUpload failed: {reg_res.text}")

# === 7. Build Post Payload ===
if asset_urn:
    print("🖼 Posting image + joke...")
    post_payload = {
        "author": f"urn:li:person:{profile_id}",
        "lifecycleState": "PUBLISHED",
        "specificContent": {
            "com.linkedin.ugc.ShareContent": {
                "shareCommentary": {"text": joke},
                "shareMediaCategory": "IMAGE",
                "media": [{
                    "status": "READY",
                    "media": asset_urn,
                    "title": {"text": "Majji's Weekly Joke"}
                }]
            }
        },
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"}
    }
else:
    print("✏️ Posting text-only joke...")
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
    print("✅ Joke posted successfully!")
    sheet.update(range_name=f"D{row_index}", values=[["TRUE"]])
    sheet.update(range_name=f"E{row_index}", values=[[datetime.now().strftime("%Y-%m-%d")]])
    sheet.update(range_name=f"F{row_index}", values=[[post_res.json().get("id", "")]])
else:
    print(f"❌ Failed to post to LinkedIn: {post_res.text}")
