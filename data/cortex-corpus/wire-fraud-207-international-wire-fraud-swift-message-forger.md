**MERIDIAN TRUST BANK**
**GLOBAL FRAUD INVESTIGATION UNIT (GFIU)**
**CASE FILE CONFIDENTIAL - INTERNAL USE ONLY**

**Case Number:** FIU-2023-0892A
**Date of Report:** November 14, 2023
**Lead Investigator:** Sarah Jenkins, Senior Fraud Investigator (ID: SJ-4429)
**Co-Investigator:** Marcus Thorne, Cyber Forensics Analyst
**Subject:** International Wire Fraud - SWIFT Message Forgery 
**Client Name:** Apex Global Logistics Inc.
**Account Compromised:** Corporate Checking #8840-2931-102

---

### INCIDENT OVERVIEW

On October 25, 2023, Cortex Bank and Trust’s Global Fraud Investigation Unit (GFIU) initiated an inquiry into a suspected unauthorized outbound international wire transfer totaling $1,450,000.00 USD. The funds were debited from the corporate operating account of Apex Global Logistics Inc. (Account #8840-2931-102) and credited to a foreign entity, Horizon Trading Ltd., via the SWIFT network. 

The client reported the discrepancy after their legitimate vendor, based in Rotterdam, claimed non-receipt of an expected quarterly payment. Preliminary analysis of Cortex Bank and Trust’s transmission logs indicated that the wire was initiated not through standard client-facing web portals, but via a highly sophisticated forgery of a SWIFT MT103 Single Customer Credit Transfer message. Threat actors bypassed Apex Global Logistics’ internal enterprise resource planning (ERP) software and directly injected a manipulated payload into Cortex Bank and Trust’s automated B2B API gateway. 

### TIMELINE OF EVENTS

*(All times are recorded in Coordinated Universal Time - UTC)*

*   **October 10, 2023 - 08:14 UTC:** Apex Global Logistics’ internal network is compromised via a targeted spear-phishing campaign. Threat actors gain persistent access to the Chief Financial Officer’s workstation, specifically targeting the API keys used for automated batch wire processing with Cortex Bank and Trust.
*   **October 22, 2023 - 23:45 UTC:** Threat actors utilize stolen API keys to initiate an authenticated session with Cortex Bank and Trust’s B2B gateway. 
*   **October 23, 2023 - 02:12 UTC:** The fraudulent SWIFT MT103 message is injected into the Cortex processing queue. 
    *   **Sender:** Cortex Bank and Trust (BIC: MERTUS33)
    *   **Receiver:** Bank of East Asia, Hong Kong (BIC: BEASHKHH)
    *   **UETR:** 8f93b2a1-7c4d-4e9f-a1b2-3c4d5e6f7a8b
    *   **Amount:** $1,450,000.00 USD
*   **October 23, 2023 - 02:15 UTC:** Automated systemic checks at Cortex Bank and Trust fail to flag the transaction, as the forged message perfectly replicates the cryptographic signature and format of Apex Global Logistics’ routine European vendor payments. 
*   **October 23, 2023 - 09:30 UTC:** Funds are successfully routed through the intermediary correspondent bank (Standard Chartered NY) and credited to Horizon Trading Ltd. (Account #015-849201-884) at the Bank of East Asia.
*   **October 25, 2023 - 14:20 UTC:** Apex Global Logistics contacts Cortex Bank and Trust Treasury Services to report the missing vendor payment.
*   **October 25, 2023 - 15:05 UTC:** Cortex Bank and Trust GFIU places a hard freeze on the Apex account and issues a formal SWIFT MT192 (Request for Cancellation) to the beneficiary bank in Hong Kong.

### INVESTIGATION STEPS

**1. Forensics and Log Analysis:**
Cyber Forensics Analyst Marcus Thorne isolated the API transaction logs from October 22 and October 23. The investigation revealed that the threat actors did not simply alter a destination account in the client's UI. Instead, they intercepted a legitimate, pre-scheduled MT103 payment file destined for the Rotterdam vendor. Using the compromised API keys, the actors modified specific data fields within the SWIFT payload before it hit the Cortex Bank and Trust firewall:
*   *Field 59 (Beneficiary Customer):* Altered from "Rotterdam Maritime Supply" to "Horizon Trading Ltd."
*   *Field 57A (Account With Institution):* Altered to route to the Hong Kong BIC.
The cryptographic hash was recalculated by the malware residing on the client’s server, allowing the forged message to pass Cortex’s automated integrity checks seamlessly.

**2. IP Address Tracing:**
Session logs tied to the API injection point indicated the traffic originated from an IP address (185.144.xxx.xxx) associated with a known commercial VPN exit node located in Frankfurt, Germany. However, deep packet inspection of the disrupted handshake protocols revealed true origin IP leakage pointing to an ISP in St. Petersburg, Russia.

**3. Interbank Coordination and Funds Tracing:**
GFIU initiated emergency communications with the Bank of East Asia’s fraud department via the SWIFT secure channel. Bank of East Asia confirmed receipt of the MT192 cancellation request but reported that rapid structuring and layering had already occurred. 
Upon crediting Horizon Trading Ltd., the $1,450,000.00 USD was immediately fragmented:
*   $800,000.00 USD was wired to a secondary corporate account in Singapore (Oversea-Chinese Banking Corporation).
*   $300,000.00 USD was transferred to a cryptocurrency exchange registered in the Seychelles.
*   $350,000.00 USD remained in the Hong Kong account and was successfully frozen by local authorities upon our request.

**4. Vulnerability Assessment:**
Cortex Bank and Trust’s internal API architecture was audited. It was determined that while the API functioned as designed by verifying the API key and cryptographic signature, it lacked "out-of-band" behavioral logic checks for sudden geographic routing changes (e.g., a routine European payment being rerouted to Asia) for amounts exceeding $1,000,000.

### RESOLUTION

**Recovery Status:**
Of the initial $1,450,000.00 USD stolen, Cortex Bank and Trust, in cooperation with the Bank of East Asia, successfully recovered and repatriated $350,000.00 USD on November 10, 2023. These funds have been credited back to Apex Global Logistics Account #8840-2931-102. The remaining $1,100,000.00 USD is currently deemed unrecoverable, having been fully laundered through decentralized cryptocurrency mixers and untraceable offshore accounts.

**Liability and Restitution:**
Following a joint review by Cortex Bank and Trust’s Legal and Compliance departments, it was determined that the primary point of compromise occurred on the client’s internal network. However, acknowledging the absence of dynamic anomaly detection on the bank's B2B API gateway, a confidential shared-loss settlement is currently being negotiated between Cortex Bank and Trust and Apex Global Logistics. 

**Regulatory and Law Enforcement Action:**
In compliance with the Bank Secrecy Act (BSA), a Suspicious Activity Report (SAR) (Tracking ID: FinCEN-2023-884920) has been filed detailing the SWIFT message forgery, the compromised API credentials, and the identified threat actor infrastructure. The complete forensic file has been handed over to the Federal Bureau of Investigation’s Internet Crime Complaint Center (IC3) and the US Secret Service Cyber Fraud Task Force.

**Internal Corrective Measures:**
Effective November 1, 2023, Cortex Bank and Trust has implemented a mandatory patch to the B2B API gateway. All corporate clients utilizing automated batch SWIFT processing are now subject to "Velocity and Destination" algorithmic screening. Any alteration to Field 59 (Beneficiary) that deviates from a client's 12-month historical payment pattern will trigger an automatic quarantine of the payload, requiring manual out-of-band voice verification via an authorized corporate signatory before release. 

**Case Status:** CLOSED pending law enforcement subpoena.