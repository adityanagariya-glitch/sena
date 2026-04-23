# NDIS Wiki Schema

This wiki is an evolving, persistent knowledge base of the NDIS Quality and Safeguards Commission documents.

## Directory Structure

- `sources/`: Raw markdown files converted from official NDIS PDFs. **Immutable.**
- `pages/summaries/`: One summary per source document.
- `pages/entities/`: Pages for organizations, groups, and roles (e.g., NDIS Commission, Providers).
- `pages/concepts/`: Pages for policies, frameworks, and key topics (e.g., Worker Screening, Behavior Support).
- `index.md`: The content-oriented master catalog.
- `log.md`: Chronological log of operations.

## Workflows

### 1. Ingest
When a new source is added to `sources/`:
1. Read the source.
2. Create a summary in `pages/summaries/`.
3. Extract/Update entities in `pages/entities/`.
4. Extract/Update concepts in `pages/concepts/`.
5. Update `index.md` and `log.md`.

### 2. Query
When asked a question:
1. Consult `index.md` to find relevant pages.
2. Read the specific summary, entity, or concept pages.
3. Synthesize the answer with citations back to the source.

### 3. Maintain (Lint)
Periodically:
- Check for broken cross-links.
- Identify missing definitions for terms used across pages.
- Flag contradictions between old and new policies.
