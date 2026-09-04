**CONFIDENTIAL - INTERNAL USE ONLY**
**MERIDIAN TRUST BANK - FRAUD OPERATIONS DIVISION**
**WIRE FRAUD INVESTIGATION REPORT**

**Case Number:** MTB-2024-WF-08492
**Date of Report:** April 18, 2024
**Lead Investigator:** Marcus Vance, CFE (Badge #8834)
**Subject:** IRS Tax Refund Diversion via Account Takeover (ATO)
**Victim/Account Holder:** Eleanor Higgins
**Compromised Account:** Checking (DDA) ending in -4491
**Total Exposure:** $18,450.00
**Actual Loss:** $0.00 (Funds Successfully Frozen and Recovered)

**INCIDENT OVERVIEW**
On March 16, 2024, the Cortex Bank and Trust (MTB) Fraud Operations Division escalated an inquiry originating from retail customer Eleanor Higgins regarding an unauthorized outbound wire transfer. The investigation determined that an unidentified threat actor successfully executed an Account Takeover (ATO) of the customer’s online banking profile. Subsequent to gaining access, the threat actor monitored the account for an incoming Automated Clearing House (ACH) credit from the United States Department of the Treasury (IRS Tax Refund) in the amount of $18,450.00. Within twelve hours of the ACH settlement, the threat actor initiated a domestic wire transfer, attempting to exfiltrate the entirety of the refund to a suspected mule account at Vanguard Fidelity Credit Union. This report details the methodology of the ATO, the timeline of unauthorized transactions, the investigative actions taken by Cortex Bank and Trust personnel, and the final resolution of the intercepted funds.

**TIMELINE OF EVENTS**
*All times listed in Eastern Standard Time (EST).*

*   **March 10, 2024 - 14:22:** Initial compromise. An unrecognized login is recorded on the online banking profile of Eleanor Higgins. The session originated from IP address 192.148.22.10, which cross-references to a known commercial Virtual Private Network (VPN) exit node located in Miami, Florida. The customer's historical login patterns typically originate from residential IP addresses in Columbus, Ohio.
*   **March 11, 2024 - 09:15:** The threat actor accesses the "Account Settings" portal and successfully adds a new mobile telephone number (407-555-0199) to the profile. A One-Time Password (OTP) was sent to the customer's primary email address to confirm this change. Subsequent forensic analysis suggests the customer’s personal email account was simultaneously compromised, allowing the threat actor to intercept the OTP seamlessly.
*   **March 11, 2024 - 09:20:** The threat actor changes the primary Multi-Factor Authentication (MFA) delivery method from the customer’s original mobile device to the newly added 407 area code number.
*   **March 15, 2024 - 03:30:** An ACH credit of $18,450.00 is posted to DDA -4491. The transaction descriptor reads: "TREAS 310 TAX REF PPD".
*   **March 15, 2024 - 11:45:** The threat actor logs in (IP address 185.220.101.4, an anonymizing proxy) and initiates a domestic wire transfer request for $18,450.00. The beneficiary is listed as "David K. Lawson" with a receiving account at Vanguard Fidelity Credit Union (Routing ending in -0221, Account ending in -8832).
*   **March 15, 2024 - 11:47:** The Cortex Bank and Trust automated wire monitoring system flags the transaction for review due to the high percentage of the account balance being depleted and the novelty of the payee. However, the transaction is automatically approved and released after the threat actor successfully inputs the OTP sent to the fraudulent 407 mobile number. The wire is transmitted via the Fedwire system.
*   **March 16, 2024 - 08:30:** Eleanor Higgins contacts the Cortex Bank and Trust customer service center to inquire about her tax refund, having received an alert from the IRS that the funds were deposited. Upon reviewing her balance with a representative, the unauthorized wire is discovered. The call is immediately transferred to the Fraud Operations Division.

**INVESTIGATION STEPS**
Upon assignment of the case on March 16, Investigator Vance immediately initiated containment and recovery protocols.

1.  **Account Securitization:** DDA -4491 was placed on a hard debit/credit freeze (Status Code: Post No Debits/Credits). The online banking profile was suspended, and all active sessions were forcefully terminated. The fraudulent 407 mobile number was scrubbed from the CIF (Customer Information File).
2.  **Victim Interview:** A recorded interview was conducted with Eleanor Higgins. She confirmed she did not authorize the wire transfer or the phone number change. Higgins stated she had recently received a deceptive email purporting to be from a popular tax preparation software company, prompting her to "re-authenticate" her banking credentials to process her refund. This establishes the initial vector of compromise as a targeted phishing campaign.
3.  **Digital Forensics and Access Logging:** Cortex Bank and Trust's cybersecurity team reviewed the session headers for the unauthorized logins. The user-agent string indicated a modified Mozilla Firefox browser operating on a Linux kernel, completely anomalous to the customer's standard iOS Safari footprint. Furthermore, the rapid execution of the wire transfer immediately following the IRS deposit indicates the threat actor was either utilizing automated script monitoring or manually checking the account balance at high frequencies specifically waiting for the treasury deposit.
4.  **Fund Recovery Operations:** At 09:15 on March 16, Investigator Vance initiated a formal Hold Harmless Letter and a SWIFT/Fedwire recall request to the fraud department at Vanguard Fidelity Credit Union. The recall request explicitly cited "Suspected Fraud - Account Takeover / Unauthorized IRS Diversion."
5.  **Inter-Bank Coordination:** At 11:30, Vanguard Fidelity Credit Union's Fraud Department responded, confirming receipt of the recall request. They reported that the funds had credited to the beneficiary account (David K. Lawson) but had not yet been withdrawn or off-ramped to a cryptocurrency exchange. Vanguard placed a restrictive hold on the beneficiary account pending reversal.
6.  **Regulatory and Law Enforcement Reporting:** Given the direct involvement of a United States Treasury deposit, the incident was escalated and reported to the IRS Criminal Investigation (IRS-CI) division via their online fraud portal. All gathered details regarding the suspected phishing vector and the compromised email account were provided to federal authorities.

**RESOLUTION**
On March 19, 2024, Cortex Bank and Trust received a full return of the wired funds ($18,450.00) from Vanguard Fidelity Credit Union via Fedwire reversal. The funds were temporarily placed in a secure internal general ledger account.

On March 20, 2024, Eleanor Higgins visited the Cortex Bank and Trust branch located at 402 West Elm Street, Columbus, OH. Her identity was verified in person using a valid Ohio Driver's License and secondary documentation. DDA -4491 was permanently closed to prevent future exploits utilizing the compromised routing and account numbers. A new checking account (DDA ending in -9902) was opened, and the recovered $18,450.00 was credited to the new account.

The customer's online banking profile was provisioned with new, strictly segregated credentials. As a mandatory condition of profile restoration, hardware-based multi-factor authentication (a physical security token) was enabled on the account, overriding and disabling all SMS-based OTP options.

A Suspicious Activity Report (SAR) was formally filed by the Cortex Bank and Trust BSA/AML compliance team on March 22, 2024. The SAR detailed the IP addresses, the fraudulent phone number, the phishing methodology, and the Vanguard Fidelity Credit Union beneficiary account information to assist the Financial Crimes Enforcement Network (FinCEN) in tracking the broader mule network. 

Case MTB-2024-WF-08492 is hereby closed as "Resolved - Funds Recovered."