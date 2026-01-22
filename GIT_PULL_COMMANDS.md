# Git Pull Commands - How to Get Updates from Repository

## Basic Git Pull

### Pull from Default Branch (usually main or master)
```powershell
git pull
```

This pulls changes from the remote repository and merges them into your current branch.

### Pull from Specific Branch
```powershell
git pull origin main
```
or
```powershell
git pull origin master
```

## Complete Workflow: Fetch, Pull, and Status

### Step 1: Check Current Status
```powershell
git status
```
Shows what branch you're on and if you have uncommitted changes.

### Step 2: Fetch (Optional - to see what's available)
```powershell
git fetch
```
Downloads changes without merging them.

### Step 3: Pull Changes
```powershell
git pull
```
Downloads and merges changes into your current branch.

### Step 4: Check Status Again
```powershell
git status
```
Verify everything is up to date.

## If You Have Uncommitted Changes

**Option 1: Commit Your Changes First**
```powershell
git add .
git commit -m "Your commit message"
git pull
```

**Option 2: Stash Your Changes (Save for later)**
```powershell
git stash
git pull
git stash pop  # Brings back your changes
```

**Option 3: Pull with Rebase**
```powershell
git pull --rebase
```

## Common Scenarios

### Pull Latest Changes
```powershell
git pull origin main
```

### Pull and Automatically Merge
```powershell
git pull --no-rebase
```

### Pull Specific Branch
```powershell
git checkout branch-name
git pull origin branch-name
```

### Check Remote Repository Info
```powershell
git remote -v
```
Shows the remote repository URL.

### See What Will Be Pulled (without actually pulling)
```powershell
git fetch
git log HEAD..origin/main
```

## Troubleshooting

### If Pull Fails Due to Conflicts:
```powershell
# See what files have conflicts
git status

# Resolve conflicts in the files, then:
git add .
git commit -m "Resolved merge conflicts"
```

### If You Want to Overwrite Local Changes:
⚠️ **WARNING: This will discard your local changes!**
```powershell
git fetch origin
git reset --hard origin/main
```

### If You Want to See Differences Before Pulling:
```powershell
git fetch
git diff HEAD origin/main
```





