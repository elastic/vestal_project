# Cortex intake: who needs which identifier

`cortex-intake` holds the complaints and disputes customers send through Cortex's web intake form. Each
record carries the customer's TIN (`customer_tin`) and account number (`account_number`) in their own
fields, and the customer's own words in `message`. Some customers type their TIN or an account number into
the message box as well.

Cortex's data protection policy for intake:

- **Identity theft reports.** Records filed through the form's identity theft page (`channel`
  `identity_theft_form`) are for investigators alone. First-line analysts must never see one of those records.
- **First-line analysts** (`cortex-analyst-l1`) handle every other intake record in full, the TIN on file
  included: they verify callers with it.
- **Investigators** (`cortex-investigator`) compare the identifiers a customer typed into the message with
  what is on file, character for character, because a mistyped digit is often the first sign of an impostor.
  The message must reach them exactly as the customer typed it.
- **Tina** flags intake where the TIN a customer typed does not match the TIN on file. For that she needs
  both in full.
