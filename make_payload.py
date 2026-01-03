import json

payload = {"user_id": "test", "message": "미국에서 선케어 신제품 기획하려고 해"}

with open("payload.json", "w", encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False)
print("wrote payload.json (utf-8)")
