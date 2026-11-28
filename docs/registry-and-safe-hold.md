# Death registry check and the safe hold

## What it does
Registered deaths from the civil registry are loaded as the `death_registry` feed, matched to pensioners by identity matching, and scored. A match opens a review case with a pre-written draft of the reasons. `/registry` shows registrations loaded, how many line up with a pensioner, the lag between death and registration, and pension credits paid after the registered date of death.

## What it deliberately does not do
It does not freeze anything on its own. The "freeze" is the existing safe hold: all four verification checks done, written reasons, a different supervisor approves, notice to the family, then suspension, with provisional restore on appeal and an independent appeal reviewer. Every step is in the hash-chained audit log.

## Why a registry match is not automatic
- A match is by name, date of birth and sometimes Aadhaar. The 2023 amendment to the Registration of Births and Deaths Act permits but does not require the Aadhaar number to be recorded, so many links are fuzzy. A namesake can be wrongly stopped.
- A wrong stop is costly and hard to undo. The US Social Security Administration's own auditors counted 24,219 beneficiaries with an incorrect death record between January 2020 and December 2024.
- A missing certificate does not mean alive. Official death registration is about 92 percent (RGI, 2019), but a household survey (NFHS 2019-21) put it at 70.8 percent, with large gaps by district and for women.
- Registration can be late. The legal window is 21 days, with delayed registration allowed after that.

## Why real systems may not already do this (inference, not confirmed)
1. Registration is run by about 290 thousand local units under state governments. A national database was only enabled by the 2023 amendment, in force from 1 October 2023. Pensions are paid by many separate bodies (central, state treasuries, banks).
2. Identity linkage is weak without a mandatory common identifier on the certificate.
3. Coverage and timing gaps mean the check finds some deaths, not all.
4. Wrongful stops carry legal and political cost, so a bad automatic stop is worse than a slow check.
5. Data sharing needs rules on who may see what and for which purpose.
6. The existing control is the annual life certificate, which is simple and already in place.
Where it is done, it is done by law: in the UK, registrars must notify the DWP of deaths and the Tell Us Once service passes a report across government. I have not verified whether Indian disbursing banks or CPAO run any registry check today.

## Sources
- RGI Vital Statistics of India based on CRS 2021: https://censusindia.mha.gov.in/nada/index.php/catalog/45554/download/49751/CRS_Report_2021.pdf
- CRS 2019 (92.0 percent): https://censusindia.gov.in/nada/index.php/catalog/42541/download/46167/CRS_Report_2019.pdf
- Bulletin of the WHO, death registration coverage 2019-2021: https://pmc.ncbi.nlm.nih.gov/articles/PMC9874366/
- Registration of Births and Deaths (Amendment) Act 2023: https://egazette.gov.in/WriteReadData/2023/248044.pdf
- RGI statement, MCCRVS 2025 (in force 1 Oct 2023): https://www.unescap.org/sites/default/d8files/event-documents/Agenda2-India_MCCRVS2025.pdf
- SSA OIG, Beneficiaries Incorrectly Recorded as Deceased: https://oig.ssa.gov/~assets/uploads/032311.pdf
- UK DWP Tell Us Once: https://www.gov.uk/after-a-death/organisations-you-need-to-contact-and-tell-us-once
- UK Social Security (Notification of Deaths) Regulations 2012: https://www.legislation.gov.uk/uksi/2012/1604/pdfs/uksiem_20121604_en.pdf
