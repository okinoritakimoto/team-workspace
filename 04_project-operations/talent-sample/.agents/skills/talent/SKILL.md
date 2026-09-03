---
name: talent
description: この repo（人材プロジェクトの運用）で、今週の状態を読む・タスクを起票する・計器盤を作り直す・会議録を残す・名前を入れ替える。/talent で使う。
---

# talent — この repo でやることの入口

> **入口はこれ1つ**。覚えることを増やさないために、動詞（今週／タスク／画面／会議／名前）で分ける。
> 正本は `20_project/`。画面 `60_outputs/dashboard/index.html` は正本から作る鏡で、**手で直さない**。

## 最初に読む（毎回・順に3つだけ）

1. `README.md` — この repo の全体像と、いまどこ
2. `20_project/03_dashboard.md` — 今週の数字（計器盤の正本）
3. `40_process_map/weekly_triangle.md` — 週の回し方と、**人が止まる場所**

これ以上は、必要になった時に `README.md` の「いまどこ」表から開く。

## 守ること（4つだけ）

- **正本は `20_project/`**。画面・レポートは投影。数字を直すときは正本を直す。
- **状態の言葉を発明しない** — 一覧は `30_semantic_map/glossary.md`。
- **数字には鮮度（いつの値か）を添える**。古い数字で判断しない。
- **人が止まる場所では止まる** — 憲章の承認は承認者、期限や範囲の変更と終結の判定はリーダーの GO を待つ。

---

## 今週（`/talent 今週`）

会議の前にやることを出す。

1. `20_project/03_dashboard.md` の5段（KGI・KPI・KDI・出来高・検診5観点）を読み、**鮮度が古い数字**を挙げる。
2. `20_project/04_tasks/` を読み、**期限が来ている／過ぎている**タスクを挙げる。
3. `20_project/06_risk_ledger.md`・`07_issue_ledger.md` の「兆候あり」「顕在化」「対応中」を挙げる。
4. 次の会議（`20_project/09_meetings/bodies/weekly.md` の枠）までに**誰が何を更新するか**を、担当ごとに1行で出す。
5. 更新が済んだら「画面」の手順で計器盤を作り直す。

⛔ 数字を推測で埋めない。分からない値は「未計測」と書く。

## タスク（`/talent タスク`・`/task`）

1件＝1ファイル（`20_project/04_tasks/T-NN.md`）。雛形は同フォルダの `_template.md`。

- **起票**: 空いている番号で新しいファイルを作る。**担当1人・期限・完了の定義**の3つが埋まらないものは起票しない。会議録④の「保留」行に理由と再検討日を書く（`status: 保留` のタスクは作らない）。
- **状態を変える**: frontmatter の `status` を書き換え、本文の「更新の記録」へ1行足す（日付・誰が・何を）。
- **完了にする**: `evidence`（証跡）が空のまま完了にしない。
- ⛔ 担当・期限・完了の定義を推測で埋めない。分からなければ聞く。
- 変えたら「画面」の手順で計器盤を作り直す（タスク一覧が画面に出る）。

## 画面（`/talent 画面`）

正本 → 画面を作り直す。画面は1ファイル（`60_outputs/dashboard/index.html`）に4つ（計器盤・タスク・メンバー・会議）。

1. 正本（`02_kpi_tree.md`・`03_dashboard.md`・`01_plan.md` §4 §5・`04_tasks/`・`05_decision_log.md`・`06_risk_ledger.md`・`07_issue_ledger.md`・`08_stakeholders.md`・`09_meetings/bodies/weekly.md`・直近の `09_meetings/MTG-*.md`）を直す。
2. `python3 tools/build_dashboard.py`
3. `python3 tools/build_dashboard.py --check`（0 なら一致。1 なら画面が古い → 2 をもう一度。2 なら正本の書き方の間違い → 表示された file:line を直す。担当の表記は §5 と完全一致でないと止まる）
4. ブラウザで開いて、4つの画面をPC幅とスマホ幅の両方で見る（「見る人」でメンバーを選んでも崩れないか）。

⛔ 画面のデザイン（見た目）を直したい時は、データ層ではなく表示層（CSS/JS）を直す。
   **データ層と表示層を混ぜない**（データ層は「元の数」だけ・割り算や判定は表示層がやる）。

## 会議（`/talent 会議`）

1. 会議の前に「今週」の手順を済ませる（**計器盤の更新が会議の入場券**）。
2. `20_project/09_meetings/_meeting_template.md` を写して `MTG-<slug>-<日付>.md` を作る。
3. ⓪〜⑥ の順で進める。**⓪（前回の検収）を飛ばさない**。
4. **会議の最後5分で PM が閉じる**: ①決めたことを全部タスクへ（担当1人・期限・完了の定義）②決定→DEC・詰まり→ISS・リスクの新規/状態変化→RSK・変更の言い出し→C の4台帳へ ③決まった決めどころを `03_dashboard.md` から外し、次週の決めどころ（最大2件）を入れる ④次回の日時と議題を `bodies/weekly.md` の「次回」へ ⑤画面を作り直して `--check`、ブラウザで確かめる（AI に `/talent 画面` と頼んでもよい）。

## 名前（`/talent 名前`）

組織名・プロジェクト名・担当者名・期間・会議の枠を入れ替える。**この repo は見本の名前が入った状態なので `--rename` を使う。**

```bash
# 1. names.yml の value を新しい値に書き換える
python3 tools/apply_names.py --rename    # 文章の差し替え（前に入れた値は names.applied.yml に控えてある）
python3 tools/apply_names.py --check     # 差し替え点の残りを確かめる
python3 tools/build_dashboard.py         # 画面に名前が入る
python3 tools/build_dashboard.py --check # 正本と画面の差を確かめる
```

まだ一度も名前を入れていない repo（差し替え点（キー名を二重の波かっこで囲んだ印）が残っている）なら `--rename` ではなく引数なしで実行する。
道具は**壊れたら止まる**（値が空・知らないキー・期間の食い違いがあれば1バイトも書かずに止まる）。

## 困ったら

| 症状 | 見る場所 |
|---|---|
| この語は何 | `30_semantic_map/glossary.md` |
| 誰が決めるのか | `40_process_map/weekly_triangle.md` の「人が止まる場所」 |
| 何が正しいのか迷う | `NORMS.md`（何が何に勝つか） |
| 画面の作り方 | `60_outputs/dashboard/README.md` |
