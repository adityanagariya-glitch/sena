# 🚀 Git Workflow Master Guide (Gitea + Multi-PC Setup)

## 📌 Purpose

This document contains all commands used during setup, along with **why** they were used.
Useful for:

* Multi-PC development
* Fixing broken repos
* Avoiding large file issues
* Clean Git workflow

---

# 🔧 1. Initial Setup

## Set Git Identity (Required)

```bash
git config --global user.name "Aditya Nagariya"
git config --global user.email "adityanagariyav@gmail.com"
```

### 💡 Why?

Git needs identity to create commits. Without this, commits fail.

---

## Fix Windows Line Ending Warnings

```bash
git config --global core.autocrlf true
```

### 💡 Why?

Prevents spam warnings like:

```
LF will be replaced by CRLF
```

---

# 🔗 2. Connecting to Remote (Gitea)

## Add Remote Repository

```bash
git remote add origin https://gitea.bosctechlab.com/aditya.nagariya/SENA.git
```

### 💡 Why?

Links local project to remote repo.

---

## Verify Remote

```bash
git remote -v
```

---

# 📥 3. Pulling Existing Code (IMPORTANT FIRST STEP)

```bash
git pull origin main
```

### 💡 Why?

Always pull before working:

* Sync with latest code
* Avoid conflicts
* Prevent overwriting

---

## If histories differ

```bash
git pull origin main --allow-unrelated-histories
```

### 💡 Why?

Allows merging when local + remote repos started separately.

---

# 🌿 4. Branch Fix (master → main)

## Check branch

```bash
git branch
```

## Switch to main

```bash
git checkout main
```

## If not exists:

```bash
git checkout -b main origin/main
```

### 💡 Why?

Remote uses `main`, local was `master`.

---

# 🧹 5. Cleaning Broken Repo (CRITICAL PART)

## Remove all tracked files (reset tracking)

```bash
git rm -r --cached .
```

### 💡 Why?

* Clears Git index
* Stops tracking unwanted files
* Respects `.gitignore` on re-add

---

## Re-add clean files

```bash
git add .
```

### 💡 Why?

Re-add only allowed files (no node_modules, no tools, etc.)

---

## Commit clean state

```bash
git commit -m "Clean repo (respect gitignore)"
```

---

# 🚫 6. Removing Junk from Tracking

## Remove specific folders

```bash
git rm -r --cached .tools
git rm -r --cached node_modules
git rm -r --cached .axon
```

### 💡 Why?

These are:

* Generated files
* Dependencies
* Machine-specific
* Should NOT be in Git

---

# 📄 7. .gitignore (Final Version)

```gitignore
# Dependencies
node_modules/

# Tools / Generated
.tools/
.axon/

# Environment
.env

# Logs
*.log

# Archives / binaries
*.zip
*.7z
*.bin

# Documents
*.pdf
Extras/*.pdf
```

### 💡 Why?

Prevents:

* Large files (PDFs, zips)
* Dependencies
* System junk

---

# 🚀 8. Normal Workflow (Daily Use)

## Always follow this order:

### 1. Pull latest

```bash
git pull
```

### 2. Add changes

```bash
git add .
```

### 3. Commit

```bash
git commit -m "your message"
```

### 4. Push

```bash
git push
```

---

# ⚠️ Golden Rule

```text
PULL → MODIFY → ADD → COMMIT → PUSH
```

---

# 🧹 9. Clean Git Internal Junk

```bash
git gc --prune=now --aggressive
```

### 💡 Why?

* Removes broken history
* Cleans unused objects
* Reduces repo size

---

# 🧠 10. Common Errors & Fixes

---

## ❌ Authentication Failed

👉 Use **Personal Access Token**, not password

---

## ❌ `remote origin already exists`

```bash
git remote remove origin
git remote add origin <url>
```

---

## ❌ `src refspec main does not match any`

👉 You’re on wrong branch → switch to `main`

---

## ❌ Large file push failed (413 / 502)

👉 Cause:

* Files too large (>100MB)

👉 Fix:

* Remove from Git
* Use `.gitignore`
* Clean history

---

## ❌ `.tools / node_modules still tracked`

👉 Fix:

```bash
git rm -r --cached .
git add .
```

---

# 🧠 Final Mental Model

```text
Git = Code only
NOT = storage system
```

---

# 🚀 Final State Achieved

✔ Clean repo
✔ No large files
✔ No junk tracking
✔ Multi-PC sync working
✔ Stable workflow

---

# 🏁 End

This is your **production-ready Git workflow**.
Follow it and you’ll never hit those issues again.
