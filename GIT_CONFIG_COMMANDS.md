# Git Configuration Commands

## Check Current Git Configuration

```powershell
# Check username
git config user.name

# Check email
git config user.email

# Check all git config
git config --list
```

## Reset Git Username and Email

### Option 1: Set for This Repository Only (Local)

```powershell
# Set username for this repository
git config user.name "Your Name"

# Set email for this repository
git config user.email "your.email@example.com"
```

### Option 2: Set for All Repositories (Global)

```powershell
# Set username globally (all repositories)
git config --global user.name "Your Name"

# Set email globally (all repositories)
git config --global user.email "your.email@example.com"
```

## Reset/Remove Configuration

```powershell
# Remove username (local)
git config --unset user.name

# Remove email (local)
git config --unset user.email

# Remove username (global)
git config --global --unset user.name

# Remove email (global)
git config --global --unset user.email
```

## Examples

**Set username and email globally:**
```powershell
git config --global user.name "John Doe"
git config --global user.email "john.doe@example.com"
```

**Set username and email for this project only:**
```powershell
git config user.name "John Doe"
git config user.email "john.doe@example.com"
```

## Verify Changes

After setting, verify with:
```powershell
git config user.name
git config user.email
```





