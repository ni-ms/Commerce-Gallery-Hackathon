"""Read-only live history audit; --supersede closes only the unused sealed-case request."""
import asyncio, hashlib, json, os, sys
from datetime import datetime, timezone
from band.client.rest import AsyncRestClient
from app.bridge import band_envelope, ROLES
from app.db import transaction, event
from psycopg.types.json import Jsonb
CASE = 'RET-115451f05dd0'
KEY = f'band-init-{CASE}-1-research'
def digest(rows):
    return hashlib.sha256(json.dumps(rows, default=str, sort_keys=True).encode()).hexdigest()
async def main():
    with transaction() as c:
        case = c.execute('SELECT * FROM return_cases WHERE id=%s',(CASE,)).fetchone()
        saved = c.execute('SELECT * FROM provider_calls WHERE request_key=%s',(KEY,)).fetchone()
        protected = {t:digest(c.execute(f'SELECT * FROM {t} ORDER BY id').fetchall()) for t in ('return_cases','shipments','route_proposals')}
        calls = c.execute('SELECT * FROM provider_calls ORDER BY request_key').fetchall()
    ids = {r:os.environ[f'BAND_{r.upper()}_AGENT_ID'] for r in ROLES}
    audit = {'checked_at':datetime.now(timezone.utc).isoformat(),'case_id':CASE,'room_id':case['data']['band_room_id'],'original_request':saved,'protected_before':protected,'roles':{},'matching_research_messages':[]}
    all_messages = {}
    for role in ROLES:
        rest=AsyncRestClient(api_key=os.environ[f'BAND_{role.upper()}_API_KEY'])
        streams={}
        for stream in ('context','messages'):
            cursor=None; seen=set(); pages=0; messages=[]
            while True:
                if stream=='context':
                    response=await rest.agent_api_context.get_agent_chat_context(chat_id=audit['room_id'],cursor=cursor,request_options={'max_retries':0})
                else:
                    response=await rest.agent_api_messages.list_agent_messages(audit['room_id'],status='all',cursor=cursor,limit=100,request_options={'max_retries':0})
                pages+=1
                for msg in response.data or []:
                    item=msg.model_dump(mode='json'); messages.append(item)
                    all_messages[item['id']]=item
                if not response.metadata.has_more: break
                cursor=response.metadata.next_cursor
                if not cursor or cursor in seen: raise RuntimeError('Incomplete history; no mutation permitted')
                seen.add(cursor)
            streams[stream]={'pages':pages,'complete':True,'messages':messages}
        audit['roles'][role]=streams
    for item in all_messages.values():
        try: env=band_envelope(item.get('content',''),ids.values())
        except (ValueError,TypeError): continue
        if isinstance(env,dict) and env.get('case_id')==CASE and env.get('version')==1 and (env.get('request_key')==KEY or env.get('event')=='research'):
            audit['matching_research_messages'].append(item)
    audit['saved_band_receipts']=[r for r in calls if r['provider']=='band' and r['data'].get('case_id')==CASE]
    audit['unique_message_count']=len(all_messages)
    audit['outcome']='No research initiation found in complete history; absence does not prove the historical send never crossed the network.'
    if '--supersede' in sys.argv:
        assert not audit['matching_research_messages'], 'Receipt requires explicit reconciliation'
        with transaction() as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',(KEY,))
            current=c.execute('SELECT * FROM return_cases WHERE id=%s FOR UPDATE',(CASE,)).fetchone()
            original=c.execute('SELECT * FROM provider_calls WHERE request_key=%s FOR UPDATE',(KEY,)).fetchone()
            assert current==case and current['status']=='awaiting_approval'
            assert (current['data'].get('inspection_condition') or current['data']['reported_condition'])=='sealed'
            assert original['status'] in ('pending','superseded')
            if original['status']=='pending':
                data={**original['data'],'supersession':{'at':audit['checked_at'],'reason':'Repair research is irrelevant to this sealed item. No uncertain message resent. Historical send acknowledgement remains unproven.','original_status':original['status'],'original_data':original['data'],'room_id':audit['room_id'],'complete_history_roles':list(ROLES),'unique_message_count':len(all_messages),'matching_research_messages':0}}
                c.execute("UPDATE provider_calls SET status='superseded',data=%s WHERE request_key=%s",(Jsonb(data),KEY))
                job=c.execute("SELECT * FROM jobs WHERE case_id=%s AND version=1 AND type='research' FOR UPDATE",(CASE,)).fetchone()
                assert job['status']=='failed'
                data['supersession']['original_job']=json.loads(json.dumps(job,default=str))
                c.execute("UPDATE provider_calls SET data=%s WHERE request_key=%s",(Jsonb(data),KEY))
                c.execute("UPDATE jobs SET status='superseded',lease_until=NULL WHERE id=%s",(job['id'],))
                event(c,current,'research_superseded',{'message':data['supersession']['reason'],'request_key':KEY,'history_checked_at':audit['checked_at']},'system')
            after={t:digest(c.execute(f'SELECT * FROM {t} ORDER BY id').fetchall()) for t in protected}
            assert after==protected
            unchanged=c.execute('SELECT * FROM provider_calls WHERE request_key<>%s ORDER BY request_key',(KEY,)).fetchall()
            assert unchanged==[r for r in calls if r['request_key']!=KEY]
            audit['protected_after']=after
            audit['outcome']+=' Unused request and failed research job superseded; original evidence retained.'
    print(json.dumps(audit,default=str,indent=2))
asyncio.run(main())
