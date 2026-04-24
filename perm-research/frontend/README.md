# PERM Research Frontend

React + Vite frontend for the BALCA/PERM research platform.

## Modules

### BALCA Decisions
Full-text search across BALCA precedent decisions with citation graph, composite ranking
(text relevance × citation authority), and advanced search operators ("phrase", -exclude, OR).

### AAO Decisions
Full-text search across AAO non-precedent and precedent decisions.

### Regulations & Policy
Searchable CFR and DOL policy guidance corpus.

### PERM Comparer
Text comparison workspace for PERM labor certification review.

**Features:**
- Load PWD (ETA-9141 PDF) — extracts job title, location, job description, minimum
  requirements, and PWD wage automatically via the Anthropic API (client-side, no backend)
- Side-by-side diff of Job Description and Minimum Requirements with token-level highlighting
- Strict mode (character-level) vs. standard word-level comparison
- Ignore Formatting mode — strips bullets/whitespace before comparing
- PWD Wage Check — validates that the offered wage range starts above the prevailing wage
- **Experience Verification Letter Modal** — see below

**Experience Verification Letter Modal:**

Opened via the "Verify Experience" button in the toolbar. Provides a full-screen
side-by-side view of the PWD requirements and uploaded experience letters.

- Upload one or more experience verification letter PDFs
- Each letter is parsed by Claude (client-side Anthropic API call): extracts employer,
  job title, employment dates, duties, skills, and full letter text
- Employment period is parsed and displayed in months/years
- "Analyze vs PWD" button compares the letter against the minimum requirements and
  returns a split view of requirements addressed vs. requirements not found
- Keywords from the PWD requirements are highlighted in the letter text; skills from
  the letter are highlighted in the PWD panel
- "Save Time" marks a letter's time as counted toward the total; saved total is shown
  in the modal header across all letters
- Multiple letters supported with a tab strip; letters persist while the modal is open

**TODO — Automated Experience Time Comparison:**
Future enhancement to compare total saved months across all letters against the years
required by the PWD. Requires careful handling of PERM language conventions (field
experience vs. per-skill experience). See journal.txt Session 8 for design notes.

## Development

```bash
npm install
npm run dev
```

The dev server proxies `/api/*` to the FastAPI backend (see `vite.config.js`).

## Build

```bash
npm run build
```
