"""Writing / speaking / grammar prompts by mode and task."""
import json

TASK_LABELS = {
    "task1": "IELTS Writing Task 1 (report/letter visual — describe data/process/map as appropriate)",
    "task2": "IELTS Writing Task 2 (essay — argue/discuss/problem-solution)",
    "letter": "CEFR Multilevel — formal/semi-formal/informal letter or email (genre, register, layout)",
}


def writing_examiner_prompt(mode: str, task_type: str, error_summary: str) -> str:
    task_human = TASK_LABELS.get(task_type, task_type)
    err = f"\n\n{error_summary}" if error_summary.strip() else ""

    dual = ""
    if mode == "IELTS":
        dual = """
Also estimate CEFR level (A2–C1) that best matches this script and briefly explain mapping.
"""
    else:
        dual = """
Primary scoring: CEFR A2–C1 per sub-skill (range, coherence, vocabulary, grammar).
Also give an approximate IELTS-like band (0–9) as secondary signal only.
"""

    rubric_hint = ""
    if task_type == "task1":
        rubric_hint = """
Use IELTS Task 1 criteria only: Task Achievement (overview, key features, accuracy), Coherence & Cohesion,
Lexical Resource, Grammatical Range & Accuracy. Do NOT penalize as if this were Task 2.
"""
    elif task_type == "task2":
        rubric_hint = """
Use IELTS Task 2 criteria only: Task Response (position, development), Coherence & Cohesion,
Lexical Resource, Grammatical Range & Accuracy. Do NOT apply Task 1 visual-description rules.
"""
    elif task_type == "letter":
        rubric_hint = """
Evaluate as a letter/email: purpose clarity, appropriate greeting/closing, register (formal/semi/informal),
organization, tone, and language accuracy. Mention layout expectations briefly.
"""

    return f"""You are an expert writing examiner. Mode: {mode}. Task type: {task_human}.
{rubric_hint}
{dual}

The learner's answer may be handwritten in an image — FIRST transcribe the English text exactly as you read it (OCR).
Then analyze and respond primarily in Uzbek for feedback narrative.

At the very end of your reply, output ONE JSON object only (no markdown outside it) with this shape:
{{
  "transcript": "exact English transcript",
  "overall_band": number or null,
  "cefr": "A2"|"B1"|"B2"|"C1"|null,
  "criteria": {{ "short keys": numbers }},
  "errors": [{{"category": "string", "snippet": "short quote"}}],
  "topic": "short topic label for vocab study",
  "keywords": ["word1", "..."],
  "collocations": ["collocation1", "..."]
}}
Use 3–6 error items max; categories should be stable (e.g. articles, tense, word_order, cohesion).

{err}
"""


def vocab_pack_prompt(topic: str, keywords: list, collocations: list) -> str:
    kw = ", ".join(keywords[:12])
    col = ", ".join(collocations[:8])
    return f"""Topic: {topic}
Keywords: {kw}
Collocations: {col}

Create 5 multiple-choice English questions (Uzbek explanations after each answer) testing these words.
Return JSON only: {{"questions":[{{"q":"...","options":["A","B","C","D"],"correct":0,"explain_uz":"..."}}]}}"""


def paraphrase_extract_sentence_prompt(essay_text: str) -> str:
    """
    Essay dan paraphrase o'yini uchun eng yaxshi 1 ta jumlani tanlab olish.
    AI eng mazmuni, murakkab va paraphrase qilishga arziydigan jumlani tanlaydi.
    """
    return f"""Sen ingliz tili o'qituvchisisan. Quyidagi essay dan paraphrase o'yini uchun eng yaxshi 1 ta jumlani tanlab ol.

Tanlov mezonlari:
- Jumla mazmuni boy bo'lsin (oddiy emas)
- Grammatik jihatdan qiziqarli struktura bo'lsin
- Paraphrase qilish mumkin bo'lsin (juda uzun yoki juda qisqa emas)
- Essay ning asosiy fikrini ifodalovchi jumla bo'lsin

Essay:
---
{essay_text}
---

Faqat 1 ta jumlani tanla va uni JSON formatda qaytar (boshqa hech narsa qo'shma):
{{"sentence": "tanlangan jumla", "reason": "nega bu jumla tanlandi (qisqa, 10 so'z ichida)"}}
"""


