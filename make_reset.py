import json
payload = {"user_id":"test","message":"/reset"}
with open("reset.json","w",encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False)
print("wrote reset.json")
