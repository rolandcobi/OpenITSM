# Local evaluation only. Run after creating and activating a virtual environment.
$ErrorActionPreference = 'Stop'
$env:ITSM_TLS = '0'
$env:ITSM_HOST = '127.0.0.1'
$env:ITSM_BACKUP = '0'
if (-not $env:ITSM_SECRET_KEY) {
  $bytes = New-Object byte[] 32
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
  $env:ITSM_SECRET_KEY = [Convert]::ToHexString($bytes)
}
if (-not (Test-Path './itsm.db') -and -not $env:ITSM_INITIAL_ADMIN_PASSWORD) {
  $secure = Read-Host 'Set initial administrator password (minimum 12 characters)' -AsSecureString
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try { $env:ITSM_INITIAL_ADMIN_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}
python app.py
