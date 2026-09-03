# tools — 正本から画面を作る／名前を入れ替える

> `build_dashboard.py` が正本から画面を作る。`apply_names.py` は文章の名前だけを入れ替える。
> どちらも標準ライブラリだけで動き、既定の root は `tools/` の親です。

## 画面を作り直す — `build_dashboard.py`

`20_project/` と `names.yml` を読み、canonical dict を1つ作り、同じ dict から次の2つを作ります。

データ層 v4 は `members[]`・`last_meeting`・`tasks[].dod`・`wps[]` を持ち、従来の `02_kpi_tree.md`・`03_dashboard.md`・`01_plan.md`・`names.yml` に加えて、`04_tasks/`・`08_stakeholders.md`・`09_meetings/` を生成元にします。`wps[]` は `01_plan.md` §2 の行順と値をそのまま投影し、`output.wp_done/wp_doing/wp_todo/wp_total` との状態集計が一致しない場合は生成を止めます。

- `20_project/targets.yml`（生成物・手編集禁止）
- `60_outputs/dashboard/index.html` の `script#dashboard-data` の中身だけ

```bash
python3 tools/build_dashboard.py          # 正本から2生成物を作る
python3 tools/build_dashboard.py --check  # 完全 read-only で一致を確認する
python3 tools/build_dashboard.py --root /path/to/repo
```

同じバイトなら書かないため、2回目の build では hash と mtime が変わりません。HTML の CSS/JS と JSON ブロック外は変更しません。

再 build だけで戻せるのは、HTML に `script#dashboard-data` が1件あり、その中身が有効な JSON で、正本との差が有効な JSON の値の差だけの場合です。埋め込み JSON が不正、対象ブロックが0件または2件以上、CSS/JS など JSON ブロック外を手編集した、のいずれかは再 build だけでは復旧しません。git で既知の正常な `index.html` へ戻してから build してください。画面から正本へ値を書き戻してはいけません。

| 終了コード | 意味 |
|:---:|---|
| **0** | 生成成功、または `--check` で正本・2生成物が一致 |
| **1** | `--check` で生成物が古い。JSON path 単位の差を表示（書き込みなし） |
| **2** | 正本の構文・必須値・型・参照・不変条件の違反（書き込みなし） |
| **3** | HTML の対象ブロックが0件・2件以上、または埋め込み JSON が不正（書き込みなし）。再 build だけでは復旧しないため、既知の正常な `index.html` へ戻してから build |

## 名前を入れ替える — `apply_names.py`

`names.yml` の値を、文章中の差し替え点（キー名を二重の波かっこで囲んだ印）へ適用します。`dashboard-data` と `targets.yml` は変更しません。名前を適用した後、`build_dashboard.py` で画面を作ります。

```bash
python3 tools/apply_names.py --dry-run  # 予定だけ見る
python3 tools/apply_names.py --rename   # この repo のように名前が入った後の入れ替え（前の値は names.applied.yml）
python3 tools/apply_names.py            # 差し替え点（二重の波かっこ）が残っている新しい写しでの初回だけ
python3 tools/apply_names.py --check    # 文章に残った差し替え点を確認
python3 tools/build_dashboard.py        # names.yml から画面へ反映
```

任意キー（`required: false`）が空のままでも `--check` は完了です。値が決まったら `names.yml` を埋めて再実行できます。

| 終了コード | 意味 |
|:---:|---|
| **0** | 適用・入れ替え成功、または `--check` で必須の残存なし |
| **1** | `--check` で適用すべき差し替え点が残っている |
| **2** | `names.yml` の構文違反、または `required` の値が空（書き込みなし） |
| **3** | `names.yml` に無い差し替え点がある（書き込みなし） |
| **7** | `names.yml` が見つからない |
| **8** | `--rename` に必要な `names.applied.yml` がない |

## 順序

```text
names.yml を更新
  → apply_names.py（文章）
  → apply_names.py --check
  → build_dashboard.py（targets.yml と画面）
  → build_dashboard.py --check
```

`apply_names.py` から build を内部呼び出ししません。どこで止まったかをコマンドごとに確認できます。
