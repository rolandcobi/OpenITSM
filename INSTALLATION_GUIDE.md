# Install and try OpenITSM: a beginner's Windows guide

This guide is for someone who has never downloaded a project from GitHub or run a Python application.

At the end, OpenITSM will open in a browser on your own computer. You can sign in, create fictional records, and try the modules. You do not need Git, a GitHub account, a paid service, or a separate database server for these steps.

This guide follows the project's evaluated **Windows x64 / Python 3.14.7** profile. It is a local engineering-preview evaluation. Shared infrastructure and production setup have separate requirements.

## Before you start

You need a 64-bit Windows computer, internet access for the downloads, and a browser such as Edge or Chrome.

A few terms used below:

| Term | Meaning |
| --- | --- |
| GitHub repository | The online folder containing the project files and instructions. |
| ZIP file | A compressed download. Extract it before using the project. |
| PowerShell | The Windows command window where you paste the commands in this guide. |
| Python environment | A local folder named .venv that keeps this project's packages together. |

## Step 1: open the project on GitHub

1. Open your browser.
2. Go to **https://github.com/rolandcobi/OpenITSM**.
3. The first page contains a file list and the README below it.
4. Scroll down to see the overview and screenshots. The screenshots are examples, not a running online application.
5. Return to the file list. If you are viewing this guide on GitHub, click the **Code tab** at the top to return to that list.

## Step 2: download all the project files

1. Check that the branch selector shows **main**.
2. Click the green **Code** button above the file list. This is different from the Code tab.
3. Click **Download ZIP**.
4. Your browser will normally save a file named **OpenITSM-main.zip** in Downloads.

