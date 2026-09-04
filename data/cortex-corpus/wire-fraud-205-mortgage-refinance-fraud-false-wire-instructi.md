**MERIDIAN TRUST BANK – FRAUD INVESTIGATION UNIT**
**CASE FILE REPORT**

**CASE NUMBER:** FIU-2023-09-1442
**DATE OF REPORT:** October 12, 2023
**INVESTIGATOR:** Lead Investigator Marcus Vance, CFE (ID #8832)
**SUBJECT:** Mortgage Refinance Fraud - False Wire Instructions
**COMPLAINANTS/CLIENTS:** Thomas and Sarah Jenkins
**MERIDIAN TRUST ACCOUNT:** Checking ending in -4921
**FUNDS AT RISK:** $184,500.00 USD

---

### **1. INCIDENT OVERVIEW**

On September 29, 2023, Cortex Bank and Trust’s Fraud Investigation Unit (FIU) was alerted to a high-dollar wire fraud incident involving retail banking clients Thomas and Sarah Jenkins. The clients reported that a domestic wire transfer in the amount of $184,500.00, initiated on September 28, 2023, was fraudulently redirected to an unauthorized third party. 

The transaction was intended to satisfy the closing costs and principal paydown for a mortgage refinance on the clients’ primary residence, facilitated by Sunrise Title & Escrow. The investigation determined that the clients fell victim to a Business Email Compromise (BEC) scheme. A malicious actor successfully intercepted the communication channel between the clients and the title company, providing spoofed wire instructions that diverted the funds to a mule account held at Apex Financial institution. Cortex Bank and Trust immediately initiated recall protocols and launched a formal investigation to trace the funds, assess liability, and attempt recovery.

### **2. TIMELINE OF EVENTS**

*(All times listed in Eastern Standard Time - EST)*

*   **September 15, 2023:** Thomas and Sarah Jenkins receive conditional approval for a mortgage refinance and begin communications with Sunrise Title & Escrow via the email address `closing@sunrisetitle.com`.
*   **September 27, 2023, 04:12 PM:** The clients receive an email containing a PDF attachment titled "FINAL_Closing_Disclosures_Wire_Instructions.pdf". The email appears to be from their escrow agent, Emily Vargas, but forensic analysis later reveals the sender address was the lookalike domain `closing@sunrisetltle.com` (using an 'l' instead of an 'i').
*   **September 28, 2023, 10:15 AM:** Thomas Jenkins visits the Cortex Bank and Trust branch in Westlake, presenting the printed PDF wire instructions. 
*   **September 28, 2023, 10:30 AM:** Cortex Bank and Trust Branch Manager, David Cho, verifies the client’s identity, processes the wire request for $184,500.00, and obtains the required physical signatures. The destination account is listed as Apex Financial, Account ending in -8839, Beneficiary: "Sunrise Title Escrow LLC".
*   **September 28, 2023, 11:45 AM:** The wire is released via Fedwire (IMAD: 0928B1B48291A019).
*   **September 29, 2023, 09:30 AM:** The legitimate Sunrise Title & Escrow contacts the clients to inquire about the missing closing funds.
*   **September 29, 2023, 09:45 AM:** The clients realize they have been defrauded and immediately contact Cortex Bank and Trust Customer Support.
*   **September 29, 2023, 10:10 AM:** Cortex Bank and Trust FIU places an internal freeze on the clients' profile, opens Case FIU-2023-09-1442, and transmits an urgent Fedwire recall message to Apex Financial.

### **3. INVESTIGATION STEPS**

**A. Inter-Bank Communication and Tracing**
Upon escalation, the undersigned investigator immediately transmitted a SWIFT/Fedwire fraud notification to the fraud department at Apex Financial. The notification cited the Fedwire IMAD (0928B1B48291A019) and requested an immediate freeze on the receiving account (ending in -8839) under the safe harbor provisions of the USA PATRIOT Act Section 314(b). 

On October 2, 2023, Apex Financial responded to the 314(b) inquiry. They confirmed that the receiving account did not belong to a title company, but rather to a newly formed entity named "Global Logistics Holdings LLC," opened strictly as a business checking account just 22 days prior to the wire deposit. This fits the established typology of a temporary mule account utilized specifically for real estate wire fraud. 

**B. Email Forensics and Client Interview**
The undersigned investigator conducted a recorded telephone interview with Thomas Jenkins on October 2, 2023. Mr. Jenkins forwarded the original emails received from the suspected fraudster. Analysis of the email headers confirmed a classic BEC intrusion. The malicious actor had likely gained access to the title company's email server weeks prior, monitoring the transaction silently. When the closing date approached, the bad actor registered the domain `sunrisetltle.com` and intercepted the email thread. 

The SPF (Sender Policy Framework) and DKIM (DomainKeys Identified Mail) signatures on the fraudulent email verified that it originated from a private server hosted in Eastern Europe, bypassing standard spam filters because the domain was freshly registered and possessed no negative reputation scores at the time of delivery. 

**C. Fund Dispersal Analysis**
Records subpoenaed from Apex Financial revealed the movement of the stolen funds. Of the original $184,500.00:
*   $40,000.00 was immediately initiated as an ACH outbound transfer to an offshore cryptocurrency exchange (Binance).
*   $12,000.00 was withdrawn via a series of ATM cash withdrawals and cashier’s checks in the Miami, Florida area.
*   $132,500.00 remained in the account when the Cortex Bank and Trust freeze request was received and successfully actioned by Apex Financial.

**D. Regulatory and Law Enforcement Reporting**
In compliance with the Bank Secrecy Act (BSA), a Suspicious Activity Report (SAR) was filed with the Financial Crimes Enforcement Network (FinCEN) on October 4, 2023, detailing the mule account information and the IP addresses extracted from the email headers. Additionally, the investigator assisted the clients in filing a formal complaint with the FBI’s Internet Crime Complaint Center (IC3), generating IC3 Complaint #2023-I-993821.

### **4. RESOLUTION**

**Recovery Status:** Partial Recovery. 
Through the rapid deployment of the Fedwire recall and cooperation with Apex Financial, Cortex Bank and Trust successfully secured $132,500.00 of the original $184,500.00. On October 10, 2023, Cortex Bank and Trust executed a standard Hold Harmless/Indemnification agreement with Apex Financial. The recovered funds were reversed and deposited back into the Jenkins' Cortex Bank and Trust checking account ending in -4921 on October 11, 2023.

The remaining $52,000.00 was unrecoverable due to being converted to cryptocurrency and withdrawn as cash before the fraud was detected. 

**Liability Assessment:**
Under the Uniform Commercial Code (UCC) Article 4A, which governs commercial and consumer wire transfers, Cortex Bank and Trust is not liable for the $52,000.00 loss. The bank successfully authenticated the client, obtained wet signatures, and executed the wire transfer exactly as instructed by the authorized account holder. The breach of security occurred externally, originating from the compromised communications of Sunrise Title & Escrow.

**Recommendations & Case Disposition:**
The FIU has provided the clients with documentation of the unrecovered loss and advised them to pursue restitution through Sunrise Title & Escrow’s cybersecurity and Errors & Omissions (E&O) insurance policies, given that the title company’s compromised network was the proximate cause of the fraudulent misdirection. 

Cortex Bank and Trust considers this internal investigation concluded. The case file will remain open solely for the purpose of law enforcement liaison, should the FBI or local authorities request further documentation regarding the mule account network.

**STATUS:** CLOSED / REFERRED TO LAW ENFORCEMENT
**SUBMITTED BY:** Marcus Vance, Lead Investigator, FIU