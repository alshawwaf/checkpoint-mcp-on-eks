# Ask the Check Point security-ops agent a question (PowerShell 5.1+ / 7+).
# Needs $env:CHKP_* -- python -m chkpmcpeks endpoints --format ps1 --reveal-secret | Invoke-Expression
param([string]$Question = "What is the reputation of https://www.checkpoint.com?")
$ErrorActionPreference = "Stop"

$basic = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("$($env:CHKP_CLIENT_ID):$($env:CHKP_CLIENT_SECRET)"))
$token = (Invoke-RestMethod -Method Post -Uri $env:CHKP_TOKEN_URL -Headers @{ Authorization = "Basic $basic" } `
          -ContentType "application/x-www-form-urlencoded" `
          -Body "grant_type=client_credentials&scope=$($env:CHKP_SCOPE)").access_token

# Self-signed demo certificate: trust exactly the stack's own certificate.
if ($env:CHKP_CA_FILE) {
  $ca = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $env:CHKP_CA_FILE
  [System.Net.ServicePointManager]::ServerCertificateValidationCallback = {
    param($s, $cert, $chain, $errors) $errors -eq 'None' -or $cert.GetCertHashString() -eq $ca.GetCertHashString() }
}

$body = @{ prompt = $Question } | ConvertTo-Json
$r = Invoke-RestMethod -Method Post -Uri $env:CHKP_AGENT_URL -Headers @{ Authorization = "Bearer $token" } `
       -ContentType "application/json" -Body $body
"model : $($r.model)"
"tools : $(($r.tool_calls | ForEach-Object name) -join ', ')"
"usage : $($r.usage | ConvertTo-Json -Compress)"
""
$r.result
