#!/usr/bin/env python3
"""从项目进度 JSON 生成可离线打开的只读看板（Python 3.9+，仅标准库）。"""
import argparse
import json
import os
from pathlib import Path
import tempfile

STATUSES = ('未开始', '进行中', '已完成')
CATEGORIES = ('构建', '静态检查', '自动化测试', '人工操作', '真机验证')


def require(*, condition, message):
    if not condition:
        raise ValueError(message)


def string(*, value, field, empty=False):
    require(condition=isinstance(value, str) and (empty or bool(value.strip())), message=f'{field} 必须是字符串' + ('' if empty else '且非空'))


def strings(*, value, field, nonempty=False):
    require(condition=isinstance(value, list), message=f'{field} 必须是数组')
    for item in value:
        string(value=item, field=field)
    require(condition=len(value) == len(set(value)), message=f'{field} 不得重复')
    require(condition=not nonempty or bool(value), message=f'{field} 不得为空')


def records(*, value, field):
    require(condition=isinstance(value, list), message=f'{field} 必须是数组')
    result = {}
    for item in value:
        require(condition=isinstance(item, dict), message=f'{field} 元素必须是对象')
        string(value=item.get('id'), field=f'{field}.id')
        require(condition=item['id'] not in result, message=f'重复编号：{item["id"]}')
        result[item['id']] = item
    return result


