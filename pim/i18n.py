"""Message catalogues. Every user-facing string is a key so a language is a
data file, not a code change. Missing keys fall back to English, never to a
blank. Translations here are working drafts and must be reviewed by a native
speaker and the pension department before real use."""
LANGS = {"en": "English", "hi": "हिन्दी"}

CATALOG = {
    "en": {
        "msg_notice_issued": "Pension review notice. Your pension payment is under review. Payment continues until {due}. You may appeal at any time before then using reference {tracking_id}.",
        "msg_death_notice_issued": "Notice. Our records suggest the pensioner may have died. If this is wrong, tell us before {due} using reference {tracking_id} or visit your pension office. Payment continues until the review ends.",
        "msg_death_finalized": "The review period for reference {tracking_id} has ended and the death has been confirmed. If this is a mistake, contact your pension office straight away; it can be reopened.",
        "msg_appeal_received": "We received your appeal (reference {tracking_id}). We have asked for your payment to continue while it is reviewed.",
        "msg_appeal_reversed": "Your appeal (reference {tracking_id}) was accepted. We have asked for your pension to continue and for any amount due to be paid.",
        "msg_appeal_upheld": "Your appeal (reference {tracking_id}) was reviewed and the decision was kept. You can ask for a further review at your pension office.",
        "msg_otp": "Your one-time code is {code}. It expires in 10 minutes. Do not share it.",
        "portal_title": "Family appeal portal",
        "portal_intro": "If you received a notice about a pension, you can appeal here. You do not need to sign in. Enter the reference from your notice.",
        "ref_label": "Reference from your notice",
        "send_code": "Send me a code",
        "code_label": "One-time code",
        "verify_code": "Check code",
        "statement_label": "Why is the decision wrong? Tell us in your own words.",
        "contact_label": "A phone number or email where we can reach you (optional)",
        "evidence_label": "Add a document or photo (optional, PDF, JPG or PNG, up to 5 MB)",
        "submit_appeal": "Send appeal",
        "status_title": "Where your case stands",
        "no_upload": "Documents cannot be uploaded here. Take them to your pension office.", "signout_case": "Sign out of this case", "nav_portal": "Family appeal portal", "nav_context": "Public data context", "nav_staff": "Staff sign in", "step_notice": "1. Notice sent", "step_appeal": "2. Appeal received", "step_decision": "3. Decision",
        "window_note": "You can appeal until {date}.",
        "provisional_note": "We have asked for your payment to continue while we review your appeal. Your pension office confirms when payment resumes.",
        "survivor_note": "If the pensioner has passed away, you may be able to claim a family pension. Ask your pension office for the family pension claim form.",
        "help_note": "You can also take your notice to your pension office. Nobody can stop a pension without a named officer and a second approval.",
        "language": "Language",
        "skip_link": "Skip to main content",
    },
    "hi": {
        "msg_notice_issued": "पेंशन समीक्षा सूचना। आपकी पेंशन की समीक्षा हो रही है। {due} तक भुगतान जारी रहेगा। उससे पहले कभी भी संदर्भ {tracking_id} से अपील कर सकते हैं।",
        "msg_death_notice_issued": "सूचना। हमारे रिकॉर्ड के अनुसार पेंशनभोगी का निधन हो सकता है। यदि यह गलत है, तो {due} से पहले संदर्भ {tracking_id} से हमें बताएं या अपने पेंशन कार्यालय जाएं। समीक्षा पूरी होने तक भुगतान जारी रहेगा।",
        "msg_death_finalized": "संदर्भ {tracking_id} की समीक्षा अवधि समाप्त हो गई है और मृत्यु की पुष्टि हो गई है। यदि यह गलती है, तो तुरंत अपने पेंशन कार्यालय से संपर्क करें; मामला दोबारा खोला जा सकता है।",
        "msg_appeal_received": "आपकी अपील (संदर्भ {tracking_id}) मिल गई है। समीक्षा के दौरान आपका भुगतान जारी रखने का अनुरोध किया गया है।",
        "msg_appeal_reversed": "आपकी अपील (संदर्भ {tracking_id}) स्वीकार हुई। हमने आपकी पेंशन जारी रखने और देय राशि के भुगतान का अनुरोध किया है।",
        "msg_appeal_upheld": "आपकी अपील (संदर्भ {tracking_id}) की समीक्षा हुई और निर्णय बना रहा। आप अपने पेंशन कार्यालय में आगे की समीक्षा मांग सकते हैं।",
        "msg_otp": "आपका एक बार का कोड {code} है। यह 10 मिनट में समाप्त हो जाएगा। इसे किसी को न बताएं।",
        "portal_title": "परिवार अपील पोर्टल",
        "portal_intro": "यदि आपको पेंशन के बारे में सूचना मिली है, तो यहां अपील कर सकते हैं। साइन इन की आवश्यकता नहीं है। अपनी सूचना का संदर्भ दर्ज करें।",
        "ref_label": "आपकी सूचना का संदर्भ",
        "send_code": "मुझे कोड भेजें",
        "code_label": "एक बार का कोड",
        "verify_code": "कोड जांचें",
        "statement_label": "निर्णय गलत क्यों है? अपने शब्दों में बताएं।",
        "contact_label": "फोन नंबर या ईमेल जिस पर हम संपर्क कर सकें (वैकल्पिक)",
        "evidence_label": "दस्तावेज़ या फोटो जोड़ें (वैकल्पिक, PDF, JPG या PNG, 5 MB तक)",
        "submit_appeal": "अपील भेजें",
        "status_title": "आपका मामला अभी कहां है",
        "no_upload": "यहां दस्तावेज़ अपलोड नहीं किए जा सकते। उन्हें अपने पेंशन कार्यालय ले जाएं।", "signout_case": "इस मामले से साइन आउट करें", "nav_portal": "परिवार अपील पोर्टल", "nav_context": "सार्वजनिक आंकड़ों का संदर्भ", "nav_staff": "कर्मचारी साइन इन", "step_notice": "1. सूचना भेजी गई", "step_appeal": "2. अपील मिली", "step_decision": "3. निर्णय",
        "window_note": "आप {date} तक अपील कर सकते हैं।",
        "provisional_note": "समीक्षा के दौरान भुगतान जारी रखने का अनुरोध किया गया है। भुगतान कब शुरू होता है, यह आपका पेंशन कार्यालय बताएगा।",
        "survivor_note": "यदि पेंशनभोगी का निधन हो गया है, तो आप पारिवारिक पेंशन का दावा कर सकते हैं। अपने पेंशन कार्यालय से दावा फॉर्म मांगें।",
        "help_note": "आप अपनी सूचना लेकर पेंशन कार्यालय भी जा सकते हैं। नामित अधिकारी और दूसरी स्वीकृति के बिना कोई पेंशन नहीं रोकी जा सकती।",
        "language": "भाषा",
        "skip_link": "मुख्य सामग्री पर जाएं",
    },
}


def t(key, lang="en", **kw):
    text = CATALOG.get(lang, {}).get(key) or CATALOG["en"].get(key) or key
    return text.format(**kw) if kw else text


def pick(lang):
    return lang if lang in CATALOG else "en"
