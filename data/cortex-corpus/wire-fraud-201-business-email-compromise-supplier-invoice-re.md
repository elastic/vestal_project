**MERIDIAN TRUST BANK – FRAUD INVESTIGATION UNIT (FIU)**
**OFFICIAL CASE FILE**

**Date of Report:** October 24, 2023  
**Case Number:** FIU-2023-0892B  
**Lead Investigator:** Marcus Thorne, Senior Fraud Investigator (ID: 4402)  
**Co-Investigator:** Sarah Jenkins, Cyber Forensics Analyst (ID: 3199)  
**Subject:** Business Email Compromise (BEC) – Supplier Invoice Redirection  
**Victim Client:** Apex Industrial Solutions LLC  
**Client Account Number:** *******4491 (Commercial Checking)  
**Targeted Amount:** $184,550.00 USD  
**Fraudulent Beneficiary:** Global Horizon Exports LLC  
**Beneficiary Bank:** Crestview Financial, NA  

---

### **Incident Overview**

On October 18, 2023, Cortex Bank and Trust’s Fraud Investigation Unit (FIU) was alerted to a suspected Business Email Compromise (BEC) resulting in a misdirected wire transfer of $184,550.00 USD. The client, Apex Industrial Solutions LLC, initiated an outbound domestic wire on October 16, 2023, believing they were settling a routine supplier invoice from their long-term vendor, Tectonics Manufacturing Corp. 

The fraud was executed via a sophisticated invoice redirection scheme. Threat actors successfully spoofed the email domain of the supplier and contacted the victim’s Accounts Payable (AP) department. The perpetrators provided a fabricated "Notice of Banking Update" letter on forged company letterhead, instructing Apex Industrial Solutions to route all future payments to a new designated account held at Crestview Financial, NA. The client unknowingly updated the vendor payment template within the Cortex Bank and Trust Corporate Banking Portal and executed the payment. The discrepancy was discovered two days later when the legitimate vendor inquired about the overdue account balance.

---

### **Timeline of Events**

*All times listed in Eastern Standard Time (EST).*

*   **October 10, 2023 – 08:14 AM:** Threat actors register the look-alike domain `tectonlcs-mfg.com` (replacing the 'i' with an 'l'), intentionally designed to bypass casual visual inspection by the victim.
*   **October 12, 2023 – 09:32 AM:** Apex Industrial’s AP Manager receives an email from `accounts@tectonlcs-mfg.com`. The email contains a PDF attachment titled *“Tectonics_Banking_Update_Oct2023.pdf”* and an invoice for $184,550.00 for a recent shipment of industrial steel components.
*   **October 14, 2023 – 11:15 AM:** The AP Manager logs into the Cortex Bank and Trust Corporate Banking Portal. Without performing an out-of-band verbal verification with the vendor, the AP Manager updates the beneficiary routing and account numbers for Tectonics Manufacturing Corp in the vendor directory.
*   **October 16, 2023 – 02:45 PM:** The AP Manager initiates Wire Transfer #WT-8839210 for $184,550.00.
*   **October 16, 2023 – 03:10 PM:** Cortex Bank and Trust’s automated fraud detection systems flag the transaction for a routine velocity check. The wire is released at 03:15 PM after passing automated threshold rules, as the client frequently wires amounts exceeding $150,000.00.
*   **October 16, 2023 – 03:42 PM:** Funds are credited to the fraudulent beneficiary account at Crestview Financial.
*   **October 18, 2023 – 10:15 AM:** The legitimate Accounts Receivable department at Tectonics Manufacturing contacts Apex Industrial to inquire about the past-due invoice.
*   **October 18, 2023 – 10:45 AM:** Apex Industrial realizes the error and contacts Cortex Bank and Trust Customer Support. The case is immediately escalated to the FIU.

---

### **Investigation Steps**

