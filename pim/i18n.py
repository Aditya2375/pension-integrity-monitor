"""Message catalogues. Every user-facing string is a key so a language is a
data file, not a code change. Missing keys fall back to English, never to a
blank. Translations here are working drafts and must be reviewed by a native
speaker and the pension department before real use."""
LANGS = {"en": "English", "hi": "हिन्दी"}

CATALOG = {
    "en": {
        "msg_notice_issued": "Pension review notice. Your pension payment is under review. Payment continues until {due}. You may appeal at any time before then using reference {tracking_id}.",
        "msg_appeal_received": "We received your appeal (reference {tracking_id}). Your pension has been restored while it is reviewed.",
        "msg_appeal_reversed": "Your appeal (reference {tracking_id}) was accepted. Your pension continues and any amount due will be paid.",
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
        "window_note": "You can appeal until {date}.",
        "provisional_note": "Your pension is restored while we review your appeal.",
        "survivor_note": "If the pensioner has passed away, you may be able to claim a family pension. Ask your pension office for the family pension claim form.",
        "help_note": "You can also take your notice to your pension office. Nobody can stop a pension without a named officer and a second approval.",
        "language": "Language",
        "skip_link": "Skip to main content",
    },
    "hi": {
        "msg_notice_issued": "पेंशन समीक्षा सूचना। आपकी पेंशन की समीक्षा हो रही है। {due} तक भुगतान जारी रहेगा। उससे पहले कभी भी संदर्भ {tracking_id} से अपील कर सकते हैं।",
        "msg_appeal_received": "आपकी अपील (संदर्भ {tracking_id}) मिल गई है। समीक्षा के दौरान आपकी पेंशन बहाल कर दी गई है।",
        "msg_appeal_reversed": "आपकी अपील (संदर्भ {tracking_id}) स्वीकार हुई। आपकी पेंशन जारी रहेगी और देय राशि का भुगतान होगा।",
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
        "window_note": "आप {date} तक अपील कर सकते हैं।",
        "provisional_note": "समीक्षा के दौरान आपकी पेंशन बहाल है।",
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
