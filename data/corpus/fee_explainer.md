---
doc_id_prefix: FE
title: "Fee Explainer: mutual fund charges and why they appear (M2)"
source_type: M2_FEE_EXPLAINER
as_of: 2026-10-03
note: "Internal explainer ported from the M2 Review Analyst. Every section cites the public page it is based on. Facts only; no investment, tax-planning, or return advice."
---

# Fee Explainer

Each `##` section is one fee type. The ingest step makes one chunk per section, and the
`doc_id` and `fee_type` lines set the chunk metadata. Scheme-specific numbers (for example a
fund's exit-load %) live in the scheme factsheets, not here.

## Exit load

doc_id: FE-EXIT-01 · fee_type: exit_load

**What it is.** An exit load is a charge some schemes levy when you redeem units before a
set holding period. It discourages early exit. If you stay invested longer than the period,
no exit load applies. Entry loads were removed in 2009, and SEBI caps the maximum exit load.

**How it is calculated.** The exit load is a percentage of the NAV, applied to units
redeemed before the period ends. The period and % are in the Scheme Information Document
and the factsheet. Units held past the period are redeemed with no exit load.

**Worked example.** A scheme has a 1% exit load and NAV ₹100. If you redeem within the
exit-load period, you get ₹99 per unit; ₹1 per unit is kept by the fund. After the period
you get the full ₹100 per unit.

**Why was I charged it?** You were charged only if you redeemed (or switched) units that
were still inside the scheme's exit-load period. If the scheme shows a 0% exit load, or your
units were held longer than the period, a lower credit comes from something else, such as
stamp duty when you bought or STT on an equity-fund redemption.

Source: https://www.mutualfundssahihai.com/en/what-are-loads ·
https://www.mutualfundssahihai.com/en/what-costs-does-one-incur-while-redeeming-mutual-fund-units

## Graded exit load (liquid funds)

doc_id: FE-GRADED-01 · fee_type: exit_load

**What it is.** Liquid funds have a small exit load if you redeem within the first 7 days.
It falls each day you stay invested and is nil from day 7. SEBI requires this for liquid
schemes (circular SEBI/HO/IMD/DF2/CIR/P/2019/101, 20 Sep 2019). The day-wise slabs are
published in each liquid fund's factsheet.

**How it is calculated.** The load is a percentage of the redemption proceeds, based on the
applicable NAV. The day is counted from when you invested. It also applies to systematic
transactions.

| Redeemed on | Exit load (% of redemption proceeds) |
|---|---|
| Day 1 | 0.0070% |
| Day 2 | 0.0065% |
| Day 3 | 0.0060% |
| Day 4 | 0.0055% |
| Day 5 | 0.0050% |
| Day 6 | 0.0045% |
| Day 7 onwards | Nil |

**Worked example.** You redeem ₹1,00,000 from a liquid fund on day 3. The exit load is
0.0060% × ₹1,00,000 = ₹6, so you receive ₹99,994.

**Why was I charged it?** You redeemed inside the first 6 days. Some summary pages show a
liquid fund's exit load as "0%", but the graded slabs in the factsheet still apply to
redemptions in the first week.

Source: https://www.sebi.gov.in/sebi_data/attachdocs/sep-2019/1568988295926.pdf

## Stamp duty

doc_id: FE-STAMP-01 · fee_type: stamp_duty

**What it is.** Since July 2020, a stamp duty of 0.005% applies when you buy mutual fund
units. This covers lump sums, SIPs and STPs, and equity, debt, hybrid and fund-of-funds
schemes. It is not charged on redemptions. Transfers between demat accounts carry 0.015%.

**How it is calculated.** Stamp duty is 0.005% of the purchase amount. It is deducted
before units are allotted, so slightly fewer units are allotted.

**Worked example.** On a ₹1,00,000 investment, stamp duty is ₹5 and units are allotted for
₹99,995. On a ₹10,000 SIP instalment, stamp duty is ₹0.50, so units are allotted for
₹9,999.50.

**Why was I charged it?** Every purchase (including each SIP instalment) pays this duty.
It explains why the "invested" value is a few paise or rupees below the amount you paid.

Source: https://www.bajajamc.com/knowledge-centre/stamp-duty-on-mutual-funds

## Securities Transaction Tax (STT)

doc_id: FE-STT-01 · fee_type: stt

**What it is.** STT is a tax on transactions in equity-oriented securities. For
equity-oriented mutual funds, it is levied on the sale (redemption) of units at 0.001% of
the sale value. Debt funds do not attract STT.

**How it is calculated.** STT is 0.001% of the redemption value of equity-oriented fund
units. It is collected at the time of the transaction.

**Worked example.** Redeeming ₹1,00,000 of equity-oriented fund units attracts STT of
₹1.

**Why was I charged it?** You redeemed units of an equity-oriented fund (for example an
ELSS, large-cap, flexi-cap or equity index fund). The deduction is small and separate from
any exit load.

Source: https://www.bajajamc.com/knowledge-centre/securities-transaction-tax ·
https://www.mutualfundssahihai.com/en/what-costs-does-one-incur-while-redeeming-mutual-fund-units

## Expense ratio (TER)

doc_id: FE-TER-01 · fee_type: expense_ratio

**What it is.** The expense ratio (Total Expense Ratio, TER) is the annual fee a scheme
charges for managing and running the fund. It is a percentage of the scheme's assets. SEBI
caps it, and the cap falls as the fund grows. The monthly factsheet shows the actual TER.

**How it is calculated.** The TER is quoted as an annual %, but it is not billed once a
year. A small part is deducted from the fund's assets every day and is reflected in the
daily NAV. Over a year, the daily deductions add up to the stated TER.

**Worked example.** A fund with a 0.14% TER and an average holding of ₹1,00,000 costs
about ₹140 over a year. You never see a separate ₹140 debit; the NAV is simply that much
lower.

**Why was I charged it?** The TER is not charged separately to your bank account or
shown as a line item. It is already inside the NAV you see.

Source: https://www.tatamutualfund.com/blogs/what-expense-ratio-mutual-funds-learn-how-much-you-are-actually-paying-your-fund ·
https://www.mutualfundssahihai.com/en/what-are-expenses-incurred-mutual-fund-scheme

## ELSS lock-in

doc_id: FE-LOCKIN-01 · fee_type: lock_in

**What it is.** ELSS (tax-saver) funds have a statutory lock-in of 3 years from allotment.
Units cannot be redeemed during the lock-in, so ELSS funds do not need an exit load.
Investments are eligible for the Section 80C deduction (up to ₹1.5 lakh a year).

**How it is calculated.** The lock-in applies to each purchase separately. For an SIP,
each instalment has its own 3-year lock-in. To withdraw 12 months of SIP instalments in
full, you wait until the last instalment completes 3 years.

**Worked example.** An SIP started in January 2024 with instalments to December 2024:
the January 2024 units unlock in January 2027, and the December 2024 units unlock in
December 2027.

**Why was I charged it?** No exit load applies to ELSS units, because they can only be
redeemed after the lock-in. A smaller credit on an ELSS transaction is usually stamp duty
(on purchase) or STT (on redemption).

Source: https://www.mutualfundssahihai.com/en/what-is-lock-in-period ·
https://www.mutualfundssahihai.com/en/should-i-invest-elss-through-sip-or-lumpsum

## Capital-gains statement

doc_id: FE-CG-01 · fee_type: capital_gains

**What it is.** After you invest, you get an account statement. It shows the date of
each transaction, the amount invested, the NAV the units were bought at, and the units
allotted. It is updated with each purchase or redemption and shows your latest unit
balance and current value. A lost statement can be re-issued.

**How it is used.** The purchase date and NAV on the statement decide which units are
inside an exit-load period or ELSS lock-in, and how gains on a redemption are worked out.
Capital-gains tax depends on the type of fund and how long you held it. This assistant does
not give tax advice; refer to the statement from your AMC or registrar.

**Worked example.** You bought units on 10 January and 10 April and redeemed on 1 May.
The statement shows each lot's date, so you can see that the April units were inside a
90-day exit-load window and the January units were not.

**Why was I charged it?** Use the statement to match each deduction to a transaction:
stamp duty on purchases, and exit load or STT on redemptions.

Source: https://www.mutualfundssahihai.com/en/what-documents-are-provided-proof-my-investment-mutual-funds ·
https://www.mutualfundssahihai.com/en/what-costs-does-one-incur-while-redeeming-mutual-fund-units
