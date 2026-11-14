"""
The current time in words, for the per-turn part of the system prompt.

A local model given only "Current time is 16:24:48" turned it into Russian
words wrongly: "четырнадцать минут тринадцатого" (12:14), and once
"четырнадцатьнадцать двадцать семь" (field test 2026-11-14). With the words
in the prompt it only has to copy them. Russian only: English and Czech
replies read the digits as they are.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

_UNITS = (
    "ноль",
    "один",
    "два",
    "три",
    "четыре",
    "пять",
    "шесть",
    "семь",
    "восемь",
    "девять",
    "десять",
    "одиннадцать",
    "двенадцать",
    "тринадцать",
    "четырнадцать",
    "пятнадцать",
    "шестнадцать",
    "семнадцать",
    "восемнадцать",
    "девятнадцать",
)
_TENS = ("", "", "двадцать", "тридцать", "сорок", "пятьдесят")
# "Минута" is feminine: "одна минута", "две минуты".
_FEMININE = {1: "одна", 2: "две"}

_LANGUAGE = "ru"


def _number(value: int, *, feminine: bool) -> str:
    """Return 0-59 in words, in the gender of the noun it counts."""
    tens, unit = divmod(value, 10)
    if value < len(_UNITS):
        tens, unit = 0, value
    word = _FEMININE.get(unit) if feminine else None
    unit_word = word or _UNITS[unit]
    if tens == 0:
        return unit_word
    return _TENS[tens] if unit == 0 else f"{_TENS[tens]} {unit_word}"


def _plural(value: int, one: str, few: str, many: str) -> str:
    """Return the noun form a Russian number takes: 1, 2-4 or 5 and up."""
    if value % 100 in range(11, 15):
        return many
    if value % 10 == 1:
        return one
    if value % 10 in (2, 3, 4):
        return few
    return many


def spoken_time(language: str | None, now: datetime) -> str:
    """Return the prompt line with the time in words, or "" for another language."""
    if not language or language.split("-")[0].lower() != _LANGUAGE:
        return ""
    hour_noun = _plural(now.hour, "час", "часа", "часов")
    hours = f"{_number(now.hour, feminine=False)} {hour_noun}"
    if now.minute == 0:
        words = f"ровно {hours}"
    else:
        minutes = _plural(now.minute, "минута", "минуты", "минут")
        words = f"{hours} {_number(now.minute, feminine=True)} {minutes}"
    return (
        f"The time in Russian words is: {words}. When asked the time, say it in "
        f'these words, for example "Сейчас {words}", without changing them.'
    )
