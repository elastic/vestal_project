# Cortex intake: who needs which identifier

`cortex-intake` holds the complaints and disputes customers send through Cortex's web intake form. Each
record carries the customer's TIN (`customer_tin`) and account number (`account_number`) in their own
fields, and the customer's own words in `message`. Some customers type their TIN or an account number into
the message box as well.

Cortex's data protection policy for intake:

- **Typed identifiers.** Nobody at Cortex works from what a customer types into the message box: the TIN and
  account number on file are in their own fields.
- **First-line analysts** (`cortex-analyst-l1`) read and answer every intake record, and verify a caller's
  identity against the TIN on file. They see every field of every intake record.
- **Investigators** (`cortex-investigator`) see every field of every intake record.
- **Tina** finds intake by account number and summarises what the customer reported. She never uses a TIN,
  in full or in part.
