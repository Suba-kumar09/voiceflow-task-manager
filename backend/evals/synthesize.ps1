<#
.SYNOPSIS
  Speak every evaluation sentence with each installed English Windows voice (16 kHz mono WAV).
.EXAMPLE
  .\evals\synthesize.ps1 -OutDir D:\voiceflow-eval\audio
#>
param(
    [string]$Dataset = (Join-Path $PSScriptRoot 'voice_dataset.json'),
    [string]$OutDir = 'D:\voiceflow-eval\audio'
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
New-Item -ItemType Directory -Force $OutDir | Out-Null
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$items = (Get-Content $Dataset -Raw | ConvertFrom-Json).items
$probe = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = $probe.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'en-*' } | ForEach-Object { $_.VoiceInfo.Name }
$probe.Dispose()
foreach ($v in $voices) {
    $tag = ($v -split ' ')[1].ToLower()  # "Microsoft David Desktop" -> "david"
    foreach ($it in $items) {
        $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
        $s.SelectVoice($v)
        $s.SetOutputToWaveFile((Join-Path $OutDir "$($it.id)_$tag.wav"), $fmt)
        $s.Speak($it.text)
        $s.Dispose()
    }
}
Write-Host "$($items.Count) sentences x $($voices.Count) voices -> $OutDir"
