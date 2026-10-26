// Exercise the actual Apps Script source with an in-memory SpreadsheetApp adapter.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
let failTab = null;
class Range {
  constructor(tab,r,c,rows=1,cols=1) { Object.assign(this,{tab,r,c,rows,cols}); }
  getValue() { return this.getValues()[0][0]; }
  getValues() { return Array.from({length:this.rows},(_,i)=>Array.from({length:this.cols},(_,j)=>this.tab.data[this.r-1+i]?.[this.c-1+j] ?? '')); }
  setValue(v) { return this.setValues([[v]]); }
  setNumberFormat() { return this; }
  setValues(values) {
    if(failTab===this.tab.name) { failTab=null; throw new Error('injected write failure'); }
    values.forEach((row,i)=>row.forEach((v,j)=>{
      this.tab.data[this.r-1+i] ||= [];
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
}
const tabs = new Map();
const spreadsheet = {
  getSheetByName:n=>tabs.get(n), insertSheet:n=>{const s=new Sheet(n);tabs.set(n,s);return s;},
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
failTab='Actions';assert.equal(call(second).ok,false);
assert.equal(call({action:'load'}).workspace.tables.holdings[0].shares,10);
assert.equal(call(second).ok,true);
// A manual edit changes the token and is not overwritten by a stale session.
tabs.get('Holdings').data[1][2]=25;
assert.equal(call(second).error,'conflict');
// Simulate a process interruption with a pending rollback image.
const before=call({action:'load'});
context.writeRecovery(spreadsheet,{workspace:before.workspace,state:{}});
context.writeState(spreadsheet,{pending:'incomplete'});
tabs.get('Holdings').data[1][2]=999;
const pendingReport=context.diagnoseRecovery();
assert.equal(pendingReport.state,'pending');
assert.equal(pendingReport.recovery,'valid');
assert.equal(pendingReport.current_matches_backup,false);
assert.equal(tabs.get('Holdings').data[1][2],999); // Diagnosis must not change the source.
assert.equal(call({action:'load'}).workspace.tables.holdings[0].shares,25);
tabs.get('_RebalanceRecovery').data=[['not-json']];
context.writeState(spreadsheet,{pending:'incomplete'});
const corruptReport=context.diagnoseRecovery();
assert.equal(corruptReport.recovery,'invalid_json');
assert.equal(call({action:'load'}).error,'recovery_required');
console.log('Apps Script contract: auth, save, replay, conflict, rollback, recovery passed');

