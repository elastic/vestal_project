---
name: regulatory-citation
description: Use when an analyst asks which law, statute or US Code section governs a pattern found on a Cortex account. Reads the governing statute from the pinned DOJ Criminal Resource Manual page through the cortex.read_page tool and cites it in Cortex house format.
---

# Regulatory citation

Cortex Bank and Trust is a fictional bank. Its compliance desk cites a statute only from the pinned source page, never from memory, so every citation can be checked against the text it came from.

The pinned source page (DOJ Criminal Resource Manual, sections 2033 and 2101):

https://raw.githubusercontent.com/elastic/vestal_project/4caa7d19ff9c1682a8b7ca6dd44229b7cb6548b3/ara-m4-pages/doj-crm-structuring-laundering.md

Steps:

1. Establish the pattern on the account with the Cortex detection tools first (for cash deposits kept just under 10,000 dollars, `cortex.structuring_deposits`). Do not guess the pattern.
2. Read the pinned page with the `cortex.read_page` tool, with `url` set to the pinned page URL above. Read it every time, even when you think you know the statute.
3. If the tool's result shows that the read failed (a failed workflow run, an error such as a 401 or a 429, or no page text), stop and report the error as it was returned. Do not cite anything.
4. Find the section of the page that describes the pattern and the US Code section it names.
5. Cite it in Cortex house format, on its own line:

   `[<US Code section> | DOJ CRM <manual section number> | <pinned page URL>]`

   Example: `[31 U.S.C. 5324 | DOJ CRM 2033 | https://raw.githubusercontent.com/...]`

6. Quote the one sentence from the page that supports the citation.
