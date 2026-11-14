# ruff: noqa: S101
"""Tests for the current time in words (core/spoken_time.py)."""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.home_generative_agent.core.spoken_time import spoken_time


def _words(hour: int, minute: int) -> str:
    line = spoken_time("ru", datetime(2026, 11, 14, hour, minute))  # noqa: DTZ001
    return line.split("words is: ", 1)[1].split(". ", 1)[0]


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        # The field case: 16:24 was said as 12:14 (2026-11-14).
        (16, 24, "шестнадцать часов двадцать четыре минуты"),
        (16, 27, "шестнадцать часов двадцать семь минут"),
        (0, 5, "ноль часов пять минут"),
        (1, 1, "один час одна минута"),
        (2, 2, "два часа две минуты"),
        (11, 11, "одиннадцать часов одиннадцать минут"),
        (12, 14, "двенадцать часов четырнадцать минут"),
        (21, 21, "двадцать один час двадцать одна минута"),
        (22, 32, "двадцать два часа тридцать две минуты"),
        (23, 59, "двадцать три часа пятьдесят девять минут"),
        (20, 40, "двадцать часов сорок минут"),
        (9, 0, "ровно девять часов"),
        (0, 0, "ровно ноль часов"),
    ],
)
def test_the_time_is_spelled_out_with_the_right_forms(
    hour: int, minute: int, expected: str
) -> None:
    assert _words(hour, minute) == expected


@pytest.mark.parametrize("language", ["ru", "ru-RU", "RU"])
def test_russian_in_any_spelling_gets_the_line(language: str) -> None:
    line = spoken_time(language, datetime(2026, 11, 14, 16, 24))  # noqa: DTZ001
    assert '"Сейчас шестнадцать часов двадцать четыре минуты"' in line


@pytest.mark.parametrize("language", [None, "", "en", "cs", "ro"])
def test_other_languages_get_no_line(language: str | None) -> None:
    assert spoken_time(language, datetime(2026, 11, 14, 16, 24)) == ""  # noqa: DTZ001
