# How to Commit Your Work to Git

## Basic Git Commit Workflow

### Step 1: Check Status
See what files have changed:
```powershell
git status
```

### Step 2: Stage Files (Add to Staging Area)
Add all changed files:
```powershell
git add .
```

Or add specific files:
```powershell
git add wallet/forms.py
git add wallet/views.py
git add templates/wallet/
git add templates/dashboard.html
```

### Step 3: Commit with Message
Commit your changes with a descriptive message:
```powershell
git commit -m "Your commit message here"
```

### Step 4: Push to Remote (Optional)
If you have a remote repository:
```powershell
git push
```

## Example for Day 4 Work

```powershell
# Check what changed
git status

# Add all changes
git add .

# Commit with descriptive message
git commit -m "Day 4: Implement wallet UI - Add deposit/withdraw forms and templates"

# Push to remote (if you have one)
git push
```

## Good Commit Messages

**Format:** 
- Start with a brief summary (50 chars or less)
- Add detailed description if needed
- Use present tense ("Add feature" not "Added feature")

**Examples:**
- `"Day 4: Add wallet deposit and withdrawal forms"`
- `"Implement wallet UI with forms and templates"`
- `"Add wallet forms, views, and templates for Day 4"`



