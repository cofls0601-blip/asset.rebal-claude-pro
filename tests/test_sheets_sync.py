import copy
import json
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock
import requests
from streamlit_app.sheets_sync import load_workspace, save_workspace, SheetsError
from streamlit_app.ledger import backup_bytes, empty_workspace, parse_table
from streamlit_app.data import normalize_holdings
from test_manual import ws as make_workspace

def run(): return None
def ws(_): return make_workspace()

URL='https://script.google.com/macros/s/test_deployment/exec'
SECRET='test-only-'+'x'*32


class Transport:
    def __init__(self, workspace):
        self.payload=json.loads(backup_bytes(workspace));self.token='base';self.last=None;self.calls=[];self.lose_response=False
    def post(self,url,**kwargs):
        self.calls.append((url,kwargs));body=kwargs['json']
        if body['action']=='save':
            if self.last==body['request_id']:
                result={'ok':True,'token':self.token,'request_id':self.last}
            elif body['expected_token']!=self.token:
                result={'ok':False,'error':'conflict'}
            else:
                self.payload=copy.deepcopy(body['workspace']);self.token='saved';self.last=body['request_id']
                if self.lose_response:self.lose_response=False;raise requests.Timeout('fake timeout')
                result={'ok':True,'token':self.token,'request_id':self.last}
        else:result={'ok':True,'workspace':copy.deepcopy(self.payload),'token':self.token}
        response=Mock();response.json.return_value=result;return response


class SheetsTests(unittest.TestCase):
    def test_leading_zero_and_parentheses_survive_sync(self):
        r=run();workspace=ws(r)
        workspace['holdings'].loc[0,['ticker','name']]=['069500','TIGER 200(합성)']
        transport=Transport(empty_workspace())
        token=save_workspace(URL,SECRET,workspace,'base',transport=transport)
        restored,_=load_workspace(URL,SECRET,transport=transport)
        self.assertEqual(token,'saved');self.assertEqual(restored['holdings'].ticker.iloc[0],'069500')
        self.assertEqual(restored['holdings'].name.iloc[0],'TIGER 200(합성)')
        self.assertTrue(all('secret' not in url and 'params' not in args for url,args in transport.calls))

    def test_lost_ack_retry_uses_same_id(self):
        workspace=ws(run());transport=Transport(empty_workspace());transport.lose_response=True
        with self.assertRaises(SheetsError):save_workspace(URL,SECRET,workspace,'base',transport=transport)
        self.assertEqual(save_workspace(URL,SECRET,workspace,'base',transport=transport),'saved')
        ids=[a['json']['request_id'] for _,a in transport.calls if a['json']['action']=='save']
        self.assertEqual(ids[0],ids[1])

    def test_conflict_does_not_overwrite_remote(self):
        transport=Transport(empty_workspace());transport.token='newer'
        with self.assertRaisesRegex(SheetsError,'다른 세션'):save_workspace(URL,SECRET,ws(run()),'base',transport=transport)
        self.assertIsNone(transport.last)

    def test_csv_leading_zero_and_literal_search(self):
        frame=ws(run())['holdings'];frame.loc[0,['ticker','name']]=['069500','TIGER 200(합성)']
        restored=normalize_holdings(parse_table(frame.to_csv(index=False)))
        self.assertEqual(restored.ticker.iloc[0],'069500')
        self.assertTrue(restored.name.str.contains('(합성)',regex=False).iloc[0])

    def test_backend_transaction_contract(self):
        if not shutil.which('node'):self.skipTest('Node.js is required for Apps Script mock contract tests')
        path=Path(__file__).with_name('test_apps_script.js')
        result=subprocess.run(['node',str(path)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()

