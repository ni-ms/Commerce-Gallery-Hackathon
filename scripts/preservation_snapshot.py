import json,hashlib
from app.db import transaction
TABLES=('return_cases','shipments','route_proposals','provider_calls','agent_sessions','tool_results','reservations','destinations','quotes','products','locations','merchants','policy_passages','buyer_orders')
with transaction() as c:
 result={t:c.execute(f'SELECT * FROM {t}').fetchall() for t in TABLES}
print(json.dumps(result,default=str,sort_keys=True,indent=2))
