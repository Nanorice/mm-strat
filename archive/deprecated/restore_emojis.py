with open("data_health_analyzer.py", "r", encoding="utf-8") as f:
    content = f.read()

replacements = {
    "[DIR]": "📁",
    "[FOLDER]": "📂",
    "[OK]": "✅",
    "[X]": "❌",
    "[!]": "⚠️",
    "[DEAD]": "💀",
    "[CHART]": "📊",
    "[LIST]": "📋",
    "[STAR]": "🌟",
    "[TIME]": "🕒",
    "[CAL]": "📅",
    "[TIP]": "💡",
    "[NOTE]": "📝",
    "[UP]": "📈",
    "[TARGET]": "🎯",
    "[GO]": "🚀",
}

for text, emoji in replacements.items():
    content = content.replace(text, emoji)

with open("data_health_analyzer.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Emojis restored!")
