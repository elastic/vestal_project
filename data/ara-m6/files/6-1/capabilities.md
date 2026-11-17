# Capability card

The closed list of capabilities Tina might lack. Three can be built here; the other two are named only.

## `account_history_window`
- Tool id: `cortex.account_history`
- Parameters: `account_id` (string), `start_days_ago` (integer), `end_days_ago` (integer)
- Reads the index: `cortex-wire-transfers`
- Key column: `event_id`
- Returns every event of one account from end_days_ago to start_days_ago whole days back.

## `counterparty_lookup`
- Tool id: `cortex.counterparty_lookup`
- Parameters: `counterparty_bank` (string)
- Reads the index: `cortex-wire-transfers`
- Key column: `account_id`
- Returns every account that sent or received a wire with that bank.

## `policy_exception_by_date`
- Tool id: `cortex.policy_exceptions`
- Parameters: `on_date` (string)
- Reads the index: `cortex-policy-exceptions`
- Key column: `exception_id`
- Returns every policy exception in force on that date (YYYY-MM-DD).

## Named only
- `sanctions_screening`
- `out_of_scope_correctly_escalated`
