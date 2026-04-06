# Zukko AI — IELTS & CEFR Telegram Bot

Ingliz tilini o'rganish uchun AI Telegram bot. IELTS va CEFR yo'nalishlarida Writing tahlili, Vocabulary mashqlari, Paraphrase o'yini va Baraban (Wheel) tizimi.

## ✨ Imkoniyatlar

- 📝 **Writing tahlili** — AI orqali IELTS Writing baholash
- 📚 **Vocabulary Booster** — So'z boyligini oshirish mashqlari
- 🔄 **Paraphrase o'yini** — Gaplarni qayta yozish ko'nikmasi
- 🎰 **Baraban tizimi** — Oddiy va Premium barabanlar bilan bonuslar
- 🤖 **AI Tutor** — Savol-javob rejimi
- 👥 **Guruh tizimi** — O'qituvchilar uchun guruh boshqaruvi va hisobotlar
- 💰 **Tanga tizimi** — Combo va bonuslar

---

## 🚀 Loyihani ishga tushirish

### 1-qadam: Python versiyasini tekshirish

Loyiha **Python 3.10+** talab qiladi.

```bash
python --version
```

### 2-qadam: Virtual muhit yaratish

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3-qadam: Bog'liqliklarni o'rnatish

```bash
pip install -r requirements.txt
```

Yoki `pyproject.toml` orqali:

```bash
pip install -e .
```

### 4-qadam: `.env` faylini sozlash

`.env.example` faylini nusxalang:

```bash
cp .env.example .env
```

`.env` faylini oching va kerakli kalitlarni to'ldiring:

| O'zgaruvchi | Tavsif |
|---|---|
| `TELEGRAM_TOKEN` | [@BotFather](https://t.me/BotFather) dan olingan bot tokeni |
| `OPENROUTER_VISION_KEY` | AI provayder API kaliti (vision/rasm tahlili uchun) |
| `OPENROUTER_TEXT_KEY` | AI provayder API kaliti (text/muloqot uchun) |
| `VISION_MODEL` | Vision modeli (standart: `google/gemini-2.0-flash-001`) |
| `TEXT_MODEL` | Text modeli (standart: `google/gemini-2.0-flash-001`) |
| `PROJECT_CHANNEL_URL` | Majburiy kanal havolasi |
| `SPONSOR_CHANNEL_URL` | Homiy kanal havolasi |

> 💡 **Eslatma:** `OPENROUTER_*` o'zgaruvchilari nomida "OpenRouter" bo'lsa-da, bu **majburiy emas**. Siz istalgan AI provayderdan foydalanishingiz mumkin (OpenAI, Google Gemini, Anthropic, va h.k.). Muhimi — API kalitingiz va model nomini to'g'ri belgilash.

### 5-qadam: Botni ishga tushirish

```bash
python main.py
```

Bot infinity polling rejimida ishlaydi — tarmoq xatolari bo'lsa avtomatik qayta ulanadi.

---

## 🎰 Baraban tizimi

### Oddiy Baraban (4 tanga)

| Sovg'a | Ehtimollik |
|---|---|
| 📚 Vocab Booster | 25% |
| 💰 10 Tanga | 25% |
| 📝 Writing One-Shot | 20% |
| 🔄 1 Kunlik Paraphrase | 15% |
| ⚡ 1 Kunlik Tutor | 10% |
| 🎲 RE-SPIN | 5% |

### Premium Baraban (40 tanga)

| Sovg'a | Ehtimollik |
|---|---|
| 🎰 Lucky Days | 25% |
| 💰 40 Tanga (Cashback) | 20% |
| 🔄 MEGA RE-SPIN + 5 TANGA | 20% |
| 📝 Writing Pro | 15% |
| 📚 Vocab King | 15% |
| 💎 JEKPOT | 5% |

---

## 📁 Loyiha tuzilishi

```
Zukko-AI/
├── main.py              # Kirish nuqtasi
├── requirements.txt     # Bog'liqliklar
├── pyproject.toml       # Loyiha konfiguratsiyasi
├── .env.example         # Muhit o'zgaruvchilari namunasi
├── data/
│   ├── samples.json     # Writing namunalari
│   └── grammar_bank.json # Grammatika banki
└── zukko/
    ├── __init__.py
    ├── app.py           # Bot handlerlari va asosiy mantiq
    ├── config.py        # Sozlamalar
    ├── db.py            # Ma'lumotlar bazasi (SQLite)
    ├── llm.py           # LLM API chaqiruvlari
    ├── wheel.py         # Baraban logikasi
    ├── prompts.py       # AI promptlari
    └── parse_json.py    # JSON parsing yordamchilari
```

---

## ⚙️ Muhit o'zgaruvchilari (to'liq ro'yxat)

```bash
# Asosiy
TELEGRAM_TOKEN=
OPENROUTER_VISION_KEY=
OPENROUTER_TEXT_KEY=
VISION_MODEL=google/gemini-2.0-flash-001
TEXT_MODEL=google/gemini-2.0-flash-001

# Kanallar
PROJECT_CHANNEL_URL=https://t.me/...
SPONSOR_CHANNEL_URL=https://t.me/...
PROJECT_CHANNEL="..."
SPONSOR_CHANNEL="..."

# Narxlar
WRITING_ANALYSIS_COST=2
WRITING_EXTRA_COST=0.5
WRITING_DAILY_FREE=3
VOCAB_COST=0.5
PARAPHRASE_COST=3
PARAPHRASE_DAILY_FREE=3

# Baraban
WHEEL_BASIC_COST=4
WHEEL_PREMIUM_COST=40
```

---

## 📝 Eslatmalar

- Bot birinchi marta ishga tushganda avtomatik SQLite ma'lumotlar bazasini yaratadi
- Foydalanuvchilar botga kirishi uchun `PROJECT_CHANNEL` va `SPONSOR_CHANNEL` kanallariga azo bo'lishi shart
- Bot ushbu kanallarda **admin** huquqiga ega bo'lishi kerak
