import requests
import json

import os
from datetime import datetime
import time

# dotenv.load_dotenv(os.path.join(os.path.dirname(__file__), "notify.env"))

# 1. Set your webhook URL
webhook_url = os.getenv("CUSTOM_NOTIFY_URL", "")

# 2. Build JSON message body
def send_text_message_to_notify_url(text,time_stamp_enabled=True,time_format="%H:%M:%S"):
    if webhook_url == "":
        print("Notify webhook URL not set; skip sending.")
        return
    """Send a plain-text message."""
    headers = {
        "Content-Type": "application/json"
    }
    if time_stamp_enabled:
        current_time = datetime.now().strftime(time_format)
        text = f"[{current_time}] {text}"
    payload = {
        "msg_type": "text",
        "content": {
            "text": text
        }
    }
    # Send POST request
    retry = 3
    while retry > 0:
        retry -= 1
        try:
            response = requests.post(webhook_url, headers=headers, data=json.dumps(payload))
            break
        except Exception as e:
            print(f"Failed to send notification: {e}")
            if retry == 0:
                print("Retries exhausted; give up sending notification.")
                return
            time.sleep(2)  # Wait 2s before retry
    
    # Print response for debugging
    print(f"Status code: {response.status_code}")
    print(f"Response body: {response.text}")