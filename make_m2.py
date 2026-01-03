import json
payload = {"user_id":"test","message":"선크림(민감피부 진정+백탁 적음), 2~3만원대, 아마존+올영글로벌"}
with open("m2.json","w",encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False)
print("wrote m2.json")