You can also use this [direct ZIP download](https://github.com/rolandcobi/OpenITSM/archive/refs/heads/main.zip).

Download the complete ZIP. Saving only app.py or the README will not download the application.

## Step 3: extract the ZIP

1. Open Windows **File Explorer** and go to **Downloads**.
2. Right-click OpenITSM-main.zip and choose **Extract All...**.
3. Choose a normal local folder and click **Extract**.
4. Open the extracted folder. If there is another OpenITSM-main folder inside it, open that too.
5. Find the folder containing **app.py**, **README.md**, **requirements.txt**, **templates**, and **static**.

This is your project folder. Keep the files together. Do not run the application from inside the ZIP viewer.

## Step 4: install Python

1. Open the official [Python 3.14.7 download page](https://www.python.org/downloads/release/python-3147/).
2. In its Files section, choose **Windows installer (64-bit)**. Choose the regular installer, not the embeddable package, 32-bit version, or ARM64 version.
3. Open the downloaded installer.
4. Enable **Add python.exe to PATH**, if offered, and keep the Python launcher option enabled.
5. Choose **Install Now** and complete the installation.
6. Close any PowerShell windows that were open before installing Python.

The commands below select Python 3.14.7 through the Windows launcher. If the download page offers the newer Python install manager prominently, the traditional 64-bit installer remains in the Files list for this evaluated version.

## Step 5: open PowerShell in the project folder

1. Return to the extracted folder containing app.py.
2. Click File Explorer's address bar at the top.
3. Type **powershell** and press **Enter**.
4. A PowerShell window should open in that folder. You do not need to run it as administrator.

Paste the following commands into PowerShell, one line at a time, pressing Enter after each line. Copy the command text only, without any surrounding explanation.

Check that you are in the correct folder:

~~~powershell
Get-ChildItem .\app.py
~~~

You should see app.py listed. If PowerShell says it cannot find the file, return to the correct extracted folder and open PowerShell there.

Check Python:

~~~powershell
py -3.14 -c "import sys; print(sys.version); print('64-bit' if sys.maxsize > 2**32 else '32-bit')"
~~~

The output should identify **Python 3.14.7** and **64-bit**. If another Python 3.14 version is selected, use the evaluated version before following these exact instructions. Other versions are outside the validation recorded here.

## Step 6: create the Python environment and install packages

First, create the environment:

~~~powershell
py -3.14 -m venv .venv
~~~

It is normal for this command to finish without printing a message. It creates the .venv folder inside your project folder.

Install the installation tool and runtime packages:

~~~powershell
.venv\Scripts\python.exe -m pip install --only-binary=:all: --require-hashes -r requirements-tools-windows-py314.lock
.venv\Scripts\python.exe -m pip install --only-binary=:all: --require-hashes -r requirements-windows-py314.lock
.venv\Scripts\python.exe -m pip check
~~~

Wait for each command to finish before starting the next. Download progress and installation messages are normal. The final command should say **No broken requirements found.**

If a command reports an error, stop and check [Troubleshooting](#troubleshooting). Do not remove the hash checks or continue after an installation failure.

You do not need to activate the environment or change Windows script-execution policy. Every command here names the correct Python program directly.

## Step 7: configure your local evaluation

Paste this entire block into the same PowerShell window:

~~~powershell
$env:ITSM_ENV = 'development'
$env:ITSM_DB = Join-Path (Get-Location) 'evaluation.sqlite'
$env:ITSM_TLS = '0'
$env:ITSM_HTTPS = '0'
$env:ITSM_DEBUG = '0'
$env:ITSM_HOST = '127.0.0.1'
$env:ITSM_ALLOWED_HOSTS = 'localhost,127.0.0.1'
$env:ITSM_BACKUP = '0'
$env:PORT = '5000'
$env:ITSM_SECRET_KEY = .venv\Scripts\python.exe -c "from pathlib import Path; import secrets; p = Path('secret.key'); p.exists() or p.write_text(secrets.token_hex(32), encoding='utf-8'); print(p.read_text(encoding='utf-8').strip())"
~~~

These commands select a local database named evaluation.sqlite and generate a private session-signing key in secret.key. Repeating the block reuses the existing key. Both files stay on your computer; keep them private.

The address 127.0.0.1 means **this computer only**. This local trial does not open OpenITSM to other devices, enable external email, configure a shared server, or enable automatic backups.

The .env.example file is a reference. OpenITSM does not load it automatically; the commands above set the configuration in the PowerShell session.

## Step 8: choose your first administrator password

For the first run with a new database, paste:

~~~powershell
$initialPassword = Read-Host 'Choose an administrator password (at least 12 characters)' -AsSecureString
$env:ITSM_INITIAL_ADMIN_PASSWORD = [System.Net.NetworkCredential]::new('', $initialPassword).Password
Remove-Variable initialPassword
~~~

Type your own password and press Enter. PowerShell hides or masks what you type. Choose at least 12 characters and remember the password.

The first username is **admin**. There is no shared default password. These commands set the bootstrap password for a new database; they do not reset an account in an existing database.

## Step 9: start OpenITSM

Run:

~~~powershell
.venv\Scripts\python.exe app.py
~~~

Keep this PowerShell window open. The command will continue running rather than returning to the usual prompt.

A message about unencrypted HTTP is expected for this explicitly local-only evaluation.

## Step 10: open the application and sign in

1. Open Edge, Chrome, or another browser.
2. Enter **http://127.0.0.1:5000** in the browser's address bar.
3. Use **http**, not https, for this local setup.
4. Sign in with username **admin** and the password you chose in Step 8.
5. Complete any requested password or profile setup.

For an evaluation profile, use fictional information, such as a name of Test Administrator, an email of tester@example.invalid, a phone number of 0000000000, an organization of Example Organization, and a position of IT Evaluator.

The browser is the application interface. GitHub is where you downloaded the source; you do not enter your OpenITSM password on GitHub.

## Step 11: try the modules

Start with a few fictional records:

1. Open **Services** and inspect or add a service.
2. Open **CMDB & Assets** and add an example device linked to a service.
3. Open **Users** and create a second evaluation user with the Requester role.
4. Open **Create Ticket**, choose a service, and submit a test request.
5. Open the ticket to explore tasks, assignment, workflow steps, and the timeline.
6. Explore **My workspace**, **Reports**, and **Calendar**.
7. Sign out and try the Requester account to see its permitted views. Different roles do not have the same permissions.

Screenshots show a separate synthetic demonstration workspace. A fresh installation will not automatically contain the same users, tickets, assets, or boards.

Email delivery is not needed for this trial. SMTP configuration is a separate administrator task.

## Step 12: stop the application

Return to the PowerShell window running OpenITSM and press **Ctrl+C**.

Your saved records remain in evaluation.sqlite. Closing the browser alone does not stop the server.

## Start it again later

1. Open PowerShell in the same project folder, as in Step 5.
2. Repeat the configuration block in **Step 7**.
3. Run the start command from **Step 9**.
4. Open http://127.0.0.1:5000 and use your existing admin password.

You do not need to download the project, recreate .venv, reinstall packages, or choose a new bootstrap password for an ordinary restart. Keep evaluation.sqlite and secret.key in the same project folder.

## Troubleshooting

| What you see | What to do |
| --- | --- |
| PowerShell cannot find app.py or a requirements file | You are in the wrong folder. Open the extracted folder containing app.py, then open PowerShell there. |
| The py command is not recognized | Finish the Python installation with the launcher enabled, close PowerShell, and open it again. |
| No suitable Python runtime found | Install the evaluated 64-bit Python 3.14.7 and rerun the version check in Step 5. |
| PowerShell cannot find .venv\Scripts\python.exe | Confirm the project folder, then complete the environment-creation command in Step 6. |
| No matching distribution, wheel, or hash error | Confirm the evaluated Python version and 64-bit architecture. Keep the hash checks. Check internet access or an organizational download proxy; ask your IT administrator if needed. |
| Initial administrator password is required or too short | In the same PowerShell window, repeat Step 8 with at least 12 characters, then start again. |
| The page does not open | Keep the server window open, check it for an error, and use http://127.0.0.1:5000 exactly. |
| Port 5000 is already in use | Stop your OpenITSM process with Ctrl+C if it is running. Set $env:PORT = '5001', start OpenITSM again, and browse to http://127.0.0.1:5001. Do not stop an unrelated program. |
| Login fails after reopening PowerShell | Restart with Step 7 and your existing database/key. Use the password originally chosen for admin; setting a new bootstrap password does not reset the stored account. |
| Your records seem to have disappeared | Check that you reopened the same extracted folder and that its evaluation.sqlite file is still present. Another folder is a separate installation. |
| Another computer cannot connect | Expected: this guide binds to 127.0.0.1 for a local trial. Shared access requires a separate HTTPS deployment configuration. |

For ordinary setup questions, see [SUPPORT.md](SUPPORT.md). When sharing an error, remove passwords, keys, cookies, personal information, and database content. Report security vulnerabilities using the private route in [SECURITY.md](SECURITY.md).

## What comes after evaluation?

For a shared organizational installation, have the infrastructure administrator review the [operational runbook](docs/P1_07_RUNBOOK.md), [configuration example](.env.example), and [security and architecture contracts](docs/ARCHITECTURE_AND_SECURITY_CONTRACTS.md). HTTPS, certificates, access permissions, service startup, backups, recovery, and SMTP need site-specific configuration and verification.

OpenITSM is an engineering preview. Successfully running this local trial does not establish production readiness.

## Official download references

- [GitHub: downloading source code archives](https://docs.github.com/en/repositories/working-with-files/using-files/downloading-source-code-archives)
- [Python 3.14.7 downloads](https://www.python.org/downloads/release/python-3147/)
