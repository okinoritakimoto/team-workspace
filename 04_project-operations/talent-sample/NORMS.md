---
kind: norms
precedence: [client_rules, structure_form, repo_protocol, room_readme, file_header]
conflict_rules: [上位優先, 特別法優先, 明示優先]
refs:
  client_rules: "サンプル株式会社の社内規程・契約（この repo の外）"
  structure_form: "支援側の運用の型（外部）"
  repo_protocol: [00_foundation/02_principles.md]
case_law:
  incidents: 20_project/09_meetings/       # 気づきは会議録⑥にそのまま残す
  promoted: 20_project/05_decision_log.md  # 全員が守ることになったら決定（DEC-）として残す
---
# NORMS — 迷ったとき、何が何に勝つか（規則の本文はここに書かない。順位と所在だけ）

## 五層（上が勝つ）

1. **先方の規程・契約（サンプル株式会社）** — この repo の外にある。ここが動けば下は全部従う。
2. **構造の型（外部）** — この repo の形の出どころ。1つの repo の都合で番号帯や法則の意味を変えない。
3. **この repo の約束（`00_foundation/`＋本書）** — このプロジェクトの事情。上2層の内側でだけ効く。
4. **部屋札（各部屋の `README.md`）** — その部屋が受け入れる物・拒む物。範囲が狭いので、条例の一般則より優先する。
5. **頭注（ファイル冒頭の但し書き）** — 最も具体。ただし上位を緩められない。

「どこに何があるか」（事実の層）は `README.md` の「いまどこ」表が持ち、この五層には入らない。場所の記述が食い違えば README が勝ち、「してよい／いけない」の衝突は本書で裁く。

## 衝突したときの3規則

- **上位優先** — 層が違えば上が勝つ。
- **特別法優先** — 同じ層なら、範囲の狭い方が勝つ（部屋札 > 一般則）。
- **明示優先** — 書いてあるものが、推測・慣習・口頭・コメント行に勝つ。

## この repo で最初から決まっていること（規則の所在）

| 決まっていること | 所在 |
|---|---|
| 正本は `20_project/`。画面・一覧は投影 | `00_foundation/02_principles.md` 原則1 |
| 週次で更新するのは `20_project/03_dashboard.md` だけ。画面（`60_outputs/dashboard/`）は `python3 tools/build_dashboard.py` で正本から作り直す。手編集しない | 同 原則1 |
| 記録は消さない・追記する（決定・変更・リスクの却下も残す） | 同 原則2 |
| 数字には鮮度（更新日）を添える。1回の更新の基準日は1つ | 同 原則3 |
| 状態の言葉を発明しない・同じ語を2つの意味に使わない（実行率／実施率） | 同 原則4・`30_semantic_map/glossary.md` |
| リーダーの GO が要る場所 | `40_process_map/weekly_triangle.md` §3 |
| 文字起こし・録音・私的メモ・鍵は Git に入れない | `.gitignore`・`60_outputs/dashboard/README.md`「入れてはいけないもの」 |

## 判例（事故が起きたら3行で足す）

書式: 「何が起きたか → どの規則で裁いたか → 何を構造へ変換したか」。出典は会議録（`20_project/09_meetings/` の⑥）か決定（`20_project/05_decision_log.md`）の1件を指す。ここに事故の本文を写さない。

（まだ無い）
