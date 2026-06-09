# hl_longs.ps1 - Hyperliquid LONG-hunt for the wallet cluster.
# No API key, no Python needed. Uses Windows' built-in PowerShell.
#
# Run from the folder containing this file:
#     powershell -ExecutionPolicy Bypass -File hl_longs.ps1
#
# Green lines = open LONG positions = the answer you are looking for.

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$url = "https://api.hyperliquid.xyz/info"

# Owner cluster (ranked). NOTE: 0x40e7f70D is the REAL big feeder; the lookalike
# 0x40e7fb7D is a poisoning decoy and is NOT included here.
$wallets = [ordered]@{
  "MAIN        0x20c2...44f5"  = "0x20c2d95a3dfdca9e9ad12794d5fa6fad99da44f5"
  "BIG FEEDER  0x40e7f70D..."  = "0x40e7f70d8c5dbf7b27dab33ed826484b3c657e56"
  "FUNNEL      0x511cCDe9..."  = "0x511ccde9444216efc26e5744a0355eaebaaea82cb"
  "FEEDER      0x8ad9765C..."  = "0x8ad9765c8613d3beb6fbfa9df44e5bd1de4934e1"
  "FEEDER      0x1e772565d..." = "0x1e772565d78761d67796643941597c9f452da0d9"
  "TWCOIN      0x9E0dEE69..."  = "0x9e0dee69b9e8efb9ab6408ad4a3e133db2da283b"
}

function Invoke-HL($type, $addr) {
  $body = @{ type = $type; user = $addr } | ConvertTo-Json -Compress
  return Invoke-RestMethod -Uri $url -Method Post -ContentType "application/json" -Body $body
}

foreach ($name in $wallets.Keys) {
  $addr = $wallets[$name]
  Write-Host ""
  Write-Host "==== $name ====" -ForegroundColor Cyan
  Write-Host "     $addr"

  try { $state = Invoke-HL "clearinghouseState" $addr }
  catch { Write-Host "     ERROR: $($_.Exception.Message)" -ForegroundColor Red; continue }

  $acct = [double]$state.marginSummary.accountValue
  Write-Host ("     Account value: " + ("{0:N2}" -f $acct) + " USD")

  $pos = @($state.assetPositions)
  if ($pos.Count -eq 0) {
    Write-Host "     no open perp positions"
  } else {
    foreach ($ap in $pos) {
      $p   = $ap.position
      $szi = [double]$p.szi
      if ($szi -gt 0) { $side = "LONG" } else { $side = "SHORT" }
      $line = "     -> " + $p.coin + " " + $side +
              "  value=" + ("{0:N0}" -f [double]$p.positionValue) + " USD" +
              "  entry=" + $p.entryPx +
              "  uPnL="  + ("{0:N0}" -f [double]$p.unrealizedPnl) + " USD" +
              "  lev="   + $p.leverage.value + "x"
      if ($side -eq "LONG") { Write-Host $line -ForegroundColor Green }
      else                  { Write-Host $line -ForegroundColor Yellow }
    }
  }

  try { $fills = @(Invoke-HL "userFills" $addr) } catch { $fills = @() }
  $openLongs = @($fills | Where-Object { $_.dir -match "Open Long" })
  if ($openLongs.Count -gt 0) {
    Write-Host ("     OPEN LONG fills on record: " + $openLongs.Count) -ForegroundColor Green
    $openLongs | Sort-Object time -Descending | Select-Object -First 5 | ForEach-Object {
      $t = ([datetimeoffset]::FromUnixTimeMilliseconds([int64]$_.time)).LocalDateTime.ToString("yyyy-MM-dd HH:mm")
      Write-Host ("        " + $t + "  " + $_.coin + "  px=" + $_.px + "  sz=" + $_.sz)
    }
  }
}

Write-Host ""
Write-Host "Done. GREEN = LONG (the wallet that opened a long is your answer)." -ForegroundColor Cyan
