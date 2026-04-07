# 🚀 Git Workflow Master Guide (Gitea + Multi-PC Setup — Final)

## 📌 Purpose

This guide covers **everything we actually faced and fixed**:

* Large file errors (HTTP 413 / 502)
* Nested repo issues
* `.tools`, `.axon`, `node_modules` problems
* Wrong branch (`master` vs `main`)
* Multi-PC sync
* Authentication + identity errors
* Broken Git history

👉 This is a **real-world, production-ready workflow (Gitea only)**

---

# 🔧 1. Initial Setup

## Set Git Identity (MANDATORY)

```bash
git config --global user.name "Aditya Nagariya"
git config --global user.email "adityanagariyav@gmail.com"
```

### ❗ Issue Faced

```
Author identity unknown
```

### ✅ Why

Git refuses to commit without identity.

---

## Fix Windows Line Ending Warnings

```bash
git config --global core.autocrlf true
```

### ❗ Issue

```
LF will be replaced by CRLF
```

### ✅ Why

Prevents warning spam (safe normalization)

---

# 🔗 2. Gitea Remote Setup

## Clone Repo (BEST METHOD)

```bash
git clone https://gitea.bosctechlab.com/aditya.nagariya/SENA.git
cd SENA
```

### ✅ Why

Avoids manual setup errors

---

## OR Add Remote (if repo exists locally)

```bash
git init
git remote add origin https://gitea.bosctechlab.com/aditya.nagariya/SENA.git
```

---

## Verify Remote

```bash
git remote -v
```

---

# 📥 3. Multi-PC Workflow (VERY IMPORTANT)

## ALWAYS Pull First

```bash
git pull origin main
```

### ❗ Issue Faced

* Conflicts
* overwritten files
* mismatched repos

---

## If histories differ

```bash
git pull origin main --allow-unrelated-histories
```

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

## If main doesn't exist

```bash
git checkout -b main origin/main
```

---

# 🧹 5. CRITICAL — Large File Issue (BIGGEST PROBLEM)

## ❗ Error Faced

```
HTTP 413
fatal: remote end hung up unexpectedly
```

## 🔍 Cause

```
Git tried to push ~1.23GB
```

👉 Due to:

* PDFs (2GB file)
* binaries
* Git history still containing large files

---

## 🧠 Key Lesson

```
Deleting file ≠ removing from Git history
```

---

## 💀 FINAL FIX (USED — BEST)

```bash
rm -r -fo .git

git init
git add .
git commit -m "Fresh clean repo"

git remote add origin https://gitea.bosctechlab.com/aditya.nagariya/SENA.git
git branch -M main
git push -u origin main --force
```

---

# 🚫 6. .gitignore (FINAL CLEAN VERSION)

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

# Documents (large files)
*.pdf
Extras/*.pdf
```

---

## ❗ Lesson

```
.gitignore only affects future files
```

To remove existing tracked files:

```bash
git rm -r --cached .
git add .
```

---

# 🧹 7. Removing Junk Tracking

```bash
git rm -r --cached .tools
git rm -r --cached node_modules
git rm -r --cached .axon
```

---

# 📂 8. Nested Repo Problem (IMPORTANT)

## ❗ Issue Faced

```
SENA/
 └── SENA/   ❌ (repo inside repo)
```

## ✅ Fix

```bash
rmdir /s /q SENA
```

---

## 🧠 Lesson

```
Never copy repo inside itself
```

---

# 🔐 9. Authentication

## ❗ Issue

```
Authentication failed
```

## ✅ Fix

Use **Personal Access Token (PAT)** instead of password

---

# 🚀 10. Daily Workflow (FINAL)

## Always follow:

```bash
git pull
git add .
git commit -m "your message"
git push origin main
```

---

# ⚠️ Golden Rule

```
PULL → MODIFY → ADD → COMMIT → PUSH
```

---

# 🧹 11. Clean Git Junk

```bash
git gc --prune=now --aggressive
```

---

# 🧠 12. Common Errors (ALL YOU FACED)

---

## ❌ HTTP 413 / 502

👉 Large files / history too big
👉 Fix: clean repo or reset `.git`

---

## ❌ `src refspec main does not match any`

👉 Wrong branch
👉 Fix:

```bash
git checkout main
```

---

## ❌ `.tools / node_modules still tracked`

👉 Fix:

```bash
git rm -r --cached .
git add .
```

---

## ❌ Nested folder issue

👉 Fix:

```bash
rmdir /s /q SENA
```

---

## ❌ Changes not showing on Gitea

👉 Cause:

```
commit done but push not done
```

👉 Fix:

```bash
git push origin main
```

---

# 🧠 FINAL MENTAL MODEL

---

## ❗ Truth 1

```
Git tracks history, not just files
```

## ❗ Truth 2

```
.gitignore ≠ delete files
```

## ❗ Truth 3

```
Git ≠ file storage system
```

## ❗ Truth 4

```
commit ≠ push
```

---

# 🚀 FINAL STATE

✔ Clean repo
✔ No large files
✔ No junk tracking
✔ Multi-PC working
✔ Gitea fully synced
✔ Stable workflow

---

# 🏁 Conclusion

You didn’t just use Git —
you debugged a **real-world production-level Git disaster** and fixed it end-to-end.

👉 This workflow is now **battle-tested and reliable**.
