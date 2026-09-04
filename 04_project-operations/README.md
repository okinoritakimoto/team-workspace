# 04_project-operations — 案件の運転（正本・週次会議・運転席）

このフォルダは、案件を**正本1か所・週次の運転・見える計器盤**で回すための置き場です。1案件＝1フォルダ。

| フォルダ | 内容 | 状態 |
|---|---|---|
| `talent-sample/` | 人材プロジェクトの運転席（4画面）と、その正本の型・道具・手引き | **見本データ**（実在の人・実績ではありません） |

## 開き方

1. [talent-sample/README.md](talent-sample/README.md) を読む（3秒で「いまどこ」が分かる表があります）
2. 画面は [talent-sample/60_outputs/dashboard/index.html](talent-sample/60_outputs/dashboard/index.html) をダブルクリック（1ファイルで完結・ログイン不要）
3. AI（Claude Code / Codex）に頼むときは **`talent-sample/` を開いて** `/talent` と打つ（このフォルダの上の階層から開くと相対パスが通りません）

## 手元に持ってくる（GitHub の Web で見ている方へ）

- 画面（`index.html`）は1ファイルで完結しています。GitHub の画面では動かないので、**手元に落として開きます**: このリポジトリの緑の「Code」ボタン → 「Download ZIP」で全部を落とすか、`git clone` で取ってきます。落としたら `04_project-operations/talent-sample/60_outputs/dashboard/index.html` をダブルクリック。
- 道具（`python3 tools/…`）と AI（`/talent`）を使うのは、当面は支援側です。使う場合は Python 3 が要り、コマンドは **`talent-sample/` の直下で**打ちます（上の階層から打つと動きません）。

## 運用の分担（当面）

PM は数字を送る／支援側が正本の更新・画面の生成・公開を行う。引き渡し後は同じ手順を PM が行います（手順は [talent-sample/docs/member-guide.md](talent-sample/docs/member-guide.md) の 5章と7章）。

## 週次の数字の送り方（当面）

| 何を | いつまでに | 誰へ | どうやって |
|---|---|---|---|
| 計器盤の1〜5段の値と鮮度・今週の一言・今週決めること（[talent-sample/20_project/03_dashboard.md](talent-sample/20_project/03_dashboard.md) の表の値だけ） | 週次会議の **2日前まで** | 支援側の担当（`talent-sample/names.yml` の OUR_CONTACT_NAME に記入） | メールかチャットで、表の値をそのまま。支援側が正本を更新 → 画面を作り直す → 同じ URL へ再公開 → PM へ「更新しました」と返す |

## 新しい案件を始めるとき

見本の履歴（タスク・会議録・週の値）をそのまま複製しません。支援側が見本を除いた初期状態を作り、`names.yml` を先方の値にしてから運転を始めます（「台帳は追記だけ」の約束と衝突させないため）。

## 正本の所在

`talent-sample/` は支援側が管理する元のリポジトリ（配布版 2026-09-04（第2版））からの写し（凍結した見本の配布キット）です。数字を直すときは支援側へ。引き渡し（このフォルダを正本にする）は、このリポジトリが非公開になってから行います（条件と手順は手引きの 7章）。
