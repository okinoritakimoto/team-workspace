#!/usr/bin/env python3
"""names.yml の限定書式を読み、文章中の {{KEY}} を差し替える。

ダッシュボード JSON と targets.yml は build_dashboard.py だけが書く。
この道具は文章の差し替え、既存値の入れ替え、差し替え印の残存検出だけを行う。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


TEXT_SUFFIXES = {".md", ".yml", ".yaml", ".json", ".html", ".txt", ".py"}
SKIP_DIRS = {".git", "tools", "node_modules", ".local"}
SKIP_FILES = {
    "names.yml",
    "names.applied.yml",
    "20_project/targets.yml",
    "60_outputs/dashboard/index.html",
}
NAMES_FILE = "names.yml"
APPLIED_FILE = "names.applied.yml"
PLACEHOLDER = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
KEY_SHAPE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class NamesError(Exception):
    pass


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        inner = value[1:-1]
        return inner.replace('\\"', '"') if value[0] == '"' else inner.replace("''", "'")
    return value


def parse_names(path: Path) -> dict[str, dict]:
    """keys → KEY → value/sample/required/description の3段だけを読む。"""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise NamesError(f"{path}: 読めません: {exc}") from exc
    keys: dict[str, dict] = {}
    current: str | None = None
    in_keys = False
    for line_no, raw in enumerate(lines, 1):
        line = raw.split(" #", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if not line.strip():
            continue
        if "\t" in line[: len(line) - len(line.lstrip())]:
            raise NamesError(f"{path}:{line_no}: インデントにタブは使えません")
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()
        if indent == 0:
            if body == "keys:":
                if in_keys or keys:
                    raise NamesError(f"{path}:{line_no}: keys が重複しています")
                in_keys = True
            elif body.startswith("schema:"):
                if body.partition(":")[2].strip() != "talent-pj-names/v1":
                    raise NamesError(f"{path}:{line_no}: schema は talent-pj-names/v1 が必要です")
                in_keys = False
            else:
                raise NamesError(f"{path}:{line_no}: 未知の最上位キーです: {body}")
            current = None
            continue
        if not in_keys:
            raise NamesError(f"{path}:{line_no}: keys: の外に値があります")
        if indent == 2 and body.endswith(":"):
            current = body[:-1].strip()
            if not KEY_SHAPE.fullmatch(current):
                raise NamesError(f"{path}:{line_no}: キー名は大文字英数字と _ だけです: {current}")
            if current in keys:
                raise NamesError(f"{path}:{line_no}: キーが重複しています: {current}")
            keys[current] = {}
            continue
        if indent == 4 and current and ":" in body:
            field, _, raw_value = body.partition(":")
            field = field.strip()
            value = raw_value.strip()
            if field not in {"value", "sample", "required", "description"}:
                raise NamesError(f"{path}:{line_no}: 未知の列です: {current}.{field}")
            if field in keys[current]:
                raise NamesError(f"{path}:{line_no}: 列が重複しています: {current}.{field}")
            if field == "required":
                if value not in {"true", "false"}:
                    raise NamesError(f"{path}:{line_no}: required は true/false が必要です")
                keys[current][field] = value == "true"
            else:
                keys[current][field] = _unquote(value)
            continue
        raise NamesError(f"{path}:{line_no}: keys → KEY → 4列の3段だけに対応します")
    expected = {"value", "sample", "required", "description"}
    if not keys:
        raise NamesError(f"{path}: keys がありません")
    for key, fields in keys.items():
        if set(fields) != expected:
            raise NamesError(f"{path}: {key} は4列が必要です。欠落={sorted(expected - set(fields))} 余分={sorted(set(fields) - expected)}")
    return keys


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def iter_targets(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = _relative(path, root)
        if relative in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        yield path


def scan(root: Path) -> dict[Path, list[tuple[int, str]]]:
    found: dict[Path, list[tuple[int, str]]] = {}
    for path in iter_targets(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        hits: list[tuple[int, str]] = []
        for line_no, line in enumerate(text.splitlines(), 1):
            hits.extend((line_no, match.group(1)) for match in PLACEHOLDER.finditer(line))
        if hits:
            found[path] = hits
    return found


def _optional_spots(
    names: dict[str, dict], field: str, found: dict[Path, list[tuple[int, str]]], root: Path
) -> list[str]:
    lines: list[str] = []
    for key, metadata in names.items():
        if metadata["required"] or metadata[field]:
            continue
        spots = [f"{_relative(path, root)}:{line_no}" for path, hits in found.items() for line_no, hit in hits if hit == key]
        if spots:
            lines.append(f"  {{{{{key}}}}}: " + ", ".join(spots))
    return lines


def cmd_check(root: Path, names: dict[str, dict]) -> int:
    found = scan(root)
    registered: dict[str, int] = {}
    unknown: dict[str, int] = {}
    for hits in found.values():
        for _, key in hits:
            target = registered if key in names else unknown
            target[key] = target.get(key, 0) + 1
    required_left = {
        key: count
        for key, count in registered.items()
        if names[key]["required"] or names[key]["value"]
    }
    optional_left = {
        key: count
        for key, count in registered.items()
        if not names[key]["required"] and not names[key]["value"]
    }
    if unknown:
        print("⛔ names.yml に無い差し替え点があります:")
        for key in sorted(unknown):
            print(f"  {{{{{key}}}}} ×{unknown[key]}")
        return 3
    if required_left:
        print("⚠️ 未適用の差し替え点があります:")
        for path, hits in found.items():
            relevant = [(line_no, key) for line_no, key in hits if key in required_left]
            for line_no, key in relevant:
                print(f"  {_relative(path, root)}:{line_no}: {{{{{key}}}}}")
        return 1
    print("✅ 必須の差し替え点は残っていません")
    if optional_left:
        print("✅ 任意キーは未記入のままです（このままで完了）:")
        for line in _optional_spots(names, "value", found, root):
            print(line)
    print("✅ 完了 — 配れる状態です")
    return 0


def _write_applied(root: Path, values: dict[str, str]) -> None:
    lines = [
        "# names.applied.yml — いまこの repo に入っている値の控え（機械が書く・手で直さない）",
        "# 名前を変えるとき: names.yml の value を新しい値にして `python3 tools/apply_names.py --rename` を実行する。",
        "schema: talent-pj-names-applied/v1",
        "values:",
    ]
    for key, value in values.items():
        if value:
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'  {key}: "{escaped}"')
    (root / APPLIED_FILE).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _read_applied(root: Path) -> dict[str, str]:
    path = root / APPLIED_FILE
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, raw_value = line.partition(":")
        key = key.strip()
        if KEY_SHAPE.fullmatch(key):
            values[key] = _unquote(raw_value.strip())
    return values


def cmd_apply(root: Path, names: dict[str, dict], *, dry_run: bool, use_sample: bool) -> int:
    found = scan(root)
    unknown = sorted({key for hits in found.values() for _, key in hits if key not in names})
    if unknown:
        print("⛔ names.yml に無い差し替え点があるため、何も書きません: " + ", ".join(f"{{{{{key}}}}}" for key in unknown))
        return 3
    field = "sample" if use_sample else "value"
    present = {key for hits in found.values() for _, key in hits}
    empty_required = sorted(key for key, metadata in names.items() if metadata["required"] and not metadata[field] and key in present)
    if empty_required:
        print(f"⛔ {field} が空の必須キーがあるため、何も書きません: " + ", ".join(empty_required))
        return 2
    values = {key: metadata[field] for key, metadata in names.items() if metadata[field]}
    plans: list[tuple[Path, str, int]] = []
    per_key: dict[str, int] = {}
    for path, hits in found.items():
        text = path.read_text(encoding="utf-8")
        new = PLACEHOLDER.sub(lambda match: values.get(match.group(1), match.group(0)), text)
        if new == text:
            continue
        count = 0
        for _, key in hits:
            if key in values:
                per_key[key] = per_key.get(key, 0) + 1
                count += 1
        plans.append((path, new, count))
    for path, new, count in plans:
        print(f"  {'[予定] ' if dry_run else ''}{_relative(path, root)}: {count} 箇所")
        if not dry_run:
            path.write_text(new, encoding="utf-8")
    if not plans:
        print("✅ 置換対象なし（差分ゼロ）")
        if (root / APPLIED_FILE).exists() and not dry_run:
            print(f"   この repo は名前が入った状態です（控え {APPLIED_FILE} あり）。入れ替えは --rename を使ってください（控えは変更していません）")
            return 0
    else:
        print(f"{'📝' if dry_run else '✅'} 置換{'予定' if dry_run else '完了'}: {len(plans)} ファイル / {sum(per_key.values())} 箇所")
    optional = _optional_spots(names, field, found, root)
    if optional:
        print("✅ 任意キーは空なので、その差し替え点は残します:")
        for line in optional:
            print(line)
    if not dry_run and not use_sample:
        _write_applied(root, {key: metadata["value"].strip() for key, metadata in names.items()})
        print(f"   控え {APPLIED_FILE} を更新しました")
        print("   画面は `python3 tools/build_dashboard.py` で作り直してください")
    return 0


def cmd_rename(root: Path, names: dict[str, dict]) -> int:
    old = _read_applied(root)
    if not old:
        print(f"⛔ {APPLIED_FILE} が見つからないか空です。初回は --rename なしで実行してください")
        return 8
    new = {key: metadata["value"].strip() for key, metadata in names.items()}
    empty_required = sorted(key for key, metadata in names.items() if metadata["required"] and not new[key])
    if empty_required:
        print("⛔ value が空の必須キーがあるため、何も書きません: " + ", ".join(empty_required))
        return 2
    pairs = [(key, old[key], new[key]) for key in old if key in new and old[key] and new[key] and old[key] != new[key]]
    pairs.sort(key=lambda item: len(item[1]), reverse=True)
    if not pairs:
        print("✅ 入れ替える値はありません（names.yml と控えが同じです）")
        return 0
    plans: list[tuple[Path, str]] = []
    for path in iter_targets(root):
        raw = path.read_text(encoding="utf-8")
        rendered = raw
        for _, old_value, new_value in pairs:
            rendered = rendered.replace(old_value, new_value)
        if rendered != raw:
            plans.append((path, rendered))
    for path, rendered in plans:
        path.write_text(rendered, encoding="utf-8")
    _write_applied(root, new)
    print(f"✅ {len(plans)} ファイルを入れ替えました")
    print("   dashboard-data と targets.yml は変更していません")
    print("   続けて `python3 tools/build_dashboard.py` を実行してください")
    return 0


EXIT_HELP = """終了コード:
  0  適用・入れ替え成功、または --check で必須の残存なし
  1  --check で適用すべき差し替え点が残っている
  2  names.yml の構文違反、または required の値が空（何も書かない）
  3  names.yml に無い差し替え点がある（何も書かない）
  7  names.yml が見つからない
  8  --rename に必要な names.applied.yml がない

