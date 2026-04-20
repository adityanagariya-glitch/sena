# Client Setup Guide — Gemini AI Access for SENA

**Who this is for:** The client team (NDIS service provider / IT admin) who needs to provision AI credentials so the SENA onboarding voice feature can run.

**What this unlocks:** The AI-powered participant onboarding flow — the voice assistant that collects personal details (name, DOB, NDIS number, address, emergency contact) during intake conversations.

---

## Which Option Should We Use?

| | Option A — AI Studio | Option B — Vertex AI |
|---|---|---|
| **Setup time** | 5 minutes | 30–60 minutes |
| **Cost** | Free tier available, pay-as-you-go after | Pay-as-you-go (no free tier) |
| **Australian data residency** | ❌ Not guaranteed | ✅ Yes — `australia-southeast1` (Sydney) |
| **NDIS compliance** | Not recommended for production PII | Recommended for production |
| **Good for** | Testing / dev only | Production with real participant data |

**Recommendation:** Use Option A first to confirm everything works, then migrate to Option B before going live with real participant data.

---

## Option A — AI Studio API Key (Dev / Testing)

### Step 1: Go to Google AI Studio
1. Open browser → go to **https://aistudio.google.com**
2. Sign in with a Google account (create one if needed — a business Google Workspace account is preferred)

### Step 2: Create API Key
1. In the left sidebar, click **"Get API key"**
2. Click **"Create API key in new project"**
   - This creates a free Google Cloud project automatically
3. A dialog shows your key — it looks like: `AIzaSy...` (39 characters)
4. Click the **copy icon** next to the key

### Step 3: Share with SENA Dev Team
Send us (securely — not via plain email):
```
GEMINI_API_KEY = AIzaSy...your-key-here...
```

> **Security note:** Treat this like a password. Share via a password manager, Signal, or encrypted file — not Slack/email plaintext.

---

## Option B — Vertex AI via Google Cloud (Production)

This is the correct path for production because it keeps participant data inside Australian servers.

### Step 1: Create a Google Cloud Account
1. Open a browser → go to **https://cloud.google.com**
2. Click **"Get started for free"** or **"Try Free"**
3. Sign in with an existing Google (Gmail) account — or create a new Google account if you don't have one. A Google Workspace business account is preferred.
4. Fill in your name, country, and other requested details → accept the Terms of Service → continue
5. Enter a credit or debit card for identity verification
   > Google may place a small temporary charge (0–1 USD) and then remove it. You will **not** be billed automatically.
6. Complete registration → you should land on the **Google Cloud Console dashboard**

### Step 2: Set Up Cloud Billing
Vertex AI requires an active billing account linked to your project.

1. In the Cloud Console go to: **https://console.cloud.google.com/billing**
2. If this is your first time, click **"Add billing account"**
3. Enter a billing account name — e.g. `NDIS Org Main Billing`
4. Select your country and currency → continue
5. Add your payment method (credit or debit card) and complete any verification steps
6. When finished, the billing account status should show **Active**

### Step 3: Create a Google Cloud Project
1. In the top bar of the Cloud Console, click the project selector (may say **"Select a project"**)
2. Click **"New Project"**
3. Set:
   - **Project name:** `sena-ai-prod` (or your preference — e.g. your organisation name)
   - **Organisation / Location:** Select your org if shown, otherwise accept defaults
4. Click **"Create"** and wait until the project is created (~15 seconds)
5. Make sure this new project is **selected in the top bar** before continuing
6. Note down your **Project ID** — shown under the project name, looks like `sena-ai-prod-123456`

### Step 4: Link the Project to Your Billing Account
1. Go to **https://console.cloud.google.com/billing**
2. Click **"Link a billing account to a project"** (or go to **My Projects** tab)
3. Find your project (e.g. `sena-ai-prod`) → click the three dots → **"Change billing"**
4. Select the billing account you created in Step 2 → click **"Set account"**
5. Confirm the project now shows your billing account name next to it

### Step 5: Grant Owner Access to the SENA Dev Team
This lets our technical team enable APIs, manage Vertex AI, and create credentials on your behalf.

