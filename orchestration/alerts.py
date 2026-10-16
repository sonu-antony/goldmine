import json
import os
import urllib.request


def send_alert(message, log):
    """Posts to Slack if SLACK_WEBHOOK_URL is set, otherwise writes the alert to the given log."""
    webhook = os.environ.get("SLACK_WEBHOOK_URL")
    if not webhook:
        log.error(message)
        return False
    request = urllib.request.Request(
        webhook, data=json.dumps({"text": message}).encode(), headers={"Content-Type": "application/json"}
    )
    urllib.request.urlopen(request, timeout=10)
    return True
