import asyncio,json,os
from collections import Counter
from datetime import datetime,timezone
from band.client.rest import AsyncRestClient
from zoowork import ZooworkClient
from app.bridge import ROLES,band_envelope
from app.db import transaction
CASE='RET-f0c0a6dc2a7f'
async def main():
 with transaction() as c:
  case=c.execute('SELECT * FROM return_cases WHERE id=%s',(CASE,)).fetchone()
  sessions=c.execute('SELECT * FROM agent_sessions WHERE case_id=%s',(CASE,)).fetchall()
  proposals=c.execute('SELECT * FROM route_proposals WHERE case_id=%s',(CASE,)).fetchall()
  receipts=c.execute("SELECT * FROM provider_calls WHERE data->>'case_id'=%s ORDER BY request_key",(CASE,)).fetchall()
  shipments=c.execute('SELECT * FROM shipments WHERE case_id=%s',(CASE,)).fetchall()
  reservations=c.execute('SELECT * FROM reservations WHERE case_id=%s',(CASE,)).fetchall()
 ids={r:os.environ[f'BAND_{r.upper()}_AGENT_ID'] for r in ROLES}
 report={'at':datetime.now(timezone.utc).isoformat(),'case':case,'proposals':proposals,'receipts':receipts,'shipments':shipments,'reservations':reservations,'band_history':{},'zoowork':{}}
 unique={}
 for role in ROLES:
  client=AsyncRestClient(api_key=os.environ[f'BAND_{role.upper()}_API_KEY'])
  pages=[];cursor=None;seen=set()
  while True:
   response=await client.agent_api_context.get_agent_chat_context(chat_id=case['data']['band_room_id'],cursor=cursor,request_options={'max_retries':0})
   messages=[m.model_dump(mode='json') for m in response.data or []];pages.append(messages)
   unique.update({m['id']:m for m in messages})
   if not response.metadata.has_more:break
   cursor=response.metadata.next_cursor
   assert cursor and cursor not in seen,'Incomplete live history'
   seen.add(cursor)
  report['band_history'][role]={'pages':pages,'complete':True}
 z=ZooworkClient()
 for row in sessions:
  d=row['data'];s=await z.get_session(d['agent_id'],d['session_id'],history=True,limit=500)
  inputs=[]
  for h in s.get('history',[]):
   m=h.get('entry',{}).get('message',{})
   if m.get('role')!='user':continue
   text=m.get('content',[]); text=text if isinstance(text,str) else ''.join(p.get('text','') for p in text if isinstance(p,dict))
   try:ctx=json.loads(text)
   except (ValueError,TypeError):continue
   if isinstance(ctx,dict) and ctx.get('trusted_case_id')==CASE:
    inputs.append({'seq':h.get('seq'),'at':h.get('created_at'),'band_message_id':ctx.get('band_message_id'),'version':ctx.get('expected_version')})
  counts=Counter(i['band_message_id'] for i in inputs)
  pending=await z.list_custom_tool_calls(d['agent_id'],session_id=d['session_id'],status='pending')
  report['zoowork'][row['role']]={'session_id':d['session_id'],'agent_id':d['agent_id'],'run_status':s.get('run_status'),'inputs':inputs,'input_counts':dict(counts),'pending_custom_tools':pending,'saved_session':d}
  assert counts and max(counts.values())==1 and not pending and not d.get('active_message')
 keys=Counter()
 for m in unique.values():
  try:env=band_envelope(m['content'],ids.values())
  except (ValueError,TypeError):continue
  if isinstance(env,dict) and env.get('request_key'):keys[env['request_key']]+=1
 report['unique_band_message_count']=len(unique);report['band_request_key_counts']=dict(keys)
 assert keys and max(keys.values())==1
 assert case['status']=='awaiting_approval' and not shipments
 assert len(proposals)==1 and proposals[0]['status']=='pending'
 assert any(r['provider']=='moss' and r['status']=='succeeded' for r in receipts)
 assert all(r['status'] not in ('pending','posting','running') for r in receipts)
 print(json.dumps(report,default=str,indent=2))
asyncio.run(main())
