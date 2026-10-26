// Bound to the user's spreadsheet. No Cloud Console or service account setup.
// Apps Script itself uses a Google-managed default Cloud project.
// Script Properties: SHEETS_SECRET (random, >=24 characters), SPREADSHEET_ID.
const TABLE_NAMES = {
  holdings: 'Holdings', strategies: 'Strategies', snapshots: 'Snapshots',
  actions: 'Actions', cashflows: 'Cashflows', category_targets: 'CategoryTargets',
  evaluations: 'Evaluations', strategy_versions: 'StrategyVersions'
};
const STATE = '_RebalanceState';
const RECOVERY = '_RebalanceRecovery';

function doGet() {
  return jsonResponse({ok: true, service: 'rebalance', protocol: 1});
}

function doPost(e) {
  const props = PropertiesService.getScriptProperties();
  let body;
  try { body = JSON.parse(e.postData.contents); }
  catch (_) { return jsonResponse({ok: false, error: 'invalid_json'}); }
  const secret = props.getProperty('SHEETS_SECRET');
  if (!secret || secret.length < 24 || body.secret !== secret) {
    return jsonResponse({ok: false, error: 'unauthorized'});
  }
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(15000)) return jsonResponse({ok: false, error: 'busy'});
  try {
    const ss = SpreadsheetApp.openById(props.getProperty('SPREADSHEET_ID'));
    recoverPending(ss);
    const workspace = readWorkspace(ss);
    const token = digest(workspace);
    if (body.action === 'load') return jsonResponse({ok: true, workspace: workspace, token: token});
    if (body.action !== 'save') return jsonResponse({ok: false, error: 'unknown_action'});
    validateWorkspace(body.workspace);
    const state = readState(ss);
    if (state.request_id === body.request_id && state.token === token) {
      return jsonResponse({ok: true, token: token, request_id: body.request_id, repeated: true});
    }
    if (body.expected_token !== token) return jsonResponse({ok: false, error: 'conflict'});
    if (!/^[a-f0-9]{64}$/.test(body.request_id || '')) throw new Error('invalid_request_id');
    // Prepare a rollback image before touching the eight user tables.
    writeRecovery(ss, {workspace: workspace, state: state});
    writeState(ss, Object.assign({}, state, {pending: body.request_id}));
    SpreadsheetApp.flush();
    try {
      writeWorkspace(ss, body.workspace);
      SpreadsheetApp.flush();
      const after = readWorkspace(ss);
      const savedToken = digest(after);
      if (savedToken !== digest(body.workspace)) throw new Error('verification_failed');
      writeState(ss, {pending: '', token: savedToken, request_id: body.request_id});
      SpreadsheetApp.flush();
      // Retain the preceding complete generation as an additional recovery copy.
      return jsonResponse({ok: true, token: savedToken, request_id: body.request_id});
    } catch (_) {
      recoverPending(ss);
      return jsonResponse({ok: false, error: 'save_failed_retry'});
    }
  } catch (err) {
    // Never echo credentials, input rows, or low-level URLs to clients.
    return jsonResponse({ok: false, error: err.message === 'recovery_required' ? 'recovery_required' : 'invalid_workspace_or_configuration'});
  } finally { lock.releaseLock(); }
}

