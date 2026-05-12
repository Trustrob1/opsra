import httpx

phone_id = "1157233560798463"
token = "EAAYBnu5XoXwBRbqYtdcFIXyEQ5sX7IimCn1wLKM0IR7wqBcQDcUsyeCXRrsClI83m3xk1OQOE4mAtIQZC6pZAZA65uqTcyJXdJegNOvrMC1eZCYkZBtzgJvFh0GtfEbCUZBIluQtx381FaOkIwaeXZCkT64wVnjvYnShi9xoZBKZAYnihZBfuyJImKO4ZBFL7XLtpYpAAZDZD"
test_number = "2348065564278"

url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
payload = {
    "messaging_product": "whatsapp",
    "to": test_number,
    "type": "text",
    "text": {"body": "Test message from Royal Rest Mattress via Opsra"}
}
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json"
}

resp = httpx.post(url, json=payload, headers=headers)
print(resp.status_code, resp.json())