def paraphrase_judge_prompt(original: str, user_rewrite: str) -> str:
    return f"""Original: {original}
Learner rewrite: {user_rewrite}

Judge briefly in Uzbek: meaning preserved? Natural English? Suggest 1 improved version. Keep under 120 words."""


def upgrade_word_prompt(simple_word: str, context_sentence: str) -> str:
    return f"""Word: {simple_word}
Context: {context_sentence}

Give 2 higher-level synonyms and one example sentence each. Uzbek explanation brief."""


def speaking_tutor_system(mode: str, task_type: str) -> str:
    tt = "Task 1" if task_type == "task1" else "Task 2"
    return f"""You are an IELTS Speaking / discussion coach in text chat. Exam mode context: {mode}. Focus: {tt}.
Give structured tips: ideas, linking, fluency, vocabulary bands. Reply in Uzbek when explaining; use English for model phrases. Keep answers concise."""


def grammar_test_generation(mode: str, bank_sample: str) -> str:
    return f"""You are an English grammar examiner. Build exactly 5 discrete grammar MCQs (upper-intermediate) for {mode} learners.
Use this style example for JSON only output:
{bank_sample}
Return JSON only: {{"questions":[{{"q":"...","options":["..."],"correct":0}}]}}"""


def writing_help_demo_message() -> str:
    return (
        "Agar Writing qiyin bo'lsa — demo darsni ko'ring va kanalimizga qo'shiling. "
        "Pastdagi tugmalar orqali o'ting."
    )


def writing_analysis_detailed_prompt(mode: str, task_type: str, error_summary: str, essay_text: str, word_count: int, min_words: int) -> str:
    """
    Prompt.md dagi formatga mos writing tahlili prompti.
    4 mezon, xatolar kategoriyasi, kuchli tomonlar, tavsiyalar.
    """
    task_human = {
        "task1": "IELTS Task 1 (grafik, diagramma, jadval, xarita tavsifi)",
        "task2": "IELTS Task 2 (argumentli esse, fikr bildirish, muammo-yechim)",
        "letter": "Umumiy writing (erkin matn, xat, hikoya, tavsif)",
    }.get(task_type, task_type)

    word_warning = ""
    if word_count < min_words:
        word_warning = f"\n⚠️ DIQQAT: So'z soni talabdan kam! Talab: {min_words}+, lekin {word_count} ta so'z."

    err_context = f"\n\nO'quvchining avvalgi xatolari:\n{error_summary}" if error_summary.strip() else ""

    return f"""Sen IELTS va ingliz tili bo'yicha ekspert ekansan. Vazifa: {task_human}.

O'quvchining inshosi:
---
{essay_text}
---

So'z soni: {word_count}{word_warning}
{err_context}

Quyidagi formatda TAHLIL QIL va faqat o'zbek tilida javob ber (ingliz tilidagi misollar bundan mustasno):

📊 WRITING TAHLILI

📝 Tur: [{task_human}]
📏 So'z soni: [{word_count} so'z] [{word_warning if word_warning else '✅ Normal'}]

━━━━━━━━━━━━━━━━━━━━━━━
📈 BAND BAHOLAR
━━━━━━━━━━━━━━━━━━━━━━━

[Task Achievement / Maqsad]: [X.X] / 9
[Coherence & Cohesion / Tuzilish]: [X.X] / 9
[Lexical Resource / Til boyligi]: [X.X] / 9
[Grammar / Grammatika]: [X.X] / 9

⭐ UMUMIY BAND: [X.X] / 9

━━━━━━━━━━━━━━━━━━━━━━━
❌ ASOSIY XATOLAR
━━━━━━━━━━━━━━━━━━━━━━━

🔴 Grammatika:
• "[Noto'g'ri jumladan parcha]" → "[To'g'ri variant]"
  📌 Sabab: [Qisqa tushuntirish]

🟡 Lug'at:
• "[Zaif so'z/ibora]" → "[Yaxshiroq variant]"
  📌 Sabab: [Nima uchun yangi variant yaxshiroq]

🟠 Tuzilish:
• [Muammo tavsifi]
  📌 Maslahat: [Qanday tuzatish mumkin]

━━━━━━━━━━━━━━━━━━━━━━━
✅ KUCHLI TOMONLAR
━━━━━━━━━━━━━━━━━━━━━━━
• [2-3 ta ijobiy narsa]

━━━━━━━━━━━━━━━━━━━━━━━
🎯 TAVSIYALAR
━━━━━━━━━━━━━━━━━━━━━━━
1. [Eng muhim yaxshilash kerak bo'lgan narsa]
2. [Ikkinchi muhim narsa]
3. [Uchinchi narsa]

💡 Keyingi writing'da e'tibor ber: [1 ta asosiy focus point]

Muhim qoidalar:
- Har bir xato uchun: original matn → to'g'ri variant → sabab
- Faqat eng muhim 3-5 ta xatoni ko'rsat (hammasi emas)
- Band baholarni 0.5 qadamda ber (6.0, 6.5, 7.0, ...)
- Umumiy band = 4 ta mezon o'rtacha, 0.5 ga yaxlitlash
- Faqat o'zbek tilida javob ber (misollar inglizcha bo'lishi mumkin)

Tahlildan so'ng, quyidagi JSON obyektini chiqar (hech narsa qo'shma):
{{
  "overall_band": number,
  "cefr": "A2"|"B1"|"B2"|"C1",
  "criteria": {{
    "task_achievement": number,
    "coherence_cohesion": number,
    "lexical_resource": number,
    "grammar": number
  }},
  "errors": [
    {{"category": "grammar"|"vocabulary"|"structure", "original": "...", "corrected": "...", "reason": "..."}}
  ],
  "strengths": ["...", "..."],
  "recommendations": ["...", "..."],
  "focus_point": "...",
  "topic": "...",
  "keywords": ["...", "..."],
  "collocations": ["...", "..."]
}}
"""


