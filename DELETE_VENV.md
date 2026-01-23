# How to Delete the venv Folder

## Method 1: Using File Explorer (Easiest)

1. Open File Explorer
2. Navigate to: `C:\Users\mwans\OneDrive\Desktop\PlayyArena`
3. Right-click on the `venv` folder
4. Click **Delete** or press **Del** key
5. Confirm deletion

## Method 2: Using PowerShell

**First, make sure the virtual environment is NOT activated** (if it is, type `deactivate` first)

Then run:
```powershell
Remove-Item -Recurse -Force venv
```

Or:
```powershell
rm -r -Force venv
```

## Method 3: Using Command Prompt (cmd)

**First, make sure the virtual environment is NOT activated** (if it is, type `deactivate` first)

Then run:
```cmd
rmdir /s /q venv
```

## Method 4: Using Python to Delete (If methods above fail)

```powershell
python -c "import shutil; shutil.rmtree('venv')"
```

## Important Notes:

⚠️ **Make sure the virtual environment is NOT activated** before deleting:
- If you see `(venv)` at the start of your command line, type `deactivate` first
- Then close and reopen your terminal/command prompt

⚠️ **If you get "folder is in use" error:**
- Close all terminals/command prompts
- Make sure no Python processes are running
- Close any IDEs or editors that might be using the venv
- Try again

After deleting, you can recreate it later with:
```powershell
python -m venv venv
```