function sheet(ss, name) { return ss.getSheetByName(name) || ss.insertSheet(name); }
function readState(ss) {
  const tab = ss.getSheetByName(STATE);
  const raw = tab ? tab.getRange(1, 1).getValue() : '';
  return raw ? JSON.parse(raw) : {};
}
function writeState(ss, value) { sheet(ss, STATE).getRange(1, 1).setValue(JSON.stringify(value)); }
function readWorkspace(ss) {
  const workspace = {schema_version: 3, tables: {}, columns: {}};
  Object.keys(TABLE_NAMES).forEach(key => {
    const tab = ss.getSheetByName(TABLE_NAMES[key]);
    const rows = tab && tab.getLastRow() ? tab.getDataRange().getValues() : [];
    const header = rows.length ? rows[0].map(String) : [];
    if (header.some(x => !x) || new Set(header).size !== header.length) throw new Error('invalid_header');
    workspace.columns[key] = header;
    workspace.tables[key] = rows.slice(1).filter(row => row.some(v => v !== '')).map(row => {
      const result = {};
      header.forEach((col, i) => {
        let value = row[i];
        if (value instanceof Date) {
          value = Utilities.formatDate(value, ss.getSpreadsheetTimeZone(), 'yyyy-MM-dd');
        }
        result[col] = value;
      });
      return result;
    });
  });
  return workspace;
}
function validateWorkspace(workspace) {
  if (!workspace || workspace.schema_version !== 3 || JSON.stringify(workspace).length > 5000000) throw new Error('invalid_workspace');
  Object.keys(TABLE_NAMES).forEach(key => {
    const cols = workspace.columns[key], rows = workspace.tables[key];
    if (!Array.isArray(cols) || !Array.isArray(rows) || new Set(cols).size !== cols.length) throw new Error('invalid_table');
    if (cols.some(c => typeof c !== 'string' || !c)) throw new Error('invalid_header');
    rows.forEach(row => cols.forEach(col => {
      const v = row[col];
      if (v !== null && typeof v !== 'string' && typeof v !== 'boolean' && !(typeof v === 'number' && Number.isFinite(v))) throw new Error('invalid_cell');
      if (typeof v === 'string' && v.length > 40000) throw new Error('cell_too_large');
    }));
  });
}
function writeWorkspace(ss, workspace) {
  Object.keys(TABLE_NAMES).forEach(key => {
    const tab = sheet(ss, TABLE_NAMES[key]), cols = workspace.columns[key];
    const values = [cols].concat(workspace.tables[key].map(row => cols.map(c => row[c] == null ? '' : row[c])));
    tab.clearContents();
    if (!cols.length) return;
    if (tab.getMaxRows() < values.length) tab.insertRowsAfter(tab.getMaxRows(), values.length - tab.getMaxRows());
    if (tab.getMaxColumns() < cols.length) tab.insertColumnsAfter(tab.getMaxColumns(), cols.length - tab.getMaxColumns());
    // Plain-text formatting preserves leading zeros. Literal '=' text never becomes a formula.
    const safe = values.map(row => row.map(v => typeof v === 'string' && v.startsWith('=') ? "'" + v : v));
    tab.getRange(1, 1, values.length, cols.length).setNumberFormat('@').setValues(safe);
    tab.setFrozenRows(1);
  });
}
function writeRecovery(ss, value) {
  const raw = JSON.stringify(value), parts = [];
  for (let i = 0; i < raw.length; i += 20000) {
    const chunk = raw.slice(i, i + 20000);
    parts.push([chunk.startsWith('=') ? "'" + chunk : chunk]);
  }
  const tab = sheet(ss, RECOVERY);
  tab.clearContents();
  if (tab.getMaxRows() < parts.length) tab.insertRowsAfter(tab.getMaxRows(), parts.length - tab.getMaxRows());
  tab.getRange(1, 1, parts.length, 1).setNumberFormat('@').setValues(parts);
  SpreadsheetApp.flush();
}
function recoverPending(ss) {
  const state = readState(ss);
  if (!state.pending) return;
  try {
    const tab = ss.getSheetByName(RECOVERY);
    const backup = JSON.parse(tab.getDataRange().getValues().map(r => r[0]).join(''));
    writeWorkspace(ss, backup.workspace);
    SpreadsheetApp.flush();
    if (digest(readWorkspace(ss)) !== digest(backup.workspace)) throw new Error('bad_recovery');
    writeState(ss, backup.state);
    SpreadsheetApp.flush();
  } catch (_) { throw new Error('recovery_required'); }
}

// Run this from the Apps Script editor when recovery_required appears.
// Read-only: the log contains no cell contents, request IDs, or credentials.
function diagnoseRecovery() {
  const report = {state: 'unknown', recovery: 'unknown', current: 'unknown'};
  try {
    const props = PropertiesService.getScriptProperties();
    const ss = SpreadsheetApp.openById(props.getProperty('SPREADSHEET_ID'));
    const stateTab = ss.getSheetByName(STATE);
    const stateRaw = stateTab ? stateTab.getRange(1, 1).getValue() : '';
    try {
      const state = stateRaw ? JSON.parse(stateRaw) : {};
      report.state = state.pending ? 'pending' : 'clean';
    } catch (_) { report.state = 'invalid_json'; }

    const tab = ss.getSheetByName(RECOVERY);
    if (!tab || !tab.getLastRow()) {
      report.recovery = 'missing_or_empty';
    } else {
      report.recovery_chunks = tab.getLastRow();
      try {
        const raw = tab.getRange(1, 1, tab.getLastRow(), 1).getValues().map(row => row[0]).join('');
        const backup = JSON.parse(raw);
        report.recovery = 'parsed';
        validateWorkspace(backup.workspace);
        report.recovery = 'valid';
        report.backup_rows = Object.keys(TABLE_NAMES).map(key => [key, backup.workspace.tables[key].length]);
        try {
          report.current_matches_backup = digest(readWorkspace(ss)) === digest(backup.workspace);
          report.current = 'readable';
        } catch (_) { report.current = 'unreadable'; }
      } catch (_) {
        if (report.recovery !== 'parsed') report.recovery = 'invalid_json';
        else report.recovery = 'invalid_workspace';
      }
    }
  } catch (_) { report.configuration = 'unavailable'; }
  console.log(JSON.stringify(report));
  return report;
}
function canonical(workspace) {
  // Object key order, blank/null cells, and integer/float encoding must not alter identity.
  return Object.keys(TABLE_NAMES).map(key => [key, workspace.columns[key], workspace.tables[key].map(row => workspace.columns[key].map(col => row[col] == null ? '' : row[col]))]);
}
function digest(workspace) {
  return Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, JSON.stringify(canonical(workspace)), Utilities.Charset.UTF_8)
    .map(x => ('0' + ((x + 256) % 256).toString(16)).slice(-2)).join('');
}
function jsonResponse(obj) { return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON); }

