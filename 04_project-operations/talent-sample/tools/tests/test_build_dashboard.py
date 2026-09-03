from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "tools/build_dashboard.py"
APPLY_NAMES = REPO / "tools/apply_names.py"

spec = importlib.util.spec_from_file_location("build_dashboard_under_test", SCRIPT)
assert spec and spec.loader
build = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = build
spec.loader.exec_module(build)


# 正本から作った期待値の全量を、固定キー順・script escape 済み JSON の digest で保存する。
# digest が変わる変更は、下の key/value assertion と合わせて意図を確認して更新する。
GOLDEN_JSON_SHA256 = "8ba80abce38de4acc848408e2e14fd47a7c2195eb7a70d342868e051139f2bf5"


COPY_FILES = [
    "names.yml",
    "20_project/00_charter.md",
    "20_project/01_plan.md",
    "20_project/02_kpi_tree.md",
    "20_project/03_dashboard.md",
    "20_project/05_decision_log.md",
    "20_project/06_risk_ledger.md",
    "20_project/07_issue_ledger.md",
    "20_project/08_stakeholders.md",
    "20_project/09_meetings/MTG-talent-sample-20260824.md",
    "20_project/09_meetings/MTG-talent-sample-20260828.md",
    "20_project/09_meetings/bodies/weekly.md",
    "20_project/targets.yml",
    "60_outputs/dashboard/index.html",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise AssertionError(f"{path}: replacement source count={count}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def remove_matching_line(path: Path, needle: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    indexes = [index for index, line in enumerate(lines) if needle in line]
    if len(indexes) != 1:
        raise AssertionError(f"{path}: matching line count={len(indexes)}: {needle!r}")
    del lines[indexes[0]]
    path.write_text("".join(lines), encoding="utf-8")


def output_state(root: Path) -> tuple[tuple[str, int], tuple[str, int]]:
    paths = [root / "20_project/targets.yml", root / "60_outputs/dashboard/index.html"]
    return tuple((sha(path), path.stat().st_mtime_ns) for path in paths)  # type: ignore[return-value]


def convert_sample_copy_to_live(root: Path) -> None:
    """写しの見本行を境界後へ移し、JSON に見本文言を残さない live 入力にする。"""

    source_paths = [
        root / relative
        for relative in COPY_FILES
        if relative.endswith((".md", ".yml")) and relative != "20_project/targets.yml"
    ]
    source_paths.extend(sorted((root / "20_project/04_tasks").glob("T-*.md")))
    replacements = [
        ("PJ-2026Q3-talent-sample", "PJ-2026Q3-talent-live"),
        ("talent-sample", "talent-live"),
        ("サンプル株式会社", "株式会社A"),
        ("人材プロジェクト（サンプル）", "人材プロジェクト"),
        ("（すべてサンプル）", ""),
        ("（サンプル）", ""),
        ("（見本）", ""),
    ]
    for path in source_paths:
        text = path.read_text(encoding="utf-8")
        for old, new in replacements:
            text = text.replace(old, new)
        text = text.replace("見本札", "__SAMPLE_FLAG__")
        text = text.replace("見本", "").replace("サンプル", "")
        text = text.replace("__SAMPLE_FLAG__", "見本札")
        path.write_text(text, encoding="utf-8")

    dashboard = root / "20_project/03_dashboard.md"
    replace_once(dashboard, "> **見本札**: true", "> **見本札**: false")

    table_paths = [path for path in source_paths if path.suffix == ".md" and "04_tasks" not in path.parts]
    for path in table_paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        index = 0
        while index + 1 < len(lines):
            if not (lines[index].strip().startswith("|") and lines[index + 1].strip().startswith("|")):
                index += 1
                continue
            separators = [cell.strip() for cell in lines[index + 1].strip()[1:-1].split("|")]
            if not separators or not all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in separators):
                index += 1
                continue
            row_end = index + 2
            while row_end < len(lines) and lines[row_end].strip().startswith("|"):
                row_end += 1
            rows = lines[index + 2 : row_end]
            boundary_indexes = []
            for row_index, row in enumerate(rows):
                cells = [cell.strip() for cell in row.strip()[1:-1].split("|")]
                if cells and all(cell == "─" for cell in cells):
                    boundary_indexes.append(row_index)
            if boundary_indexes:
                rows = rows[: boundary_indexes[0]]
            boundary = "| " + " | ".join("─" for _ in separators) + " |"
            lines[index + 2 : row_end] = [boundary, *rows]
            index += 3 + len(rows)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    for old_path in sorted((root / "20_project/09_meetings").glob("MTG-talent-sample-*.md")):
        old_path.rename(old_path.with_name(old_path.name.replace("talent-sample", "talent-live")))


class DashboardCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in COPY_FILES:
            source = REPO / relative
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        task_target = self.root / "20_project/04_tasks"
        task_target.mkdir(parents=True)
        for source in sorted((REPO / "20_project/04_tasks").glob("T-*.md")):
            shutil.copy2(source, task_target / source.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_build(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def assert_exit(self, expected: int, *args: str) -> str:
        result = self.run_build(*args)
        self.assertEqual(expected, result.returncode, result.stdout)
        return result.stdout

    def fresh_root(self) -> Path:
        other = Path(tempfile.mkdtemp(dir=self.temp.name))
        for relative in COPY_FILES:
            source = REPO / relative
            target = other / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        target_tasks = other / "20_project/04_tasks"
        target_tasks.mkdir(parents=True)
        for source in sorted((REPO / "20_project/04_tasks").glob("T-*.md")):
            shutil.copy2(source, target_tasks / source.name)
        return other

    def run_at(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )

    def test_01_current_sample_matches_golden_json(self) -> None:
        canonical = build.build_canonical(self.root)
        digest = hashlib.sha256(build.render_json(canonical).encode("utf-8")).hexdigest()
        self.assertEqual(GOLDEN_JSON_SHA256, digest)
        self.assertEqual("talent-dashboard/v4", canonical["meta"]["schema"])
        self.assertEqual("tools/build_dashboard.py", canonical["meta"]["generator"])
        self.assertIs(canonical["meta"]["sample"], True)
        self.assertEqual(
            ["name", "role", "raci", "load", "load_note", "stakeholder"],
            list(canonical["members"][0]),
        )
        self.assertEqual(
            [
                "PM（サンプル）", "リーダー（サンプル）", "現場責任者（サンプル）",
                "採用担当A（サンプル）", "採用担当B（サンプル）", "事務担当（サンプル）",
                "受け入れ担当（サンプル）",
            ],
            [member["name"] for member in canonical["members"]],
        )
        self.assertEqual(30, canonical["members"][0]["load"]["8月"])
        self.assertEqual("A", canonical["members"][0]["raci"]["WP-05"])
        self.assertEqual("指導", canonical["members"][0]["stakeholder"]["engagement"])
        self.assertEqual("MTG-talent-sample-20260828", canonical["last_meeting"]["id"])
        self.assertEqual(
            ["id", "date", "time", "minutes", "title", "facilitator", "attendees", "review", "review_done", "review_due", "actions", "actions_total", "actions_tasked", "actions_held", "decisions", "notes"],
            list(canonical["last_meeting"]),
        )
        self.assertEqual("PJ-2026Q3-talent-sample/ISS-01", canonical["tasks"][0]["related"])
        self.assertEqual("現場責任者（サンプル）", canonical["tasks"][0]["owner"])
        self.assertEqual("WP-03 面談の運営（枠・日程・記録）", canonical["tasks"][0]["wp"])
        self.assertEqual(["id", "text", "wp", "owner", "due", "state", "related", "dod"], list(canonical["tasks"][0]))
        task_dod = {
            path.stem: build.parse_task(path)["definition_of_done"]
            for path in sorted((self.root / "20_project/04_tasks").glob("T-*.md"))
        }
        self.assertEqual(task_dod, {task["id"]: task["dod"] for task in canonical["tasks"]})
        self.assertEqual(canonical, build.parse_targets((self.root / "20_project/targets.yml").read_text(encoding="utf-8")))
        block = build.parse_html_block((self.root / "60_outputs/dashboard/index.html").read_text(encoding="utf-8"), self.root / "60_outputs/dashboard/index.html")
        self.assertEqual(canonical, block.parsed)

    def test_02_two_builds_keep_hash_and_mtime(self) -> None:
        self.assert_exit(0)
        first = output_state(self.root)
        self.assert_exit(0)
        second = output_state(self.root)
        self.assertEqual(first, second)

    def test_03_html_prefix_and_suffix_are_byte_stable(self) -> None:
        html = self.root / "60_outputs/dashboard/index.html"
        replace_once(html, '"generator": "tools/build_dashboard.py"', '"generator": "stale"')
        before = build.parse_html_block(html.read_text(encoding="utf-8"), html)
        prefix_hash = hashlib.sha256(before.prefix.encode("utf-8")).hexdigest()
        suffix_hash = hashlib.sha256(before.suffix.encode("utf-8")).hexdigest()
        self.assert_exit(0)
        after = build.parse_html_block(html.read_text(encoding="utf-8"), html)
        self.assertEqual(prefix_hash, hashlib.sha256(after.prefix.encode("utf-8")).hexdigest())
        self.assertEqual(suffix_hash, hashlib.sha256(after.suffix.encode("utf-8")).hexdigest())

    def test_04_check_reports_stale_and_is_read_only(self) -> None:
        source = self.root / "20_project/03_dashboard.md"
        replace_once(source, "必要な面談90人に対しリストは132人。42人の余裕がある", "必要な面談90人に対しリストは132人。余裕は42人")
        before = output_state(self.root)
        output = self.assert_exit(1, "--check")
        after = output_state(self.root)
        self.assertEqual(before, after)
        self.assertIn("$.kpi[0].note", output)

    def test_05_missing_required_values_never_write_outputs(self) -> None:
        cases = [
            ("names.yml", '    value: "PJ-2026Q3-talent-sample"', '    value: ""'),
            ("20_project/02_kpi_tree.md", "| 受け入れ確定人数 | 参加に合意し、受け入れ日が決まった人 | 20 | 人 | 2026-11-27 |", "| 受け入れ確定人数 | 参加に合意し、受け入れ日が決まった人 | | 人 | 2026-11-27 |"),
            ("20_project/04_tasks/T-01.md", 'due: "2026-09-02"\n', ""),
        ]
        for relative, old, new in cases:
            with self.subTest(relative=relative):
                root = self.fresh_root()
                replace_once(root / relative, old, new)
                before = output_state(root)
                result = self.run_at(root)
                self.assertEqual(2, result.returncode, result.stdout)
                self.assertEqual(before, output_state(root))

    def test_06_column_reorder_succeeds(self) -> None:
        path = self.root / "20_project/02_kpi_tree.md"
        old = (
            "| 指標名 | 一言訳（数え方） | 目標値（目標） | 単位 | 期限 |\n"
            "|--------|---------------|---------------|------|------|\n"
            "| 受け入れ確定人数 | 参加に合意し、受け入れ日が決まった人 | 20 | 人 | 2026-11-27 |"
        )
        new = (
            "| 単位 | 指標名 | 期限 | 目標値（目標） | 一言訳（数え方） |\n"
            "|------|--------|------|---------------|---------------|\n"
            "| 人 | 受け入れ確定人数 | 2026-11-27 | 20 | 参加に合意し、受け入れ日が決まった人 |"
        )
        replace_once(path, old, new)
        self.assert_exit(0)
        self.assert_exit(0, "--check")

    def test_07_column_missing_duplicate_unknown_and_cell_count_fail(self) -> None:
        cases = [
            ("| 指標名 | 一言訳（数え方） | 目標値（目標） | 単位 | 期限 |", "| 指標名 | 一言訳（数え方） | 目標値（目標） | 単位 |"),
            ("| 指標名 | 一言訳（数え方） | 目標値（目標） | 単位 | 期限 |", "| 指標名 | 一言訳（数え方） | 目標値（目標） | 目標値（目標） | 期限 |"),
            ("| 指標名 | 一言訳（数え方） | 目標値（目標） | 単位 | 期限 |", "| 指標名 | 一言訳（数え方） | 目標値（目標） | 未知列 | 期限 |"),
            ("| 受け入れ確定人数 | 参加に合意し、受け入れ日が決まった人 | 20 | 人 | 2026-11-27 |", "| 受け入れ確定人数 | 参加に合意し、受け入れ日が決まった人 | 20 | 人 |"),
        ]
        for index, (old, new) in enumerate(cases):
            with self.subTest(case=index):
                root = self.fresh_root()
                replace_once(root / "20_project/02_kpi_tree.md", old, new)
                result = self.run_at(root)
                self.assertEqual(2, result.returncode, result.stdout)

    def test_08_boundary_mixing_and_partial_rows_fail(self) -> None:
        cases = [
            ("20_project/01_plan.md", "| ─ | ─ | ─ | ─ | ─ | ─ |", "| ─ | X | ─ | ─ | ─ | ─ |"),
            ("20_project/01_plan.md", "| WP-13 | | | | | 未着手 |", "| WP-13 | 追加成果物 | 完了を確認できる | PM（サンプル） | 2026-11-27 | 未着手 |"),
            ("20_project/03_dashboard.md", "| 候補者リスト数 | 132人 | 110% | +12人 | 2026-09-04 09:00 | 必要な面談90人に対しリストは132人。42人の余裕がある |", "| 候補者リスト数 | 132人 | 110% | +12人 | | 必要な面談90人に対しリストは132人。42人の余裕がある |"),
        ]
        for relative, old, new in cases:
            with self.subTest(relative=relative, new=new[:20]):
                root = self.fresh_root()
                replace_once(root / relative, old, new)
                result = self.run_at(root)
                self.assertEqual(2, result.returncode, result.stdout)

    def test_09_boolean_and_numbers_keep_native_types(self) -> None:
        canonical = build.build_canonical(self.root)
        self.assertIs(type(canonical["meta"]["sample"]), bool)
        self.assertIs(type(canonical["milestones"]["phases"][0]["gate_done"]), bool)
        self.assertIs(type(canonical["kgi"]["as_is"]), int)
        self.assertIs(type(canonical["decide"][0]["landing_lever"]["conv_rate"]), type(None))
        root = self.fresh_root()
        names_path = root / "names.yml"
        names_text = names_path.read_text(encoding="utf-8")
        names_path.write_text(names_text.replace("    required: true", '    required: "true"', 1), encoding="utf-8")
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)

    def test_10_names_and_charter_id_and_period_must_match(self) -> None:
        cases = [
            ("`PJ-2026Q3-talent-sample`", "`PJ-2026Q3-other`"),
            ("2026-08-17 〜 2026-11-27", "2026-08-18 〜 2026-11-27"),
        ]
        for old, new in cases:
            with self.subTest(new=new):
                root = self.fresh_root()
                replace_once(root / "20_project/00_charter.md", old, new)
                result = self.run_at(root)
                self.assertEqual(2, result.returncode, result.stdout)

    def test_11_health_fixed_order_and_single_bottleneck(self) -> None:
        root = self.fresh_root()
        path = root / "20_project/03_dashboard.md"
        first = "| スケジュール | 🟡 注意 | 必要ペース週8人に対し今週は5人。2026-09-07 に決めれば20人に届く。決めなければ着地14人 |"
        second = "| スコープ | 🟢 健全 | 受け入れ20人・4フェーズ・期限（2026-11-27）は開始日（2026-08-17）から変更なし |"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace(first + "\n" + second, second + "\n" + first, 1), encoding="utf-8")
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)

        root = self.fresh_root()
        replace_once(root / "20_project/02_kpi_tree.md", "| 候補者リスト数 | 連絡先が分かり、打診できる人 | 累計 | 上がると良い | 120 | 人 | |", "| 候補者リスト数 | 連絡先が分かり、打診できる人 | 累計 | 上がると良い | 120 | 人 | ● |")
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)

    def test_12_history_length_and_last_value_invariants(self) -> None:
        cases = [
            ("| 第3週 | 2026-08-31〜2026-09-06 | 4人 | 132人 | 18人 | 22% | 40% | 5人 | 8人 | 面談官2名が他案件へ移った（−3）。今週はリーダー（サンプル）が1人ぶん肩代わりして5人 |\n", ""),
            ("| 第3週 | 2026-08-31〜2026-09-06 | 4人 | 132人 | 18人 | 22% | 40% | 5人 | 8人 |", "| 第3週 | 2026-08-31〜2026-09-06 | 4人 | 131人 | 18人 | 22% | 40% | 5人 | 8人 |"),
        ]
        for old, new in cases:
            with self.subTest(new=new[:30]):
                root = self.fresh_root()
                replace_once(root / "20_project/03_dashboard.md", old, new)
                result = self.run_at(root)
                self.assertEqual(2, result.returncode, result.stdout)

    def test_13_kdi_week_target_matches_bottleneck_pace(self) -> None:
        replace_once(
            self.root / "20_project/02_kpi_tree.md",
            "| **面談の実施** | 実際に面談を行った人数 | **8** | 人 | **週8人**（90人 ÷ 面談期間12週 ＝ 7.5 → 切り上げ） |",
            "| **面談の実施** | 実際に面談を行った人数 | **7** | 人 | **週8人**（90人 ÷ 面談期間12週 ＝ 7.5 → 切り上げ） |",
        )
        self.assert_exit(2)

    def test_14_wp_and_due_equations_are_checked(self) -> None:
        root = self.fresh_root()
        replace_once(root / "20_project/03_dashboard.md", "| 完了WP数（累計） | 3 | 3 |", "| 完了WP数（累計） | 2 | 3 |")
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)

        root = self.fresh_root()
        path = root / "20_project/03_dashboard.md"
        replace_once(path, "| 実行率（完了÷期限到来） | **78%** | — | 7件 ÷ 9件。期限到来9件", "| 実行率（完了÷期限到来） | **88%** | — | 7件 ÷ 8件。期限到来8件")
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)

    def test_15_decide_limit_stars_and_lever_are_checked(self) -> None:
        root = self.fresh_root()
        path = root / "20_project/03_dashboard.md"
        row = "| 2 | 書類確認を1段ふやして確定率を30%へ上げるか（面談官は1名追加で週6人） | 面談の前に書類確認を1段入れ、確定率を 22% → 30% へ上げる案。面談官は1名追加（3名＝週6人）で足りる。ただし**率が上がる保証はない**（22%のままなら着地16人）。 | リーダー（サンプル） | 2026-09-07（月）の週次運転会議 | 週ペース 6人／確定率 30% | **20人**（4 ＋ 54人 × 30%） | T-02・PJ-2026Q3-talent-sample/RSK-01 |"
        third = row.replace("| 2 |", "| 3 |", 1).replace("T-02", "T-03")
        replace_once(path, row, row + "\n" + third)
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)

        root = self.fresh_root()
        replace_once(root / "20_project/09_meetings/bodies/weekly.md", "| ③ | **決めどころ2: 書類確認を1段ふやして確定率を30%へ上げるか** | **★** |", "| ③ | **決めどころ2: 書類確認を1段ふやして確定率を30%へ上げるか** | |")
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)

        root = self.fresh_root()
        replace_once(root / "20_project/03_dashboard.md", "週ペース 8人／確定率は実績のまま | **20人**", "週ペース 9人／確定率は実績のまま | **20人**")
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)

    def test_16_phase_and_gate_dates_must_be_contained(self) -> None:
        replace_once(
            self.root / "20_project/01_plan.md",
            "| ② | 候補者づくり（先行面談あり） | 2026-08-31 〜 2026-09-27 | 第3〜6週 | 進行中（3週目/4週） | 候補者120人と面談枠（週8人）の確保 | 2026-09-27 |",
            "| ② | 候補者づくり（先行面談あり） | 2026-08-31 〜 2026-09-27 | 第3〜6週 | 進行中（3週目/4週） | 候補者120人と面談枠（週8人）の確保 | 2026-10-01 |",
        )
        self.assert_exit(2)

    def test_17_task_id_wp_related_and_assignee_references_are_exact(self) -> None:
        cases = [
            ('id: "T-01"', 'id: "T-99"'),
            ('wp: "WP-03"', 'wp: "WP-99"'),
            ('related: ["PJ-2026Q3-talent-sample/ISS-01"]', 'related: ["ISS-01"]'),
            ('assignee: "現場責任者（サンプル）"', 'assignee: "現場責任者"'),
        ]
        for old, new in cases:
            with self.subTest(new=new):
                root = self.fresh_root()
                replace_once(root / "20_project/04_tasks/T-01.md", old, new)
                result = self.run_at(root)
                self.assertEqual(2, result.returncode, result.stdout)

    def test_ot02_task_may_reference_decision_older_than_latest_two(self) -> None:
        decision_path = self.root / "20_project/05_decision_log.md"
        third_decision = (
            "| DEC-20260901-01 | 2026-09-01 | 第3の決定 | 週次運転会議 | "
            "数字で確認した | WP-05 | PM（サンプル） |"
        )
        replace_once(
            decision_path,
            "| ─ | ─ | ─ | ─ | ─ | ─ | ─ |",
            third_decision + "\n| ─ | ─ | ─ | ─ | ─ | ─ | ─ |",
        )
        task_path = self.root / "20_project/04_tasks/T-09.md"
        task_path.write_text(
            """---
id: "T-09"
title: "最初の決定を検収する"
wp: "WP-05"
assignee: "PM（サンプル）"
due: "2026-09-04"
status: "完了"
definition_of_done: "最初の決定を検収済み"
related: ["DEC-20260824-01"]
evidence: ["20_project/05_decision_log.md"]
---
""",
            encoding="utf-8",
        )

        canonical = build.build_canonical(self.root)
        self.assertEqual(
            ["DEC-20260828-01", "DEC-20260901-01"],
            [item["id"] for item in canonical["decisions"]],
        )

    def test_ot08_optional_task_fields_may_be_omitted_and_wp_dash_is_allowed(self) -> None:
        task_path = self.root / "20_project/04_tasks/T-03.md"
        replace_once(task_path, 'wp: "WP-03"', 'wp: "—"')
        replace_once(task_path, "related: []\n", "")
        replace_once(task_path, "evidence: []\n", "")

        canonical = build.build_canonical(self.root)
        task = next(item for item in canonical["tasks"] if item["id"] == "T-03")
        self.assertEqual("—", task["wp"])
        self.assertEqual("", task["related"])
        parsed = build.parse_task(task_path)
        self.assertEqual([], parsed["related"])
        self.assertEqual([], parsed["evidence"])

        root = self.fresh_root()
        completed = root / "20_project/04_tasks/T-03.md"
        replace_once(completed, 'status: "進行中"', 'status: "完了"')
        replace_once(completed, "evidence: []\n", "")
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("完了タスクは evidence が必要です", result.stdout)

    def test_ot05_stale_freshness_warns_to_stderr_without_stopping(self) -> None:
        path = self.root / "20_project/03_dashboard.md"
        replace_once(path, "| +12人 | 2026-09-04 09:00 |", "| +12人 | 2026-08-27 09:00 |")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertRegex(
            result.stderr,
            r"20_project/03_dashboard\.md:\d+: 鮮度警告: KPI「候補者リスト数」の鮮度は基準日から8日前です",
        )

    def test_ot06_weekly_history_rejects_period_gaps_cumulative_decrease_and_actual_mismatch(self) -> None:
        cases = [
            (
                "2026-08-24〜2026-08-30",
                "2026-08-25〜2026-08-31",
                "期間が前週と連続していません",
            ),
            (
                "2026-08-24〜2026-08-30",
                "2026-08-23〜2026-08-29",
                "期間が前週と連続していません",
            ),
            (
                "| 1人 | 96人 | 5人 |",
                "| 1人 | 121人 | 5人 |",
                "候補者リスト数の累計が前週から減っています",
            ),
            (
                "| 3人 | 120人 | 13人 | 23% | 25% | 8人 | 8人 |",
                "| 3人 | 120人 | 13人 | 23% | 25% | 7人 | 8人 |",
                "面談の実績（その週）が面談完了（累計）の前週差と一致しません",
            ),
        ]
        for old, new, message in cases:
            with self.subTest(message=message):
                root = self.fresh_root()
                replace_once(root / "20_project/03_dashboard.md", old, new)
                result = self.run_at(root)
                self.assertEqual(2, result.returncode, result.stdout)
                self.assertIn(message, result.stdout)
                self.assertRegex(result.stdout, r"20_project/03_dashboard\.md:\d+:")

    def test_ot07_next_meeting_before_dashboard_date_is_rejected(self) -> None:
        path = self.root / "20_project/09_meetings/bodies/weekly.md"
        replace_once(path, "| 次回 | 2026-09-07 09:00 |", "| 次回 | 2026-09-03 09:00 |")
        replace_once(
            path,
            "## 次回の議題（2026-09-07 09:00〜10:00・★＝この回で決めること）",
            "## 次回の議題（2026-09-03 09:00〜10:00・★＝この回で決めること）",
        )
        result = self.run_build()
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("bodies/weekly.md の次回を更新してください", result.stdout)
        self.assertRegex(result.stdout, r"20_project/09_meetings/bodies/weekly\.md:\d+:")

    def test_ot01_build_after_interview_window_lands_at_current_value(self) -> None:
        def advance_to_week_14(root: Path) -> None:
            dashboard = root / "20_project/03_dashboard.md"
            replace_once(
                dashboard,
                "> 最終更新: 2026-09-04（更新者: PM（サンプル））",
                "> 最終更新: 2026-11-16（更新者: PM（サンプル））",
            )
            replace_once(
                dashboard,
                "2026-09-04（金）09:00 ＝ 第3週",
                "2026-11-16（月）09:00 ＝ 第14週",
            )
            replace_once(
                dashboard,
                "| **面談 週8人**（残り72人 ÷ 残り9週） |",
                "| **—** |",
            )
            replace_once(dashboard, "| +12人 | 2026-09-04 09:00 |", "| ±0人 | 2026-09-04 09:00 |")
            replace_once(dashboard, "| +5人 | 2026-09-04 09:00 |", "| ±0人 | 2026-09-04 09:00 |")
            replace_once(dashboard, "| −1pt | 2026-09-04 09:00 |", "| ±0pt | 2026-09-04 09:00 |")
            replace_once(dashboard, "| +15pt | 2026-09-03 17:00 |", "| ±0pt | 2026-09-03 17:00 |")
            replace_once(
                dashboard,
                "週ペース 8人／確定率は実績のまま | **20人**（4 ＋ 72人 × 22%）",
                "週ペース 8人／確定率 22% | **4人**（面談期間終了）",
            )
            replace_once(
                dashboard,
                "週ペース 6人／確定率 30% | **20人**（4 ＋ 54人 × 30%）",
                "週ペース 6人／確定率 30% | **4人**（面談期間終了）",
            )
            rows = []
            week_start = date(2026, 9, 7)
            for week in range(4, 15):
                week_end = week_start + timedelta(days=6)
                rows.append(
                    f"| 第{week}週 | {week_start.isoformat()}〜{week_end.isoformat()} | "
                    "4人 | 132人 | 18人 | 22% | 40% | 0人 | 0人 | 期間終了まで増減なし |"
                )
                week_start += timedelta(days=7)
            boundary = "| ─ | ─ | ─ | ─ | ─ | ─ | ─ | ─ | ─ | ─ |"
            replace_once(dashboard, boundary, "\n".join(rows + [boundary]))
            replace_once(
                dashboard,
                "| 実行率（完了÷期限到来） | **78%** | — | 7件 ÷ 9件。期限到来9件",
                "| 実行率（完了÷期限到来） | **47%** | — | 7件 ÷ 15件。期限到来15件",
            )

            weekly = root / "20_project/09_meetings/bodies/weekly.md"
            replace_once(weekly, "| 次回 | 2026-09-07 09:00 |", "| 次回 | 2026-11-23 09:00 |")
            replace_once(
                weekly,
                "## 次回の議題（2026-09-07 09:00〜10:00・★＝この回で決めること）",
                "## 次回の議題（2026-11-23 09:00〜10:00・★＝この回で決めること）",
            )

        advance_to_week_14(self.root)
        self.assert_exit(0)
        canonical = build.parse_targets((self.root / "20_project/targets.yml").read_text(encoding="utf-8"))
        self.assertEqual("2026-11-16", canonical["project"]["updated_at"])

        def assert_safe(value: object, path: str = "$") -> None:
            self.assertIsNotNone(value, path)
            if isinstance(value, dict):
                for key, child in value.items():
                    assert_safe(child, f"{path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    assert_safe(child, f"{path}[{index}]")
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                self.assertTrue(math.isfinite(value), path)
                self.assertGreaterEqual(value, 0, path)

        assert_safe(canonical)
        json.dumps(canonical, allow_nan=False)

        root = self.fresh_root()
        advance_to_week_14(root)
        replace_once(root / "20_project/03_dashboard.md", "| **—** |", "| **面談 週8人** |")
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("面談期間終了後", result.stdout)

    def test_ot09_live_copy_uses_live_rows_and_contains_no_sample_wording(self) -> None:
        convert_sample_copy_to_live(self.root)
        result = self.run_build()
        self.assertEqual(0, result.returncode, result.stdout)
        canonical = build.parse_targets((self.root / "20_project/targets.yml").read_text(encoding="utf-8"))
        self.assertIs(canonical["meta"]["sample"], False)
        self.assertEqual("", canonical["meta"]["note"])
        strings = json.dumps(canonical, ensure_ascii=False)
        self.assertNotIn("見本", strings)
        self.assertNotIn("サンプル", strings)

    def test_task_frontmatter_errors_point_to_the_field_line(self) -> None:
        cases = [
            ('due: "2026-09-02"', 'due: "2026-99-99"', 6),
            ('wp: "WP-03"', 'wp: "WP-99"', 4),
            ('assignee: "現場責任者（サンプル）"', 'assignee: "未知担当"', 5),
            (
                'related: ["PJ-2026Q3-talent-sample/ISS-01"]',
                'related: ["ISS-01"]',
                9,
            ),
        ]
        for old, new, line in cases:
            with self.subTest(field=old.partition(":")[0]):
                root = self.fresh_root()
                replace_once(root / "20_project/04_tasks/T-01.md", old, new)
                result = self.run_at(root)
                self.assertEqual(2, result.returncode, result.stdout)
                self.assertIn(f"20_project/04_tasks/T-01.md:{line}:", result.stdout)

    def test_ot08_and_ot10_readmes_state_the_actual_contract(self) -> None:
        task_readme = (REPO / "20_project/04_tasks/README.md").read_text(encoding="utf-8")
        self.assertIn("省略時は `[]`", task_readme)
        self.assertIn('`wp: "—"`', task_readme)
        self.assertIn("frontmatter の欄は上の9つだけ", task_readme)
        self.assertNotIn("欄の追加は自由", task_readme)

        tools_readme = (REPO / "tools/README.md").read_text(encoding="utf-8")
        self.assertIn("有効な JSON の値の差だけ", tools_readme)
        self.assertIn("git で既知の正常な `index.html` へ戻してから build", tools_readme)
        self.assertIn("再 build だけでは復旧しません", tools_readme)

    def test_18_derived_keys_are_rejected(self) -> None:
        canonical = build.build_canonical(self.root)
        blocked = copy.deepcopy(canonical)
        blocked["kgi"]["achievement_percent"] = 20
        with self.assertRaises(build.SourceError):
            build._validate_no_derived(blocked)
        found = set()

        def walk(value: object) -> None:
            if isinstance(value, dict):
                found.update(value.keys())
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(canonical)
        self.assertFalse(found & build.DERIVED_KEYS)

    def test_19_script_and_html_injection_are_rejected_or_escaped(self) -> None:
        for payload in ("</script>", "<img onerror=x>", '<mark class="x">危険</mark>'):
            with self.subTest(payload=payload):
                root = self.fresh_root()
                replace_once(root / "20_project/03_dashboard.md", "候補者は足りている。**詰まっているのは面談の本数ひとつ**です。", f"候補者は足りている。{payload}です。")
                result = self.run_at(root)
                self.assertEqual(2, result.returncode, result.stdout)
        canonical = build.build_canonical(self.root)
        escaped = copy.deepcopy(canonical)
        escaped["meta"]["note"] = "<>&\u2028\u2029"
        rendered = build.render_json(escaped)
        self.assertNotIn("<", rendered)
        self.assertNotIn(">", rendered)
        self.assertNotIn("&", rendered)
        self.assertNotIn("\u2028", rendered.replace("\\u2028", ""))

    def test_20_dashboard_block_zero_two_and_invalid_are_exit_3(self) -> None:
        cases = []
        current = (self.root / "60_outputs/dashboard/index.html").read_text(encoding="utf-8")
        cases.append(current.replace('id="dashboard-data"', 'id="dashboard-gone"', 1))
        match = re.search(r'(<script type="application/json" id="dashboard-data">.*?</script>)', current, re.S)
        self.assertIsNotNone(match)
        cases.append(current.replace("</body>", match.group(1) + "\n</body>", 1))  # type: ignore[union-attr]
        cases.append(current.replace('"schema": "talent-dashboard/v4"', '"schema": ', 1))
        for index, text in enumerate(cases):
            with self.subTest(case=index):
                root = self.fresh_root()
                (root / "60_outputs/dashboard/index.html").write_text(text, encoding="utf-8")
                result = self.run_at(root)
                self.assertEqual(3, result.returncode, result.stdout)

    def test_21_sample_false_needs_live_rows_and_view_supports_meta_sample(self) -> None:
        # 見本札だけを false にしても、正本の表に見本行が残っていれば生成器は止まる（見本と実データを混ぜない）
        replace_once(self.root / "20_project/03_dashboard.md", "> **見本札**: true", "> **見本札**: false")
        output = self.assert_exit(2)
        self.assertIn("見本行が混在", output)
        # 表示層は meta.sample を読み、live のとき data-live を立てて見本の札（data-sample-only）を消す
        html = (self.root / "60_outputs/dashboard/index.html").read_text(encoding="utf-8")
        view = html.split('id="dashboard-data"', 1)[1]
        self.assertRegex(view, r"D\.meta && D\.meta\.sample")
        self.assertIn('setAttribute("data-live", "1")', view)
        self.assertIn("html[data-live] [data-sample-only]{ display:none !important; }", html)
        # 見本の札は静的にも表示層の生成にも置ける。数ではなく「札があること」と「消える仕組みがあること」を見る
        self.assertGreaterEqual(html.count("data-sample-only"), 1)
        self.assertRegex(view, r'"data-sample-only"')

    def test_22_view_referenced_json_keys_exist_with_compatible_types(self) -> None:
        canonical = build.build_canonical(self.root)
        required_paths = [
            "project.id", "project.name", "project.org", "project.our_org", "project.status", "project.pm", "project.leader",
            "project.period.start", "project.period.end", "project.updated_at",
            "plan.interview_window_start", "plan.interview_window_end",
            "headline.text", "headline.sub", "headline.update_rule",
            "kgi.unit", "kgi.as_is", "kgi.to_be", "kgi.deadline", "kgi.as_of", "kgi.history",
            "output.wp_done", "output.wp_total", "output.wp_doing", "output.wp_todo", "output.wp_done_plan", "output.tasks_done_week", "output.tasks_due_week", "output.note",
            "kgi.title", "kgi.gloss", "kgi.judge", "kgi.judge_label", "kgi.judge_reason",
            "milestones.today", "milestones.overlap_note", "milestones.phases",
            "next_meeting.kind", "next_meeting.date", "next_meeting.time", "next_meeting.minutes", "next_meeting.slot_label", "next_meeting.attendees", "next_meeting.agenda", "next_meeting.decide_index",
        ]

        def resolve(path: str) -> object:
            value: object = canonical
            for part in path.split("."):
                self.assertIsInstance(value, dict, path)
                self.assertIn(part, value, path)  # type: ignore[operator]
                value = value[part]  # type: ignore[index]
            return value

        for path in required_paths:
            with self.subTest(path=path):
                self.assertIsNotNone(resolve(path))
        for item in canonical["kpi"]:
            self.assertTrue({"name", "gloss", "agg", "value", "unit", "target", "history", "as_of", "good_when", "note"} <= item.keys())
        self.assertEqual(1, sum(1 for item in canonical["kpi"] if item.get("bottleneck") and "pace_weekly" in item))
        for item in canonical["kdi"]:
            self.assertTrue({"name", "gloss", "actual", "target", "unit", "owner"} <= item.keys())
        for item in canonical["health"]:
            self.assertTrue({"name", "signal", "label", "why"} <= item.keys())
        for item in canonical["decide"]:
            self.assertTrue({"no", "title", "text", "owner", "related", "landing_lever"} <= item.keys())
            self.assertIsInstance(item["related"], list)
        self.assertIn("members", canonical)
        member_types: dict[str, object] = {
            "name": str,
            "role": (str, type(None)),
            "raci": dict,
            "load": dict,
            "load_note": str,
            "stakeholder": (dict, type(None)),
        }
        for item in canonical["members"]:
            self.assertTrue(member_types.keys() <= item.keys())
            for key, expected_type in member_types.items():
                self.assertIsInstance(item[key], expected_type)  # type: ignore[arg-type]
        self.assertIn("last_meeting", canonical)
        last_meeting = canonical["last_meeting"]
        self.assertTrue(last_meeting is None or isinstance(last_meeting, dict))
        if last_meeting is not None:
            meeting_types = {
                "id": str,
                "date": str,
                "time": str,
                "minutes": int,
                "title": str,
                "facilitator": str,
                "attendees": list,
                "review": list,
                "review_done": int,
                "review_due": int,
                "actions": list,
                "actions_total": int,
                "actions_tasked": int,
                "actions_held": int,
                "decisions": list,
                "notes": list,
            }
            self.assertTrue(meeting_types.keys() <= last_meeting.keys())
            for key, expected_type in meeting_types.items():
                self.assertIsInstance(last_meeting[key], expected_type)
        self.assertIn("wps", canonical)
        for item in canonical["wps"]:
            self.assertTrue({"id", "name", "lead", "due", "state"} <= item.keys())
            for key in ("id", "name", "lead", "due", "state"):
                self.assertIsInstance(item[key], str)
        for item in canonical["decisions"]:
            self.assertTrue({"id", "date", "text", "where", "why"} <= item.keys())
        for item in canonical["risks"]:
            self.assertTrue({"id", "text", "state", "impact", "plan", "watcher"} <= item.keys())
        for item in canonical["issues"]:
            self.assertTrue({"id", "text", "impact", "owner", "due", "state"} <= item.keys())
        lm = canonical["last_meeting"]
        if lm is not None:
            for item in lm["review"]:
                self.assertTrue({"task", "owner", "state", "evidence", "note"} <= item.keys())
            for item in lm["actions"]:
                self.assertTrue({"text", "owner", "due", "dod", "task"} <= item.keys())
            for item in lm["notes"]:
                self.assertTrue({"text", "route", "detail"} <= item.keys())
        for item in canonical["tasks"]:
            self.assertTrue({"id", "text", "wp", "owner", "due", "state", "related", "dod"} <= item.keys())
            self.assertIsInstance(item["related"], str)
            self.assertIsInstance(item["dod"], str)
        js = (self.root / "60_outputs/dashboard/index.html").read_text(encoding="utf-8").split('id="dashboard-data"', 1)[1]
        self.assertRegex(js, r"D\.meta\.sample")

    def test_23_members_require_exact_raci_headers_and_named_pm_leader(self) -> None:
        root = self.fresh_root()
        replace_once(
            root / "20_project/01_plan.md",
            "| 現場責任者（サンプル） | 採用担当A（サンプル） |",
            "| 現場責任者 | 採用担当A（サンプル） |",
        )
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("現場責任者（サンプル）", result.stdout)
        self.assertIn("§4 列見出し", result.stdout)

        root = self.fresh_root()
        replace_once(
            root / "20_project/01_plan.md",
            "| PM（サンプル） | 30% | 30% | 30% | 40% | 計器盤の更新と会議の進行 |",
            "| 別PM（サンプル） | 30% | 30% | 30% | 40% | 計器盤の更新と会議の進行 |",
        )
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("PM_NAME", result.stdout)
        self.assertIn("PM（サンプル）", result.stdout)

    def test_24_raci_accountable_count_and_wp_set_are_checked(self) -> None:
        root = self.fresh_root()
        replace_once(
            root / "20_project/01_plan.md",
            "| WP-01 募集要項 | I | C | C | **A** | R | | | C |",
            "| WP-01 募集要項 | **A** | C | C | **A** | R | | | C |",
        )
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("WP WP-01 の A", result.stdout)
        self.assertIn("2個", result.stdout)

        root = self.fresh_root()
        remove_matching_line(root / "20_project/01_plan.md", "| WP-12 完了報告と引き渡し | **A** |")
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("§4 の WP ID 集合", result.stdout)
        self.assertIn("§2", result.stdout)

    def test_25_missing_stakeholder_is_null_and_invented_engagement_fails(self) -> None:
        root = self.fresh_root()
        remove_matching_line(root / "20_project/08_stakeholders.md", "| PM（サンプル） | 責任者（PM）・回す人 |")
        canonical = build.build_canonical(root)
        pm = next(member for member in canonical["members"] if member["name"] == "PM（サンプル）")
        self.assertIsNone(pm["role"])
        self.assertIsNone(pm["stakeholder"])

        root = self.fresh_root()
        replace_once(
            root / "20_project/08_stakeholders.md",
            "| 中 | 高 | 中立 | 支援型 | 書類確認1段追加",
            "| 中 | 高 | 熱心 | 支援型 | 書類確認1段追加",
        )
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("現在の関与度", result.stdout)
        self.assertIn("熱心", result.stdout)

    def test_26_last_meeting_uses_latest_filename_and_zero_files_is_null(self) -> None:
        canonical = build.build_canonical(self.root)
        self.assertEqual("2026-08-28", canonical["last_meeting"]["date"])
        self.assertEqual(7, canonical["last_meeting"]["actions_total"])

        root = self.fresh_root()
        (root / "20_project/09_meetings/MTG-talent-sample-20260824.md").unlink()
        (root / "20_project/09_meetings/MTG-talent-sample-20260828.md").unlink()
        self.assertIsNone(build.build_canonical(root)["last_meeting"])

    def test_27_last_meeting_identity_attendee_and_date_are_checked(self) -> None:
        cases = [
            (
                "| 会議ID | MTG-talent-sample-20260828 |",
                "| 会議ID | MTG-talent-sample-20260899 |",
                "ファイル名",
            ),
            (
                "受け入れ担当（すべてサンプル）",
                "未知担当（すべてサンプル）",
                "§5 メンバーにない出席者",
            ),
            (
                "| 日時・時間 | 2026-08-28 16:00〜17:00（60分・第2週の金曜） |",
                "| 日時・時間 | 2026-09-05 16:00〜17:00（60分・第2週の金曜） |",
                "project.updated_at",
            ),
        ]
        for old, new, message in cases:
            with self.subTest(message=message):
                root = self.fresh_root()
                replace_once(root / "20_project/09_meetings/MTG-talent-sample-20260828.md", old, new)
                result = self.run_at(root)
                self.assertEqual(2, result.returncode, result.stdout)
                self.assertIn(message, result.stdout)

    def test_28_last_meeting_rates_and_references_are_checked(self) -> None:
        cases = [
            ("実行率: 完了3件 ÷ 期限到来3件", "実行率: 完了2件 ÷ 期限到来3件", "実行率行が表と一致"),
            ("決定がタスクになった割合: 7件 ÷ 7件", "決定がタスクになった割合: 6件 ÷ 7件", "タスク化割合行が表と一致"),
            ("[../04_tasks/T-01.md](../04_tasks/T-01.md)（A-01）", "[../04_tasks/T-99.md](../04_tasks/T-99.md)（A-01）", "T-99 が 04_tasks/ にありません"),
            ("05_decision_log.md) DEC-20260828-01。", "05_decision_log.md) DEC-20260828-99。", "DEC-20260828-99 が 05_decision_log.md にありません"),
        ]
        for old, new, message in cases:
            with self.subTest(message=message):
                root = self.fresh_root()
                replace_once(root / "20_project/09_meetings/MTG-talent-sample-20260828.md", old, new)
                result = self.run_at(root)
                self.assertEqual(2, result.returncode, result.stdout)
                self.assertIn(message, result.stdout)

    def test_29_last_meeting_action_without_task_is_null(self) -> None:
        root = self.fresh_root()
        path = root / "20_project/09_meetings/MTG-talent-sample-20260828.md"
        replace_once(
            path,
            "[../04_tasks/T-08.md](../04_tasks/T-08.md)（A-07）",
            "保留（再検討日 2026-09-07）",
        )
        replace_once(
            path,
            "決定がタスクになった割合: 7件 ÷ 7件 ＝ **100%**（保留0件）",
            "決定がタスクになった割合: 6件 ÷ 7件 ＝ **86%**（保留1件）",
        )
        canonical = build.build_canonical(root)
        self.assertIsNone(canonical["last_meeting"]["actions"][-1]["task"])
        self.assertEqual(6, canonical["last_meeting"]["actions_tasked"])
        self.assertEqual(1, canonical["last_meeting"]["actions_held"])

    def test_30_last_meeting_empty_review_uses_target_none(self) -> None:
        root = self.fresh_root()
        path = root / "20_project/09_meetings/MTG-talent-sample-20260828.md"
        for needle in (
            "| 募集要項を確定し3社へ配布 |",
            "| 選考基準の文書化と読み合わせ |",
            "| 面談記録の様式の確定 |",
        ):
            remove_matching_line(path, needle)
        replace_once(
            path,
            "実行率: 完了3件 ÷ 期限到来3件 ＝ 100%（①準備フェーズのゲートは 2026-08-30 に通過見込み）",
            "実行率: 対象なし",
        )
        meeting = build.build_canonical(root)["last_meeting"]
        self.assertEqual([], meeting["review"])
        self.assertEqual(0, meeting["review_done"])
        self.assertEqual(0, meeting["review_due"])

    def test_31_wps_follow_plan_order_and_match_output_counts(self) -> None:
        canonical = build.build_canonical(self.root)
        plan = build.parse_plan(
            self.root / "20_project/01_plan.md",
            build.parse_names(self.root / "names.yml"),
            True,
        )
        expected = [{"id": wp_id, **wp} for wp_id, wp in plan["wp_by_id"].items()]
        self.assertEqual(expected, canonical["wps"])
        self.assertEqual([f"WP-{number:02d}" for number in range(1, 13)], [wp["id"] for wp in canonical["wps"]])
        wps_counts = {
            "done": sum(1 for wp in canonical["wps"] if wp["state"] == "完了"),
            "doing": sum(1 for wp in canonical["wps"] if wp["state"] == "進行中"),
            "todo": sum(1 for wp in canonical["wps"] if wp["state"] == "未着手"),
            "total": len(canonical["wps"]),
        }
        output_counts = {
            "done": canonical["output"]["wp_done"],
            "doing": canonical["output"]["wp_doing"],
            "todo": canonical["output"]["wp_todo"],
            "total": canonical["output"]["wp_total"],
        }
        self.assertEqual(output_counts, wps_counts)

    def test_32_single_history_accepts_no_delta_and_rejects_value(self) -> None:
        def keep_only_latest_as_week_one(root: Path) -> Path:
            path = root / "20_project/03_dashboard.md"
            remove_matching_line(path, "| 第1週 |")
            remove_matching_line(path, "| 第2週 |")
            replace_once(path, "| 第3週 | 2026-08-31〜2026-09-06 |", "| 第1週 | 2026-08-31〜2026-09-06 |")
            replace_once(
                path,
                "| 4人 | 132人 | 18人 | 22% | 40% | 5人 | 8人 | 面談官2名",
                "| 4人 | 132人 | 18人 | 22% | 40% | 18人 | 8人 | 面談官2名",
            )
            return path

        path = keep_only_latest_as_week_one(self.root)
        replace_once(path, "| +12人 | 2026-09-04 09:00 |", "| — | 2026-09-04 09:00 |")
        replace_once(path, "| +5人 | 2026-09-04 09:00 |", "|  | 2026-09-04 09:00 |")
        replace_once(path, "| −1pt | 2026-09-04 09:00 |", "| — | 2026-09-04 09:00 |")
        replace_once(path, "| +15pt | 2026-09-03 17:00 |", "|  | 2026-09-03 17:00 |")
        parsed = build.parse_dashboard(path, build.parse_kpi_design(self.root / "20_project/02_kpi_tree.md", True), True)
        self.assertTrue(all(len(item["history"]) == 1 for item in parsed["kpi"]))

        root = self.fresh_root()
        keep_only_latest_as_week_one(root)
        result = self.run_at(root)
        self.assertEqual(2, result.returncode, result.stdout)
        self.assertIn("前週比", result.stdout)
        self.assertNotIn("IndexError", result.stdout)


class ApplyNamesContractTests(unittest.TestCase):
    def test_help_lists_implemented_exit_codes_and_builder_handoff(self) -> None:
        result = subprocess.run(
            [sys.executable, str(APPLY_NAMES), "--help"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout)
        for code in ("0", "1", "2", "3", "7", "8"):
            self.assertRegex(result.stdout, rf"(?m)^  {code}  ")
        for removed in ("4", "5", "6"):
            self.assertNotRegex(result.stdout, rf"(?m)^  {removed}  ")
        self.assertIn("build_dashboard.py", result.stdout)


if __name__ == "__main__":
    unittest.main()