def vocabulary_detailed_prompt(topic: str, keywords: list, collocations: list) -> str:
    """
    Prompt.md dagi vocabulary formatiga mos prompt.
    """
    kw_list = ", ".join(keywords[:12]) if keywords else ""
    col_list = ", ".join(collocations[:8]) if collocations else ""

    return f"""Sen IELTS ingliz tili o'qituvchisisan. Mavzu: {topic}

Kalit so'zlar: {kw_list}
Kollokatsiyalar: {col_list}

Quyidagi formatda javob ber (faqat o'zbek tilida, inglizcha misollar bilan):

📚 MAVZU VOCABULARY: {topic}

━━━━━━━━━━━━━━━━━━━━━━━
🔑 ASOSIY SO'ZLAR (8-10 ta)
━━━━━━━━━━━━━━━━━━━━━━━

1. [Word] /[transkriptsiya]/ — [O'zbekcha ma'no]
   📝 Misol: "[IELTS darajasida jumla]"

2. [Word] ...

━━━━━━━━━━━━━━━━━━━━━━━
💬 FOYDALI IBORALAR (5-7 ta)
━━━━━━━━━━━━━━━━━━━━━━━

• [Phrase] — [Ma'no va qachon ishlatiladi]
  Misol: "[Jumla]"

━━━━━━━━━━━━━━━━━━━━━━━
⚠️ KO'P QILINADIGAN XATOLAR
━━━━━━━━━━━━━━━━━━━━━━━
• [Xato variant] ❌ → [To'g'ri variant] ✅

Tahlildan so'ng, quyidagi JSON obyektini chiqar:
{{
  "words": [
    {{"word": "...", "transcription": "...", "meaning_uz": "...", "example": "..."}},
  ],
  "phrases": [
    {{"phrase": "...", "meaning": "...", "when_to_use": "...", "example": "..."}},
  ],
  "common_mistakes": [
    {{"wrong": "...", "correct": "...", "explanation": "..."}},
  ]
}}
"""


