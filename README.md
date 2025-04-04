# LinkedIn Joke Bot with Doodle

This bot posts a weekly joke with a doodle cartoon image to your LinkedIn account.

It supports rotation between joke styles and tracks posting in a Google Sheet.

## Setup
- Add `service_account.json` manually to Azure after deployment (do not commit it)
- Configure environment variables in Azure App Service:
  - LINKEDIN_CLIENT_ID
  - LINKEDIN_CLIENT_SECRET
  - LINKEDIN_REFRESH_TOKEN
  - OPENAI_API_KEY
