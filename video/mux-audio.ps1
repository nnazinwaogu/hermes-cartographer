param([int]$PreRollMs = 0)
$ErrorActionPreference = "Stop"
$dir = $PSScriptRoot
ffmpeg -y -i "$dir\hermes-cartographer.mp4" -i "$dir\audio\mix.wav" `
  -filter_complex "[1:a]adelay=$PreRollMs|$PreRollMs[a]" `
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart `
  "$dir\hermes-cartographer.tmp.mp4"
Move-Item -Force "$dir\hermes-cartographer.tmp.mp4" "$dir\hermes-cartographer.mp4"