def validate(*, data):
    require(condition=isinstance(data, dict) and data.get('schema_version') == 1, message='schema_version 必须为 1')
    project = data.get('project')
    require(condition=isinstance(project, dict), message='缺少 project')
    for key in ('name', 'current_stage', 'updated_at'):
        string(value=project.get(key), field=f'project.{key}')
    require(condition=isinstance(project.get('demo'), bool), message='project.demo 必须为布尔值')
    reqs = records(value=data.get('requirements'), field='requirements')
    tasks = records(value=data.get('tasks'), field='tasks')
    changes = records(value=data.get('changes'), field='changes')
    all_ids = list(reqs) + list(tasks) + list(changes)
    require(condition=len(set(all_ids)) == len(all_ids), message='需求、任务、变更编号不得跨类型重复')
    for rid, req in reqs.items():
        for key in ('title', 'scope'):
            string(value=req.get(key), field=f'{rid}.{key}')
        require(condition=req.get('confirmation') in ('待确认', '已确认'), message=f'{rid} 确认状态无效')
        require(condition=isinstance(req.get('cancelled'), bool), message=f'{rid}.cancelled 必须为布尔值')
        strings(value=req.get('acceptance_criteria'), field=f'{rid}.acceptance_criteria', nonempty=True)
    for tid, task in tasks.items():
        for key in ('title', 'stage', 'scope'):
            string(value=task.get(key), field=f'{tid}.{key}')
        for key in ('blocked_reason', 'acceptance_evidence'):
            string(value=task.get(key), field=f'{tid}.{key}', empty=True)
        for key in ('implemented', 'cancelled'):
            require(condition=isinstance(task.get(key), bool), message=f'{tid}.{key} 必须为布尔值')
        require(condition=task.get('status') in STATUSES, message=f'{tid} 状态无效')
        require(condition=task.get('acceptance_result') in ('待验证', '通过', '未通过'), message=f'{tid} 验收结果无效')
        for key in ('requirement_ids', 'dependencies', 'acceptance_criteria', 'remaining_items', 'required_checks'):
            strings(value=task.get(key), field=f'{tid}.{key}', nonempty=key in ('requirement_ids', 'acceptance_criteria'))
        require(condition=set(task['requirement_ids']) <= reqs.keys(), message=f'{tid} 引用了不存在的需求')
        require(condition=set(task['dependencies']) <= tasks.keys(), message=f'{tid} 缺失依赖任务')
        require(condition=set(task['required_checks']) <= set(CATEGORIES), message=f'{tid} 验证类别无效')
        checks = task.get('verification')
        require(condition=isinstance(checks, list), message=f'{tid}.verification 必须为数组')
        seen = set()
        for check in checks:
            require(condition=isinstance(check, dict), message=f'{tid} 验证记录必须为对象')
            category = check.get('category')
            require(condition=category in CATEGORIES and category not in seen, message=f'{tid} 验证类别无效或重复')
            seen.add(category)
            require(condition=check.get('result') in ('待验证', '通过', '未通过'), message=f'{tid} 验证结果无效')
            for key in ('evidence', 'checked_at'):
                string(value=check.get(key), field=f'{tid}.verification.{key}', empty=check['result'] == '待验证')
        history = task.get('history')
        require(condition=isinstance(history, list), message=f'{tid}.history 必须为数组')
        for event in history:
            require(condition=isinstance(event, dict), message=f'{tid} 历史必须为对象')
            for key in ('at', 'status', 'note'):
                string(value=event.get(key), field=f'{tid}.history.{key}')
            require(condition=event['status'] in STATUSES, message=f'{tid} 历史状态无效')
        if task['acceptance_result'] == '通过':
            string(value=task['acceptance_evidence'], field=f'{tid}.acceptance_evidence')
        if task['implemented']:
            require(condition=task['status'] != '未开始', message=f'{tid} 已实现任务不能为未开始')
        if task['status'] == '已完成':
            require(condition=task['implemented'] and task['acceptance_result'] == '通过' and bool(task['acceptance_evidence'].strip()), message=f'{tid} 已完成必须已实现并提供验收通过依据')
            results = {c['category']: c['result'] for c in checks}
            require(condition=all(results.get(c) == '通过' for c in task['required_checks']) and all(c['result'] == '通过' for c in checks), message=f'{tid} 必要验证缺失或仍有未通过、待验证项')
            require(condition=not task['blocked_reason'].strip() and not task['remaining_items'], message=f'{tid} 已完成不能有阻塞或未完成事项')
            require(condition=all(reqs[r]['confirmation'] == '已确认' for r in task['requirement_ids']), message=f'{tid} 未确认需求不能完成')
    # DFS 检查依赖，包含历史任务，避免隐藏无效引用。
    visited, visiting = set(), set()

    def visit(*, tid):
        require(condition=tid not in visiting, message=f'依赖循环：{tid}')
        if tid in visited:
            return
        visiting.add(tid)
        for dep in tasks[tid]['dependencies']:
            visit(tid=dep)
        visiting.remove(tid)
        visited.add(tid)

    for tid in tasks:
        visit(tid=tid)
    for cid, change in changes.items():
        require(condition=change.get('type') in ('新增', '修改', '取消'), message=f'{cid} 变更类型无效')
        require(condition=change.get('confirmation') in ('待确认', '已确认'), message=f'{cid} 确认状态无效')
        for key in ('at', 'summary', 'reason'):
            string(value=change.get(key), field=f'{cid}.{key}')
        for key, known in (('requirement_ids', reqs), ('task_ids', tasks)):
            strings(value=change.get(key), field=f'{cid}.{key}')
            require(condition=set(change[key]) <= known.keys(), message=f'{cid} 存在无效关联')
    return data


def generate(*, source, output):
    source, output = Path(source), Path(output)
    require(condition=source.resolve() != output.resolve() and output.suffix.lower() == '.html', message='输出必须为独立的 .html 文件')
    data = validate(data=json.loads(source.read_text(encoding='utf-8')))
    # 不允许用户文本终止 application/json script 标签。
    payload = json.dumps(data, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    template = Path(__file__).with_name('board.html').read_text(encoding='utf-8')
    html = template.replace('__BOARD_DATA__', payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=output.parent, delete=False, suffix='.tmp') as handle:
            temporary = handle.name
            handle.write(html)
        os.replace(temporary, output)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return output


def main():
    root = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=root / '项目进度.json')
    parser.add_argument('--output', type=Path, default=root / '开发进度看板.html')
    args = parser.parse_args()
    try:
        result = generate(source=args.input, output=args.output)
    except (ValueError, OSError, RecursionError) as error:
        parser.exit(1, f'生成失败，原看板未覆盖：{error}\n')
    print(f'已生成：{result.resolve()}')


if __name__ == '__main__':
    main()
