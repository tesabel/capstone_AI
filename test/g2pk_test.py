from g2pk import G2p
import epitran
import panphon

g2p = G2p()
epi = epitran.Epitran('kor-Hang')
ft = panphon.FeatureTable()

text = "뭐가 그렇게 재밌어"
pronounced_korean = g2p(text)  # '함니적인 판단'
ipa_korean = epi.transliterate(pronounced_korean)
print("IPA:", ipa_korean)
