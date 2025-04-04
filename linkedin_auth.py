import requests
import os

def refresh_access_token(client_id, client_secret, refresh_token):
    token_url = "https://www.linkedin.com/oauth/v2/accessToken"
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": client_id,
        "client_secret": client_secret
    }
    response = requests.post(token_url, data=data)
    if response.status_code == 200:
        return response.json()["access_token"]
    else:
        raise Exception(f"Error refreshing token: {response.text}")
