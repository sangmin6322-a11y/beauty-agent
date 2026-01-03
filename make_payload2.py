import json
payload = {"user_id":"test","message":"선크림이고 민감피부 진정+백탁 적은 타입, 20대~30대 여성. 2~3만원대, 아마존+올리브영글로벌 중심"}
with open("payload2.json","w",encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False)
print("wrote payload2.json")
