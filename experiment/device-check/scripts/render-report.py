#!/usr/bin/env python3
"""Render deterministic device checks with unmodified calls and recorded video."""
import argparse
import base64
import html
import json
import shutil
from pathlib import Path


def render(run: Path) -> None:
    sections = []
    summaries = []
    for name in ('summary.json', 'followup-summary.json', 'perception-summary.json', 'perception-retry-summary.json'):
        file = run / name
        if not file.exists():
            continue
        value = json.loads(file.read_text())
        summaries.append({'file': name, 'completed': value.get('completed'), 'passed': value.get('passed'), 'failed': value.get('failed')})
        checks = value.get('checks', [])
        rows = ''.join(
            f'<details><summary>{html.escape(c["status"].upper())} · {html.escape(c["name"])}</summary>'
            f'<pre>{html.escape(json.dumps(c, ensure_ascii=False, indent=2))}</pre></details>' for c in checks
        )
        sections.append(f'<h2>{html.escape(name)}</h2>{rows}')
    videos = ''.join(
        f'<h3>{html.escape(v.stem)}</h3><video controls preload="metadata" src="{html.escape(v.relative_to(run).as_posix())}"></video>'
        for v in sorted(run.glob('roboenv/*/evidence/recording/*.mp4'))
    )
    calls = []
    media = {}
    def collect(value):
        if isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, str) and value.startswith('/tmp/roboenv-images-'):
            source = Path(value)
            if source.is_file() and source.suffix in ('.png', '.pgm'):
                target = run / 'retained-media' / source.name
                target.parent.mkdir(exist_ok=True)
                shutil.copy2(source, target)
                media[value] = target.relative_to(run).as_posix()
    for file in sorted(run.glob('*calls.jsonl')):
        for line in file.read_text().splitlines():
            event = json.loads(line)
            collect(event)
            if isinstance(event.get('result', {}).get('output'), str):
                try:
                    collect(json.loads(event['result']['output']))
                except json.JSONDecodeError:
                    pass
            previews = ''
            for attachment in event.get('result', {}).get('attachments', []):
                if attachment.get('mime', '').startswith('image/') and attachment.get('data'):
                    previews += f'<img src="data:{attachment["mime"]};base64,{attachment["data"]}">'
            calls.append(
                f'<details><summary>{html.escape(file.name)} · {html.escape(event.get("callID", ""))} · '
                f'{html.escape(event.get("name", ""))} · {html.escape(event.get("type", ""))}</summary>{previews}'
                f'<pre>{html.escape(json.dumps(event, ensure_ascii=False, indent=2))}</pre></details>'
            )
    text = f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>Kinex device compatibility checks</title>
<style>body{{font:16px system-ui;max-width:1150px;margin:32px auto;padding:0 24px;color:#222;background:#f7f7f5}}h1{{font-size:26px}}details{{padding:10px 0;border-bottom:1px solid #ddd}}summary{{cursor:pointer}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;background:#fff;padding:16px;font-size:12px}}video{{width:100%;max-height:540px;background:#111}}img{{max-width:48%;margin:8px}}</style>
<h1>Kinex 设备接口检查</h1><p>{html.escape(run.name)} · 确定性检查，无 LLM/API 推理调用。</p>
<p>本页保留测试预期错误与后续复查。开口几何上限与归一化全开目标分别记录；方向检查通过不代表达到几何上限。接口检查通过不等于任务成功。</p>
<pre>{html.escape(json.dumps(summaries, indent=2))}</pre>
<h2>完整录制（25 FPS）</h2>{videos}
{''.join(sections)}<h2>完整指令与返回</h2>{''.join(calls)}</html>'''
    (run / 'trace.html').write_text(text, encoding='utf-8')
    (run / 'retained-media-map.json').write_text(json.dumps(media, indent=2), encoding='utf-8')
    print(run / 'trace.html')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('runs', nargs='+', type=Path)
    args = parser.parse_args()
    for run in args.runs:
        render(run.resolve())
