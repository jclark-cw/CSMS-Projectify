# CSMS DocuSign → Asana Automation

## What This Does
When a DocuSign envelope is completed, it automatically creates an Asana project from a template, then builds out sections and tasks based on which deliverables were selected in the Bill of Materials.

---

## Architecture

```
DocuSign: Envelope Completed
   │
   ├─ Zap 1: CSMS Test Project
   │    1. DocuSign — Envelope Completed (trigger)
   │    2. Asana — Create Project From Template
   │    3. Code by Zapier — filter checked deliverables → checked_labels, checked_sections
   │    4. Formatter — Split checked_labels by comma → line items
   │    5. Looping by Zapier — loop over line items
   │    6. Google Sheets — Find Many Rows (lookup by deliverable_label)
   │    7. Asana — Create Section (using Rows COL B)
   │    8. Webhooks — POST to Zap 2 (section_gid, project_gid, deliverable_label)
   │
   └─ Zap 2: CSMS Task Builder
        1. Webhooks — Catch Hook (trigger)
        2. Google Sheets — Find Many Rows (lookup by deliverable_label)
        3. Code by Zapier — create all tasks via Asana API
```

---

## DocuSign Setup
- **Template:** BOM template with 11 Envelope Custom Fields (List type, Yes/No)
- **Document 1:** Contract (prose, no structured fields)
- **Document 2:** Bill of Materials (CMC26_Bill_of_Materials.pdf)

### Envelope Custom Field Data Labels
| Label | Deliverable |
|---|---|
| `dlv_speaking` | Speaking & Presentation |
| `dlv_booth` | Booth & Expo |
| `dlv_media` | Media & Content |
| `dlv_branding_onsite` | On-Site Marketing & Branding |
| `dlv_social_cmc` | CMC Platform & Social Promotion |
| `dlv_joint_content` | Partnership — Joint Content Collaboration |
| `dlv_partner_marketing` | Partnership — CMS Platform Marketing |
| `dlv_recognition` | Partnership — Recognition & Visibility |
| `dlv_events` | Events & Experiences |
| `dlv_discounts` | Discounts & Added Value |
| `dlv_barter` | Barter — Content Workshop → CMS |

---

## Zap 1 — Code Step (Run Javascript)
Reads all 11 DocuSign fields and outputs only the checked ones.

**Input Data:** all 11 `dlv_*` fields mapped from DocuSign trigger

**Code:**
```javascript
const deliverables = [
  { label: 'dlv_speaking',        section: 'Speaking & Presentation' },
  { label: 'dlv_booth',           section: 'Booth & Expo' },
  { label: 'dlv_media',           section: 'Media & Content' },
  { label: 'dlv_branding_onsite', section: 'On-Site Marketing & Branding' },
  { label: 'dlv_social_cmc',      section: 'CMC Platform & Social Promotion' },
  { label: 'dlv_joint_content',   section: 'Partnership — Joint Content Collaboration' },
  { label: 'dlv_partner_marketing', section: 'Partnership — CMS Platform Marketing' },
  { label: 'dlv_recognition',     section: 'Partnership — Recognition & Visibility' },
  { label: 'dlv_events',          section: 'Events & Experiences' },
  { label: 'dlv_discounts',       section: 'Discounts & Added Value' },
  { label: 'dlv_barter',          section: 'Barter — Content Workshop → CMS' },
];

const checkedLabels = [];
const checkedSections = [];

deliverables.forEach(d => {
  if (inputData[d.label] === 'Yes') {
    checkedLabels.push(d.label);
    checkedSections.push(d.section);
  }
});

return {
  checked_labels: checkedLabels.join(','),
  checked_sections: checkedSections.join(','),
  count: checkedLabels.length,
};
```

---

## Zap 1 — Webhook POST to Zap 2
Sends per deliverable (fires once per loop iteration):
- `section_gid` — from Asana Create Section step
- `project_gid` — from Asana Create Project From Template step
- `deliverable_label` — Loop current item

**Zap 2 Webhook URL:** `https://hooks.zapier.com/hooks/catch/22623479/422plpi/`

---

## Zap 2 — Code Step (Run Javascript)
Creates all tasks for a deliverable via Asana API.

**Input Data:**
| Key | Source |
|---|---|
| `section_gid` | Webhook trigger → Section Gid |
| `project_gid` | Webhook trigger → Project Gid |
| `n0`–`n6` | Google Sheets → Sub 0–6 → COL C (task names) |
| `d0`–`d6` | Google Sheets → Sub 0–6 → COL D (task notes) |

Slots with no matching row should be left empty or mapped to non-existent sub rows (they'll pass as empty strings and be skipped).

**Code:**
```javascript
const sectionGid = inputData.section_gid;
const projectGid = inputData.project_gid;
const token = 'YOUR_ASANA_PAT_HERE';

const tasks = [];
for (let i = 0; i <= 6; i++) {
  const name = (inputData[`n${i}`] || '').trim();
  if (name && name.toLowerCase() !== 'skip') {
    tasks.push({ 
      name: name, 
      notes: (inputData[`d${i}`] || '').trim() 
    });
  }
}

const results = [];
for (const task of tasks) {
  const resp = await fetch('https://app.asana.com/api/1.0/tasks', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      data: {
        name: task.name,
        notes: task.notes,
        projects: [projectGid],
        memberships: [{ 
          project: projectGid,
          section: sectionGid 
        }]
      }
    })
  });
  const json = await resp.json();
  results.push(json.data ? json.data.gid : 'error: ' + JSON.stringify(json));
}

return { 
  created_tasks: results.join(','), 
  count: results.length 
};
```

---

## Google Sheet — Task Library
**File:** `CMC26_Zapier_Table` (Google Drive)
**Local CSV:** `/Users/josephclark/Projects/CSMS/CMC26_Zapier_Table.csv`

**Columns:**
| COL A | COL B | COL C | COL D |
|---|---|---|---|
| deliverable_label | section_name | task_name | task_notes |

One row per task. To add/remove tasks, edit the sheet — no Zap changes needed.

---

## Local Files
| File | Purpose |
|---|---|
| `CSMS/CMC26_Bill_of_Materials.pdf` | BOM document for DocuSign (Document 2) |
| `CSMS/make_bom.py` | Script to regenerate the BOM PDF |
| `CSMS/CMC26_Zapier_Table.csv` | Task library source (also in Google Sheets) |
| `CSMS/CW Contracts/CMC26_+_Partnership_-_Content_Workshop_-_1-11-2026.pdf` | Original contract used to build deliverable list |

---

## Known Issues / Next Steps
- The duplicate first task issue may still occur if the old "Create Task" step in Zap 1 wasn't deleted — verify it's gone
- Asana template used is "Test DocuSign Project" — update to the real client template before go-live
- DocuSign template needs to be tested with all 11 deliverables set to Yes to confirm full coverage
- Consider adding the contract PDF as an Asana task attachment after project creation
