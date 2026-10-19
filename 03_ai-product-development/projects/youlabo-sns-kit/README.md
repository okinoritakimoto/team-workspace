# youlabo-sns-kit — ユーラボ月100万AI駆動タスクリストを Claude Code で回すキット

Googleスプレッドシート「[ユーラボ月100万AI駆動タスクリスト](https://docs.google.com/spreadsheets/d/1pytoaCdgc_bJuw6O0ZDKjfB8v98XgDNki8VMBmtrQnc/edit)」の全90タスクを、Claude Code のスキルとコマンドで1つずつ実行できるようにしたものです。

## 開き方

1. このフォルダ（`youlabo-sns-kit/`）を Claude Code で開く（上の階層から開くとコマンドが見えません）
2. `/yl` と打つ → `TASKS.md` の次の未完タスクを実行し、成果物を保存して `[x]` を付けます

## コマンド

| コマンド | やること |
|---|---|
| `/yl` | 次の未完タスクを1つ実行（`/yl 1-05` で ID 指定、`/yl 状況` で進捗） |
| `/yl-status` | フェーズごとの完了数と次の3タスク（読むだけ） |
| `/yl-0` 〜 `/yl-7` | フェーズを指定して進める（`/yl-3 3-05` のように ID も渡せる） |

## フェーズ

| # | フェーズ | タスク数 | 主な成果物の置き場 |
|---|---|---|---|
| 0 | 前準備 | 1 | `CLAUDE.md` |
| 1 | リサーチ・コンセプト | 17 | `research/`・`knowledge/concept/` |
| 2 | ナレッジを入れる | 8 | `knowledge/`・`rules/` |
| 3 | 発信、集客 | 16 | `posts/`・`analysis/` |
| 4 | 商品設計・作成（note） | 15 | `products/note/` |
| 5 | 販売プロモーション | 12 | `promotion/` |
| 6 | 高単価商品の作成 | 12 | `products/high-ticket/` |
| 7 | 導線設計・セールス | 9 | `funnel/` |

## ファイル

| ファイル | 中身 |
|---|---|
| `TASKS.md` | 全タスクの一覧と完了チェック（**進捗の正本**） |
| `CLAUDE.md` | 前提ルールと6セクション（2-02 で埋める） |
| `.claude/skills/yl/SKILL.md` | 実行の手順と守ること |
| `.claude/skills/yl/phases/*.md` | フェーズ別のプロンプト（シートの原文） |
| `tools/gen_from_sheet.py` | シートの CSV から `TASKS.md` と `phases/` を作り直す |

## シートを更新したとき

シートを CSV でダウンロード（ファイル → ダウンロード → CSV）して、このフォルダの直下で次を実行します。

```
python3 tools/gen_from_sheet.py <ダウンロードしたCSV> .
```

⚠ `TASKS.md` は上書きされ、完了チェックが消えます。先に控えを取り、済んだ印を付け直してください。

## シートから作るときの読み替え

- シートで上の行と結合されているタスク名（1-04、6-11）は「（続き）」として別 ID にしました。
- 6-10 はタスク名がオンボーディングですが、プロンプトはつまずきポイントの予測です。シートの原文のままにしています。
