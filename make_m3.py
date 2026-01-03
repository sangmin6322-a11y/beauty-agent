import json
payload = {"user_id":"test","message":"20~30대 여성 민감피부, 2~3만원대, 아마존+올리브영글로벌 중심, 진정+백탁적음"}
with open("m3.json","w",encoding="utf-8") as f:
    json.dump(payload, f, ensure_ascii=False)
print("wrote m3.json")
