#!/usr/bin/env python3
"""正本から talent-dashboard/v4 を作り、2つの投影へ反映する。

外部ライブラリは使わない。YAML は names.yml と task frontmatter に必要な
限定構文だけ、Markdown は節名と列名が一致する表だけを読む。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import stat
import sys
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "talent-dashboard/v4"
GENERATOR = "tools/build_dashboard.py"
SOURCE_ROOT = "20_project/"
NOTE = "見本データです。数値・人名はすべてサンプルで、実在の個人・組織・実績を示しません。"
TARGETS_PATH = Path("20_project/targets.yml")
HTML_PATH = Path("60_outputs/dashboard/index.html")

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})$")
RANGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\s*〜\s*(\d{4}-\d{2}-\d{2})$")
WP_ID_RE = re.compile(r"^WP-\d{2}$")
TASK_ID_RE = re.compile(r"^T-\d{2}$")
DEC_ID_RE = re.compile(r"^DEC-(\d{8})-\d{2}$")

ACTIVE_TASK_STATES = {"未着手", "進行中", "レビュー待ち", "ブロック"}
ALL_TASK_STATES = ACTIVE_TASK_STATES | {"完了", "中止"}  # 保留は状態にしない（会議録④の保留行）
WP_STATES = {"未着手", "進行中", "レビュー待ち", "ブロック", "完了", "中止"}  # 保留は状態にしない
RISK_STATES = {"監視中", "兆候あり", "顕在化", "クローズ"}
ISSUE_STATES = {"対応中", "クローズ"}
INFLUENCE_INTEREST_VALUES = {"高", "中", "低"}
ENGAGEMENT_VALUES = {"不認識", "抵抗", "中立", "支援型", "指導"}
HEALTH_NAMES = ["スケジュール", "スコープ", "品質", "チーム", "リスク"]
HEALTH_MAP = {"🟢 健全": ("ok", "健全"), "🟡 注意": ("warn", "注意"), "🔴 危険": ("stop", "危険")}
GOOD_WHEN = {"上がると良い": "up", "下がると良い": "down"}
CIRCLED = {"①": 1, "②": 2, "③": 3, "④": 4, "⑤": 5, "⑥": 6, "⑦": 7, "⑧": 8}

DERIVED_KEYS = {
    "achievement_percent",
    "completion_percent",
    "execution_rate",
    "implementation_rate",
    "week_over_week",
    "required_pace",
    "plan_to_date",
    "late",
    "late_days",
    "phase_state",
    "landing",
    "landing_people",
    "week_no",
}


class SourceError(Exception):
    """正本の構文・値・参照・不変条件違反。"""


class HtmlError(Exception):
    """HTML の dashboard-data ブロック違反。"""


def _source(path: Path, line: int, section: str, detail: str) -> SourceError:
    return SourceError(f"{path}:{line}: {section}: {detail}")


def _read(path: Path, *, html: bool = False) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        if html:
            raise HtmlError(f"{path}: HTML を読めません: {exc}") from exc
        raise SourceError(f"{path}:1: ファイル: 読めません: {exc}") from exc


def _valid_date(value: str, path: Path, line: int, section: str, column: str) -> date:
    if not DATE_RE.fullmatch(value):
        raise _source(path, line, section, f"列「{column}」は YYYY-MM-DD 完全形が必要です: {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise _source(path, line, section, f"列「{column}」の日付が不正です: {value!r}") from exc


def _valid_datetime(value: str, path: Path, line: int, section: str, column: str) -> tuple[date, str]:
    match = DATETIME_RE.fullmatch(value)
    if not match:
        raise _source(path, line, section, f"列「{column}」は YYYY-MM-DD HH:MM が必要です: {value!r}")
    day = _valid_date(match.group(1), path, line, section, column)
    try:
        datetime.strptime(match.group(2), "%H:%M")
    except ValueError as exc:
        raise _source(path, line, section, f"列「{column}」の時刻が不正です: {value!r}") from exc
    return day, match.group(2)


def _valid_range(value: str, path: Path, line: int, section: str, column: str) -> tuple[date, date]:
    match = RANGE_RE.fullmatch(value)
    if not match:
        raise _source(path, line, section, f"列「{column}」は YYYY-MM-DD 〜 YYYY-MM-DD が必要です: {value!r}")
    start = _valid_date(match.group(1), path, line, section, column)
    end = _valid_date(match.group(2), path, line, section, column)
    if start > end:
        raise _source(path, line, section, f"列「{column}」の開始日が終了日より後です: {value!r}")
    return start, end


def _clean_md(value: str) -> str:
    value = value.strip()
    value = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", value)
    value = value.replace("**", "").replace("`", "")
    return value.strip()


def _plain_int(value: str, path: Path, line: int, section: str, column: str) -> int:
    cleaned = _clean_md(value)
    if not re.fullmatch(r"0|[1-9]\d*", cleaned):
        raise _source(path, line, section, f"列「{column}」は0以上の整数が必要です: {value!r}")
    return int(cleaned)


def _number_with_unit(value: str, unit: str, path: Path, line: int, section: str, column: str) -> int:
    cleaned = _clean_md(value)
    match = re.fullmatch(r"(0|[1-9]\d*)" + re.escape(unit), cleaned)
    if not match:
        raise _source(path, line, section, f"列「{column}」は整数＋単位 {unit!r} が必要です: {value!r}")
    return int(match.group(1))


def _round_percent(numerator: int, denominator: int) -> int:
    """JavaScript Math.round と同じ、非負値の 0.5 切り上げ。"""
    return math.floor(numerator / denominator * 100 + 0.5)


def _strip_yaml_comment(raw: str) -> str:
    quote: str | None = None
    escaped = False
    for index, char in enumerate(raw):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or raw[index - 1].isspace()):
            return raw[:index].rstrip()
    return raw.rstrip()


def _yaml_scalar(raw: str, path: Path, line: int, context: str) -> Any:
    raw = _strip_yaml_comment(raw).strip()
    if not raw:
        return ""
    if raw.startswith("&") or raw.startswith("*") or raw.startswith("!") or raw in {"|", ">"}:
        raise _source(path, line, context, f"未対応の YAML 構文です: {raw!r}")
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise _source(path, line, context, f"二重引用符の値が不正です: {raw!r}") from exc
        if not isinstance(value, str):
            raise _source(path, line, context, "文字列が必要です")
        return value
    if raw.startswith("'"):
        if len(raw) < 2 or not raw.endswith("'"):
            raise _source(path, line, context, f"単一引用符が閉じていません: {raw!r}")
        return raw[1:-1].replace("''", "'")
    if raw in {"true", "false"}:
        return raw == "true"
    if raw.startswith("["):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise _source(path, line, context, f"配列は JSON 互換の角括弧形式だけ対応します: {raw!r}") from exc
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise _source(path, line, context, "配列は文字列だけにしてください")
        return value
    if any(token in raw for token in ("{", "}", "[", "]")):
        raise _source(path, line, context, f"未対応の YAML 構文です: {raw!r}")
    return raw


def parse_names(path: Path) -> dict[str, str]:
    lines = _read(path).splitlines()
    entries: dict[str, dict[str, Any]] = {}
    current: str | None = None
    in_keys = False
    schema_seen = False
    for line_no, raw in enumerate(lines, 1):
        if "\t" in raw[: len(raw) - len(raw.lstrip())]:
            raise _source(path, line_no, "names.yml", "インデントにタブは使えません")
        line = _strip_yaml_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()
        if indent == 0:
            current = None
            if body.startswith("schema:"):
                if schema_seen:
                    raise _source(path, line_no, "names.yml", "schema が重複しています")
                schema_seen = True
                if body.partition(":")[2].strip() != "talent-pj-names/v1":
                    raise _source(path, line_no, "names.yml", "schema は talent-pj-names/v1 が必要です")
                in_keys = False
            elif body == "keys:":
                if in_keys or entries:
                    raise _source(path, line_no, "names.yml", "keys が重複しています")
                in_keys = True
            else:
                raise _source(path, line_no, "names.yml", f"未知の最上位キーです: {body!r}")
            continue
        if not in_keys:
            raise _source(path, line_no, "names.yml", "keys: の外に値があります")
        if indent == 2 and body.endswith(":"):
            current = body[:-1]
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", current):
                raise _source(path, line_no, "names.yml", f"キー名が不正です: {current!r}")
            if current in entries:
                raise _source(path, line_no, "names.yml", f"キーが重複しています: {current}")
            entries[current] = {}
            continue
        if indent == 4 and current and ":" in body:
            field, _, raw_value = body.partition(":")
            if field not in {"value", "sample", "required", "description"}:
                raise _source(path, line_no, "names.yml", f"キー {current} に未知の列があります: {field}")
            if field in entries[current]:
                raise _source(path, line_no, "names.yml", f"キー {current} の列 {field} が重複しています")
            entries[current][field] = _yaml_scalar(raw_value, path, line_no, f"names.yml / {current}.{field}")
            continue
        raise _source(path, line_no, "names.yml", "対応する構造は keys → KEY → 4列だけです")
    if not schema_seen or not entries:
        raise _source(path, 1, "names.yml", "schema または keys がありません")
    required_fields = {"value", "sample", "required", "description"}
    for key, fields in entries.items():
        missing = required_fields - fields.keys()
        extra = fields.keys() - required_fields
        if missing or extra:
            raise _source(path, 1, f"names.yml / {key}", f"4列が必要です。欠落={sorted(missing)} 余分={sorted(extra)}")
        if not isinstance(fields["value"], str) or not isinstance(fields["sample"], str) or not isinstance(fields["description"], str):
            raise _source(path, 1, f"names.yml / {key}", "value/sample/description は文字列が必要です")
        if type(fields["required"]) is not bool:
            raise _source(path, 1, f"names.yml / {key}", "required は boolean が必要です")
    needed = {
        "PROJECT_ID", "PROJECT_NAME_JA", "ORG_NAME_JA", "OUR_ORG_NAME_JA", "PM_NAME", "LEADER_NAME",
        "PROJECT_SLUG", "PERIOD_START", "PERIOD_END", "WEEKLY_MEETING_SLOT",
    }
    missing_keys = sorted(needed - entries.keys())
    if missing_keys:
        raise _source(path, 1, "names.yml", f"必須 ID がありません: {', '.join(missing_keys)}")
    values: dict[str, str] = {}
    for key in needed:
        value = entries[key]["value"]
        if not value:
            raise _source(path, 1, f"names.yml / {key}", "value が空です")
        values[key] = value
    _valid_date(values["PERIOD_START"], path, 1, "names.yml", "PERIOD_START")
    _valid_date(values["PERIOD_END"], path, 1, "names.yml", "PERIOD_END")
    return values


@dataclass(frozen=True)
class TableRow:
    line: int
    cells: dict[str, str]


@dataclass(frozen=True)
class Table:
    section: str
    header_line: int
    headers: list[str]
    rows: list[TableRow]
    boundary_index: int | None

    def active_rows(self, path: Path, sample: bool, *, allow_empty: Iterable[str] = ()) -> list[TableRow]:
        allowed = set(allow_empty)
        if self.boundary_index is None:
            selected = self.rows
        elif sample:
            selected = self.rows[: self.boundary_index]
            for row in self.rows[self.boundary_index + 1 :]:
                values = [value for header, value in row.cells.items() if header not in allowed]
                if values and all(value.strip() for value in values):
                    raise _source(path, row.line, self.section, "見本行と記入済みの実データ行が境界の両側に混在しています")
        else:
            before = self.rows[: self.boundary_index]
            after = self.rows[self.boundary_index + 1 :]
            if any(any(value.strip() for value in row.cells.values()) for row in before):
                raise _source(path, before[0].line if before else self.header_line, self.section, "live データに見本行が混在しています")
            selected = after
        for row in selected:
            missing = [header for header, value in row.cells.items() if header not in allowed and not value.strip()]
            if missing:
                raise _source(path, row.line, self.section, f"部分記入行です。空の列={', '.join(missing)}")
        return selected


def _split_table_line(raw: str, path: Path, line_no: int, section: str) -> list[str]:
    if not raw.strip().startswith("|") or not raw.strip().endswith("|"):
        raise _source(path, line_no, section, "Markdown 表は行頭・行末の | が必要です")
    body = raw.strip()[1:-1]
    if "\\|" in body:
        raise _source(path, line_no, section, "セル内のエスケープされた | は未対応です")
    return [cell.strip() for cell in body.split("|")]


def _is_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells)


class MarkdownDoc:
    def __init__(self, path: Path):
        self.path = path
        self.lines = _read(path).splitlines()

    def _section_bounds(self, title: str, *, prefix: bool = False) -> tuple[int, int, str]:
        matches: list[tuple[int, int, str]] = []
        for index, raw in enumerate(self.lines):
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", raw)
            if not match:
                continue
            actual = match.group(2)
            if actual == title or (prefix and actual.startswith(title)):
                matches.append((index, len(match.group(1)), actual))
        if len(matches) != 1:
            raise _source(self.path, 1, title, f"節が {len(matches)} 件です（厳密に1件必要）")
        start, level, actual = matches[0]
        end = len(self.lines)
        for index in range(start + 1, len(self.lines)):
            match = re.match(r"^(#{1,6})\s+", self.lines[index])
            if match and len(match.group(1)) <= level:
                end = index
                break
        return start, end, actual

    def table(
        self,
        section: str,
        expected: Iterable[str],
        *,
        prefix: bool = False,
        whole_file: bool = False,
        allow_extra: bool = False,
    ) -> Table:
        expected_list = list(expected)
        expected_set = set(expected_list)
        if len(expected_list) != len(expected_set):
            raise AssertionError("expected headers must be unique")
        if whole_file:
            start, end, actual = 0, len(self.lines), section
        else:
            start, end, actual = self._section_bounds(section, prefix=prefix)
        candidates: list[Table] = []
        index = start + 1
        while index + 1 < end:
            if not self.lines[index].strip().startswith("|") or not self.lines[index + 1].strip().startswith("|"):
                index += 1
                continue
            raw_headers = _split_table_line(self.lines[index], self.path, index + 1, actual)
            separators = _split_table_line(self.lines[index + 1], self.path, index + 2, actual)
            if not _is_separator(separators) or len(separators) != len(raw_headers):
                index += 1
                continue
            headers = [_clean_md(value) for value in raw_headers]
            if len(headers) != len(set(headers)):
                duplicate = sorted({header for header in headers if headers.count(header) > 1})
                if set(headers) == expected_set or expected_set.issubset(set(headers)):
                    raise _source(self.path, index + 1, actual, f"列名が重複しています: {', '.join(duplicate)}")
            rows: list[TableRow] = []
            boundary: int | None = None
            row_index = index + 2
            while row_index < end and self.lines[row_index].strip().startswith("|"):
                cells = _split_table_line(self.lines[row_index], self.path, row_index + 1, actual)
                if len(cells) != len(headers):
                    raise _source(self.path, row_index + 1, actual, f"セル数 {len(cells)} が列数 {len(headers)} と一致しません")
                boundary_cells = [cell.strip() == "─" for cell in cells]
                if any(boundary_cells):
                    if not all(boundary_cells):
                        raise _source(self.path, row_index + 1, actual, "境界行は全セルを厳密に ─ にしてください")
                    if boundary is not None:
                        raise _source(self.path, row_index + 1, actual, "境界行が重複しています")
                    boundary = len(rows)
                rows.append(TableRow(row_index + 1, dict(zip(headers, cells))))
                row_index += 1
            headers_set = set(headers)
            if (allow_extra and expected_set.issubset(headers_set)) or (not allow_extra and headers_set == expected_set):
                candidates.append(Table(actual, index + 1, headers, rows, boundary))
            elif len(expected_set & headers_set) >= (1 if allow_extra else 2):
                missing = sorted(expected_set - headers_set)
                unknown = sorted(headers_set - expected_set)
                raise _source(self.path, index + 1, actual, f"列が一致しません。欠落={missing} 未知={unknown}")
            index = row_index
        if len(candidates) != 1:
            raise _source(self.path, start + 1, actual, f"見出し {expected_list} の表が {len(candidates)} 件です（厳密に1件必要）")
        return candidates[0]

    def unique_line(self, pattern: re.Pattern[str], section: str) -> tuple[int, re.Match[str]]:
        matches: list[tuple[int, re.Match[str]]] = []
        for index, raw in enumerate(self.lines, 1):
            match = pattern.fullmatch(raw)
            if match:
                matches.append((index, match))
        if len(matches) != 1:
            raise _source(self.path, 1, section, f"必要な行が {len(matches)} 件です（厳密に1件必要）")
        return matches[0]


def parse_charter(path: Path, names: dict[str, str], sample: bool) -> str:
    doc = MarkdownDoc(path)
    table = doc.table("基本情報", ["項目", "記入欄", "記入のコツ"])
    rows = table.active_rows(path, sample)
    values = {_clean_md(row.cells["項目"]): (_clean_md(row.cells["記入欄"]), row.line) for row in rows}
    needed = ["PJ ID", "プロジェクト名（日本語）", "持ち主（組織）", "期間", "状態"]
    missing = [key for key in needed if key not in values]
    if missing:
        raise _source(path, table.header_line, table.section, f"必須項目がありません: {', '.join(missing)}")
    checks = {
        "PJ ID": names["PROJECT_ID"],
        "プロジェクト名（日本語）": names["PROJECT_NAME_JA"],
        "持ち主（組織）": names["ORG_NAME_JA"],
    }
    for key, expected in checks.items():
        actual, line = values[key]
        if actual != expected:
            raise _source(path, line, table.section, f"項目「{key}」={actual!r} が names.yml={expected!r} と一致しません")
    period, line = values["期間"]
    start, end = _valid_range(period, path, line, table.section, "期間")
    if start.isoformat() != names["PERIOD_START"] or end.isoformat() != names["PERIOD_END"]:
        raise _source(path, line, table.section, "期間が names.yml と一致しません")
    status, _ = values["状態"]
    if not status:
        raise _source(path, line, table.section, "状態が空です")
    return status


def _load_percent(value: str, path: Path, line: int, section: str, column: str) -> int:
    cleaned = _clean_md(value)
    match = re.fullmatch(r"(0|[1-9]\d*)%", cleaned)
    if not match:
        raise _source(path, line, section, f"列「{column}」は 0%〜100% の整数が必要です: {value!r}")
    percent = int(match.group(1))
    if percent > 100:
        raise _source(path, line, section, f"列「{column}」は 0%〜100% の範囲が必要です: {value!r}")
    return percent


def parse_raci(
    path: Path,
    wp_ids: Iterable[str],
    member_names: list[str],
    sample: bool,
) -> dict[str, dict[str, str]]:
    section = "§4 体制・責任マトリックス（RACI簡略版）"
    doc = MarkdownDoc(path)
    table = doc.table(section, ["作業（WP単位）"], allow_extra=True)
    people_headers = [header for header in table.headers if header != "作業（WP単位）"]
    if not people_headers:
        raise _source(path, table.header_line, section, "担当者の列がありません")
    rows = table.active_rows(path, sample, allow_empty=people_headers)
    raci_by_member: dict[str, dict[str, str]] = {name: {} for name in member_names}
    for member in member_names:
        if member not in people_headers:
            raise _source(
                path,
                table.header_line,
                section,
                f"§5 メンバー {member!r} に一致する §4 列見出しがありません。§4 列見出し={people_headers!r}",
            )

    seen_wp: set[str] = set()
    for row in rows:
        wp_label = _clean_md(row.cells["作業（WP単位）"])
        match = re.match(r"^(WP-\d{2})(?:\s|$)", wp_label)
        if not match:
            raise _source(path, row.line, section, f"列「作業（WP単位）」の WP ID が不正です: {wp_label!r}")
        wp_id = match.group(1)
        if wp_id in seen_wp:
            raise _source(path, row.line, section, f"WP ID が重複しています: {wp_id}")
        seen_wp.add(wp_id)
        accountable = 0
        for person in people_headers:
            value = _clean_md(row.cells[person])
            if value and value not in {"R", "A", "C", "I"}:
                raise _source(path, row.line, section, f"WP {wp_id} の列「{person}」は R/A/C/I または空欄が必要です: {value!r}")
            if value == "A":
                accountable += 1
            if value and person in raci_by_member:
                raci_by_member[person][wp_id] = value
        if accountable != 1:
            raise _source(path, row.line, section, f"WP {wp_id} の A は全列でちょうど1つ必要です: {accountable}個")

    expected_wp = set(wp_ids)
    if seen_wp != expected_wp:
        raise _source(
            path,
            table.header_line,
            section,
            f"§4 の WP ID 集合が §2 WBS と一致しません。§4={sorted(seen_wp)!r} §2={sorted(expected_wp)!r}",
        )
    return raci_by_member


def _parse_resources(
    path: Path,
    names: dict[str, str],
    sample: bool,
    wp_ids: Iterable[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    section = "§5 リソースカレンダー"
    member_column = "メンバー"
    note_column = "備考（掛け持ち・調達予定）"
    doc = MarkdownDoc(path)
    table = doc.table(section, [member_column, note_column], allow_extra=True)
    load_columns = [header for header in table.headers if header not in {member_column, note_column}]
    if not load_columns:
        raise _source(path, table.header_line, section, "月の列がありません")
    rows = table.active_rows(path, sample)
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        member = _clean_md(row.cells[member_column])
        if "人ではなく枠" in member:
            continue
        if member in seen:
            raise _source(path, row.line, section, f"列「{member_column}」が重複しています: {member!r}")
        seen.add(member)
        load = {
            column: _load_percent(row.cells[column], path, row.line, section, column)
            for column in load_columns
        }
        members.append({
            "name": member,
            "load": load,
            "load_note": _clean_md(row.cells[note_column]),
        })
    if not members:
        raise _source(path, table.header_line, section, "メンバーが0件です")
    member_names = [member["name"] for member in members]
    for name_key in ("PM_NAME", "LEADER_NAME"):
        expected = names[name_key]
        if expected not in seen:
            raise _source(
                path,
                table.header_line,
                section,
                f"names.yml {name_key}={expected!r} が §5 メンバーにありません。§5 メンバー={member_names!r}",
            )
    raci_by_member = parse_raci(path, wp_ids, member_names, sample)
    for member in members:
        member["raci"] = raci_by_member[member["name"]]
    return members, seen


def parse_plan(path: Path, names: dict[str, str], sample: bool) -> dict[str, Any]:
    doc = MarkdownDoc(path)
    wbs_headers = ["WP ID", "成果物", "完了基準（何をもって完成か）", "リード（1人）", "期限", "状態"]
    wbs_rows = doc.table("§2 WBS / ワークパッケージ（成果物の束）", wbs_headers).active_rows(path, sample)
    wp_by_id: dict[str, dict[str, Any]] = {}
    for row in wbs_rows:
        wp_id = _clean_md(row.cells["WP ID"])
        if not WP_ID_RE.fullmatch(wp_id):
            raise _source(path, row.line, "§2 WBS", f"列「WP ID」の ID が不正です: {wp_id!r}")
        if wp_id in wp_by_id:
            raise _source(path, row.line, "§2 WBS", f"WP ID が重複しています: {wp_id}")
        state_value = _clean_md(row.cells["状態"])
        if state_value not in WP_STATES:
            raise _source(path, row.line, "§2 WBS", f"WP {wp_id} の状態が未知です: {state_value!r}")
        due = _clean_md(row.cells["期限"])
        _valid_date(due, path, row.line, "§2 WBS", "期限")
        wp_by_id[wp_id] = {
            "name": _clean_md(row.cells["成果物"]),
            "lead": _clean_md(row.cells["リード（1人）"]),
            "due": due,
            "state": state_value,
        }
    if not wp_by_id:
        raise _source(path, 1, "§2 WBS", "WP が0件です")

    phase_headers = ["#", "フェーズ", "期間", "週", "状態", "ゲート（これを満たしたら次へ）", "判定日", "ゲート通過", "ゲート注記"]
    phase_rows = doc.table("§3 フェーズとスケジュール", phase_headers).active_rows(path, sample)
    phases: list[dict[str, Any]] = []
    for row in phase_rows:
        no_raw = _clean_md(row.cells["#"])
        if no_raw not in CIRCLED:
            raise _source(path, row.line, "§3 フェーズとスケジュール", f"列「#」が不正です: {no_raw!r}")
        start, end = _valid_range(_clean_md(row.cells["期間"]), path, row.line, "§3 フェーズとスケジュール", "期間")
        gate_date_raw = _clean_md(row.cells["判定日"])
        gate_date = _valid_date(gate_date_raw, path, row.line, "§3 フェーズとスケジュール", "判定日")
        bool_raw = _clean_md(row.cells["ゲート通過"])
        if bool_raw not in {"true", "false"}:
            raise _source(path, row.line, "§3 フェーズとスケジュール", "列「ゲート通過」は true/false が必要です")
        phases.append({
            "no": CIRCLED[no_raw],
            "name": _clean_md(row.cells["フェーズ"]),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "gate": _clean_md(row.cells["ゲート（これを満たしたら次へ）"]),
            "gate_date": gate_date.isoformat(),
            "gate_done": bool_raw == "true",
            "gate_note": _clean_md(row.cells["ゲート注記"]),
            "_line": row.line,
        })
    if [phase["no"] for phase in phases] != list(range(1, len(phases) + 1)):
        raise _source(path, phase_rows[0].line if phase_rows else 1, "§3 フェーズとスケジュール", "フェーズ番号が1から連続していません")
    overlap_line, overlap_match = doc.unique_line(
        re.compile(r"> \*\*重なり注記\*\*: (.+)"), "§3 / 重なり注記"
    )
    overlap_note = _clean_md(overlap_match.group(1))
    if not overlap_note:
        raise _source(path, overlap_line, "§3 / 重なり注記", "値が空です")

    window_headers = ["項目", "値", "なぜ"]
    window_rows = doc.table("面談に使える期間（この計画の要）", window_headers).active_rows(path, sample)
    window = {_clean_md(row.cells["項目"]): (_clean_md(row.cells["値"]), row.line) for row in window_rows}
    if "面談に使える全期間" not in window:
        raise _source(path, 1, "面談に使える期間", "行「面談に使える全期間」がありません")
    range_text = re.sub(r"（.*）$", "", window["面談に使える全期間"][0]).strip()
    interview_start, interview_end = _valid_range(range_text, path, window["面談に使える全期間"][1], "面談に使える期間", "値")

    member_sources, known_people = _parse_resources(path, names, sample, wp_by_id)
    for wp_id, wp in wp_by_id.items():
        if wp["lead"] not in known_people:
            raise _source(path, 1, "§2 WBS", f"WP {wp_id} のリード {wp['lead']!r} が §5 のメンバーにありません")

    period_start = date.fromisoformat(names["PERIOD_START"])
    period_end = date.fromisoformat(names["PERIOD_END"])
    if not phases:
        raise _source(path, 1, "§3 フェーズとスケジュール", "フェーズが0件です")
    if phases[0]["start"] != names["PERIOD_START"] or phases[-1]["end"] != names["PERIOD_END"]:
        raise _source(path, phases[0]["_line"], "§3 フェーズとスケジュール", "フェーズの端がプロジェクト期間と一致しません")
    previous_end: date | None = None
    for phase in phases:
        start = date.fromisoformat(phase["start"])
        end = date.fromisoformat(phase["end"])
        gate = date.fromisoformat(phase["gate_date"])
        if not (period_start <= start <= end <= period_end):
            raise _source(path, phase["_line"], "§3 フェーズとスケジュール", f"フェーズ {phase['no']} が全期間の外です")
        if not (start <= gate <= end):
            raise _source(path, phase["_line"], "§3 フェーズとスケジュール", f"フェーズ {phase['no']} のゲート日が期間外です")
        if previous_end and start != previous_end + timedelta(days=1):
            raise _source(path, phase["_line"], "§3 フェーズとスケジュール", f"フェーズ {phase['no']} が前フェーズと連続していません")
        previous_end = end
        del phase["_line"]
    if not (period_start <= interview_start <= interview_end <= period_end):
        raise _source(path, window["面談に使える全期間"][1], "面談に使える期間", "面談期間が全期間の外です")

    counts = {state_name: sum(1 for wp in wp_by_id.values() if wp["state"] == state_name) for state_name in WP_STATES}
    return {
        "plan": {"interview_window_start": interview_start.isoformat(), "interview_window_end": interview_end.isoformat()},
        "wp_by_id": wp_by_id,
        "wp_counts": {"total": len(wp_by_id), "done": counts["完了"], "doing": counts["進行中"], "todo": counts["未着手"]},
        "phases": phases,
        "overlap_note": overlap_note,
        "member_sources": member_sources,
        "known_people": known_people,
    }


def parse_kpi_design(path: Path, sample: bool) -> dict[str, Any]:
    doc = MarkdownDoc(path)
    kgi_headers = ["指標名", "一言訳（数え方）", "目標値（目標）", "単位", "期限"]
    kgi_rows = doc.table("第1層: KGI（最終目標）", kgi_headers).active_rows(path, sample)
    if len(kgi_rows) != 1:
        raise _source(path, kgi_rows[0].line if kgi_rows else 1, "第1層: KGI", f"KGI は1件だけ必要です: {len(kgi_rows)}件")
    row = kgi_rows[0]
    deadline = _clean_md(row.cells["期限"])
    _valid_date(deadline, path, row.line, "第1層: KGI", "期限")
    kgi = {
        "title": _clean_md(row.cells["指標名"]),
        "gloss": _clean_md(row.cells["一言訳（数え方）"]),
        "to_be": _plain_int(row.cells["目標値（目標）"], path, row.line, "第1層: KGI", "目標値（目標）"),
        "unit": _clean_md(row.cells["単位"]),
        "deadline": deadline,
    }

    kpi_headers = ["KPI名", "計測方法（＝画面に出る一言訳）", "集計", "上がると良い／下がると良い", "目標値", "単位", "律速"]
    kpi_rows = doc.table("第2層: KPI（経路の中間指標）", kpi_headers).active_rows(path, sample, allow_empty={"律速"})
    kpis: list[dict[str, Any]] = []
    seen: set[str] = set()
    for kpi_row in kpi_rows:
        name = _clean_md(kpi_row.cells["KPI名"])
        if name in seen:
            raise _source(path, kpi_row.line, "第2層: KPI", f"KPI名が重複しています: {name}")
        seen.add(name)
        good_raw = _clean_md(kpi_row.cells["上がると良い／下がると良い"])
        if good_raw not in GOOD_WHEN:
            raise _source(path, kpi_row.line, "第2層: KPI", f"KPI {name} の向きが未知です: {good_raw!r}")
        marker = _clean_md(kpi_row.cells["律速"])
        if marker not in {"", "●"}:
            raise _source(path, kpi_row.line, "第2層: KPI", f"KPI {name} の律速印は空か ● だけです")
        kpis.append({
            "name": name,
            "gloss": _clean_md(kpi_row.cells["計測方法（＝画面に出る一言訳）"]),
            "agg": _clean_md(kpi_row.cells["集計"]),
            "target": _plain_int(kpi_row.cells["目標値"], path, kpi_row.line, "第2層: KPI", "目標値"),
            "unit": _clean_md(kpi_row.cells["単位"]),
            "good_when": GOOD_WHEN[good_raw],
            "bottleneck": marker == "●",
            "_line": kpi_row.line,
        })
    bottlenecks = [item for item in kpis if item["bottleneck"]]
    if len(bottlenecks) != 1:
        raise _source(path, kpi_rows[0].line if kpi_rows else 1, "第2層: KPI", f"律速は厳密に1件必要です: {len(bottlenecks)}件")

    kdi_headers = ["KDI名（行動の数）", "一言訳", "週あたり目標量", "単位", "計画の週ペース（律速KPIの週あたり）", "担当", "どのKPIを動かす想定か"]
    kdi_rows = doc.table("第3層: KDI（行動量）", kdi_headers).active_rows(path, sample)
    kdis: list[dict[str, Any]] = []
    pace_rows: list[dict[str, Any]] = []
    for kdi_row in kdi_rows:
        name = _clean_md(kdi_row.cells["KDI名（行動の数）"])
        unit = _clean_md(kdi_row.cells["単位"])
        pace_raw = _clean_md(kdi_row.cells["計画の週ペース（律速KPIの週あたり）"])
        pace_weekly: int | None = None
        if pace_raw != "—":
            match = re.match(r"^週(\d+)人", pace_raw)
            if not match:
                raise _source(path, kdi_row.line, "第3層: KDI", f"KDI {name} の計画ペースを読めません: {pace_raw!r}")
            pace_weekly = int(match.group(1))
        target_kpi = re.sub(r"（律速）$", "", _clean_md(kdi_row.cells["どのKPIを動かす想定か"])).strip()
        item = {
            "name": name,
            "gloss": _clean_md(kdi_row.cells["一言訳"]),
            "design_target": _plain_int(kdi_row.cells["週あたり目標量"], path, kdi_row.line, "第3層: KDI", "週あたり目標量"),
            "unit": unit,
            "design_owner": _clean_md(kdi_row.cells["担当"]),
            "target_kpi": target_kpi,
            "pace_weekly": pace_weekly,
            "_line": kdi_row.line,
        }
        kdis.append(item)
        if pace_weekly is not None:
            pace_rows.append(item)
    if len(pace_rows) != 1:
        raise _source(path, kdi_rows[0].line if kdi_rows else 1, "第3層: KDI", f"計画の週ペースは厳密に1件必要です: {len(pace_rows)}件")
    bottleneck = bottlenecks[0]
    pace_item = pace_rows[0]
    if pace_item["target_kpi"] != bottleneck["name"]:
        raise _source(path, pace_item["_line"], "第3層: KDI", f"計画ペースの対象 {pace_item['target_kpi']!r} が律速 {bottleneck['name']!r} と一致しません")
    if pace_item["design_target"] != pace_item["pace_weekly"]:
        raise _source(path, pace_item["_line"], "第3層: KDI", "週あたり目標量と律速の計画ペースが一致しません")
    bottleneck["pace_weekly"] = pace_item["pace_weekly"]
    for item in kpis:
        item.pop("_line", None)
    return {"kgi": kgi, "kpis": kpis, "kdis": kdis}


def _headline_text(raw: str, path: Path, line: int) -> str:
    if any(tag in raw.lower() for tag in ("<img", "</script", "<mark ")):
        raise _source(path, line, "冒頭: 今週の一言", "headline.text に許可されない HTML があります")
    if raw.count("**") % 2:
        raise _source(path, line, "冒頭: 今週の一言", "** の対が閉じていません")
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<mark>\1</mark>", raw)
    if "**" in rendered:
        raise _source(path, line, "冒頭: 今週の一言", "入れ子の強調は未対応です")
    _validate_headline(rendered, path, line)
    return rendered


def _validate_headline(value: str, path: Path, line: int) -> None:
    rest = re.sub(r"<mark>[^<>]*</mark>", "", value)
    if "<" in rest or ">" in rest:
        raise _source(path, line, "冒頭: 今週の一言", "headline.text は属性なしの <mark>...</mark> 対だけ許可します")


def _bullet_value(doc: MarkdownDoc, label: str) -> tuple[str, int]:
    pattern = re.compile(r"- \*\*" + re.escape(label) + r"(?:（見本）)?\*\*: (.+)")
    line, match = doc.unique_line(pattern, f"冒頭: {label}")
    value = match.group(1).strip()
    if not value:
        raise _source(doc.path, line, f"冒頭: {label}", "値が空です")
    return value, line


def parse_dashboard(path: Path, design: dict[str, Any], sample: bool) -> dict[str, Any]:
    doc = MarkdownDoc(path)
    update_line, update_match = doc.unique_line(re.compile(r"> 最終更新: (\d{4}-\d{2}-\d{2})（更新者: (.+)）"), "頭注 / 最終更新")
    updated_at = update_match.group(1)
    _valid_date(updated_at, path, update_line, "頭注 / 最終更新", "最終更新")
    sample_line, sample_match = doc.unique_line(re.compile(r"> \*\*見本札\*\*: (true|false)"), "頭注 / 見本札")
    actual_sample = sample_match.group(1) == "true"
    if actual_sample != sample:
        raise _source(path, sample_line, "頭注 / 見本札", "内部の見本札判定が一致しません")

    headline_raw, headline_line = _bullet_value(doc, "一言")
    sub_raw, _ = _bullet_value(doc, "分かれ目の数字")
    update_rule_raw, _ = _bullet_value(doc, "更新の約束")
    headline = {
        "text": _headline_text(headline_raw, path, headline_line),
        "sub": _clean_md(sub_raw),
        "update_rule": _clean_md(update_rule_raw),
    }

    kgi_headers = ["KGI", "一言訳", "いま", "差分（目標まで）", "期限", "必要ペース（残り ÷ 残りの面談週）", "判定", "判定の理由"]
    kgi_rows = doc.table("1段目: ゴールとの差分（KGI）", kgi_headers).active_rows(path, sample)
    if len(kgi_rows) != 1:
        raise _source(path, kgi_rows[0].line if kgi_rows else 1, "1段目: KGI", "KGI 行は1件必要です")
    row = kgi_rows[0]
    d_kgi = design["kgi"]
    title = _clean_md(row.cells["KGI"])
    gloss = _clean_md(row.cells["一言訳"])
    if title != d_kgi["title"] or gloss != d_kgi["gloss"]:
        raise _source(path, row.line, "1段目: KGI", "KGI 名または一言訳が 02_kpi_tree.md と一致しません")
    current = _number_with_unit(row.cells["いま"], d_kgi["unit"], path, row.line, "1段目: KGI", "いま")
    deadline = _clean_md(row.cells["期限"])
    _valid_date(deadline, path, row.line, "1段目: KGI", "期限")
    if deadline != d_kgi["deadline"]:
        raise _source(path, row.line, "1段目: KGI", "期限が 02_kpi_tree.md と一致しません")
    judge_raw = _clean_md(row.cells["判定"])
    if judge_raw not in HEALTH_MAP:
        raise _source(path, row.line, "1段目: KGI", f"判定が未知です: {judge_raw!r}")
    judge, judge_label = HEALTH_MAP[judge_raw]

    design_kpis = {item["name"]: item for item in design["kpis"]}
    kpi_headers = ["KPI", "現在値", "達成%", "前週比", "鮮度", "一言（画面に出る注記）"]
    kpi_rows = doc.table("2段目: KPI（経路の中間指標）", kpi_headers).active_rows(
        path, sample, allow_empty={"前週比"}
    )
    current_kpis: dict[str, dict[str, Any]] = {}
    derived_cells: dict[str, tuple[str, str, int]] = {}
    for kpi_row in kpi_rows:
        name = re.sub(r"（律速）$", "", _clean_md(kpi_row.cells["KPI"])).strip()
        if name not in design_kpis:
            raise _source(path, kpi_row.line, "2段目: KPI", f"KPI {name!r} が 02_kpi_tree.md にありません")
        if name in current_kpis:
            raise _source(path, kpi_row.line, "2段目: KPI", f"KPI が重複しています: {name}")
        unit = design_kpis[name]["unit"]
        as_of = _clean_md(kpi_row.cells["鮮度"])
        _valid_datetime(as_of, path, kpi_row.line, "2段目: KPI", "鮮度")
        current_kpis[name] = {
            "value": _number_with_unit(kpi_row.cells["現在値"], unit, path, kpi_row.line, "2段目: KPI", "現在値"),
            "as_of": as_of,
            "note": _clean_md(kpi_row.cells["一言（画面に出る注記）"]),
            "line": kpi_row.line,
        }
        derived_cells[name] = (_clean_md(kpi_row.cells["達成%"]), _clean_md(kpi_row.cells["前週比"]), kpi_row.line)
    if set(current_kpis) != set(design_kpis):
        raise _source(path, kpi_rows[0].line if kpi_rows else 1, "2段目: KPI", f"KPI 集合が一致しません。03={sorted(current_kpis)} 02={sorted(design_kpis)}")

    design_kdis = {item["name"]: item for item in design["kdis"]}
    kdi_headers = ["KDI", "一言訳", "今週実績", "週の予定", "実施率", "担当"]
    kdi_rows = doc.table("3段目: KDI（今週の行動量 対 予定）", kdi_headers).active_rows(path, sample)
    current_kdis: dict[str, dict[str, Any]] = {}
    for kdi_row in kdi_rows:
        name = _clean_md(kdi_row.cells["KDI"])
        if name not in design_kdis:
            raise _source(path, kdi_row.line, "3段目: KDI", f"KDI {name!r} が 02_kpi_tree.md にありません")
        unit = design_kdis[name]["unit"]
        actual = _number_with_unit(kdi_row.cells["今週実績"], unit, path, kdi_row.line, "3段目: KDI", "今週実績")
        target = _number_with_unit(kdi_row.cells["週の予定"], unit, path, kdi_row.line, "3段目: KDI", "週の予定")
        shown_rate = _clean_md(kdi_row.cells["実施率"])
        expected_rate = f"{_round_percent(actual, target)}%" if target else None
        if target == 0 or shown_rate != expected_rate:
            raise _source(path, kdi_row.line, "3段目: KDI", f"KDI {name} の実施率 {shown_rate!r} が {actual}/{target} と一致しません")
        current_kdis[name] = {"actual": actual, "target": target, "owner": _clean_md(kdi_row.cells["担当"]), "line": kdi_row.line}
    if set(current_kdis) != set(design_kdis):
        raise _source(path, kdi_rows[0].line if kdi_rows else 1, "3段目: KDI", "KDI 集合が 02_kpi_tree.md と一致しません")

    output_headers = ["指標", "実績", "予定", "備考"]
    output_rows = doc.table("4段目: 出来高（終わったWP/タスク数 対 予定）", output_headers).active_rows(path, sample)
    output_map = {_clean_md(output_row.cells["指標"]): output_row for output_row in output_rows}
    output_needed = ["完了WP数（累計）", "完了タスク数（今週）", "実行率（完了÷期限到来）"]
    missing_output = [key for key in output_needed if key not in output_map]
    if missing_output:
        raise _source(path, output_rows[0].line if output_rows else 1, "4段目: 出来高", f"行がありません: {missing_output}")
    wp_row = output_map["完了WP数（累計）"]
    tasks_row = output_map["完了タスク数（今週）"]
    exec_row = output_map["実行率（完了÷期限到来）"]
    wp_actual = _plain_int(wp_row.cells["実績"], path, wp_row.line, "4段目: 出来高", "実績")
    wp_plan = _plain_int(wp_row.cells["予定"], path, wp_row.line, "4段目: 出来高", "予定")
    tasks_done = _number_with_unit(tasks_row.cells["実績"], "件", path, tasks_row.line, "4段目: 出来高", "実績")
    exec_note = _clean_md(exec_row.cells["備考"])
    due_match = re.search(r"期限到来(\d+)件", exec_note)
    if not due_match:
        raise _source(path, exec_row.line, "4段目: 出来高", "備考から期限到来件数を読めません")
    tasks_due = int(due_match.group(1))
    shown_exec = _clean_md(exec_row.cells["実績"])
    if tasks_due == 0 or shown_exec != f"{_round_percent(tasks_done, tasks_due)}%":
        raise _source(path, exec_row.line, "4段目: 出来高", "実行率が完了÷期限到来と一致しません")

    health_headers = ["観点", "信号", "一言（信号の理由）"]
    health_rows = doc.table("5段目: 健全性5観点（人が判定・週次）", health_headers).active_rows(path, sample)
    health: list[dict[str, str]] = []
    for health_row in health_rows:
        name = _clean_md(health_row.cells["観点"])
        signal_raw = _clean_md(health_row.cells["信号"])
        if signal_raw not in HEALTH_MAP:
            raise _source(path, health_row.line, "5段目: 健全性", f"観点 {name} の信号が未知です: {signal_raw!r}")
        signal, label = HEALTH_MAP[signal_raw]
        health.append({"name": name, "signal": signal, "label": label, "why": _clean_md(health_row.cells["一言（信号の理由）"])})
    if [item["name"] for item in health] != HEALTH_NAMES:
        raise _source(path, health_rows[0].line if health_rows else 1, "5段目: 健全性", f"固定5件・順序が違います: {[item['name'] for item in health]}")

    decide_headers = ["#", "決めること", "本文（判断材料）", "決める人", "決める場", "てこ（週ペース／確定率）", "着地の試算", "関連"]
    decide_rows = doc.table("今週これを決める（画面の「決めどころ」の正本）", decide_headers).active_rows(path, sample)
    if len(decide_rows) > 2:
        raise _source(path, decide_rows[2].line, "今週これを決める", f"決めどころは2件までです: {len(decide_rows)}件")
    decide: list[dict[str, Any]] = []
    landing_expected: list[tuple[int, int]] = []
    for decide_row in decide_rows:
        no = _plain_int(decide_row.cells["#"], path, decide_row.line, "今週これを決める", "#")
        lever_raw = _clean_md(decide_row.cells["てこ（週ペース／確定率）"])
        same = re.fullmatch(r"週ペース\s*(\d+)人／確定率は実績のまま", lever_raw)
        changed = re.fullmatch(r"週ペース\s*(\d+)人／確定率\s*(\d+)%", lever_raw)
        if same:
            pace, conv = int(same.group(1)), None
        elif changed:
            pace, conv = int(changed.group(1)), int(changed.group(2))
        else:
            raise _source(path, decide_row.line, "今週これを決める", f"てこの構文を読めません: {lever_raw!r}")
        landing_match = re.match(r"^(\d+)人", _clean_md(decide_row.cells["着地の試算"]))
        if not landing_match:
            raise _source(path, decide_row.line, "今週これを決める", "着地の試算から人数を読めません")
        related = [part.strip() for part in _clean_md(decide_row.cells["関連"]).split("・") if part.strip()]
        decide.append({
            "no": no,
            "title": _clean_md(decide_row.cells["決めること"]),
            "text": _clean_md(decide_row.cells["本文（判断材料）"]),
            "owner": _clean_md(decide_row.cells["決める人"]),
            "related": related,
            "landing_lever": {"pace_weekly": pace, "conv_rate": conv},
            "_line": decide_row.line,
        })
        landing_expected.append((int(landing_match.group(1)), decide_row.line))
    if [item["no"] for item in decide] != list(range(1, len(decide) + 1)):
        raise _source(path, decide_rows[0].line if decide_rows else 1, "今週これを決める", "# は1から連続させてください")

    history_headers = ["週", "期間", "KGI 受け入れ確定（累計）", "候補者リスト", "面談完了（累計）", "面談→確定率（累計÷累計）", "受け入れ準備", "面談の実績（その週）", "面談の計画（その週）", "備考"]
    history_rows = doc.table("週ごとの値（**追記だけ**・上書きしない）", history_headers).active_rows(path, sample)
    histories: dict[str, list[int]] = {name: [] for name in design_kpis}
    kgi_history: list[int] = []
    previous_period_end: date | None = None
    for expected_week, history_row in enumerate(history_rows, 1):
        week_raw = _clean_md(history_row.cells["週"])
        if week_raw != f"第{expected_week}週":
            raise _source(path, history_row.line, "週ごとの値", f"週が連続していません: {week_raw!r}")
        period_start, period_end = _valid_range(
            _clean_md(history_row.cells["期間"]), path, history_row.line, "週ごとの値", "期間"
        )
        if previous_period_end is not None and period_start != previous_period_end + timedelta(days=1):
            raise _source(path, history_row.line, "週ごとの値", "期間が前週と連続していません（重複または飛びがあります）")
        previous_period_end = period_end
        kgi_value = _number_with_unit(
            history_row.cells["KGI 受け入れ確定（累計）"],
            d_kgi["unit"],
            path,
            history_row.line,
            "週ごとの値",
            "KGI 受け入れ確定（累計）",
        )
        if kgi_history and kgi_value < kgi_history[-1]:
            raise _source(path, history_row.line, "週ごとの値", "KGI 受け入れ確定の累計が前週から減っています")
        kgi_history.append(kgi_value)
        values_by_name = {
            "候補者リスト数": _number_with_unit(history_row.cells["候補者リスト"], design_kpis["候補者リスト数"]["unit"], path, history_row.line, "週ごとの値", "候補者リスト"),
            "面談完了数": _number_with_unit(history_row.cells["面談完了（累計）"], design_kpis["面談完了数"]["unit"], path, history_row.line, "週ごとの値", "面談完了（累計）"),
            "面談→確定率": _number_with_unit(history_row.cells["面談→確定率（累計÷累計）"], design_kpis["面談→確定率"]["unit"], path, history_row.line, "週ごとの値", "面談→確定率（累計÷累計）"),
            "受け入れ準備の完了率": _number_with_unit(history_row.cells["受け入れ準備"], design_kpis["受け入れ準備の完了率"]["unit"], path, history_row.line, "週ごとの値", "受け入れ準備"),
        }
        for name, value in values_by_name.items():
            if design_kpis[name]["agg"] == "累計" and histories[name] and value < histories[name][-1]:
                raise _source(path, history_row.line, "週ごとの値", f"{name}の累計が前週から減っています")
            histories[name].append(value)
        interview_actual = _number_with_unit(
            history_row.cells["面談の実績（その週）"],
            design_kpis["面談完了数"]["unit"],
            path,
            history_row.line,
            "週ごとの値",
            "面談の実績（その週）",
        )
        previous_interviews = histories["面談完了数"][-2] if len(histories["面談完了数"]) > 1 else 0
        if interview_actual != values_by_name["面談完了数"] - previous_interviews:
            raise _source(
                path,
                history_row.line,
                "週ごとの値",
                "面談の実績（その週）が面談完了（累計）の前週差と一致しません",
            )
        if values_by_name["面談完了数"] == 0 or _round_percent(kgi_history[-1], values_by_name["面談完了数"]) != values_by_name["面談→確定率"]:
            raise _source(path, history_row.line, "週ごとの値", "KGI累計÷面談累計が確定率と一致しません")

    kpis: list[dict[str, Any]] = []
    for item in design["kpis"]:
        name = item["name"]
        current_item = current_kpis[name]
        history = histories[name]
        if not history or history[-1] != current_item["value"]:
            raise _source(path, current_item["line"], "週ごとの値", f"KPI {name} の history 末尾が現在値と一致しません")
        shown_ach, shown_delta, line = derived_cells[name]
        expected_ach = f"{_round_percent(current_item['value'], item['target'])}%"
        if len(history) == 1:
            expected_delta = None
            delta_matches = shown_delta in {"", "—"}
        else:
            delta = current_item["value"] - history[-2]
            sign = "+" if delta > 0 else "−" if delta < 0 else "±"
            delta_unit = "pt" if item["unit"] == "%" else item["unit"]
            expected_delta = f"{sign}{abs(delta)}{delta_unit}"
            delta_matches = shown_delta == expected_delta
        if shown_ach != expected_ach or not delta_matches:
            expected_delta_label = expected_delta if expected_delta is not None else "— または空（前週比なし）"
            raise _source(path, line, "2段目: KPI", f"KPI {name} の派生表示が履歴・目標と一致しません: 達成={shown_ach!r}/{expected_ach!r}, 前週比={shown_delta!r}/{expected_delta_label!r}")
        out = {
            "name": name,
            "gloss": item["gloss"],
            "agg": item["agg"],
            "value": current_item["value"],
            "unit": item["unit"],
            "target": item["target"],
            "history": history,
            "as_of": current_item["as_of"],
            "good_when": item["good_when"],
            "note": current_item["note"],
        }
        if item.get("pace_weekly") is not None:
            out["pace_weekly"] = item["pace_weekly"]
        if item["bottleneck"]:
            out["bottleneck"] = True
        kpis.append(out)

    kdis: list[dict[str, Any]] = []
    for item in design["kdis"]:
        current_item = current_kdis[item["name"]]
        kdis.append({
            "name": item["name"],
            "gloss": item["gloss"],
            "actual": current_item["actual"],
            "target": current_item["target"],
            "unit": item["unit"],
            "owner": current_item["owner"],
        })

    return {
        "updated_at": updated_at,
        "freshness": [
            {"kind": "KGI", "name": d_kgi["title"], "as_of": updated_at, "line": update_line},
            *(
                {
                    "kind": "KPI",
                    "name": name,
                    "as_of": current_kpis[name]["as_of"],
                    "line": current_kpis[name]["line"],
                }
                for name in current_kpis
            ),
        ],
        "headline": headline,
        "kgi": {
            "title": d_kgi["title"], "gloss": d_kgi["gloss"], "unit": d_kgi["unit"],
            "as_is": current, "to_be": d_kgi["to_be"], "deadline": d_kgi["deadline"], "as_of": updated_at,
            "history": kgi_history, "judge": judge, "judge_label": judge_label,
            "judge_reason": _clean_md(row.cells["判定の理由"]),
        },
        "kgi_required_pace": (
            _clean_md(row.cells["必要ペース（残り ÷ 残りの面談週）"]),
            row.line,
        ),
        "kpi": kpis,
        "kdi": kdis,
        "output_source": {
            "wp_actual": wp_actual, "wp_plan": wp_plan, "tasks_done": tasks_done,
            "tasks_due": tasks_due, "note": exec_note, "line": exec_row.line,
        },
        "health": health,
        "decide": decide,
        "landing_expected": landing_expected,
    }


def _ledger_rows(path: Path, section: str, headers: list[str], sample: bool) -> list[TableRow]:
    return MarkdownDoc(path).table(section, headers, whole_file=True).active_rows(path, sample)


def _parse_all_decisions(path: Path, sample: bool) -> list[dict[str, str]]:
    headers = ["DEC-ID", "日付", "決定内容（1〜2行で言い切る）", "決定した場", "理由・根拠（どの数字・どの判断か）", "影響範囲（変わるもの）", "周知先"]
    rows = _ledger_rows(path, "意思決定ログ", headers, sample)
    decisions: list[dict[str, str]] = []
    for row in rows:
        dec_id = _clean_md(row.cells["DEC-ID"])
        match = DEC_ID_RE.fullmatch(dec_id)
        if not match:
            raise _source(path, row.line, "意思決定ログ", f"DEC-ID が不正です: {dec_id!r}")
        day = _clean_md(row.cells["日付"])
        _valid_date(day, path, row.line, "意思決定ログ", "日付")
        if day.replace("-", "") != match.group(1):
            raise _source(path, row.line, "意思決定ログ", f"DEC-ID と日付が一致しません: {dec_id} / {day}")
        decisions.append({
            "id": dec_id,
            "date": day,
            "text": _clean_md(row.cells["決定内容（1〜2行で言い切る）"]),
            "where": _clean_md(row.cells["決定した場"]),
            "why": _clean_md(row.cells["理由・根拠（どの数字・どの判断か）"]),
        })
    decisions.sort(key=lambda item: (item["date"], item["id"]))
    return decisions


def parse_decisions(path: Path, sample: bool) -> list[dict[str, str]]:
    return _parse_all_decisions(path, sample)[-2:]


def parse_risks(path: Path, project_id: str, sample: bool) -> list[dict[str, str]]:
    headers = ["RSK-ID", "内容（何が起きるとどう困るか）", "影響", "分類", "対応策", "監視サイン（数字/条件）", "担当", "状態"]
    rows = _ledger_rows(path, "リスク台帳", headers, sample)
    risks: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        risk_id = _clean_md(row.cells["RSK-ID"])
        if not re.fullmatch(re.escape(project_id) + r"/RSK-\d{2}", risk_id):
            raise _source(path, row.line, "リスク台帳", f"RSK-ID はフル ID が必要です: {risk_id!r}")
        if risk_id in seen:
            raise _source(path, row.line, "リスク台帳", f"ID が重複しています: {risk_id}")
        seen.add(risk_id)
        state_value = _clean_md(row.cells["状態"])
        if state_value not in RISK_STATES:
            raise _source(path, row.line, "リスク台帳", f"状態が未知です: {state_value!r}")
        if state_value == "クローズ":
            continue
        risks.append({
            "id": risk_id,
            "text": _clean_md(row.cells["内容（何が起きるとどう困るか）"]),
            "state": state_value,
            "impact": _clean_md(row.cells["影響"]),
            "plan": _clean_md(row.cells["対応策"]),
            "watcher": _clean_md(row.cells["担当"]),
        })
    if len(risks) > 3:
        raise _source(path, rows[3].line, "リスク台帳", "非クローズのリスクが3件を超えています。順位欄なしでは選べません")
    return risks


def parse_issues(path: Path, project_id: str, sample: bool) -> list[dict[str, str]]:
    headers = ["ISS-ID", "内容（何に・いつから詰まっているか）", "影響（放置するとどうなるか）", "担当（解決を動かす人）", "期限", "状態"]
    rows = _ledger_rows(path, "課題台帳", headers, sample)
    issues: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        issue_id = _clean_md(row.cells["ISS-ID"])
        if not re.fullmatch(re.escape(project_id) + r"/ISS-\d{2}", issue_id):
            raise _source(path, row.line, "課題台帳", f"ISS-ID はフル ID が必要です: {issue_id!r}")
        if issue_id in seen:
            raise _source(path, row.line, "課題台帳", f"ID が重複しています: {issue_id}")
        seen.add(issue_id)
        state_value = _clean_md(row.cells["状態"])
        if state_value not in ISSUE_STATES:
            raise _source(path, row.line, "課題台帳", f"状態が未知です: {state_value!r}")
        if state_value != "対応中":
            continue
        due = _clean_md(row.cells["期限"])
        _valid_date(due, path, row.line, "課題台帳", "期限")
        issues.append({
            "id": issue_id,
            "text": _clean_md(row.cells["内容（何に・いつから詰まっているか）"]),
            "impact": _clean_md(row.cells["影響（放置するとどうなるか）"]),
            "owner": _clean_md(row.cells["担当（解決を動かす人）"]),
            "due": due,
            "state": state_value,
        })
    return issues


def parse_stakeholders(path: Path, sample: bool) -> dict[str, dict[str, Any]]:
    section = "一覧"
    headers = [
        "氏名/組織",
        "役割・立場",
        "影響力",
        "関心度",
        "現在の関与度",
        "望ましい関与度",
        "次の一手（バイネーム+期限）",
    ]
    rows = MarkdownDoc(path).table(section, headers).active_rows(path, sample)
    stakeholders: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = _clean_md(row.cells["氏名/組織"])
        if name in stakeholders:
            raise _source(path, row.line, section, f"列「氏名/組織」が重複しています: {name!r}")
        influence = _clean_md(row.cells["影響力"])
        interest = _clean_md(row.cells["関心度"])
        engagement = _clean_md(row.cells["現在の関与度"])
        engagement_desired = _clean_md(row.cells["望ましい関与度"])
        if influence not in INFLUENCE_INTEREST_VALUES:
            raise _source(path, row.line, section, f"{name!r} の列「影響力」が未知です: {influence!r}")
        if interest not in INFLUENCE_INTEREST_VALUES:
            raise _source(path, row.line, section, f"{name!r} の列「関心度」が未知です: {interest!r}")
        if engagement not in ENGAGEMENT_VALUES:
            raise _source(path, row.line, section, f"{name!r} の列「現在の関与度」が未知です: {engagement!r}")
        if engagement_desired not in ENGAGEMENT_VALUES:
            raise _source(path, row.line, section, f"{name!r} の列「望ましい関与度」が未知です: {engagement_desired!r}")
        stakeholders[name] = {
            "role": _clean_md(row.cells["役割・立場"]),
            "stakeholder": {
                "influence": influence,
                "interest": interest,
                "engagement": engagement,
                "engagement_desired": engagement_desired,
                "next_step": _clean_md(row.cells["次の一手（バイネーム+期限）"]),
            },
        }
    return stakeholders


def _expand_people_list(raw: str, path: Path, line: int, section: str, known_people: set[str]) -> list[str]:
    sample_all = "（すべてサンプル）" in raw
    raw = raw.replace("（すべてサンプル）", "")
    attendees = [part.strip() for part in raw.split("・") if part.strip()]
    if sample_all:
        attendees = [person if person.endswith("（サンプル）") else person + "（サンプル）" for person in attendees]
    if len(attendees) != len(set(attendees)):
        raise _source(path, line, section, "出席者が重複しています")
    unknown = [person for person in attendees if person not in known_people]
    if unknown:
        raise _source(path, line, section, f"§5 メンバーにない出席者です: {unknown}")
    return attendees


def _expand_attendees(raw: str, path: Path, line: int, known_people: set[str]) -> list[str]:
    section = "次回の議題 / 出席（予定）"
    if "／進行 " not in raw:
        raise _source(path, line, section, "「／進行 」で進行役を明記してください")
    attendees_raw, facilitator = raw.split("／進行 ", 1)
    attendees = _expand_people_list(attendees_raw, path, line, section, known_people)
    facilitator = facilitator.strip()
    attendees.append(facilitator)
    if len(attendees) != len(set(attendees)):
        raise _source(path, line, section, "出席者が重複しています")
    unknown = [person for person in attendees if person not in known_people]
    if unknown:
        raise _source(path, line, section, f"§5 メンバーにない出席者です: {unknown}")
    return attendees


def parse_weekly(
    path: Path,
    names: dict[str, str],
    known_people: set[str],
    decide_count: int,
    project_updated_at: str,
    sample: bool,
) -> dict[str, Any]:
    doc = MarkdownDoc(path)
    info_headers = ["項目", "記入欄"]
    info_rows = doc.table("会議体情報", info_headers, whole_file=True).active_rows(path, sample)
    info = {_clean_md(row.cells["項目"]): (_clean_md(row.cells["記入欄"]), row.line) for row in info_rows}
    for key in ("表示名", "リズム・時間", "次回"):
        if key not in info:
            raise _source(path, 1, "会議体情報", f"項目「{key}」がありません")
    if names["WEEKLY_MEETING_SLOT"] not in info["リズム・時間"][0]:
        raise _source(path, info["リズム・時間"][1], "会議体情報", "リズム・時間が names.yml の WEEKLY_MEETING_SLOT と一致しません")
    next_match = re.fullmatch(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})", info["次回"][0])
    if not next_match:
        raise _source(path, info["次回"][1], "会議体情報", "次回は YYYY-MM-DD HH:MM が必要です")
    next_day, _ = _valid_datetime(info["次回"][0], path, info["次回"][1], "会議体情報", "次回")
    if next_day < date.fromisoformat(project_updated_at):
        raise _source(
            path,
            info["次回"][1],
            "会議体情報",
            "次回が計器盤の基準日より前です。bodies/weekly.md の次回を更新してください",
        )

    _, _, agenda_section = doc._section_bounds("次回の議題（", prefix=True)
    heading_match = re.fullmatch(r"次回の議題（(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})〜(\d{2}:\d{2})・★＝この回で決めること）", agenda_section)
    if not heading_match:
        raise _source(path, 1, agenda_section, "見出しは完全日付・開始終了時刻・★の説明が必要です")
    agenda_date, start_time, end_time = heading_match.groups()
    _valid_date(agenda_date, path, 1, agenda_section, "日付")
    if agenda_date != next_match.group(1) or start_time != next_match.group(2):
        raise _source(path, 1, agenda_section, "次回欄と議題見出しの日時が一致しません")
    start_dt = datetime.strptime(start_time, "%H:%M")
    end_dt = datetime.strptime(end_time, "%H:%M")
    minutes = int((end_dt - start_dt).total_seconds() // 60)
    if minutes <= 0:
        raise _source(path, 1, agenda_section, "終了時刻は開始時刻より後にしてください")

    agenda_headers = ["#", "議題", "★"]
    agenda_rows = doc.table("次回の議題（", agenda_headers, prefix=True).active_rows(path, sample, allow_empty={"★"})
    agenda: list[str] = []
    star_indexes: list[int] = []
    for index, row in enumerate(agenda_rows):
        agenda.append(_clean_md(row.cells["議題"]))
        star = _clean_md(row.cells["★"])
        if star:
            if star != "★":
                raise _source(path, row.line, agenda_section, "★列は空か ★ だけです")
            star_indexes.append(index)
    if len(star_indexes) != decide_count:
        raise _source(path, agenda_rows[0].line if agenda_rows else 1, agenda_section, f"★件数 {len(star_indexes)} が決めどころ {decide_count} 件と一致しません")
    if star_indexes and star_indexes != list(range(star_indexes[0], star_indexes[0] + len(star_indexes))):
        raise _source(path, agenda_rows[star_indexes[0]].line, agenda_section, "★行は連続させてください")

    attendance_headers = ["項目", "値"]
    attendance_rows = doc.table("次回の議題（", attendance_headers, prefix=True).active_rows(path, sample)
    attendance = {_clean_md(row.cells["項目"]): (_clean_md(row.cells["値"]), row.line) for row in attendance_rows}
    if "出席（予定）" not in attendance:
        raise _source(path, 1, agenda_section, "出席（予定）がありません")
    attendees = _expand_attendees(attendance["出席（予定）"][0], path, attendance["出席（予定）"][1], known_people)
    return {
        "kind": info["表示名"][0],
        "date": agenda_date,
        "time": f"{start_time}〜{end_time}",
        "minutes": minutes,
        "slot_label": names["WEEKLY_MEETING_SLOT"],
        "attendees": attendees,
        "agenda": agenda,
        "decide_index": star_indexes[0] if star_indexes else 0,
    }


def parse_last_meeting(
    directory: Path,
    project_slug: str,
    known_people: set[str],
    task_ids: set[str],
    decision_ids: set[str],
    project_updated_at: str,
    next_meeting_date: str,
    sample: bool,
) -> dict[str, Any] | None:
    filename_re = re.compile(r"^MTG-" + re.escape(project_slug) + r"-(\d{8})\.md$")
    candidates: list[tuple[str, Path]] = []
    for path in directory.glob(f"MTG-{project_slug}-*.md"):
        match = filename_re.fullmatch(path.name)
        if not match:
            continue
        compact_day = match.group(1)
        filename_day = f"{compact_day[:4]}-{compact_day[4:6]}-{compact_day[6:]}"
        _valid_date(filename_day, path, 1, "会議ファイル名", "日付")
        candidates.append((compact_day, path))
    if not candidates:
        return None
    _, path = max(candidates, key=lambda item: item[0])
    doc = MarkdownDoc(path)

    info_headers = ["項目", "記入欄"]
    info_table = doc.table("会議情報", info_headers)
    info_rows = info_table.active_rows(path, sample)
    info: dict[str, tuple[str, int]] = {}
    for row in info_rows:
        key = _clean_md(row.cells["項目"])
        if key in info:
            raise _source(path, row.line, "会議情報", f"項目が重複しています: {key!r}")
        info[key] = (_clean_md(row.cells["記入欄"]), row.line)
    for key in ("会議ID", "日時・時間", "参加者", "進行役"):
        if key not in info:
            raise _source(path, info_table.header_line, "会議情報", f"項目「{key}」がありません")

    meeting_id, id_line = info["会議ID"]
    if meeting_id != path.stem:
        raise _source(path, id_line, "会議情報", f"会議ID {meeting_id!r} がファイル名 {path.stem!r} と一致しません")
    datetime_raw, datetime_line = info["日時・時間"]
    datetime_match = re.match(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})〜(\d{2}:\d{2})", datetime_raw)
    if not datetime_match:
        raise _source(path, datetime_line, "会議情報", f"列「日時・時間」を読めません: {datetime_raw!r}")
    meeting_date, start_time, end_time = datetime_match.groups()
    meeting_day = _valid_date(meeting_date, path, datetime_line, "会議情報", "日時・時間")
    try:
        start_dt = datetime.strptime(start_time, "%H:%M")
        end_dt = datetime.strptime(end_time, "%H:%M")
    except ValueError as exc:
        raise _source(path, datetime_line, "会議情報", f"列「日時・時間」の時刻が不正です: {datetime_raw!r}") from exc
    minutes = int((end_dt - start_dt).total_seconds() // 60)
    if minutes <= 0:
        raise _source(path, datetime_line, "会議情報", "列「日時・時間」の終了時刻は開始時刻より後にしてください")
    updated_day = date.fromisoformat(project_updated_at)
    next_day = date.fromisoformat(next_meeting_date)
    if meeting_day > updated_day:
        raise _source(path, datetime_line, "会議情報", f"会議日 {meeting_date} が project.updated_at {project_updated_at} より未来です")
    if meeting_day >= next_day:
        raise _source(path, datetime_line, "会議情報", f"会議日 {meeting_date} は next_meeting.date {next_meeting_date} より前である必要があります")

    facilitator, facilitator_line = info["進行役"]
    if facilitator not in known_people:
        raise _source(path, facilitator_line, "会議情報", f"列「進行役」の {facilitator!r} が §5 メンバーにありません")
    attendees_raw, attendees_line = info["参加者"]
    attendees = _expand_people_list(attendees_raw, path, attendees_line, "会議情報 / 参加者", known_people)

    h1_matches: list[tuple[int, str]] = []
    for line_no, raw in enumerate(doc.lines, 1):
        match = re.fullmatch(r"#\s+(.+?)\s*", raw)
        if match:
            h1_matches.append((line_no, match.group(1)))
    if len(h1_matches) != 1:
        raise _source(path, 1, "H1", f"H1 が {len(h1_matches)} 件です（厳密に1件必要）")
    h1_line, h1 = h1_matches[0]
    if h1 == meeting_id:
        title = ""
    elif h1.startswith(meeting_id + " — "):
        title = _clean_md(h1[len(meeting_id + " — "):])
    else:
        raise _source(path, h1_line, "H1", f"H1 の会議IDが会議情報・ファイル名と一致しません: {h1!r}")

    review_section = "⓪ 前回アクションの確認"
    review_headers = ["前回タスク", "担当", "状態", "証跡", "未完なら理由と扱い"]
    review_rows = doc.table(review_section, review_headers, prefix=True).active_rows(path, sample)
    review: list[dict[str, str]] = []
    for row in review_rows:
        owner = _clean_md(row.cells["担当"])
        state_value = _clean_md(row.cells["状態"])
        if owner not in known_people:
            raise _source(path, row.line, review_section, f"列「担当」の {owner!r} が §5 メンバーにありません")
        if state_value not in ALL_TASK_STATES:
            raise _source(path, row.line, review_section, f"列「状態」が未知です: {state_value!r}")
        review.append({
            "task": _clean_md(row.cells["前回タスク"]),
            "owner": owner,
            "state": state_value,
            "evidence": _clean_md(row.cells["証跡"]),
            "note": _clean_md(row.cells["未完なら理由と扱い"]),
        })
    rate_pattern = re.compile(
        r"実行率:\s*(?:完了(\d+)件\s*÷\s*期限到来(\d+)件\s*[＝=]\s*(?:\*\*)?(\d+)%(?:\*\*)?.*|対象なし)"
    )
    rate_line, rate_match = doc.unique_line(rate_pattern, review_section + " / 実行率")
    if rate_match.group(1) is None:
        if review:
            raise _source(path, rate_line, review_section, "実行率が「対象なし」ですが前回タスク表に行があります")
        review_done = review_due = 0
    else:
        review_done = int(rate_match.group(1))
        review_due = int(rate_match.group(2))
        shown_rate = int(rate_match.group(3))
        actual_done = sum(item["state"] == "完了" for item in review)
        if review_due == 0:
            raise _source(path, rate_line, review_section, "期限到来0件は実行率を「対象なし」にしてください")
        expected_rate = _round_percent(actual_done, len(review)) if review else 0
        if review_done != actual_done or review_due != len(review) or shown_rate != expected_rate:
            raise _source(
                path,
                rate_line,
                review_section,
                f"実行率行が表と一致しません。表示={review_done}/{review_due}/{shown_rate}% 表={actual_done}/{len(review)}/{expected_rate}%",
            )

    action_section = "④ アクション決定 → タスク化"
    action_headers = ["決定（アクション）", "→ 担当", "期限", "完了の定義", "起票（ID）"]
    action_rows = doc.table(action_section, action_headers, prefix=True).active_rows(path, sample, allow_empty={"起票（ID）"})
    actions: list[dict[str, Any]] = []
    for row in action_rows:
        owner = _clean_md(row.cells["→ 担当"])
        if owner not in known_people:
            raise _source(path, row.line, action_section, f"列「→ 担当」の {owner!r} が §5 メンバーにありません")
        due = _clean_md(row.cells["期限"])
        _valid_date(due, path, row.line, action_section, "期限")
        task_matches = list(dict.fromkeys(re.findall(r"T-\d{2}", row.cells["起票（ID）"])))
        if len(task_matches) > 1:
            raise _source(path, row.line, action_section, f"列「起票（ID）」に複数の T-ID があります: {task_matches!r}")
        task_id = task_matches[0] if task_matches else None
        if task_id is not None and task_id not in task_ids:
            raise _source(path, row.line, action_section, f"列「起票（ID）」の {task_id} が 04_tasks/ にありません")
        actions.append({
            "text": _clean_md(row.cells["決定（アクション）"]),
            "owner": owner,
            "due": due,
            "dod": _clean_md(row.cells["完了の定義"]),
            "task": task_id,
        })
    action_rate_pattern = re.compile(
        r"決定がタスクになった割合:\s*(\d+)件\s*÷\s*(\d+)件\s*[＝=]\s*\*\*(\d+)%\*\*（保留(\d+)件）.*"
    )
    action_rate_line, action_rate_match = doc.unique_line(action_rate_pattern, action_section + " / タスク化割合")
    actions_tasked = int(action_rate_match.group(1))
    actions_total = int(action_rate_match.group(2))
    shown_action_rate = int(action_rate_match.group(3))
    actions_held = int(action_rate_match.group(4))
    actual_tasked = sum(item["task"] is not None for item in actions)
    actual_held = len(actions) - actual_tasked
    if not actions:
        raise _source(path, action_rate_line, action_section, "アクション表が0件です")
    expected_action_rate = _round_percent(actual_tasked, len(actions))
    if (
        actions_total != len(actions)
        or actions_tasked != actual_tasked
        or actions_held != actual_held
        or shown_action_rate != expected_action_rate
    ):
        raise _source(
            path,
            action_rate_line,
            action_section,
            f"タスク化割合行が表と一致しません。表示={actions_tasked}/{actions_total}/{shown_action_rate}%/保留{actions_held} 表={actual_tasked}/{len(actions)}/{expected_action_rate}%/保留{actual_held}",
        )

    meeting_decisions: list[str] = []
    decision_lines: dict[str, int] = {}
    for line_no, raw in enumerate(doc.lines, 1):
        for decision_id in re.findall(r"DEC-\d{8}-\d{2}", raw):
            if decision_id not in decision_lines:
                decision_lines[decision_id] = line_no
                meeting_decisions.append(decision_id)
    for decision_id in meeting_decisions:
        if decision_id not in decision_ids:
            raise _source(path, decision_lines[decision_id], "本文 / DEC", f"{decision_id} が 05_decision_log.md にありません")

    notes_section = "⑥ 気づき・なるほどメモ"
    notes_headers = ["気づき", "行き先（a/b/c）"]
    note_rows = doc.table(notes_section, notes_headers, prefix=True).active_rows(path, sample)
    notes: list[dict[str, str]] = []
    for row in note_rows:
        route_raw = _clean_md(row.cells["行き先（a/b/c）"])
        route = route_raw[:1]
        if route not in {"a", "b", "c"}:
            raise _source(path, row.line, notes_section, f"列「行き先（a/b/c）」の先頭は a/b/c が必要です: {route_raw!r}")
        detail_match = re.search(r"（(.*)）", route_raw)
        notes.append({
            "text": _clean_md(row.cells["気づき"]),
            "route": route,
            "detail": detail_match.group(1) if detail_match else "",
        })

    return {
        "id": meeting_id,
        "date": meeting_date,
        "time": f"{start_time}〜{end_time}",
        "minutes": minutes,
        "title": title,
        "facilitator": facilitator,
        "attendees": attendees,
        "review": review,
        "review_done": review_done,
        "review_due": review_due,
        "actions": actions,
        "actions_total": actions_total,
        "actions_tasked": actions_tasked,
        "actions_held": actions_held,
        "decisions": meeting_decisions,
        "notes": notes,
    }


TASK_REQUIRED_FIELDS = {"id", "title", "wp", "assignee", "due", "status", "definition_of_done"}
TASK_OPTIONAL_FIELDS = {"related", "evidence"}
TASK_FIELDS = TASK_REQUIRED_FIELDS | TASK_OPTIONAL_FIELDS


def parse_task(path: Path) -> dict[str, Any]:
    lines = _read(path).splitlines()
    if not lines or lines[0] != "---":
        raise _source(path, 1, "frontmatter", "先頭に --- が必要です")
    try:
        end = lines.index("---", 1)
    except ValueError as exc:
        raise _source(path, 1, "frontmatter", "閉じる --- がありません") from exc
    values: dict[str, Any] = {}
    field_lines: dict[str, int] = {}
    for index, raw in enumerate(lines[1:end], 2):
        if not raw.strip():
            continue
        if raw.startswith(" ") or "\t" in raw:
            raise _source(path, index, "frontmatter", "入れ子・インデントは未対応です")
        if ":" not in raw:
            raise _source(path, index, "frontmatter", "key: value 形式が必要です")
        key, _, raw_value = raw.partition(":")
        if key not in TASK_FIELDS:
            raise _source(path, index, "frontmatter", f"未知の列です: {key}")
        if key in values:
            raise _source(path, index, "frontmatter", f"列が重複しています: {key}")
        values[key] = _yaml_scalar(raw_value, path, index, f"frontmatter / {key}")
        field_lines[key] = index
    missing = sorted(TASK_REQUIRED_FIELDS - values.keys())
    if missing:
        raise _source(path, 1, "frontmatter", f"必須列がありません: {missing}")
    for field in TASK_OPTIONAL_FIELDS:
        values.setdefault(field, [])
    for field in TASK_REQUIRED_FIELDS:
        if not isinstance(values[field], str) or not values[field]:
            raise _source(path, field_lines[field], "frontmatter", f"列 {field} は空でない文字列が必要です")
    for field in ("related", "evidence"):
        if not isinstance(values[field], list):
            raise _source(path, field_lines[field], "frontmatter", f"列 {field} は文字列配列が必要です")
    if not TASK_ID_RE.fullmatch(values["id"]):
        raise _source(path, field_lines["id"], "frontmatter", f"task ID が不正です: {values['id']!r}")
    if path.stem != values["id"]:
        raise _source(path, field_lines["id"], "frontmatter", f"ファイル名 {path.stem!r} と ID {values['id']!r} が一致しません")
    if values["wp"] != "—" and not WP_ID_RE.fullmatch(values["wp"]):
        raise _source(path, field_lines["wp"], "frontmatter", f"WP ID が不正です: {values['wp']!r}")
    _valid_date(values["due"], path, field_lines["due"], "frontmatter", "due")
    if values["status"] not in ALL_TASK_STATES:
        raise _source(path, field_lines["status"], "frontmatter", f"状態が未知です: {values['status']!r}")
    if values["status"] == "完了" and not values["evidence"]:
        raise _source(path, field_lines.get("evidence", field_lines["status"]), "frontmatter", "完了タスクは evidence が必要です")
    values["_line_by_field"] = field_lines
    return values


def parse_tasks(directory: Path, wp_by_id: dict[str, dict[str, Any]], known_people: set[str], related_ids: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    paths = sorted(directory.glob("T-*.md"))
    if not paths:
        raise SourceError(f"{directory}:1: tasks: T-*.md が0件です")
    all_tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        task = parse_task(path)
        field_lines = task["_line_by_field"]
        task_id = task["id"]
        if task_id in seen:
            raise _source(path, field_lines["id"], "frontmatter", f"task ID が重複しています: {task_id}")
        seen.add(task_id)
        if task["wp"] != "—" and task["wp"] not in wp_by_id:
            raise _source(path, field_lines["wp"], "frontmatter", f"task {task_id} の WP {task['wp']} が 01_plan.md にありません")
        if task["assignee"] not in known_people:
            raise _source(path, field_lines["assignee"], "frontmatter", f"task {task_id} の assignee {task['assignee']!r} が 01_plan.md §5 にありません")
        for related in task["related"]:
            if related not in related_ids:
                raise _source(path, field_lines["related"], "frontmatter", f"task {task_id} の related {related!r} が台帳にありません（短縮・曖昧一致は不可）")
        all_tasks.append(task)
    active: list[dict[str, Any]] = []
    for task in all_tasks:
        if task["status"] not in ACTIVE_TASK_STATES:
            continue
        wp_label = "—" if task["wp"] == "—" else f"{task['wp']} {wp_by_id[task['wp']]['name']}"
        active.append({
            "id": task["id"],
            "text": task["title"],
            "wp": wp_label,
            "owner": task["assignee"],
            "due": task["due"],
            "state": task["status"],
            "related": "・".join(task["related"]),
            "dod": task["definition_of_done"],
        })
    active.sort(key=lambda item: (item["due"], item["id"]))
    return active, all_tasks


def _assert_people(path: Path, section: str, values: Iterable[str], known_people: set[str]) -> None:
    unknown = sorted(set(values) - known_people)
    if unknown:
        raise _source(path, 1, section, f"01_plan.md §5 にない担当です: {unknown}")


def _remaining_weeks(as_of: date, interview_end: date) -> int:
    add = (7 - as_of.weekday()) % 7
    if add == 0:
        add = 7
    next_monday = as_of + timedelta(days=add)
    days = (interview_end - next_monday).days + 1
    return math.ceil(days / 7) if days > 0 else 0


def _validate_no_derived(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in DERIVED_KEYS:
                raise SourceError(f"canonical JSON: {path}.{key}: 派生 key は保存できません")
            _validate_no_derived(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_no_derived(child, f"{path}[{index}]")


def build_canonical(root: Path) -> dict[str, Any]:
    names_path = root / "names.yml"
    names = parse_names(names_path)
    dashboard_path = root / "20_project/03_dashboard.md"
    dashboard_doc = MarkdownDoc(dashboard_path)
    sample_line, sample_match = dashboard_doc.unique_line(re.compile(r"> \*\*見本札\*\*: (true|false)"), "頭注 / 見本札")
    sample = sample_match.group(1) == "true"

    status = parse_charter(root / "20_project/00_charter.md", names, sample)
    plan_data = parse_plan(root / "20_project/01_plan.md", names, sample)
    stakeholder_data = parse_stakeholders(root / "20_project/08_stakeholders.md", sample)
    members: list[dict[str, Any]] = []
    for source in plan_data["member_sources"]:
        joined = stakeholder_data.get(source["name"])
        members.append({
            "name": source["name"],
            "role": joined["role"] if joined else None,
            "raci": source["raci"],
            "load": source["load"],
            "load_note": source["load_note"],
            "stakeholder": joined["stakeholder"] if joined else None,
        })
    design = parse_kpi_design(root / "20_project/02_kpi_tree.md", sample)
    current = parse_dashboard(dashboard_path, design, sample)
    project_id = names["PROJECT_ID"]
    decision_path = root / "20_project/05_decision_log.md"
    all_decisions = _parse_all_decisions(decision_path, sample)
    decisions = all_decisions[-2:]
    risks = parse_risks(root / "20_project/06_risk_ledger.md", project_id, sample)
    issues = parse_issues(root / "20_project/07_issue_ledger.md", project_id, sample)
    related_ledger_ids = {item["id"] for item in all_decisions + risks + issues}
    tasks, all_tasks = parse_tasks(root / "20_project/04_tasks", plan_data["wp_by_id"], plan_data["known_people"], related_ledger_ids)
    next_meeting = parse_weekly(
        root / "20_project/09_meetings/bodies/weekly.md",
        names,
        plan_data["known_people"],
        len(current["decide"]),
        current["updated_at"],
        sample,
    )
    last_meeting = parse_last_meeting(
        root / "20_project/09_meetings",
        names["PROJECT_SLUG"],
        plan_data["known_people"],
        {item["id"] for item in all_tasks},
        {item["id"] for item in all_decisions},
        current["updated_at"],
        next_meeting["date"],
        sample,
    )

    _assert_people(root / "20_project/03_dashboard.md", "KDI 担当", (item["owner"] for item in current["kdi"]), plan_data["known_people"])
    _assert_people(root / "20_project/03_dashboard.md", "決めどころ担当", (item["owner"] for item in current["decide"]), plan_data["known_people"])
    _assert_people(root / "20_project/06_risk_ledger.md", "リスク担当", (item["watcher"] for item in risks), plan_data["known_people"])
    _assert_people(root / "20_project/07_issue_ledger.md", "課題担当", (item["owner"] for item in issues), plan_data["known_people"])

    task_ids = {item["id"] for item in all_tasks}
    valid_decide_related = task_ids | related_ledger_ids
    for item in current["decide"]:
        for related in item["related"]:
            if related not in valid_decide_related:
                raise _source(dashboard_path, item["_line"], "今週これを決める", f"関連 ID {related!r} が正本にありません（短縮・曖昧一致は不可）")
        item.pop("_line", None)

    updated = date.fromisoformat(current["updated_at"])
    period_start = date.fromisoformat(names["PERIOD_START"])
    period_end = date.fromisoformat(names["PERIOD_END"])
    if not (period_start <= updated <= period_end):
        raise _source(dashboard_path, 1, "不変条件", "最終更新日がプロジェクト期間の外です")
    if current["kgi"]["deadline"] != names["PERIOD_END"]:
        raise _source(dashboard_path, 1, "不変条件", "KGI 期限が project.period.end と一致しません")
    elapsed_week = (updated - period_start).days // 7 + 1
    if len(current["kgi"]["history"]) != elapsed_week:
        raise _source(dashboard_path, 1, "不変条件", f"KGI history 長 {len(current['kgi']['history'])} が経過週 {elapsed_week} と一致しません")
    if current["kgi"]["history"][-1] != current["kgi"]["as_is"]:
        raise _source(dashboard_path, 1, "不変条件", "KGI history 末尾が現在値と一致しません")
    for item in current["kpi"]:
        if len(item["history"]) != elapsed_week:
            raise _source(dashboard_path, 1, "不変条件", f"KPI {item['name']} の history 長が経過週と一致しません")
        kpi_day, _ = _valid_datetime(item["as_of"], dashboard_path, 1, "不変条件", f"KPI {item['name']}.as_of")
        if kpi_day > updated:
            raise _source(dashboard_path, 1, "不変条件", f"KPI {item['name']} の鮮度が基準日より未来です")
    for item in current["freshness"]:
        stale_days = (updated - date.fromisoformat(item["as_of"][:10])).days
        if stale_days > 7:
            print(
                f"{dashboard_path}:{item['line']}: 鮮度警告: "
                f"{item['kind']}「{item['name']}」の鮮度は基準日から{stale_days}日前です",
                file=sys.stderr,
            )

    bottleneck = next(item for item in current["kpi"] if item.get("bottleneck"))
    pace_kdis = [item for item in current["kdi"] if item["target"] == bottleneck["pace_weekly"] and item["unit"] == bottleneck["unit"]]
    if len(pace_kdis) != 1:
        raise _source(dashboard_path, 1, "不変条件", f"律速ペースと一致する KDI は厳密に1件必要です: {len(pace_kdis)}件")

    output_source = current["output_source"]
    wp_counts = plan_data["wp_counts"]
    wps = [{"id": wp_id, **wp} for wp_id, wp in plan_data["wp_by_id"].items()]
    wps_counts = {
        "total": len(wps),
        "done": sum(1 for wp in wps if wp["state"] == "完了"),
        "doing": sum(1 for wp in wps if wp["state"] == "進行中"),
        "todo": sum(1 for wp in wps if wp["state"] == "未着手"),
    }
    if wps_counts != wp_counts:
        raise _source(
            root / "20_project/01_plan.md",
            1,
            "§2 WBS / 不変条件",
            f"output.wp_done/doing/todo/total と wps[] の状態集計が一致しません: output={wp_counts}, wps={wps_counts}",
        )
    if output_source["wp_actual"] != wp_counts["done"]:
        raise _source(dashboard_path, output_source["line"], "4段目: 出来高", "完了WP実績が 01_plan.md の状態集計と一致しません")
    overdue_active = [task for task in all_tasks if task["status"] in ACTIVE_TASK_STATES and date.fromisoformat(task["due"]) <= updated]
    if output_source["tasks_due"] != output_source["tasks_done"] + len(overdue_active):
        raise _source(dashboard_path, output_source["line"], "4段目: 出来高", f"期限到来 {output_source['tasks_due']} != 完了 {output_source['tasks_done']} + 未完了 {len(overdue_active)}")

    rem_weeks = max(
        0,
        _remaining_weeks(updated, date.fromisoformat(plan_data["plan"]["interview_window_end"])),
    )
    required_pace, required_pace_line = current["kgi_required_pace"]
    if rem_weeks == 0 and required_pace != "—":
        raise _source(
            dashboard_path,
            required_pace_line,
            "1段目: KGI",
            "面談期間終了後の必要ペースは — と書いてください",
        )
    actual_rate: float | None = None
    if rem_weeks > 0 and bottleneck["value"] > 0:
        actual_rate = current["kgi"]["as_is"] / bottleneck["value"]
    for item, (shown, line) in zip(current["decide"], current["landing_expected"]):
        lever = item["landing_lever"]
        if rem_weeks == 0:
            calculated = current["kgi"]["as_is"]
        else:
            rate = actual_rate if lever["conv_rate"] is None else lever["conv_rate"] / 100
            if rate is None:
                raise _source(dashboard_path, line, "今週これを決める", "実績の確定率は面談完了数が0件のため計算できません")
            calculated = math.floor(current["kgi"]["as_is"] + lever["pace_weekly"] * rem_weeks * rate)
        if calculated != shown:
            raise _source(dashboard_path, line, "今週これを決める", f"着地の試算 {shown} がてこからの計算 {calculated} と一致しません")

    canonical: dict[str, Any] = {
        "meta": {
            "schema": SCHEMA,
            "generated_at": current["updated_at"],
            "generator": GENERATOR,
            "source_root": SOURCE_ROOT,
            "sample": sample,
            "note": NOTE if sample else "",
        },
        "project": {
            "id": project_id,
            "name": names["PROJECT_NAME_JA"],
            "org": names["ORG_NAME_JA"],
            "our_org": names["OUR_ORG_NAME_JA"],
            "status": status,
            "pm": names["PM_NAME"],
            "leader": names["LEADER_NAME"],
            "period": {"start": names["PERIOD_START"], "end": names["PERIOD_END"]},
            "updated_at": current["updated_at"],
        },
        "plan": plan_data["plan"],
        "wps": wps,
        "headline": current["headline"],
        "kgi": current["kgi"],
        "kpi": current["kpi"],
        "kdi": current["kdi"],
        "output": {
            "wp_done": wp_counts["done"],
            "wp_total": wp_counts["total"],
            "wp_doing": wp_counts["doing"],
            "wp_todo": wp_counts["todo"],
            "wp_done_plan": output_source["wp_plan"],
            "tasks_done_week": output_source["tasks_done"],
            "tasks_due_week": output_source["tasks_due"],
            "note": output_source["note"],
        },
        "health": current["health"],
        "milestones": {
            "today": current["updated_at"],
            "overlap_note": plan_data["overlap_note"],
            "phases": plan_data["phases"],
        },
        "decide": current["decide"],
        "decisions": decisions,
        "risks": risks,
        "issues": issues,
        "next_meeting": next_meeting,
        "members": members,
        "last_meeting": last_meeting,
        "tasks": tasks,
    }
    if not (canonical["meta"]["generated_at"] == canonical["project"]["updated_at"] == canonical["kgi"]["as_of"] == canonical["milestones"]["today"]):
        raise _source(dashboard_path, 1, "不変条件", "generated_at / project.updated_at / kgi.as_of / milestones.today が一致しません")
    if type(canonical["meta"]["sample"]) is not bool:
        raise _source(dashboard_path, sample_line, "頭注 / 見本札", "sample は boolean が必要です")
    _validate_no_derived(canonical)
    return canonical


def render_json(canonical: dict[str, Any]) -> str:
    rendered = json.dumps(canonical, ensure_ascii=False, indent=2) + "\n"
    return (
        rendered.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


TARGETS_HEADER = (
    "# targets.yml — 生成物・手編集禁止\n"
    "# 復旧は `python3 tools/build_dashboard.py` の再実行。\n"
    "# 生成元: 20_project/02_kpi_tree.md・20_project/03_dashboard.md・20_project/01_plan.md・20_project/04_tasks/・20_project/08_stakeholders.md・20_project/09_meetings/・names.yml。\n"
)


def render_targets(canonical: dict[str, Any]) -> str:
    return TARGETS_HEADER + render_json(canonical)


@dataclass(frozen=True)
class HtmlBlock:
    prefix: str
    body: str
    suffix: str
    parsed: Any


SCRIPT_RE = re.compile(r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>", re.IGNORECASE | re.DOTALL)


def parse_html_block(text: str, path: Path) -> HtmlBlock:
    matches: list[re.Match[str]] = []
    for match in SCRIPT_RE.finditer(text):
        attrs = match.group("attrs")
        if re.search(r"\bid\s*=\s*(['\"])dashboard-data\1", attrs, re.IGNORECASE):
            matches.append(match)
    if len(matches) != 1:
        raise HtmlError(f"{path}: script#dashboard-data が {len(matches)} 件です（厳密に1件必要）")
    match = matches[0]
    attrs = match.group("attrs")
    if not re.search(r"\btype\s*=\s*(['\"])application/json\1", attrs, re.IGNORECASE):
        raise HtmlError(f"{path}: script#dashboard-data の type は application/json が必要です")
    body = match.group("body")
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HtmlError(f"{path}: script#dashboard-data の JSON が不正です: {exc}") from exc
    return HtmlBlock(text[: match.start("body")], body, text[match.end("body") :], parsed)


def render_html(block: HtmlBlock, canonical: dict[str, Any]) -> str:
    inner = "\n" + render_json(canonical)
    rendered = block.prefix + inner + block.suffix
    if not rendered.startswith(block.prefix) or not rendered.endswith(block.suffix):
        raise HtmlError("HTML の script ブロック外が変わりました")
    return rendered


def parse_targets(text: str) -> Any:
    body_lines = [line for line in text.splitlines() if not line.startswith("#")]
    body = "\n".join(body_lines).strip()
    if not body:
        raise ValueError("JSON 本文がありません")
    return json.loads(body)


def json_diffs(expected: Any, actual: Any, path: str = "$") -> list[str]:
    if type(expected) is not type(actual):
        return [f"{path}: expected type={type(expected).__name__} value={expected!r}, actual type={type(actual).__name__} value={actual!r}"]
    if isinstance(expected, dict):
        diffs: list[str] = []
        for key in expected:
            child = f"{path}.{key}"
            if key not in actual:
                diffs.append(f"{child}: missing (expected={expected[key]!r})")
            else:
                diffs.extend(json_diffs(expected[key], actual[key], child))
        for key in actual:
            if key not in expected:
                diffs.append(f"{path}.{key}: unexpected (actual={actual[key]!r})")
        return diffs
    if isinstance(expected, list):
        diffs = []
        if len(expected) != len(actual):
            diffs.append(f"{path}: length expected={len(expected)}, actual={len(actual)}")
        for index, (left, right) in enumerate(zip(expected, actual)):
            diffs.extend(json_diffs(left, right, f"{path}[{index}]"))
        return diffs
    if expected != actual:
        return [f"{path}: expected={expected!r}, actual={actual!r}"]
    return []


def atomic_write(path: Path, text: str) -> bool:
    data = text.encode("utf-8")
    try:
        current = path.read_bytes()
    except FileNotFoundError:
        current = None
    if current == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise
    return True


def check(root: Path, canonical: dict[str, Any], html_block: HtmlBlock) -> int:
    diffs: list[str] = []
    target_path = root / TARGETS_PATH
    try:
        target_text = _read(target_path)
        target_doc = parse_targets(target_text)
    except (SourceError, ValueError, json.JSONDecodeError) as exc:
        diffs.append(f"targets {TARGETS_PATH} $: 読めません: {exc}")
    else:
        diffs.extend(f"targets {diff}" for diff in json_diffs(canonical, target_doc))
    diffs.extend(f"html {diff}" for diff in json_diffs(canonical, html_block.parsed))
    if diffs:
        print("⚠️ 生成物が古いです")
        for diff in diffs:
            print(f"  {diff}")
        return 1
    print("✅ 正本・targets.yml・HTML埋め込みJSONは一致しています")
    return 0


def run(root: Path, check_only: bool) -> int:
    canonical = build_canonical(root)
    html_path = root / HTML_PATH
    html_text = _read(html_path, html=True)
    block = parse_html_block(html_text, html_path)
    if check_only:
        return check(root, canonical, block)
    targets_text = render_targets(canonical)
    html_rendered = render_html(block, canonical)
    targets_changed = atomic_write(root / TARGETS_PATH, targets_text)
    html_changed = atomic_write(html_path, html_rendered)
    print(f"{'更新' if targets_changed else '変更なし'}: {TARGETS_PATH}")
    print(f"{'更新' if html_changed else '変更なし'}: {HTML_PATH}（dashboard-data の中身だけ）")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="20_project の正本から targets.yml と dashboard-data を作る",
        epilog="終了コード: 0=一致/生成成功, 1=--checkで生成物が古い, 2=正本違反, 3=HTMLブロック違反",
    )
    parser.add_argument("--check", action="store_true", help="完全 read-only で生成物との差を JSON path 単位に確認する")
    parser.add_argument("--root", type=Path, default=None, help="repo root（既定: tools/ の親）")
    args = parser.parse_args(argv)
    root = (args.root or Path(__file__).resolve().parent.parent).resolve()
    try:
        return run(root, args.check)
    except SourceError as exc:
        print(f"⛔ 正本エラー: {exc}", file=sys.stderr)
        return 2
    except HtmlError as exc:
        print(f"⛔ HTMLエラー: {exc}", file=sys.stderr)
        return 3
    except OSError as exc:
        print(f"⛔ 正本エラー: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
