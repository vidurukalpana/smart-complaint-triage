# EDA summary

Analysis of `complaints_clean`: 34,009 English complaints with narratives, received
15 May – 11 Aug 2026, about banks and lenders. Run `make eda` to repeat it; the queries are in
`src/smart_complaint_triage/eda.py` and the full results go to `reports/eda/`.

## Teams

| Team | Complaints | Monetary relief | Late response | Median words |
|---|---|---|---|---|
| Recoveries & CRIB Disputes | 10,223 | 0.4% | 4.2% | 131 |
| Deposits & Savings | 7,089 | 14.3% | 0.7% | 199 |
| Cards | 6,772 | 17.4% | 2.5% | 217 |
| Payments & Digital Banking | 2,955 | 9.4% | 1.8% | 192 |
| Personal Loans | 2,647 | 2.0% | 21.2% | 201 |
| Housing Loans | 2,544 | 1.8% | 6.3% | 257 |
| Leasing & Vehicle Loans | 1,779 | 2.3% | 2.1% | 222 |

- **Coverage:** every CFPB product in the data is mapped to a team or explicitly excluded.
- **Imbalance:** the largest team has about 6 times as many complaints as the smallest, which
  supports macro-F1 as the main routing metric.
- **Merged team:** CRIB Disputes had 98 complaints, under the 500 minimum. It would have about 12
  complaints in the test split, too few to measure. Its text is closest to Recoveries (word-use
  similarity 0.78; next closest Cards at 0.64), and 62% of CRIB complaints and 38% of Recoveries
  complaints mention a credit report. It is merged into **Recoveries & CRIB Disputes**.
- **Top issues:** purchases shown on a statement (Cards, 2,187) and managing an account
  (Deposits & Savings, 4,005) are the largest issues outside Recoveries.

## Outcomes and the escalation cutoff

Overall, 7.8% of complaints ended in monetary relief and 4.3% had a late response.

| Week starting | Complaints | Monetary relief | Late response | In progress |
|---|---|---|---|---|
| 11 May – 6 Jul (9 weeks) | 775–4,486 | 6.5–8.2% | 4.1–5.2% | 0 |
| 13 Jul | 2,389 | 8.8% | 2.6% | 4 |
| 20 Jul | 818 | 10.3% | 0.5% | 0 |
| 27 Jul | 421 | 10.7% | 1.4% | 0 |

Only 4 complaints are "In progress", so that check alone gives no reason to move the cutoff. The
outcome rates do: after 12 July, late responses drop sharply and relief rises. The pattern fits
complaints being published only after the company responded, so the last weeks hold mostly fast
responses. This is an inference from the rates; CFPB's archive does not state its publication
timing. Labels after 12 July are biased, so **the escalation cutoff moves from 29 July to 12 July**.

## Splits

The original dates left only 422 complaints in the routing test split, because narratives thin
out after mid-July. New dates, on week boundaries:

| Task | Train | Validation | Test |
|---|---|---|---|
| Routing | 15 May – 28 Jun: 23,635 | 29 Jun – 12 Jul: 6,745 | 13 Jul – 14 Aug: 3,629 |
| Escalation | 15 May – 21 Jun: 19,966 | 22 – 28 Jun: 3,669 | 29 Jun – 12 Jul: 6,745 |

- The smallest team has 217 complaints in the routing test split.
- The escalation test split is larger than its validation split on purpose. Positives are rare,
  and it has 520 relief and 292 late complaints to measure.
- Late rates are stable across the escalation splits (4.7%, 4.6%, 4.3%).
- **Routing test mix differs slightly from train:** Recoveries is 24.8% of test and 31.9% of
  train, because of the same publication effect.

## Things later branches need to handle

| Finding | Branch | What to do |
|---|---|---|
| 1,886 narratives are exact copies of an earlier one, 98% of them in Recoveries (template letters; the largest has 283 copies). 344 validation and test complaints are copies. | 7–12 | Train and evaluate on `NOT is_duplicate_narrative`, or scores will be too high. This does not catch near-copies that differ in a few words. |
| Daily counts are uneven: Fridays and Saturdays are often very low, and some days have almost none (2 complaints on 10 and 11 July). 15 of 76 days have under 50. | 13 | This looks like publication batches, not real complaint volume (not confirmed). Weekly counts here are not reliable as true volume; volume also falls away after 12 July. Prefer each issue's share of the week, and test the detector up to 12 July. |
| `submitted_via` is "Web" for every complaint. | 12 | Drop it as a feature; it carries no information. |
| Late responses are concentrated in a few US companies: student loan servicers, e.g. MOHELA (393 late of 510). Student loans are 40.3% late; other personal loans 5.1%. | 12 | A late-response model may simply learn company names, which mean nothing to a Sri Lankan bank. Do not use company name directly, and report results with and without these companies. |
| 5–19% of narratives per team are over 512 words. | 9 | Long narratives exceed DistilBERT's limit, as the guide expects; use the first and last parts. |
