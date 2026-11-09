# Design references for the review and appeal portal

Public, government-grade references gathered for the visual build. They are inspiration and rules to follow, not assets copied into the repo. Check each licence before reusing any code or artwork.

## India
- UX4G, the MeitY / Digital India Corporation design system (v2.0 web kit, open source): https://doc.ux4g.gov.in/ , source https://github.com/ux4g/ux4g-design-system-v1/ , programme page https://dic.gov.in/ux4g/ . The natural visual language for an Indian government tool: use its tokens and component conventions as the base.
- GIGW 3.0, Guidelines for Indian Government Websites and apps: https://guidelines.india.gov.in/accessibility-guidelines-and-attributes/ . Accessibility is adopted from WCAG 2.1, so the portal targets WCAG 2.1 AA at least.
- Law and compliance overview: https://wcagrules.com/laws/india-rpwd-gigw

## Case and status patterns
- DWP Design System, status pages ("what is the claim, case or item doing right now"): https://design-system.dwp.gov.uk/design-for/status . Use for the family status view: notification banner, quick reference, tags.
- MOJ Design System, case list pages: https://design-patterns.service.justice.gov.uk/pages/case-list/ . Use for the officer queue: few columns, clear headings, sortable table, tabs for groups of cases.
- GOV.UK Design System: https://design-system.service.gov.uk/ ; question pages https://design-system.service.gov.uk/patterns/question-pages/ ; complete multiple tasks (task list) https://design-system.service.gov.uk/patterns/complete-multiple-tasks/ ; accessibility strategy https://design-system.service.gov.uk/accessibility/accessibility-strategy/ . Use for the appeal form (one question per step, plain language) and the four-check verification list.
- Government of Alberta, review and action example: https://design.alberta.ca/examples/review-and-action/ . Use for the supervisor approve or reject screen.
- US Web Design System: https://designsystem.digital.gov/documentation/getting-started-for-designers/ . Reference for accessible components and tokens.
- Case management discussion, UK Home Office design system: https://github.com/UKHomeOffice/design-system/discussions/338

## How these map to the build
- Family side: plain language, one task per page, large touch targets, Hindi and English toggle, a status page that always says what happens next and the appeal deadline, and honest "messages are queued, not sent" wording.
- Officer queue: priority shown as uncalibrated review priority, few columns, SLA tag, jurisdiction filter.
- Case page: evidence summary, four-check task list, audit trail, decision panel with the four-eyes rule visible.
- Quality bar: WCAG 2.1 AA (contrast, focus order, keyboard use, labels, error summaries), screen-reader pass, and screenshot proof reviewed before anything is called done.
