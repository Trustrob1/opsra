import hmac, hashlib, json

secret = "test-app-secret"
phone  = "09081374721"

payload = {
  "object": "whatsapp_business_account",
  "entry": [{
    "changes": [{
      "field": "messages",
      "value": {
        "metadata": {"phone_number_id": "test"},
        "contacts": [{"profile": {"name": "Test Sender"}, "wa_id": phone}],
        "messages": [{
          "id": "test-msg-001",
          "from": phone,
          "type": "text",
          "text": {"body": "Hello I need help with my Inventory Solution"}
        }],
        "statuses": []
      }
    }]
  }]
}

body = json.dumps(payload, separators=(',', ':')).encode()
sig  = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
print("SIG:", sig)
print("BODY:", body.decode())