画面の反映:
  apply_names.py は dashboard-data と targets.yml を書き換えません。
  名前の適用後に `python3 tools/build_dashboard.py` を実行してください。"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="names.yml の値を文章の差し替え点 {{KEY}} へ適用する",
        epilog=EXIT_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--check", action="store_true", help="文章に残った差し替え点を file:line で確認する")
    parser.add_argument("--dry-run", action="store_true", help="置換予定だけ表示し、書かない")
    parser.add_argument("--sample", action="store_true", help="value ではなく sample を使う")
    parser.add_argument("--rename", action="store_true", help="控えの旧値を names.yml の新しい value へ入れ替える")
    parser.add_argument("--root", type=Path, default=None, help="names.yml のある root（既定: tools/ の親）")
    args = parser.parse_args(argv)
    root = (args.root or Path(__file__).resolve().parent.parent).resolve()
    names_path = root / NAMES_FILE
    if not names_path.is_file():
        print(f"⛔ {names_path} が見つかりません（--root で場所を指定してください）")
        return 7
    try:
        names = parse_names(names_path)
    except NamesError as exc:
        print(f"⛔ names.yml エラー: {exc}")
        return 2
    if args.check:
        return cmd_check(root, names)
    if args.rename:
        return cmd_rename(root, names)
    return cmd_apply(root, names, dry_run=args.dry_run, use_sample=args.sample)


if __name__ == "__main__":
    raise SystemExit(main())
