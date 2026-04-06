# Sena - POC Meeting Notes

## Reference Links

- [Change Register](https://docs.google.com/spreadsheets/d/1H2SZCcZXTCXrac887LxD5R-jqhA77K8d5Jff0xQ4tHc/edit?pli=1&gid=0#gid=0)
- [Figma](https://www.figma.com/design/Sy5oKABpKKC4PJdSKeSs0L/Sena-App-Flow?node-id=15333-2959&p=f&t=jg5VbyJmRZfi93Ts-0)

---

## Platform Overview

> Sena is a platform built as a pathway to connect the service providers, that help the disabled people more like NGOs in India, to the clients who are the actual disabled people. The NDIS pays them to do this work.
>
> Here all the service providers have different policies (like all NGOs have their ways of working set of rules), & on top of that there are some common rules that should be followed by all the service provider.
>
> We need to give them an AI chatbot with all the knowledge of that company policies. That AI chatbot should have all the knowledge of the common ie government policies and the company specific policies.
>
> **And for major security reasons, all the data related to specific provider should be completely isolated. The data isolation is the most critical part and it should comply with the AUS laws.**
>
> The platform is the complete platform for the service provider where they have HR system workforce management & schedule services, client pays based on service received, and the money earned shared with the inter people of service provider so we have the payroll system too.
>
> There can be multiple organization with their separate staff and, they combining can give service to the client ie a client registered with other service provider without knowing.

- In the staff management section > under staff onboarding mobile: when asking for government ID's like `drivers licence` we have to perform OCR to extract correct info from documents and also give option to edit

---

## Client On-Boarding Flow

> Once the client receives the link of onboarding, the comes the most important AI part, its kind of AI assistant that help user end to end with registration they want it not to sound like AI, they want it to sound natural, conversational and helping if didn't understand that AI should also ask questions.

- Complete onboarding help, steps and screen wise so AI should also be able to see the screen (i think so) (they want the AI to be as close as to a human support person, that asks what help do you need helps out end to end)
- If AI didn't understand anything than AI should ask counter question to clarify, at the same time not just keep asking question
- They want the assistant to fill the details, like page wise if name is the first section ask the user what your name, and autonomously fill the name and details
- Is a user slink cannot there it the user should be able to reclarify ask, by interrupting
- Continue this until the complete onboarding is done

---

## Web-Sena AI

> In the Sena AI which is in the web mostly used by the employee of the organization or the service provider admin. It should be limited to the service provider itself, ie isolation of all service provider. And the NDIS rules/policies are common on all service provider.

There are different sections in this AI chatbot, one of which is:

### Policies

- If there are any policies update then they can ask here and AI should tell and explain them
- If they want to know about existing policies, they just ask here
- Some policies can be in the document form and some can be added from the portal we need to directly fetch from the

### My View Point

I think they don't want to provide us data in the Sena admin/employee chatbot. Per service provider, they want us to develop a pipeline where AI read data from the database and trains itself over it and give answers, and it can be RAG or any other way, but I think they want perfections ie almost 100% accuracy.

### Shift-Check

- There is a shift scheduler module where each employee has they schedule shift and internal meeting, so this AI should also be able to answer this things
   - Here I think we also need to isolate the shift or personal data per employee

### Procedures

- Processes used in the system ie registers
   - Registers are library, something used to keep notes of particular things
      - eg:

| Title | Items | Meaning |
| --- | --- | --- |
| Asset register |  | Like what kind of assets a company owns |
| Documents register |  | Like what kind of documents the system have and which document is assigned to whom |
| Risk management plan register |  | If client is assigned to someone and there could be a delay and there is a risk based on this delay |

### Client Information

- The AI should have knowledge of clients that were onboarded per service provider

> **Note:** All this info is frequently added and updated, so AI should be able to handle gracefully.

### Report Generation

> After all this there is a separate option for service provider admin.

- They also want that same AI chatbot to generate report and they want the exact structure of the report as it is (we will probably use LaTeX here), because its their standard
- They can select a specific client and based on that client we can generate a specific report (report document will be provided by them)

---

## The Support Worker - Staff Flow

*The person who will go physically to the place to help disabled people.*

> In the staff flow, the organization service provider will schedule a specific shift based on the service required, and it will be done from web application and specific note. Where the client who need service will be selected, what kind of service needed is selected which support workers are assigned to that service what is the agenda for that shift. Like sleepover / 24 hour care etc and based on that the particular support worker will see the next shift details of himself.

- The ground worker (support worker) will see where is it's next shift on mobile app on screen and see all the details
- **AI part:** Here we need to create a summary of `all the past shift` (don't show if there are no past shift then we will not show summary) and this is for a specific client
- At the end there will be a case note, here the AI will ask about everything and fill everything
- AI is important here because there are too much details that needs to be updated for the case, because staff do not have much time generally because they have back to back shifts if they miss then they will forget something, and will not be able to add it later
- Just like the client onboarding we using AI, the same way we use AI to help the worker fill the case notes
- At the end there will be a summary generated based on this case note using AI
- This summary chunks or say paragraph chunks generated by AI based on case notes, there should be a flagging system, that check this paras, based on rules, that rules to flag should be taken from the NDIS official documents
- **Flag:**
   - A scenario based on data, like taking consent before helping or touching
   - Or like a client misbehaved after properly doing the work
- Also employees can also ask AI to help them schedule shift if there are any allocated shift on specific days or not (I don't see this in UI where will they ask)
- There is a restrictive practice register where the things that are restricted to do is listed things that should not be done not even by participant or by the support worker (search for restrictive practices NDIS)

   [Regulated Restrictive Practices Guide - regulated-restrictive-practice-guide-rrp-20200.pdf](https://res.craft.do/user/full/25d603cc-4057-1f52-28dc-b5cba31ccc85/doc/cc516255-e4bc-4f30-9668-663106d5f661/b8b4673d-3c9a-4c6d-a509-dab83a3869af)

- Identify based on this support worker filled in the data, compare it with the rules flag anything suspicious

> Incident reports and case notes can also be filed out later.

---

## Sena AI For Staff

- Same Sena AI will also be there for mobile, it will be for the staff on the, also on the website
- It can be accessed by a kind of a support coordinator - or a manager on the web
   - Here the Sena employee can see all the support workers that go physically on ground to help, all the shifts they have done, the summary per shift and also the common summary combining all the shifts
   - Summary is of the case note submitted by the support worker
   - Also an overview report monthly and when approved should automatically be filled out based on actual report the structure (format) provided by the client, like who the report should look like

### Phase 2 - AI Module Breakdown

| 48 | Participant onboarding      | Mobile       | AI | AI Assistant while onboarding for helping participant.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         | 0  | 20 | 8  | 40 | Yes | In subject to LLM capability of NDIS understanding and knowledge       |   | Phase 2 |   |   |
| -- | --------------------------- | ------------ | -- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -- | -- | -- | -- | --- | ---------------------------------------------------------------------- | - | ------- | - | - |
| 49 | Case Notes Register         | Web - Mobile | AI | AI Case Note Review & Insight Extraction  <br>- Purpose : Identify progress, risks, and patterns from case notes  <br>- Web : Full document analysis, highlighted excerpts, confidence scores, approval/dismissal, report generation  <br>- Mobile : View AI summary and flagged highlights only  <br>- Human Control Point : Manager / Compliance approval required                                                                                                                                                                                                                                           | 10 | 8  | 24 | 16 |     |                                                                        |   | Phase 2 |   |   |
| 50 | Case Note Drafting (Mobile) | Mobile       | AI | AI Conversational Case Note Drafting (Mobile)  <br>- Purpose : Enable rapid, on-the-go case note drafting via voice input  <br>- Web : Review, edit, compliance-check, and approve AI-drafted case notes  <br>- Mobile : Voice-based conversational AI captures shift activities; prompts for missing details (goals, behaviours, risks, incidents); generates a structured draft case note for review.  <br>- Human Control point : missing details (goals, behaviours, risks, incidents); generates a structured draft case note for review, Support worker must review, edit, and approve before submission | 10 | 20 | 8  | 40 |     |                                                                        |   | Phase 2 |   |   |
| 51 | Restrictive Practices       | Web          | AI | AI Incident & Restrictive Practice Drafting  <br>- Purpose : Pre-draft compliant reports  <br>- Web : Full draft generation, editing, validation checks, approval workflow  <br>- Mobile : Draft preview only (no submission)  <br>- Human Control : Human sign-off mandatory                                                                                                                                                                                                                                                                                                                                  |    | 8  | 16 | 50 |     | ( RAG )  <br>Get Knowledge Based for Restrictive Practice as per NDIS |   | Phase 2 |   |   |
| 52 | Shift                       | Web          | AI | AI-driven recommendations based on:  <br>- Client's submitted NDIS goals.  <br>- Prior shift activities.  <br>- Support worker feedback and history.                                                                                                                                                                                                                                                                                                                                                                                                                                                           | 10 |    | 15 | 20 |     |                                                                        |   | Phase 2 |   |   |
| 53 | Audit                       | Web          | AI | AI-Powered Compliance Audits  <br>- Compliance status across all NDIS standards.  <br>- Identified risks and mitigation strategies.  <br>- Recommendations for service improvements.                                                                                                                                                                                                                                                                                                                                                                                                                           |    |    |    | 0  |     | Considered in AI Case Note Review & Insight Extraction                 |   | Phase 2 |   |   |
| 54 | Risk                        | Web          | AI | AI Risk Flagging & Escalation Detection  <br>- Purpose : Detect critical or emerging risks  <br>- Web : Risk dashboard, trend analysis, evidence trail, escalation controls  <br>- Mobile : Push alerts + read-only risk summary  <br>- Human Control : Manager decides escalation actions                                                                                                                                                                                                                                                                                                                     |    | 0  |    | 0  |     | Considered in AI Case Note Review & Insight Extraction                 |   |         |   |   |

| 56 | AI Support Worker Briefing            | Web        | AI | AI Support Worker Briefings  <br>- Purpose : Translate plans into practical guidance  <br>- Web : Create, edit, and tailor briefings  <br>- Mobile : Primary consumption platform for shift guidance  <br>- Human Control : Manager controls content   |    | 0 |    | 0  |   | Considered in AI Case Note Review & Insight Extraction                                                                             |   |         |   |   |
| -- | ------------------------------------- | ---------- | -- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -- | - | -- | -- | - | ---------------------------------------------------------------------------------------------------------------------------------- | - | ------- | - | - |
| 57 | AI Search & Pattern Recognition       | Web        | AI | AI Search & Pattern Recognition  <br>- Purpose : Identify service-wide trends  <br>- Web : Advanced filters, analytics dashboards, audit prep  <br>- Mobile : Not available  <br>- Human Control : Governance review required                          |    |   |    | 0  |   | As per 15-12-2025 meeting, the pattern recognition is considered in AI Case Note Review & Insight Extraction.                      |   |         |   |   |
| 58 | AI Communication Log Analysis         | Web-Mobile | AI | AI Communication Log Analysis  <br>- Purpose : Detect sentiment, breakdowns, disengagement  <br>- Web : Full conversation analysis, risk tagging  <br>- Mobile : Alert-only notifications  <br>- Human Control : Human interpretation required         |    |   | 12 | 24 |   |                                                                                                                                    |   |         |   |   |
| 59 | AI Medication & Health Risk Detection | Web-Mobile | AI | AI Medication & Health Risk Detection  <br>- Purpose : Flag immediate health risks  <br>- Web : Immediate flag + escalation workflow  <br>- Mobile : Instant alert to management  <br>- Human Control : Clinical judgment remains human                |    |   | 16 | 8  |   | Need to check which health risk need to be detected ?  <br>Keep track of weekly updated.  <br>Should included the clients details. |   |         |   |   |
| 60 | Reporting                             | Web-Mobile | AI | AI Monthly Reports & Progress Summaries  <br>- Purpose : Consolidate participant progress  <br>- Web : Report creation, editing, export for stakeholders  <br>- Mobile : Read-only summary view  <br>- Human Control : Manager approves before sharing | 30 |   | 40 | 80 |   |                                                                                                                                    |   | Phase 2 |   |   |

---

## Some Extra Things to Note

- There will be some another UIs to where
   - Different rules and compliance, to check if things are maintained properly or not
      - If for an example a laptop is being used by the organization but the
         - Things are not up to date
         - If system are following proper rule or not
         - If manager or support worker are provided any task or not, if they are properly doing task or not
- For all this we have to generate a combined report if things are maintained properly for specific service provider
- Detect risk using AI and make drafts ready so anyone with higher authority can escalate on the risk dashboard so the issues can be fixed out

### Action Items

- [ ] Ask for the video where the Sena team and Varun Bhai are discussing about the AI
- [ ] Also client wants to connect with the AI team (ie us)
- [ ] We will have some real data by the end of March
- [ ] We can ask for data help to Sandeep from Sena team
- [ ] We cannot share any document in group, if needed share it from the drive link

---
