# Playleast: Youtube playlist analyzer

## Setup
- poetry add google-api-python-client google-auth-oauthlib google-auth-httplib2 pandas xlsxwriter isodate fastapi uvicorn jinja2 python-multipart

## Cloud 
- Go to https://console.cloud.google.com/

- Enable the YouTube Data API v3 for your project

- go to "APIs & Services" > "Credentials" > "Create Credentials" > "OAuth client ID" >  "Desktop app"

- Download the JSON file & Place it as client_secret.json in the same directory as the py file

## run
`python youtube_analysis`
OR
`uvicorn main:app --reload`