def paraphrase_judge_detailed_prompt(original: str, user_rewrite: str) -> str:
    """
    Prompt.md dagi paraphrase o'yini formatiga mos prompt.
    """
    return f"""Sen paraphrase o'yini hakamisam. O'quvchi asl jumlani paraphrase qilishga harakat qildi.

Asl jumla: "{original}"
O'quvchi varianti: "{user_rewrite}"

Baholash mezonlari (0-10):
- 10: Ma'no saqlangan + til darajasi yuqori + original so'z yo'q
- 7-9: Yaxshi, lekin kichik kamchilik
- 4-6: Ma'no saqlangan lekin o'zgarish kam
- 0-3: Xato yoki ma'no o'zgargan

Quyidagi formatda javob ber (faqat o'zbek tilida):

🎮 PARAPHRASE NATIJASI

Asl jumla: "{original}"
Sening variant: "{user_rewrite}"

━━━━━━━━━━━━━━━
Baho: [X] / 10
━━━━━━━━━━━━━━━

[✅ Yaxshi / 🟡 O'rtacha / ❌ Zaif]

📝 Izoh:
• [Nima yaxshi]
• [Nima yaxshilanishi kerak, agar bo'lsa]

💡 Ideal variant: "[Sen taklif qiladigan yaxshiroq paraphrase]"

Tahlildan so'ng, quyidagi JSON obyektini chiqar:
{{
  "score": number,
  "verdict": "good"|"average"|"weak",
  "positive": "...",
  "needs_improvement": "...",
  "ideal_variant": "...",
  "meaning_preserved": true/false,
  "grammar_issues": ["...", "..."]
}}
"""


def group_analysis_report_prompt(students_data: list[dict], period: str) -> str:
    """
    Prompt.md dagi guruh tahlili formatiga mos prompt.
    """
    students_json = json.dumps(students_data, ensure_ascii=False, indent=2)

    return f"""Sen IELTS o'qituvchisiga guruh tahlili hisobotini tayyorlayapsan.

Davri: {period}
O'quvchilar ma'lumotlari:
{students_json}

Quyidagi formatda hisobot tayyorla (faqat o'zbek tilida):

👥 GURUH TAHLILI HISOBOTI
📅 Davr: [{period}]

━━━━━━━━━━━━━━━━━━━━━━━
📊 UMUMIY STATISTIKA
━━━━━━━━━━━━━━━━━━━━━━━
• O'quvchilar soni: [N]
• Jami writing'lar: [N]
• O'rtacha band: [X.X]
• O'sish: [+/-X.X band, oldingi davrga nisbatan]

━━━━━━━━━━━━━━━━━━━━━━━
🔴 GURUHNING ZAIF JOYLARI
━━━━━━━━━━━━━━━━━━━━━━━
1. [Eng ko'p uchraydigan xato turi] — [N] ta o'quvchida
2. [Ikkinchi muammo]
3. [Uchinchi muammo]

━━━━━━━━━━━━━━━━━━━━━━━
🏆 INDIVIDUAL NATIJAR
━━━━━━━━━━━━━━━━━━━━━━━
📈 O'sgan o'quvchilar:
• [Ism]: [Avvalgi band] → [Hozirgi band] (+[X.X])

📉 Diqqat kerak:
• [Ism]: [Avvalgi band] → [Hozirgi band] (-[X.X])

━━━━━━━━━━━━━━━━━━━━━━━
💡 O'QITUVCHIGA MASLAHATLAR
━━━━━━━━━━━━━━━━━━━━━━━
1. [Konkret dars rejasi tavsiyasi]
2. [Guruh uchun mashq turi]
3. [Alohida e'tibor kerak bo'lgan o'quvchi va nima qilish kerak]

Hisobotdan so'ng, quyidagi JSON obyektini chiqar:
{{
  "period": "...",
  "total_students": number,
  "total_writings": number,
  "average_band": number,
  "band_change": number,
  "weak_areas": [
    {{"area": "...", "affected_students": number}},
  ],
  "improved_students": [
    {{"name": "...", "old_band": number, "new_band": number, "change": number}},
  ],
  "struggling_students": [
    {{"name": "...", "old_band": number, "new_band": number, "change": number}},
  ],
  "recommendations": ["...", "...", "..."]
}}
"""
