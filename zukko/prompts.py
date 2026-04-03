"""Writing / speaking / grammar prompts by mode and task."""

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
