**CASE FILE: Cortex Bank and Trust Corporate Security Division**

**Case Number:** MTB-WF-2026-0803A
**Investigator:** Lead Fraud Analyst Elena Rostova, Badge #8442
**Date of Report:** August 3, 2026
**Client/Victim:** Horizon Tech Solutions (Cortex Bank and Trust Commercial Account Holder)
**Incident Type:** Business Email Compromise (BEC) / Executive Impersonation Wire Fraud

**1. Incident Overview**
On July 29, 2026, Cortex Bank and Trust’s Fraud Investigations Unit was contacted by the Chief Financial Officer (CFO) of Horizon Tech Solutions, a commercial banking client, regarding a suspected fraudulent wire transfer. The transfer, totaling $1,850,000.00 USD, was executed on July 28, 2026, under the guise of funding a highly confidential overseas corporate acquisition.

Preliminary analysis confirmed that this incident was a classic Business Email Compromise (BEC) orchestrated through executive impersonation. Threat actors utilized a carefully constructed lookalike domain to impersonate Horizon Tech’s Chief Executive Officer (CEO), David Aris. The fraudulent emails explicitly instructed the CFO, Sarah Jenkins, to bypass standard procurement protocols to ensure the absolute secrecy of the fictitious acquisition. Because the transaction was authenticated by an authorized user using valid credentials and multi-factor authentication (MFA) via Cortex Bank and Trust’s commercial banking portal, the transfer initially bypassed automated behavioral fraud filters.

**2. Timeline of Events (All times in EST)**
*   **July 27, 2026, 14:32:** The threat actor registers a typosquatted domain, `horizon-techsolutlons.com` (replacing the ‘i’ with an ‘l’), through an offshore registrar.
*   **July 28, 2026, 08:14:** CFO Sarah Jenkins receives an email purporting to be from CEO David Aris. The email states he is in restricted-access negotiations in London and requires an expedited wire transfer for a foreign acquisition. The tone is urgent, demanding absolute confidentiality and speed.
*   **July 28, 2026, 09:45:** Jenkins replies to the spoofed email, requesting the beneficiary routing details.
*   **July 28, 2026, 10:12:** The attacker provides SWIFT wire instructions for a corporate shell account held at Vantage Orient Bank in Hong Kong.
*   **July 28, 2026, 11:30:** Jenkins logs into the Cortex Bank and Trust commercial portal. She initiates an international SWIFT transfer of $1,850,000.00 USD to the provided beneficiary.
*   **July 28, 2026, 11:35:** Cortex Bank and Trust’s transaction monitoring system flags the unusual offshore destination. An automated SMS verification prompt is sent to Jenkins’ registered mobile device.
*   **July 28, 2026, 11:38:** Jenkins inputs the SMS One-Time Password (OTP). The funds are successfully debited from Horizon Tech’s operating account and released to the SWIFT network.
*   **July 29, 2026, 09:00:** The legitimate CEO, David Aris, returns to the corporate office.
*   **July 29, 2026, 11:15:** During a routine financial briefing, Jenkins asks for the countersigned acquisition paperwork. Aris confirms he has no knowledge of the transaction or any ongoing London negotiations.
*   **July 29, 2026, 11:30:** Horizon Tech contacts Cortex Bank and Trust’s corporate fraud hotline. Escalation to the internal Fraud Investigations Unit begins immediately.

**3. Investigation**
Upon assignment to the case, Cortex Bank and Trust investigators immediately initiated trace and freeze protocols. The first priority was mapping the technical execution of the fraud to confirm the integrity of the bank’s internal systems. Forensic review of the session logs for the Cortex Bank and Trust web portal confirmed that the CFO’s session originated from a known, whitelisted corporate IP address (198.51.100.42) with no signs of session hijacking or malware interference. The authorization was cryptographically sound; the vulnerability was entirely based on human social engineering.

Analysis of the email headers provided by Horizon Tech’s IT department revealed the meticulous nature of the attack. The "Reply-To" address in the initial email was hardcoded to route responses to the spoofed domain `horizon-techsolutlons.com`. Furthermore, the attackers demonstrated significant prior knowledge of the company’s internal hierarchy, executive travel schedule, and communication style. This indicated a likely preceding reconnaissance phase, potentially involving a compromised third-party vendor or a previous low-level phishing intrusion that granted them read-only access to corporate communications.

Financial tracing of the $1.85 million USD revealed that the funds were routed through a US-based correspondent bank before landing at Vantage Orient Bank in Hong Kong. Using secure inter-bank channels, Cortex Bank and Trust issued a highly urgent SWIFT MT192 message (Request for Cancellation) to the beneficiary institution, citing suspected international wire fraud. Concurrently, our compliance team filed a Suspicious Activity Report (SAR) with the Financial Crimes Enforcement Network (FinCEN) and engaged the FBI’s Internet Crime Complaint Center (IC3), successfully activating the Financial Fraud Kill Chain (FFKC) protocol.

**4. Resolution**
Due to the rapid reporting by the client—within 24 hours of the fraudulent execution—the Financial Fraud Kill Chain proved partially successful. Vantage Orient Bank acknowledged the MT192 request on July 30, 2026. They reported that $1,150,000.00 USD remained frozen in the beneficiary account. Unfortunately, the remaining $700,000.00 USD had already been rapidly dispersed into multiple localized cryptocurrency exchanges and secondary shell company accounts, moving them beyond immediate traditional banking recovery jurisdiction.

Cortex Bank and Trust’s legal and wire compliance departments are currently facilitating the international hold-harmless and indemnification process to repatriate the frozen $1,150,000.00 USD back to Horizon Tech Solutions. This process is expected to take between 30 to 60 business days, pending Hong Kong regulatory clearances.

To prevent future occurrences, Cortex Bank and Trust’s risk advisory team has enforced several mandatory security updates for Horizon Tech’s commercial profile. First, Dual Control (Maker/Checker) authorization has been rigidly enforced for all outward wire transfers exceeding $10,000 USD, requiring a secondary authorized executive to approve the transaction from a separate session. Second, mandatory out-of-band verbal verification protocols have been established for any transfer to a new beneficiary, regardless of internal executive email mandates. Finally, we have supplied Horizon Tech with comprehensive BEC awareness training materials for all finance personnel, focusing on identifying typosquatted domains and safely handling out-of-process executive directives. Case remains open strictly pending final fund repatriation.