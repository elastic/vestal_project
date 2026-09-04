**MERIDIAN TRUST BANK - GLOBAL FRAUD INVESTIGATION UNIT**
**CASE FILE:** FIR-2023-10-8842
**DATE OF REPORT:** November 2, 2023
**LEAD INVESTIGATOR:** Marcus Thorne, Senior Fraud Investigator (Badge #4199)
**SUBJECT:** Real Estate Wire Fraud - Closing Day Interception
**VICTIMS:** Eleanor and Thomas Vance (Cortex Bank and Trust Account ending in -4402)
**TOTAL EXPOSURE:** $142,500.00 USD

---

### INCIDENT OVERVIEW

On October 25, 2023, Cortex Bank and Trust’s Fraud Escalation Desk received an urgent claim from account holders Eleanor and Thomas Vance regarding a suspected fraudulent wire transfer. On October 24, 2023, the Vances authorized an outgoing domestic wire transfer in the amount of $142,500.00, intended for Horizon Title & Escrow to cover the closing costs and down payment on a residential property located at 4022 Sycamore Drive, Austin, TX. 

The investigation revealed that the Vances were victims of a sophisticated Business Email Compromise (BEC) scheme. Threat actors intercepted unencrypted communications between the clients and their legitimate title agent, subsequently utilizing a lookalike domain to send fraudulent wiring instructions. Cortex Bank and Trust processed the authorized wire in good faith, transferring the funds to an account at Apex Financial Corporation controlled by the threat actors. The fraud was only identified at the physical closing table the following day when the genuine Horizon Title & Escrow reported that the funds had never been received.

### TIMELINE

**October 14, 2023:** 
Eleanor Vance and Horizon Title & Escrow agent Sarah Jenkins initiate an email thread regarding the upcoming closing. The legitimate domain used by the title company is `@horizontitle.com`.

**October 21, 2023 (Estimated):** 
Threat actors compromise the email server of a third-party real estate broker involved in the transaction, gaining read-access to the closing schedule and financial details.

**October 23, 2023 - 14:12 EST:** 
The threat actors register a spoofed domain: `@horizontitle-escrow.com`.

**October 23, 2023 - 15:45 EST:** 
Eleanor Vance receives an email from `sarah.jenkins@horizontitle-escrow.com`. The email contains a counterfeit PDF on Horizon Title letterhead, citing "unexpected audit maintenance on our primary escrow account." The document provides new wiring instructions directing funds to an account at Apex Financial Corporation.

**October 24, 2023 - 09:15 EST:** 
Eleanor Vance visits Cortex Bank and Trust Branch #104 in Westlake to authorize the wire transfer. 

**October 24, 2023 - 09:32 EST:** 
Cortex Bank and Trust Branch Manager David Raskin processes the wire request. Standard Customer Identification Program (CIP) protocols are followed. The customer signs the standard Wire Transfer Authorization form, which includes a real estate fraud warning. The wire of $142,500.00 is executed to Apex Financial Routing #122000496, Account #9983441209, under the beneficiary name "Global Ventures Holdings LLC."

**October 25, 2023 - 13:00 EST:** 
The Vances arrive at Horizon Title & Escrow for the property closing. Title agent Sarah Jenkins informs them that the escrow account has not been funded.

**October 25, 2023 - 13:45 EST:** 
The Vances contact Cortex Bank and Trust Customer Service. The call is immediately routed to the Fraud Escalation Desk. Case #FIR-2023-10-8842 is opened.

### INVESTIGATION STEPS

**1. Immediate Containment and Recovery Efforts**
Upon notification, Cortex Bank and Trust’s Wire Operations department immediately initiated a SWIFT recall and dispatched a formal hold harmless/indemnification request to Apex Financial’s fraud department via the Financial Crimes Enforcement Network (FinCEN) secure portal. The request cited suspected BEC and demanded an immediate freeze on Account #9983441209.

**2. Internal Process Review**
Investigators reviewed the actions of Cortex Bank and Trust personnel to ensure compliance with internal security policies. Branch Manager David Raskin verified Mrs. Vance’s identity using her Texas Driver’s License and Cortex debit card PIN authentication. CCTV footage from October 24 confirms Mrs. Vance was present and acting without physical duress. Furthermore, the electronic signature log confirms Mrs. Vance acknowledged the digital "Real Estate Wire Fraud Alert" prompt on the branch tablet before the transfer was finalized. Cortex Bank and Trust staff executed the transaction precisely as directed by the fully authenticated account holder.

**3. Beneficiary Account Tracing**
On October 26, 2023, Apex Financial responded to the indemnification request. Apex reported that the receiving account was a newly established commercial checking account opened by a synthetic identity using fraudulent Delaware LLC registration documents. Apex Financial ledger analysis showed that upon receipt of the $142,500.00 from Cortex Bank and Trust, the threat actors immediately executed three sequential outbound transfers:
*   $45,000.00 to a cryptocurrency exchange (Binance)
*   $65,000.00 via international wire to a financial institution in Hong Kong
*   $32,500.00 remained in the account, pending a scheduled ACH withdrawal.

Apex Financial successfully froze the remaining $32,500.00. The outbound transfers were deemed unrecoverable.

**4. Cyber Forensics**
With the Vances' consent, Cortex Bank and Trust’s cybersecurity unit analyzed the email headers of the fraudulent instructions. The analysis confirmed the Sender Policy Framework (SPF) and DomainKeys Identified Mail (DKIM) failed to match the genuine title company. The originating IP address (197.210.64.12) was traced to a data center in Lagos, Nigeria, utilizing a virtual private network (VPN) masking node in Frankfurt, Germany.

### RESOLUTION

Based on the investigative findings, the incident is definitively categorized as Authorized Push Payment (APP) fraud facilitated by third-party Business Email Compromise. Because the threat actors breached external communication channels (the real estate broker/title network) rather than Cortex Bank and Trust’s secure infrastructure, and because the client explicitly authorized the transaction after bypassing standard fraud warnings, Cortex Bank and Trust holds no financial liability for the loss under the Uniform Commercial Code (UCC) Article 4A. 

However, in the interest of customer advocacy, Cortex Bank and Trust facilitated the following remediation steps:

1.  **Fund Recovery:** Cortex Bank and Trust successfully coordinated with Apex Financial to repatriate the frozen $32,500.00. These funds were credited back to the Vances’ account ending in -4402 on October 30, 2023. The remaining $110,000.00 is classified as an unrecoverable loss.
2.  **Law Enforcement Referral:** Cortex Bank and Trust filed Suspicious Activity Report (SAR) #33994821 with FinCEN, detailing the beneficiary account information, synthetic LLC data, and Nigerian IP addresses. A full evidentiary packet was forwarded to the FBI’s Internet Crime Complaint Center (IC3). 
3.  **Policy Recommendations:** Following this incident, Cortex Bank and Trust's Risk Management Committee has initiated a protocol update requiring branch managers to verbally ask all customers executing wires over $50,000 to real estate title companies to verbally confirm the recipient instructions via a known phone number, independent of email correspondence.

This investigation is now concluded and the case file is marked closed, pending any subpoenas or informational requests from federal law enforcement.