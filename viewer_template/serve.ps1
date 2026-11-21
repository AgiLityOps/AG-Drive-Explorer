# Minimal static file server for the AG Drive Track Explorer (used when Python is not installed).
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$mime = @{ '.html'='text/html'; '.js'='text/javascript'; '.mjs'='text/javascript'; '.css'='text/css'; '.json'='application/json';
           '.glb'='model/gltf-binary'; '.webp'='image/webp'; '.jpg'='image/jpeg'; '.png'='image/png'; '.txt'='text/plain'; '.md'='text/plain' }
$listener = $null
foreach ($p in 8642..8661) {
  try { $l = New-Object System.Net.HttpListener; $l.Prefixes.Add("http://127.0.0.1:$p/"); $l.Start(); $listener = $l; $port = $p; break } catch { }
}
if (-not $listener) { Write-Host 'No free port found.'; Read-Host 'Press Enter to exit'; exit 1 }
$url = "http://127.0.0.1:$port/"
Write-Host "AG Drive Track Explorer running at $url"
Write-Host 'Close this window to stop.'
Start-Process $url
while ($listener.IsListening) {
  $ctx = $listener.GetContext()
  try {
    $path = [Uri]::UnescapeDataString($ctx.Request.Url.AbsolutePath.TrimStart('/'))
    if ($path -eq '') { $path = 'index.html' }
    $file = [IO.Path]::GetFullPath((Join-Path $root $path))
    if ($file.StartsWith($root) -and (Test-Path $file -PathType Leaf)) {
      $ext = [IO.Path]::GetExtension($file).ToLower()
      $ctx.Response.ContentType = $(if ($mime.ContainsKey($ext)) { $mime[$ext] } else { 'application/octet-stream' })
      $bytes = [IO.File]::ReadAllBytes($file)
      $ctx.Response.ContentLength64 = $bytes.Length
      $ctx.Response.OutputStream.Write($bytes, 0, $bytes.Length)
    } else { $ctx.Response.StatusCode = 404 }
  } catch { } finally { $ctx.Response.Close() }
}