**1. Wire Trace and Recall Initiation**
Immediately upon notification at 10:45 AM on October 18, Investigator Thorne issued a SWIFT MT192 message (Request for Cancellation) to Crestview Financial, NA, citing "Fraudulent Beneficiary/BEC" as the reason for the recall. Concurrently, a hold harmless indemnification agreement was transmitted to Crestview Financial to facilitate the freezing of the beneficiary account.

**2. Section 314(b) Information Sharing**
Under Section 314(b) of the USA PATRIOT Act, Cortex Bank and Trust initiated direct communication with Crestview Financial’s fraud department. Crestview confirmed that the receiving account, registered to "Global Horizon Exports LLC," was a newly established commercial account opened just three weeks prior by an individual utilizing a synthetic identity. 

**3. Transaction Flow Analysis**
Crestview Financial provided an analysis of the funds' movement post-deposit. Upon receiving the $184,550.00 on October 16, the threat actors waited twenty-four hours to ensure the funds cleared. On October 17 at 11:00 AM, a secondary outbound wire of $150,000.00 was executed from the Crestview account to an offshore cryptocurrency exchange based in the Seychelles. Crestview Financial successfully placed a hard freeze on the remaining ledger balance of $34,550.00.

**4. Digital Forensics and Security Review**
Analyst Sarah Jenkins reviewed the client’s login history and session logs for the Cortex Bank and Trust Corporate Banking Portal. IP telemetry confirmed that the login on October 14 and the wire initiation on October 16 originated from Apex Industrial’s authorized corporate IP address (192.144.xx.xx) in Chicago, Illinois. There was no evidence of a direct system breach or unauthorized access to the Cortex Bank and Trust infrastructure. The compromise was strictly external, relying entirely on social engineering.

**5. Email Header Analysis**
The client provided the original fraudulent email (.msg format) to the FIU. Forensic review of the email headers revealed:
*   **Return-Path:** `<accounts@tectonlcs-mfg.com>`
*   **Authentication-Results:** The email passed SPF and DKIM checks because the threat actors had properly configured DNS records for their newly registered, malicious domain. 
*   **Originating IP:** Traced to a commercial virtual private network (VPN) exit node located in Frankfurt, Germany.

---

### **Resolution**

**Financial Recovery:**
Due to the swift action of the Cortex Bank and Trust FIU and the cooperation of Crestview Financial, $34,550.00 of the original $184,550.00 was successfully frozen. On October 22, 2023, Crestview Financial repatriated the recovered funds to Cortex Bank and Trust. The $34,550.00 was credited back to Apex Industrial Solutions LLC's commercial checking account (*******4491) on October 23, 2023. 

The remaining $150,000.00 is deemed unrecoverable, as the funds were converted to cryptocurrency and moved outside of U.S. banking jurisdiction. Cortex Bank and Trust bears no financial liability for the loss, as the client authorized the transaction through securely authenticated channels, bypassing recommended out-of-band verification procedures.

**Regulatory and Law Enforcement Reporting:**
Investigator Thorne has filed a Suspicious Activity Report (SAR) with the Financial Crimes Enforcement Network (FinCEN), detailing the synthetic identity used at Crestview Financial and the offshore crypto exchange routing. Additionally, the FIU assisted Apex Industrial Solutions in filing a formal complaint with the FBI’s Internet Crime Complaint Center (IC3), reference number #I231018-0992-BEC.

**Client Remediation and Policy Update:**
A post-incident review meeting was held with the CFO of Apex Industrial Solutions on October 24, 2023. Cortex Bank and Trust has mandated the activation of Dual-Authorization protocols for all vendor template modifications and outgoing wire transfers on the client's account. Furthermore, the client has been provided with Cortex Bank and Trust’s "Corporate Fraud Prevention Playbook," highlighting the necessity of verifying all vendor payment changes via a known, trusted telephone number prior to systemic updates. 

**Case Status:** Closed. Pending any further inquiries from federal law enforcement.