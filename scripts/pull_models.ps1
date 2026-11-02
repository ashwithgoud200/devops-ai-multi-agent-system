$ErrorActionPreference = 'Stop'
$models = @(
  'qwen2.5:3b',
  'llama3.2:3b',
  'qwen2.5-coder:3b',
  'stablelm-zephyr:3b',
  'phi3.5:3.8b',
  'granite3.1-dense:2b'
)
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  throw 'Ollama CLI not found. Install Ollama and start its service first.'
}
foreach ($model in $models) {
  Write-Host "Pulling $model ..." -ForegroundColor Cyan
  ollama pull $model
  if ($LASTEXITCODE -ne 0) { throw "Failed to pull $model" }
}
Write-Host 'All configured agent models are pulled.' -ForegroundColor Green
ollama list
 