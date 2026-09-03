# CLAUDE.md — AI への道案内（規則はここに書かない。指すだけ）

このファイルは、Claude Code のような AI の道具が**自動で読む**道案内です（同じ役目のものが [AGENTS.md](AGENTS.md)）。
**このフォルダ（`04_project-operations/talent-sample/`）を作業ルート（cwd）として開いてください。** 上の階層（team-workspace の root）から開くと、ここに書いてある相対パスが通りません。
**扉ではありません。** 規則の本文は下の2枚にあり、ここはその指差しだけです。人は読まなくて構いません。

## まず読む（この2枚を、この順で）

1. [README.md](README.md) — このフォルダが何のためにあるか・いまどこ・週次の回し方
2. [NORMS.md](NORMS.md) — 迷ったとき何が何に勝つか（五層）

約束の本文は [00_foundation/02_principles.md](00_foundation/02_principles.md)（6つ）。言葉は [30_semantic_map/glossary.md](30_semantic_map/glossary.md)。

## 手を動かす前に（この5つを守れば事故は起きません）

1. **正本は [20_project/](20_project/README.md) の Markdown / YAML だけ。** 数字・決定・タスク・リスク・会議録を直すときは、ここを直します。 **ただしこの配布キットは公開の置き場にある凍結した見本です。実データ（実名・実績）を入れない・同期しない。** 引き渡し（非公開化の後）までは、実データの正本は支援側が管理する元のリポジトリです。
2. **[60_outputs/dashboard/index.html](60_outputs/dashboard/index.html) を手で書き換えない。** 中の JSON（データ層）も含めてです。画面は `python3 tools/build_dashboard.py` で正本から作り直します。良かれと思って数字を合わせに行くと、正本と画面のどちらが本当か誰にも分からなくなります。
3. **状態の言葉を発明しない。** タスクの状態は [20_project/04_tasks/README.md](20_project/04_tasks/README.md)、リスクと課題の状態は [20_project/06_risk_ledger.md](20_project/06_risk_ledger.md)・[20_project/07_issue_ledger.md](20_project/07_issue_ledger.md) にある語だけを使います（一覧は [30_semantic_map/glossary.md](30_semantic_map/glossary.md)）。「ほぼ完了」は状態ではありません。
4. **名前の入れ替えは [names.yml](names.yml) を直して `python3 tools/apply_names.py --rename`（文章）→ `python3 tools/build_dashboard.py`（画面）の順に1回ずつ。** 固有名を1つずつ手で置換しないでください（値が空のまま走らせると、道具は何も書かずに止まります）。
5. **週に触るのは [20_project/03_dashboard.md](20_project/03_dashboard.md)。** 会議の前日までに更新します（更新が会議の入場券）。`targets.yml` は道具が作る生成物なので手で直しません。台帳（決定・変更・リスク）は**追記だけ**で、過去の行を消しません。

## 人の GO が要ること

憲章の承認／期限・予算・範囲の変更／終結の判定は、人が止まる場所です。誰が止めるかは [40_process_map/weekly_triangle.md](40_process_map/weekly_triangle.md) にあります。ここは自分で決めずに聞いてください。

**このファイルに規則を書き足さないでください。** 増やすのは、守れなかった事故が起きた時に [00_foundation/02_principles.md](00_foundation/02_principles.md) へ（記録と一緒に）。
