param([ValidateSet('capability', 'recognize')][string]$Mode = 'capability')
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$engine = $null
$audio = $null
try {
    Add-Type -AssemblyName System.Speech
    $installed = @([System.Speech.Recognition.SpeechRecognitionEngine]::InstalledRecognizers() | Where-Object { $_.Culture.Name -eq 'en-US' })
    if ($Mode -eq 'capability') {
        @{available = ($installed.Count -gt 0)} | ConvertTo-Json -Compress
        exit 0
    }
    if ($installed.Count -eq 0) { throw 'recognizer_unavailable' }
    $encoded = [Console]::In.ReadToEnd()
    if ($encoded.Length -gt 261524) { throw 'audio_too_large' }
    $bytes = [Convert]::FromBase64String($encoded)
    if ($bytes.Length -gt 196096) { throw 'audio_too_large' }
    $audio = [System.IO.MemoryStream]::new($bytes, $false)
    $engine = [System.Speech.Recognition.SpeechRecognitionEngine]::new($installed[0].Id)
    $phrases = [System.Speech.Recognition.Choices]::new()
    foreach ($prefix in @('Producer please', 'Sarge', '')) {
        foreach ($command in @('camera one', 'camera two', 'camera three', 'camera four', 'clip that', 'save the last fifteen seconds', 'save the last thirty seconds', 'save the last sixty seconds', 'save the last one hundred twenty seconds')) {
            $phrases.Add(($prefix + ' ' + $command).Trim())
        }
    }
    $builder = [System.Speech.Recognition.GrammarBuilder]::new($phrases)
    $builder.Culture = [System.Globalization.CultureInfo]::GetCultureInfo('en-US')
    $engine.LoadGrammar([System.Speech.Recognition.Grammar]::new($builder))
    $engine.InitialSilenceTimeout = [TimeSpan]::FromSeconds(2)
    $engine.BabbleTimeout = [TimeSpan]::FromSeconds(6)
    $engine.EndSilenceTimeout = [TimeSpan]::FromMilliseconds(500)
    $engine.EndSilenceTimeoutAmbiguous = [TimeSpan]::FromMilliseconds(500)
    $engine.SetInputToWaveStream($audio)
    $result = $engine.Recognize([TimeSpan]::FromSeconds(8))
    if ($null -eq $result) {
        @{ok = $true; text = ''; confidence = 0.0} | ConvertTo-Json -Compress
    } else {
        @{ok = $true; text = $result.Text; confidence = [double]$result.Confidence} | ConvertTo-Json -Compress
    }
} catch {
    if ($Mode -eq 'capability') {
        @{available = $false} | ConvertTo-Json -Compress
    } else {
        @{ok = $false} | ConvertTo-Json -Compress
    }
} finally {
    if ($null -ne $engine) { $engine.Dispose() }
    if ($null -ne $audio) { $audio.Dispose() }
}
