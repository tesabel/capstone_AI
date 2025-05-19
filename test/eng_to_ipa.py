import re
import eng_to_ipa as ipa

text = "It is so nice day?"

# 특수문자 제거 및 소문자화
clean = re.sub(r"[^A-Za-z ]", "", text).lower()

ipa_result = ipa.convert(clean)

print(f"원문: {text}")
print(f"IPA: {ipa_result}")
