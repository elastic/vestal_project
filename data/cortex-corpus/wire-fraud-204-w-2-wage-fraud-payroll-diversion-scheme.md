**CONFIDENTIAL - INTERNAL INVESTIGATION MEMORANDUM**

**Institution:** Cortex Bank and Trust  
**Department:** Fraud Investigations Unit (FIU)  
**Case Number:** FRA-2023-0941-W2  
**Date of Report:** October 24, 2023  
**Lead Investigator:** Marcus Sterling, Senior Fraud Investigator (Badge #4492)  
**Subject:** W-2 Wage Fraud - Payroll Diversion Scheme  
**Victim Entity:** Apex Industrial Solutions LLC (MTB Commercial Account ending in -4491)  

---

### Incident Overview

On October 16, 2023, Cortex Bank and Trust (MTB) initiated a formal investigation following an urgent fraud claim filed by our commercial client, Apex Industrial Solutions. The client reported that their semi-monthly payroll had been compromised via a W-2 Wage Fraud and Payroll Diversion Scheme. 

The total compromised amount was $142,850.00, affecting twelve senior executive employees. The investigation revealed that unknown threat actors executed a sophisticated Business Email Compromise (BEC) attack against the Apex Human Resources department. By compromising the email account of the HR Director, the attackers successfully submitted fraudulent direct deposit update forms to the internal payroll processing team. Consequently, Cortex Bank and Trust processed a legitimate ACH batch file containing the altered destination accounts, inadvertently funneling the executives' wages into three fraudulent accounts controlled by the syndicate. 

### Timeline

*All times listed in Eastern Standard Time (EST).*

**October 5, 2023**
*   **09:14 AM:** Sarah Jenkins, HR Director at Apex Industrial Solutions, receives a targeted phishing email appearing to be from the company's IT Helpdesk regarding a mandatory Office 365 password expiration.
*   **09:42 AM:** Jenkins clicks the embedded link and inputs her corporate credentials into a spoofed Microsoft login portal.

**October 9, 2023**
*   **02:11 AM:** Unauthorized login to Jenkins' email account originates from IP Address 185.12.89.44 (identified as a commercial VPN node located in Frankfurt, Germany).
*   **02:15 AM:** Threat actor establishes malicious inbox routing rules: `If Subject contains "payroll", "ACH", "direct deposit", or "W-2" -> Mark as Read -> Move to Archive folder`.

**October 11, 2023**
*   **10:33 AM:** Threat actor, acting as Jenkins, emails David Cho, Apex Payroll Administrator. The email requests immediate direct deposit account updates for twelve executives, citing a "recent executive banking transition."
*   **10:35 AM:** Attached to the email is a consolidated PDF containing twelve forged voided checks matching the names of the targeted executives. 
*   **02:45 PM:** Cho processes the account updates in the Apex ADP portal without initiating out-of-band verification.

**October 15, 2023**
*   **12:01 AM:** Normal payroll cycle executes. Cortex Bank and Trust receives and processes the authorized ACH batch file (Batch ID: ACH-99281-MTB). Funds are successfully dispatched to the clearinghouse.

**October 16, 2023**
*   **08:30 AM:** Multiple Apex executives report non-receipt of their scheduled payroll.
*   **09:15 AM:** Apex Industrial Solutions contacts the Cortex Bank and Trust Commercial Support Desk. 
*   **09:45 AM:** MTB FIU formally opens Case FRA-2023-0941-W2. Hold Harmless and Letter of Indemnity (LOI) protocols are initiated.

### Investigation Steps

**1. Transaction Analysis and Tracing**
Upon receiving the fraud notification, MTB's Fraud Unit immediately analyzed ACH Batch ID ACH-99281-MTB. The $142,850.00 in stolen wages was traced to three distinct receiving depository financial institutions (RDFIs):

*   **Account A (Nexus Credit Union):** Routing #25607xxxx, Account ending -8831. Received $65,000.00 (representing wages of 5 executives).
*   **Account B (Horizon Digital Bank):** Routing #12104xxxx, Account ending -0992. Received $48,350.00 (representing wages of 4 executives).
*   **Account C (Vanguard Fidelity Trust):** Routing #06310xxxx, Account ending -1124. Received $29,500.00 (representing wages of 3 executives).

**2. Bank-to-Bank Communications**
At 10:15 AM on October 16, MTB transmitted urgent SWIFT/FedLine messages accompanied by formal Letters of Indemnity to the three receiving institutions, requesting immediate account freezes and the reversal of the fraudulent ACH credits under NACHA rules.

**3. Asset Recovery Assessment**
*   *Nexus Credit Union:* Responded on October 17. The suspect account was frozen with a remaining balance of $12,000.00. Forensics showed $53,000.00 had already been transferred out via wire transfer (Wire ID: 8839-BIN) to a cryptocurrency exchange (Binance) to purchase USDT (Tether), placing those funds beyond standard banking recovery mechanisms.
*   *Horizon Digital Bank:* Responded on October 17. The MTB LOI arrived before the fraudsters could initiate outgoing transfers. The account was frozen with the full $48,350.00 intact. Horizon confirmed the account was opened online five days prior using a synthetic identity utilizing a stolen Social Security Number.
*   *Vanguard Fidelity Trust:* Responded on October 18. The account was frozen with a balance of $5,000.00. The missing $24,500.00 had been systematically withdrawn via coordinated ATM cash-outs in the metropolitan Atlanta, GA area between October 15 and October 16.

**4. Client Systems Forensics**
In cooperation with Apex's retained third-party cybersecurity firm, MTB investigators confirmed the vector of compromise. System logs verified the unauthorized access via the German VPN IP address and documented the creation of the malicious forwarding rules that prevented the actual HR Director from seeing the payroll administrator's confirmation emails.

### Resolution

**Funds Disposition**
Through rapid inter-bank communication, Cortex Bank and Trust successfully recovered a total of $65,350.00. These funds were credited back to the Apex Industrial Solutions operating account (-4491) on October 20, 2023. The remaining $77,500.00 is deemed a non-recoverable loss. Under the Uniform Commercial Code (UCC) and the terms of the MTB Commercial Treasury Agreement, Cortex Bank and Trust holds no liability for the unrecovered funds, as the ACH batch file was properly authenticated and authorized by the client's internal systems prior to transmission to the bank. 

**Regulatory and Law Enforcement Referrals**
A Suspicious Activity Report (SAR) has been filed with the Financial Crimes Enforcement Network (FinCEN) regarding the receiving accounts and the synthetic identity data (Filing ID: 3991-0029-A). Furthermore, a comprehensive dossier has been forwarded to the FBI's Internet Crime Complaint Center (IC3) to assist in broader BEC syndicate tracking.

**Security Recommendations and Remediation**
To prevent recurrence, Cortex Bank and Trust has mandated the following operational changes for Apex Industrial Solutions:
1.  **Implementation of ACH Positive Pay:** Apex is now enrolled in MTB's ACH Filter and Positive Pay services to flag anomalous outbound payroll batches.
2.  **Out-of-Band Authentication:** MTB Treasury Management has advised Apex to institute a mandatory voice-verification policy for any changes to employee W-2 or direct deposit information. 
3.  **Enhanced Access Controls:** Apex IT has implemented conditional access policies, geo-blocking logins from outside North America, and enforced hardware-key Multi-Factor Authentication (MFA) for all administrative and HR personnel.

This case is closed pending any further subpoenas or inquiries from federal law enforcement.