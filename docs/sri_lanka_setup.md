# Sri Lankan bank setup

The data is US CFPB complaints, but the system is configured to behave like a Sri Lankan bank:
Sri Lankan team names, Central Bank deadlines, Sri Lankan holidays and local terms.
A Sri Lankan bank using its own complaints would keep these files and change only the data.

| File | What it holds |
|---|---|
| `configs/taxonomy.yaml` | Bank teams and the CFPB products routed to each |
| `configs/sla.yaml` | Central Bank deadlines and the working-day calendar |
| `configs/holidays_lk.csv` | Holidays added on top of the `holidays` package |
| `configs/glossary.yaml` | US terms and their Sri Lankan equivalents |

## Teams

Each CFPB product is mapped to one team. The routing models learn to predict the team.

| Team | CFPB products |
|---|---|
| Deposits & Savings | Checking or savings account |
| Cards | Credit card, Prepaid card |
| Housing Loans | Mortgage |
| Personal Loans | Payday, title, personal or advance loans; Student loan |
| Leasing & Vehicle Loans | Vehicle loan or lease |
| Payments & Digital Banking | Money transfer, virtual currency, or money service |
| Recoveries | Debt collection |
| Credit Information (CRIB) Disputes | Credit reporting (complaints about what the bank reported) |

- Older CFPB names for the same products are mapped too, because CFPB renamed several of them.
- **Excluded products:** "Debt or credit management" and "Other financial service" are not
  bank services, so these complaints are dropped.
- **Unknown products** raise an error instead of being dropped silently, so a new CFPB product
  name is noticed and added to the file.
- Complaints the model is not confident about go to the **Human Triage Queue**.
- Each team has a description. Staff see it, and the LLM router (branch 10) uses it to choose a team.

## Central Bank deadlines

Source: Financial Consumer Protection Regulations No. 1 of 2023 (Gazette Extraordinary
No. 2344/17, 9 August 2023), in force since February 2024.

| Deadline | What the regulation says | Type | Example: received Mon 27 Jul 2026 |
|---|---|---|---|
| Acknowledgement (43.3) | "within a reasonable time [preferably within five (05) working days]" | Recommended target | due Tue 4 Aug (skips the weekend and Esala Poya on 29 Jul) |
| Resolution (46.1) | "resolve such complaint within 21 calendar days" | Legal limit | due Mon 17 Aug |

Both are counted from the date the complaint was received; that day itself is day 0. A complaint
received on a weekend or holiday starts counting from the next working day.

**Not modelled:** regulation 46.1 lets a bank extend the resolution time, up to a maximum of
3 months, if it tells the customer the reasons before day 21. There is no data on whether or how
often Sri Lankan banks use this, so the system always uses the 21-day limit.

Regulation 46.2 asks banks to resolve urgent complaints "within the earliest possible time,
considering the impact, urgency and risk". This is what the priority score (branch 12) supports.

### Status

For each deadline, days remaining = due date − today, in calendar days.

| Status | Rule |
|---|---|
| On track | more days left than the "due soon" limit |
| Due soon | ≤ 5 days left for resolution (≤ 2 for acknowledgement), including the due date itself |
| Overdue | the 21-day legal limit has passed |
| Past recommended time | the 5-working-day acknowledgement target has passed |

The acknowledgement uses "past recommended time" instead of "overdue" because the regulation
only *prefers* 5 working days; the legal requirement is "a reasonable time".

A complaint's overall status follows the **resolution** deadline. The CFPB data does not record
when a complaint was acknowledged, so the acknowledgement status is shown separately and not
combined into the overall status.

### Working-day calendar

- Weekends: Saturday and Sunday.
- Holidays: public, bank and Poya holidays from the `holidays` Python package.
- The package currently has Sri Lankan holidays up to **2026** only. `configs/holidays_lk.csv`
  is added on top of it: it holds a copy of 2026 (fallback) and is where later years or special
  holidays declared at short notice are added.
- If a deadline falls in a year with no holiday data, the code raises an error instead of
  treating every day as a working day. This matters for complaints received in late December
  2026, whose deadline runs into 2027.

## Local terms

`configs/glossary.yaml` replaces US terms with Sri Lankan ones in text shown to staff and in LLM
prompts, for example:

| US term | Sri Lankan term |
|---|---|
| credit bureau, Equifax, Experian, TransUnion | CRIB |
| credit report | CRIB report |
| ACH | SLIPS |
| wire transfer | CEFTS |
| Zelle, Venmo, Cash App | LankaPay |
| checking account | current account |
| mortgage | housing loan |
| debt collector | recoveries officer |

The payment systems are close equivalents, not exact ones. Only whole words are replaced, and
plural forms (e.g. "mortgages") are not replaced yet. The complaint text used for training is
not changed; the glossary is only for display and prompts.

## Not covered by the US data

| Service | Why | What happens |
|---|---|---|
| Pawning (gold loans) | No CFPB product matches it, so there are no training examples | The model has low confidence and sends these complaints to the Human Triage Queue |

Other Sri Lankan specifics, such as leasing companies regulated by the Central Bank, are only
approximated by the closest US product.
