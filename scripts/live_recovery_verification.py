"""Actual-provider fault verification, scoped to one explicitly labeled test case.
Run with the ordinary worker stopped. Never approves or ships. All effects use
production bridge/tools; faults discard only acknowledgements after acceptance.
"""
import asyncio,json,sys,time
from datetime import datetime,timezone
from app.bridge import LiveBridge
from app.db import transaction
CASE=sys.argv[1]; MODE=sys.argv[2]
class LostVerificationAcknowledgement(RuntimeError): pass
class ZooProxy:
    def __init__(self,zoo,fault,report): self.zoo=zoo; self.fault=fault; self.report=report; self.used=False
    def __getattr__(self,name): return getattr(self.zoo,name)
    async def post_events(self,agent,session,events):
        receipts=await self.zoo.post_events(agent,session,events)
        if MODE=='interrupt-input' and not self.used:
            self.used=True
            self.report['fault']={'kind':'accepted ZooWork input acknowledgement discarded','agent_id':agent,'session_id':session,'accepted_receipts':receipts,'delivery_key':events[0]['idempotency_key']}
            self.fault.set()
            raise LostVerificationAcknowledgement('Verification: accepted ZooWork input acknowledgement interrupted')
        return receipts
class ToolsProxy:
    def __init__(self,tools,bridge): self.tools=tools; self.bridge=bridge
    def __getattr__(self,name): return getattr(self.tools,name)
    async def execute_tool_call(self,name,args):
        receipt=await self.tools.execute_tool_call(name,args)
        if MODE=='interrupt-handoff' and name=='band_send_message' and not self.bridge.injected:
            self.bridge.injected=True
            self.bridge.report['fault']={'kind':'accepted Band handoff acknowledgement discarded','request_key':json.loads(args['content'])['request_key'],'accepted_receipt':receipt}
            self.bridge.fault.set()
            raise LostVerificationAcknowledgement('Verification: accepted Band handoff acknowledgement interrupted')
        return receipt
class VerificationBridge(LiveBridge):
    async def receive(self,role,msg,tools,participants,room):
        if room==self.report.get("room_id"):
            print("LIVE_DELIVERY="+json.dumps({"role":role,"id":msg.id,"content":msg.content},default=str),flush=True)
        return await super().receive(role,msg,tools,participants,room)
    async def resolve(self,role,case_id,version,call_id,name,args,tools):
        if case_id==CASE and MODE=='interrupt-handoff': tools=ToolsProxy(tools,self)
        return await super().resolve(role,case_id,version,call_id,name,args,tools)
def state():
    with transaction() as c:
        return {'case':c.execute('SELECT * FROM return_cases WHERE id=%s',(CASE,)).fetchone(),'sessions':c.execute('SELECT * FROM agent_sessions WHERE case_id=%s',(CASE,)).fetchall(),'provider_calls':c.execute("SELECT * FROM provider_calls WHERE data->>'case_id'=%s ORDER BY created_at,request_key",(CASE,)).fetchall(),'proposals':c.execute('SELECT * FROM route_proposals WHERE case_id=%s',(CASE,)).fetchall(),'shipments':c.execute('SELECT * FROM shipments WHERE case_id=%s',(CASE,)).fetchall(),'jobs':c.execute('SELECT * FROM jobs WHERE case_id=%s',(CASE,)).fetchall()}
async def main():
    report={'case_id':CASE,'mode':MODE,'started_at':datetime.now(timezone.utc).isoformat(),'recovery_errors':[]}
    initial=state(); case=initial['case']
    assert case and case['data']['reason'].startswith('LIVE VERIFICATION') and case['version']==2
    assert not initial['shipments'] and case['status']!='approved'
    report['room_id']=case['data'].get('band_room_id')
    bridge=VerificationBridge(); bridge.report=report; bridge.fault=asyncio.Event(); bridge.injected=False
    bridge.zoo=ZooProxy(bridge.zoo,bridge.fault,report)
    try:
        await bridge.start()
        job={'case_id':CASE,'version':case['version'],'type':'plan'}
        try: await bridge.initiate(job)
        except Exception as exc: report['recovery_errors'].append({'type':type(exc).__name__,'message':str(exc)})
        with transaction() as c:
            c.execute("UPDATE jobs SET status='done',lease_until=NULL,error=NULL WHERE case_id=%s AND version=2 AND type='plan'",(CASE,))
            # The pre-inspection job is obsolete, never sent.
            c.execute("UPDATE jobs SET status='superseded' WHERE case_id=%s AND version=1 AND status='pending'",(CASE,))
        deadline=time.monotonic()+420; next_recover=time.monotonic()+12
        while time.monotonic()<deadline:
            current=state()
            if MODE.startswith('interrupt') and bridge.fault.is_set():
                await asyncio.sleep(2)
                report['result']='Acknowledgement interruption injected after real provider acceptance; original delivery/session retained for recovery.'
                break
            if MODE=='complete' and current['case']['status']=='awaiting_approval' and current['sessions'] and all(not r['data'].get('active_message') for r in current['sessions']):
                report['result']='Live recommendation completed; no merchant approval or shipment.'
                break
            if time.monotonic()>next_recover:
                next_recover=time.monotonic()+15
                try: await bridge.recover_deliveries(current['case'],current['case']['data']['band_room_id'])
                except Exception as exc: report['recovery_errors'].append({'type':type(exc).__name__,'message':str(exc)})
            await asyncio.sleep(1)
        else: report['result']='Verification deadline reached; external review may be required.'
    finally:
        await asyncio.gather(*(agent.stop() for agent in bridge.agents),return_exceptions=True)
        report['final']=state()
        assert not report['final']['shipments']
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        print('VERIFICATION_REPORT='+json.dumps(report,default=str),flush=True)
asyncio.run(main())
