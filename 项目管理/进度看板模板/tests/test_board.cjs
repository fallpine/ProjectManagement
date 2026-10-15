// 页面脚本单元测试：用最小 DOM 替身执行原脚本，不启动或控制浏览器。
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const template = fs.readFileSync(path.join(root, 'tools/board.html'), 'utf8');
const script = template.match(/<script>\s*([\s\S]*?)<\/script>/)[1];
const demo = JSON.parse(fs.readFileSync(path.join(root, '演示/项目进度.json'), 'utf8'));
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; this.value = ''; this._text = ''; }
  set textContent(text) { this._text = String(text); this.children = []; }
  get textContent() { return this._text + this.children.map(c => c.textContent).join(''); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this._text = ''; this.children = children; }
  setAttribute() {}
  addEventListener(name, handler) { this.events[name] = handler; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
function setup(data) {
  const elements = new Map();
  const get = id => { if (!elements.has(id)) elements.set(id, new Element('div')); return elements.get(id); };
  get('board-data').textContent = JSON.stringify(data);
  const document = {getElementById:get,createElement:tag=>new Element(tag),createTextNode:text=>{const n=new Element('text');n.textContent=text;return n;}};
  const context = vm.createContext({document});
  vm.runInContext(script, context);
  return {get, context};
}
function cards(board) { return board.children.flatMap(col => col.children.filter(n => n.tag === 'button')); }
const {get} = setup(demo);
assert.match(get('stats').textContent, /20%/);
assert.equal(cards(get('board')).length, 5);
assert.match(get('archive-title').textContent, /2/);
get('search').value = '等待格式确认';get('search').events.input();
assert.equal(cards(get('board')).length, 1);
get('reset').events.click();
get('status').value = '已完成';get('status').events.change();
assert.equal(cards(get('board')).length, 1);
cards(get('board'))[0].events.click();
assert.equal(get('detail').open, true);
assert.match(get('detail-body').textContent, /演示验收/);
get('close').events.click();assert.equal(get('detail').open, false);
get('reset').events.click();get('requirement').value='R-002';get('requirement').events.change();
assert.equal(cards(get('board')).length, 2);
get('stage').value='不存在的阶段';get('stage').events.change();assert.equal(cards(get('board')).length, 0);
get('reset').events.click();assert.equal(cards(get('board')).length, 5);
assert.match(get('stats').textContent, /20%/); // 筛选不改变全局统计。
get('search').value = '新增记录校验';get('search').events.input();
cards(get('board'))[0].events.click();assert.match(get('detail-body').textContent, /原版验收通过/);
assert.match(get('detail-body').textContent, /C-002/);
const empty = setup(JSON.parse(fs.readFileSync(path.join(root,'项目进度.json'),'utf8')));
assert.match(empty.get('stats').textContent,/暂无任务/);assert.equal(cards(empty.get('board')).length,0);
const changed = structuredClone(demo);
changed.tasks[0].status = '进行中';changed.tasks[0].acceptance_result = '待验证';
assert.match(setup(changed).get('stats').textContent,/0%/);
const cancelled = structuredClone(demo);cancelled.requirements[1].cancelled=true;
assert.equal(cards(setup(cancelled).get('board')).length,3);
const added = structuredClone(demo);const next = structuredClone(demo.tasks[3]);next.id='T-008';added.tasks.push(next);
assert.match(setup(added).get('stats').textContent,/17%/);
console.log('页面脚本检查通过：统计、草稿排除、取消、新增、重新打开、搜索、组合筛选、重置、详情和关闭；未进行真实浏览器视觉验收。');
