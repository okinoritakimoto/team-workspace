"""シートのCSVからタスク一覧とフェーズ別の手順ファイルを生成する。
使い方: python3 tools/gen_from_sheet.py <sheet.csv> <出力先kitディレクトリ>
"""
import csv, os, re, sys

src, kit = sys.argv[1], sys.argv[2]
rows = list(csv.reader(open(src, encoding="utf-8")))[1:]

PHASES = {
    "0": ("前準備", "."),
    "1": ("リサーチ・コンセプト", None),
    "2": ("ナレッジを入れる", "knowledge"),
    "3": ("発信、集客", "posts"),
    "4": ("商品設計・作成（note）", "products/note"),
    "5": ("販売プロモーション", "promotion"),
    "6": ("高単価商品の作成", "products/high-ticket"),
    "7": ("導線設計・セールス", "funnel"),
}
NUM = {"⓪": "0", "①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5", "⑥": "6", "⑦": "7"}

def clean(s):
    return s.replace("[merged] ", "").replace("\\[merged\\] ", "").strip()

def short(name):
    s = re.split(r"[（(]", name)[0]
    s = re.sub(r"[\\/:*?\"<>|　 、。・→]", "", s)
    return s[:24]

# 既定の置き場では合わないタスクだけ明示する
OVERRIDES = {
    "0-01": "CLAUDE.md",
    "2-01": "README.md（ディレクトリのルール）",
    "2-02": "CLAUDE.md",
    "2-05": "rules/判断基準.md",
    "2-06": "knowledge/文体集/",
    "2-08": "knowledge/見本投稿/",
    "2-07": "knowledge/スキル化メモ.md",
}
NAME_OVERRIDES = {"キラーワードを収集する": "knowledge/キラーワード.md"}

tasks, phase, mid = [], None, ""
seq = {}
for r in rows:
    r = (r + [""] * 10)[:10]
    big, mcat, know, _, _, name, pat, _, prompt, url = [clean(x) for x in r]
    if not any(r):
        continue
    if big:
        phase = NUM[big[0]]
    if mcat:
        mid = mcat
    if not name and not prompt:
        continue
    if not name:  # シートで上の行と結合されているセル
        name = re.sub(r"（続き）$", "", tasks[-1]["name"]) + "（続き）"
    seq[phase] = seq.get(phase, 0) + 1
    tid = f"{phase}-{seq[phase]:02d}"
    hit = [v for k, v in NAME_OVERRIDES.items() if name.startswith(k)]
    if tid in OVERRIDES:
        out = OVERRIDES[tid]
    elif hit:
        out = hit[0]
    elif "スキル" in name or "Skill" in name:
        out = ".claude/skills/（作ったスキル名）/SKILL.md"
    else:
        base = PHASES[phase][1]
        if base is None:
            base = "research" if pat == "調査" else "knowledge/concept"
        if phase == "3" and "分析" in name:
            base = "analysis"
        out = f"{base}/{tid}_{short(name)}.md"
    tasks.append(dict(id=tid, phase=phase, mid=mid, know=know, name=name,
                      pat=pat, prompt=prompt, url=url, out=out))

# TASKS.md（進捗の正本）
lines = ["# タスク一覧（進捗の正本）", "",
         "> 元: Googleスプレッドシート「ユーラボ月100万AI駆動タスクリスト」。",
         "> 終わったら `[ ]` を `[x]` に変える（`/yl` が実行後に自動で付ける）。シート側のチェックは手で付ける。",
         ""]
for p, (title, _) in PHASES.items():
    lines += [f"## {p}. {title}", "", "| 済 | ID | 中カテゴリ | タスク | 種類 | 成果物の置き場 |", "|---|---|---|---|---|---|"]
    for t in [t for t in tasks if t["phase"] == p]:
        lines.append(f"| [ ] | {t['id']} | {t['mid']} | {t['name']} | {t['pat']} | `{t['out']}` |")
    lines.append("")
open(os.path.join(kit, "TASKS.md"), "w").write("\n".join(lines))

# フェーズ別の手順（プロンプトはシートの原文のまま）
pdir = os.path.join(kit, ".claude/skills/yl/phases")
os.makedirs(pdir, exist_ok=True)
for p, (title, _) in PHASES.items():
    out = [f"# {p}. {title}", "",
           "> プロンプトはシートの原文。実行のしかたは `../SKILL.md` の「実行の手順」に従う。", ""]
    for t in [t for t in tasks if t["phase"] == p]:
        out += [f"## {t['id']} {t['name']}", "",
                f"- 中カテゴリ: {t['mid'] or '—'}",
                f"- 種類: {t['pat']}",
                f"- 成果物: `{t['out']}`" + (f"（ナレッジ: {t['know']}）" if t['know'] else ""),
                ]
        if t["url"]:
            out.append(f"- 参考URL: {t['url']}")
        out.append("")
        if t["prompt"] in ("", "-"):
            out += ["**プロンプトなし（素材を入れるタスク）**: ユーザーに素材（文章・URL・ファイル）を貼ってもらい、成果物の置き場に整理して保存する。", ""]
        else:
            body = "\n".join("> " + l if l else ">" for l in t["prompt"].splitlines())
            out += ["プロンプト:", "", body, ""]
    open(os.path.join(pdir, f"{p}.md"), "w").write("\n".join(out))

print(len(tasks), "tasks")
for p in PHASES:
    print(p, sum(t["phase"] == p for t in tasks))