1. In the Cloud Console (with your project selected), go to **IAM & Admin → IAM** in the left menu
   - Direct link: `https://console.cloud.google.com/iam-admin/iam`
2. Click the blue **"+ Grant Access"** (or **"+ Add"**) button at the top
3. In the **"New principals"** field, enter the SENA dev team email:
   ```
   maheshlalwani.dev@gmail.com
   ```
4. Under **"Role"**, search for and select **Project → Owner**
5. Click **"Save"**
   > The dev team will receive an email notification and can now manage the project.

### Step 6: Enable the Vertex AI API
1. Go to **APIs & Services → Library**: `https://console.cloud.google.com/apis/library`
2. Search **"Vertex AI API"** → click it → click **"Enable"** → wait ~30 seconds
3. In the same library, also search **"Generative Language API"** → **"Enable"**

### Step 7: Create a Service Account (app authentication)
This is the credential SENA's server uses to call Gemini automatically.

1. Go to **IAM & Admin → Service Accounts**: `https://console.cloud.google.com/iam-admin/serviceaccounts`
2. Click **"+ Create Service Account"**
3. Fill in:
   - **Name:** `sena-gemini-service`
   - **Description:** `SENA AI onboarding — Gemini access`
4. Click **"Create and Continue"**
5. Add role: click **"Select a role"** → search **"Vertex AI User"** → select it
6. Click **"Continue"** → **"Done"**

### Step 8: Download the Service Account Key
1. On the Service Accounts list, find `sena-gemini-service` → click `⋮` → **"Manage keys"**
2. Click **"Add Key"** → **"Create new key"** → select **JSON** → **"Create"**
3. A `.json` file downloads automatically — this is the credential file

### Step 9: Verify Data Residency Region
1. In Cloud Console → **Vertex AI → Dashboard**
2. Confirm region **`australia-southeast1 (Sydney)`** is available for Generative AI models
3. Take a screenshot and include it when you send us the files

### Step 10: Share with SENA Dev Team
Send the following **securely** (password manager, encrypted ZIP, or secure file share — not plain email):

1. **The JSON key file** from Step 8 — filename like `sena-ai-prod-123456-abcdef.json`
2. **Your Project ID** — e.g. `sena-ai-prod-123456`
3. **Screenshot** from Step 9 confirming `australia-southeast1` is available

We will place the JSON file on the server (never committed to git) and configure the environment automatically.

---

### Quick Checklist — Option B

- [ ] Google Cloud account created and Console accessible
- [ ] Billing account created and status shows **Active**
- [ ] Project created (e.g. `sena-ai-prod`)
- [ ] Project linked to billing account
- [ ] Owner role granted to `maheshlalwani.dev@gmail.com` via IAM
- [ ] Vertex AI API enabled
- [ ] Generative Language API enabled
- [ ] Service account `sena-gemini-service` created with Vertex AI User role
- [ ] JSON key file downloaded
- [ ] `australia-southeast1` region confirmed available
- [ ] All items shared securely with SENA dev team

---

## What We Do On Our End (For Reference)

Once you share the credentials, we make a single code change to switch from AI Studio to Vertex AI:

**Before (AI Studio):**
```python
client = genai.Client(api_key=settings.gemini_api_key)
```

**After (Vertex AI):**
```python
client = genai.Client(
    vertexai=True,
    project=settings.google_cloud_project,
    location="australia-southeast1",
)
```

The prompts, field extraction logic, and all other code stays identical.

---

## Billing Estimate (Vertex AI)

For the personal details onboarding flow:
- Average session: ~8 turns, ~300 tokens input + ~200 tokens output per turn
- ~4,000 tokens total per participant onboarding
- Gemini 2.0 Flash pricing: ~$0.0001 per 1K tokens
- **Cost per onboarding: < $0.001 (less than 0.1 cent)**

For 1,000 participant onboardings: **< $1 AUD**

---

## Questions?

Reach out to the SENA dev team with:
- Any error messages from the Google Cloud Console
- Screenshots of the Service Accounts page if you get stuck on Step 5/6
- Confirmation of which option you're starting with (A or B)
