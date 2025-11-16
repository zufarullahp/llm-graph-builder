from test_utils.fake_graph import FakeGraph
from src.rule_instance import create_rule_instance

g = FakeGraph()
print('before:', g.rule_instances)
print('first id:', create_rule_instance(g, 's1', 'ask_email_if_missing', 1))
print('after first:', g.rule_instances)
print('second id:', create_rule_instance(g, 's1', 'ask_email_if_missing', 2))
print('after second:', g.rule_instances)
