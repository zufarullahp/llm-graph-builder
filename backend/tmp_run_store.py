import os
from test_utils.fake_graph import FakeGraph
from src.proactive_actions import store_email_and_notify

os.environ['ENABLE_PROACTIVE_ACTIONS'] = '1'

g = FakeGraph()
# seed rule instances
g.rule_instances.append({
    'id': 'ri-old-1', 'rule_id': 'ask_email_if_missing', 'status': 'WAITING', 'asked_at_turn': 1, 'metadata': {}
})
g.rule_instances.append({
    'id': 'ri-old-2', 'rule_id': 'ask_email_if_missing', 'status': 'WAITING', 'asked_at_turn': 2, 'metadata': {}
})
g.rule_instances.append({
    'id': 'ri-primary', 'rule_id': 'ask_email_if_missing', 'status': 'WAITING', 'asked_at_turn': 3, 'metadata': {}
})

res = store_email_and_notify(g, 'sess-cleanup-1', {'email': 'user@example.com'}, {'id':'ri-primary','rule_id':'ask_email_if_missing','asked_at_turn':3})
print('result:', res)
print('rule instances after:')
for r in g.rule_instances:
    print(r)
