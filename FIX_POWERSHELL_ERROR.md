# Fixing PowerShell Execution Policy Error

You're getting this error because PowerShell scripts are disabled on your system. Here are **5 ways to fix it**:

## Solution 1: Use Command Prompt Instead (Easiest)

Instead of PowerShell, use **Command Prompt (cmd)**:

1. Open **Command Prompt** (not PowerShell)
2. Navigate to your project:
   ```cmd
   cd C:\Users\mwans\OneDrive\Desktop\PlayyArena
   ```
3. Activate virtual environment:
   ```cmd
   venv\Scripts\activate.bat
   ```

## Solution 2: Change PowerShell Execution Policy (Recommended for PowerShell users)

**Option A: For Current User Only (Safer)**
Run PowerShell as Administrator and execute:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

**Option B: For Current Session Only (No Admin Needed)**
Run this in your current PowerShell window:
```powershell
Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
```
Then activate:
```powershell
.\venv\Scripts\Activate.ps1
```

## Solution 3: Bypass Policy for One Command (Quick Fix)

Run the activation with a bypass:
```powershell
powershell -ExecutionPolicy Bypass -File .\venv\Scripts\Activate.ps1
```

Or activate directly:
```powershell
& .\venv\Scripts\Activate.ps1 -ExecutionPolicy Bypass
```

Actually, simpler:
```powershell
.\venv\Scripts\activate.bat
```

## Solution 4: Use the Batch File Directly

PowerShell can run .bat files without policy issues:
```powershell
.\venv\Scripts\activate.bat
```

## Solution 5: Run Django Without Activating (If Virtual Env Has All Packages)

If Django is already installed in your venv, you can use the full path:
```powershell
.\venv\Scripts\python.exe manage.py runserver
```

Or install globally and skip virtual env (not recommended):
```powershell
python -m pip install -r requirements.txt
python manage.py createcachetable
python manage.py runserver
```

---

## Recommended Quick Fix

**Just use Solution 4 - it's the simplest:**
```powershell
.\venv\Scripts\activate.bat
```

This will work in both PowerShell and Command Prompt without changing any policies!











