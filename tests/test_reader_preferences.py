"""Execute the production reader script with browser storage across reloads."""
import shutil
import subprocess
from pathlib import Path
import pytest


def test_visit_cutoff_survives_reload_and_idle_starts_a_new_visit():
    node = shutil.which('node')
    if not node: pytest.skip('Node is needed for the browser storage regression')
    script = r'''
const fs = require('node:fs'), vm = require('node:vm'), assert = require('node:assert/strict');
const code = fs.readFileSync(process.argv[1], 'utf8');
const storage = () => { const data = new Map(); return {getItem:k=>data.get(k) ?? null,setItem:(k,v)=>data.set(k,v)}; };
const localStorage = storage(), sessionStorage = storage();
let clock = 100000;
class Clock extends Date { static now() { return clock; } }
function load(arrival) {
  const item = {dataset:{articleId:'late',firstSeen:new Date(arrival).toISOString()}};
  const badge = {hidden:true,closest:()=>item};
  const elements = {'reader-new-count':{},'mark-news-read':{},'saved-count':{},'density-toggle':{setAttribute(){}}};
  const document = {body:{dataset:{}},addEventListener(){},getElementById:id=>elements[id] || null,
    querySelectorAll:selector=>selector==='[data-article-id][data-first-seen]'?[item]:selector==='[data-new-badge]'?[badge]:[]};
  const window = {addEventListener(){}};
  vm.runInNewContext(code,{localStorage,sessionStorage,document,window,Date:Clock,location:{pathname:'/',href:'https://example.com/',origin:'https://example.com'},URL,console});
  return {badge,elements,window};
}
assert.equal(load(90000).badge.hidden,true); // First visit does not mark the old archive.
clock = 120000;
assert.equal(load(110000).badge.hidden,false); // Arrival between initial load and reload is new.
assert.equal(load(110000).elements['reader-new-count'].textContent,'1 nový článok na tejto stránke');
clock = 130000;
assert.equal(load(110000).badge.hidden,false); // A further reload cannot clear the mark.
clock += 31*60*1000;
assert.equal(load(125000).badge.hidden,true); // A new visit compares against the end of the last visit.
assert.equal(load(clock-1000).badge.hidden,false);
localStorage.setItem('news-saved-v1',JSON.stringify(Array.from({length:300},(_,i)=>'x'+String(i).padStart(79,'0'))));
const headers=load(0).window.newsReaderHeaders('https://example.com/ulozene');
assert.equal(Object.keys(headers).length,5);
assert.equal(Object.values(headers).every(value=>value.length<=6000),true);
assert.equal(Object.values(headers).join(',').split(',').length,300);
assert.deepEqual(Object.keys(load(0).window.newsReaderHeaders('https://elsewhere.com/ulozene')),[]);
'''
    result = subprocess.run([node, '-e', script, str(Path(__file__).resolve().parents[1] / 'static/reader.js')],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
