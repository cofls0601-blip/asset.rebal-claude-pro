// Exercise the actual Apps Script source with an in-memory SpreadsheetApp adapter.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
let failTab = null;
let mangle = null; // {from,to}: a cell the sheet changes on its own, to test the error detail
class Range {
  constructor(tab,r,c,rows=1,cols=1) { Object.assign(this,{tab,r,c,rows,cols}); }
  getValue() { return this.getValues()[0][0]; }
  getValues() { return Array.from({length:this.rows},(_,i)=>Array.from({length:this.cols},(_,j)=>this.tab.data[this.r-1+i]?.[this.c-1+j] ?? '')); }
  setValue(v) { return this.setValues([[v]]); }
  setNumberFormat(f) { this.fmt=f; return this; }
  setValues(values) {
    if(failTab===this.tab.name) { failTab=null; throw new Error('injected write failure'); }
    values.forEach((row,i)=>row.forEach((v,j)=>{
      this.tab.data[this.r-1+i] ||= [];
      // Like Google Sheets: plain-text ('@') cells keep numbers and booleans as text.
      if(this.fmt==='@' && typeof v==='number') v=String(v);
      if(this.fmt==='@' && typeof v==='boolean') v=v?'TRUE':'FALSE';
      if(mangle && v===mangle.from){ v=mangle.to; mangle=null; }
      this.tab.data[this.r-1+i][this.c-1+j] = typeof v==='string' && v.startsWith("'=") ? v.slice(1) : v;
    }));
    return this;
  }
}
class Sheet {
  constructor(name) { this.name=name;this.data=[]; }
  getRange(...args) { return new Range(this,...args); }
  getDataRange() { return new Range(this,1,1,Math.max(1,this.data.length),Math.max(1,...this.data.map(r=>r.length))); }
  getLastRow() { return this.data.length; }
  clearContents() { this.data=[]; }
  getMaxRows() { return 10000; }
  getMaxColumns() { return 100; }
  setFrozenRows() {}
  getName() { return this.name; }
  setName(n) { tabs.delete(this.name); this.name=n; tabs.set(n,this); return this; }
}
const tabs = new Map();
const order = []; let active = null; // tab order, like the sheet bar at the bottom
const spreadsheet = {
  getSheetByName:n=>tabs.get(n), insertSheet:n=>{const s=new Sheet(n);tabs.set(n,s);order.push(s);return s;},
  getSheets:()=>order.filter(s=>tabs.get(s.name)===s), getNumSheets:()=>order.filter(s=>tabs.get(s.name)===s).length,
  setActiveSheet:s=>{active=s;}, moveActiveSheet:pos=>{const live=order.filter(s=>tabs.get(s.name)===s&&s!==active);live.splice(pos-1,0,active);order.length=0;order.push(...live);},
  getSpreadsheetTimeZone:()=> 'Asia/Seoul'
};
const secret='test-only-'+'x'.repeat(32);
const context=vm.createContext({
  PropertiesService:{getScriptProperties:()=>({getProperty:k=>k==='SHEETS_SECRET'?secret:'test-sheet'})},
  SpreadsheetApp:{openById:()=>spreadsheet,flush:()=>{}},
  LockService:{getScriptLock:()=>({tryLock:()=>true,releaseLock:()=>{}})},
  Utilities:{DigestAlgorithm:{SHA_256:'sha256'},Charset:{UTF_8:'utf8'},
    computeDigest:(_algorithm,input)=>[...crypto.createHash('sha256').update(input).digest()]},
  ContentService:{MimeType:{JSON:'json'},createTextOutput:text=>({setMimeType:()=>text})}
});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../apps_script/Code.gs'),'utf8'),context);
function call(body) { return JSON.parse(context.doPost({postData:{contents:JSON.stringify({secret,...body})}})); }
const original=call({action:'load'});assert.equal(original.ok,true);
assert.equal(context.diagnoseRecovery().state,'clean');
assert.equal(context.diagnoseRecovery().recovery,'missing_or_empty');
const workspace=original.workspace;
workspace.columns.holdings=['ticker','name','shares'];
workspace.tables.holdings=[{ticker:'069500',name:'TIGER 200(합성)',shares:10}];
workspace.columns.actions=['execution_id','actual_amount'];
workspace.tables.actions=[{execution_id:'e1',actual_amount:1000}];
const first={action:'save',workspace,expected_token:original.token,request_id:'a'.repeat(64)};
assert.equal(call({...first,secret:'wrong'}).error,'unauthorized');
const saved=call(first);assert.equal(saved.ok,true);
assert.equal(call(first).repeated,true);
assert.equal(call({action:'load'}).workspace.tables.actions.length,1);
const second=structuredClone(first);second.request_id='b'.repeat(64);
assert.equal(call(second).error,'conflict');
second.expected_token=saved.token;second.workspace.tables.holdings[0].shares=20;
failTab='거래 기록';assert.equal(call(second).ok,false);
assert.equal(Number(call({action:'load'}).workspace.tables.holdings[0].shares),10);
assert.equal(call(second).ok,true);
// A manual edit changes the token and is not overwritten by a stale session.
tabs.get('보유').data[1][2]=25;
assert.equal(call(second).error,'conflict');
// Simulate a process interruption with a pending rollback image.
const before=call({action:'load'});
context.writeRecovery(spreadsheet,{workspace:before.workspace,state:{}});
context.writeState(spreadsheet,{pending:'incomplete'});
tabs.get('보유').data[1][2]=999;
const pendingReport=context.diagnoseRecovery();
assert.equal(pendingReport.state,'pending');
assert.equal(pendingReport.recovery,'valid');
assert.equal(pendingReport.current_matches_backup,false);
assert.equal(tabs.get('보유').data[1][2],999); // Diagnosis must not change the source.
assert.equal(Number(call({action:'load'}).workspace.tables.holdings[0].shares),25);
tabs.get('_RebalanceRecovery').data=[['not-json']];
context.writeState(spreadsheet,{pending:'incomplete'});
const corruptReport=context.diagnoseRecovery();
assert.equal(corruptReport.recovery,'invalid_json');
assert.equal(call({action:'load'}).error,'recovery_required');
// Numbers and booleans sent as such come back as text and still count as saved.
tabs.get('_RebalanceRecovery').data=[];context.writeState(spreadsheet,{});
const fresh=call({action:'load'});const typed=structuredClone(fresh.workspace);
typed.columns.strategies=['code','active','target'];typed.tables.strategies=[{code:'GSM',active:true,target:12.5}];
const ok=call({action:'save',workspace:typed,expected_token:fresh.token,request_id:'c'.repeat(64)});
assert.equal(ok.ok,true,JSON.stringify(ok));
assert.equal(call({action:'load'}).workspace.tables.strategies[0].active,'TRUE');
// A cell the sheet really changes is reported by tab, row and column, without its value.
mangle={from:'GSM',to:'GSMX'};
const typed2=structuredClone(typed);typed2.tables.strategies[0].target=20;
const bad=call({action:'save',workspace:typed2,expected_token:ok.token,request_id:'d'.repeat(64)});mangle=null;
assert.equal(bad.error,'save_failed_retry');
assert.deepEqual(bad.detail,{stage:'verify',table:'_전략 설정',row:2,column:'code',sent:'text',sheet:'text'});
assert.ok(!JSON.stringify(bad).includes('GSM'));
assert.equal(Number(call({action:'load'}).workspace.tables.strategies[0].target),12.5); // rolled back
// Moving an existing English-tab sheet to the 2026-11-28 layout.
tabs.clear();order.length=0;
const legacy=spreadsheet.insertSheet('Holdings');legacy.data=[['strategy','ticker','shares'],['GSM','069500','10']];
spreadsheet.insertSheet('Evaluations').data=[['run_id'],['r1']];spreadsheet.insertSheet('메모');
const old=call({action:'load'});assert.equal(old.workspace.tables.holdings[0].ticker,'069500'); // read from the English tab
const moved=call({action:'save',workspace:old.workspace,expected_token:old.token,request_id:'e'.repeat(64)});
assert.equal(moved.ok,true,JSON.stringify(moved));
assert.deepEqual(tabs.get('보유').data[1],['GSM','069500','10']);
assert.deepEqual(tabs.get('_예전_Holdings').data[1],['GSM','069500','10']); // original kept as a copy
assert.ok(tabs.get('_예전_Evaluations') && !tabs.get('Evaluations'));
const names=spreadsheet.getSheets().map(s=>s.getName());
assert.deepEqual(names.slice(0,4),['보유','월별 기록','거래 기록','입출금']);
assert.ok(names.indexOf('메모')<names.indexOf('_전략 설정') && names.slice(names.indexOf('_전략 설정')).every(n=>n.startsWith('_')),names.join());
assert.equal(call({action:'load'}).workspace.tables.holdings[0].ticker,'069500');
console.log('Apps Script contract: auth, save, replay, conflict, rollback, recovery, plain-text read-back, error detail, 2026-11-28 tab layout passed');

