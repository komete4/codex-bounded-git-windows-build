[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$SourceDirectory,
    [string]$KitDirectory = $PSScriptRoot,
    [Parameter(Mandatory = $true)][string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'Run only in the GitHub-hosted Windows build workflow'
}
$env:CARGO_TARGET_DIR = Join-Path $env:RUNNER_TEMP 'codex-target'
$baseCommit = '74e804deeb1241d5fe699b31fb319f7d46454c42'
$patchSha256 = '5ECB0A71AA3CE2FB0D2259661D1C804198D9FFEBF80D2317812CE332666F377D'
$target = 'x86_64-pc-windows-msvc'
$expectedV8ManifestSha256 = 'a4d6221dddb4b5724b23411eaac47caf6095489fbf9d126f65b33cef96a0a8ef'
$expectedNormalizerSha256 = '904daf3359c49e48edcb4fea4b3ff562febd76f15e5057827a4acaedb7ed6c5b'
$expectedLockBeforeSha256 = 'ddc24c397a491b690393cd966e62c1b968e5e1588bf78668c44fb5d27e55ec3c'
$expectedLockAfterSha256 = 'ea13254132d6e75e6ce399140791b4e471edd08c91a36d39299fc1e7cad4c789'
$sourcePath = (Get-Item -LiteralPath $SourceDirectory).FullName
$kitPath = (Get-Item -LiteralPath $KitDirectory).FullName
$workspacePath = Join-Path $sourcePath 'codex-rs'
$patchPath = Join-Path $kitPath 'community-bounded-git.patch'
$normalizerPath = Join-Path $kitPath 'normalize-lockfile.py'
$smokePath = Join-Path $kitPath 'smoke-candidate.py'
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$outputPath = (Get-Item -LiteralPath $OutputDirectory).FullName
$logsPath = Join-Path $outputPath 'logs'
New-Item -ItemType Directory -Path $logsPath -Force | Out-Null
$utf8 = [System.Text.UTF8Encoding]::new($false)

function Invoke-LoggedNative {
    param([string]$FilePath, [string[]]$ArgumentList, [string]$LogName)
    & $FilePath @ArgumentList 2>&1 | Tee-Object -FilePath (Join-Path $logsPath $LogName)
    if ($LASTEXITCODE -ne 0) { throw "$FilePath failed with exit code $LASTEXITCODE; see $LogName" }
}
function Save-Json {
    param([object]$Value, [string]$Name)
    [IO.File]::WriteAllText((Join-Path $outputPath $Name), ($Value | ConvertTo-Json -Depth 15), $utf8)
}
function Get-Sha256 {
    param([string]$Path)
    (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

$buildStartedUtc = [DateTime]::UtcNow.ToString('o')
$receipt = [ordered]@{
    status = 'STARTED'; started_utc = $buildStartedUtc; base_commit = $baseCommit
    target = $target; patch_sha256 = $patchSha256.ToLowerInvariant()
    installed = $false; client_changed = $false; native_process_cleanup_verified = $false
}
Save-Json $receipt 'build-receipt.json'
try {
    $receipt.kit_commit = (& git -c core.autocrlf=false -c core.longpaths=true -C $kitPath rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Build kit commit identity unavailable' }
    $actualCommit = (& git -c core.autocrlf=false -c core.longpaths=true -C $sourcePath rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualCommit -ne $baseCommit) { throw 'Upstream HEAD does not match the reviewed commit' }
    $sourceStatus = & git -c core.autocrlf=false -c core.longpaths=true --no-optional-locks -C $sourcePath status --porcelain
    if ($LASTEXITCODE -ne 0 -or $sourceStatus) { throw 'Source checkout must be clean before patching' }
    if ((Get-Sha256 $patchPath) -ne $patchSha256.ToLowerInvariant()) { throw 'Reviewed patch checksum mismatch' }
    if (-not (Test-Path -LiteralPath $normalizerPath -PathType Leaf)) { throw 'Reviewed lockfile normalizer missing' }
    if (-not (Test-Path -LiteralPath $smokePath -PathType Leaf)) { throw 'Reviewed finite smoke harness missing' }
    $receipt.normalizer_sha256 = Get-Sha256 $normalizerPath
    $receipt.smoke_harness_sha256 = Get-Sha256 $smokePath
    if ($receipt.normalizer_sha256 -ne $expectedNormalizerSha256) { throw 'Reviewed normalizer checksum mismatch' }
    if ((Get-Sha256 (Join-Path $workspacePath 'Cargo.lock')) -ne $expectedLockBeforeSha256) { throw 'Original lockfile checksum mismatch' }
    Copy-Item -LiteralPath $patchPath -Destination (Join-Path $outputPath 'community-bounded-git.patch')
    Copy-Item -LiteralPath (Join-Path $sourcePath 'LICENSE') -Destination (Join-Path $outputPath 'LICENSE')
    Copy-Item -LiteralPath (Join-Path $sourcePath 'NOTICE') -Destination (Join-Path $outputPath 'NOTICE')
    Copy-Item -LiteralPath (Join-Path $workspacePath 'Cargo.lock') -Destination (Join-Path $outputPath 'Cargo.lock.before')
    Invoke-LoggedNative git @('-c', 'core.autocrlf=false', '-c', 'core.longpaths=true', '-C', $sourcePath, 'apply', '--check', '--whitespace=error-all', $patchPath) 'patch-check.log'
    Invoke-LoggedNative git @('-c', 'core.autocrlf=false', '-c', 'core.longpaths=true', '-C', $sourcePath, 'apply', '--whitespace=error-all', $patchPath) 'patch-apply.log'

    Push-Location $workspacePath
    try {
        $rustVersion = (& rustc +1.95.0 --version).Trim()
        if ($LASTEXITCODE -ne 0 -or $rustVersion -notmatch '^rustc 1\.95\.0 ') { throw 'Rust 1.95.0 is required' }
        $receipt.rustc = $rustVersion
        $receipt.cargo = (& cargo +1.95.0 --version).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Cargo version failed' }
        $receipt.windows_sdk = $env:WindowsSDKVersion
        $receipt.vc_tools_directory = $env:VCToolsInstallDir
        $receipt.linker = $env:CARGO_TARGET_X86_64_PC_WINDOWS_MSVC_LINKER
        $receipt.runner_image = $env:ImageVersion
        Invoke-LoggedNative python @($normalizerPath, (Join-Path $workspacePath 'Cargo.lock'), (Join-Path $workspacePath 'Cargo.toml'), '--apply', '--report', (Join-Path $outputPath 'lockfile-normalization.json')) 'normalize-lockfile.log'
        if ((Get-Sha256 (Join-Path $workspacePath 'Cargo.lock')) -ne $expectedLockAfterSha256) { throw 'Normalized lockfile checksum differs from the reviewed result' }
        Copy-Item -LiteralPath (Join-Path $workspacePath 'Cargo.lock') -Destination (Join-Path $outputPath 'Cargo.lock.normalized')
        Invoke-LoggedNative git @('-c', 'core.autocrlf=false', '-c', 'core.longpaths=true', '-C', $sourcePath, 'diff', '--', 'codex-rs/Cargo.lock') 'lockfile-diff.patch'
        Invoke-LoggedNative git @('-c', 'core.autocrlf=false', '-c', 'core.longpaths=true', '-C', $sourcePath, 'diff', '--stat') 'source-diff-stat.log'

        # Match the fixed upstream setup-rusty-v8 action without its checkout-path assumption.
        $v8Version = (& python (Join-Path $sourcePath '.github/scripts/rusty_v8_bazel.py') resolved-v8-crate-version).Trim()
        if ($LASTEXITCODE -ne 0 -or $v8Version -ne '150.4.0') { throw 'Unexpected V8 crate version' }
        $v8Dir = Join-Path $env:RUNNER_TEMP 'reviewed-rusty-v8'
        New-Item -ItemType Directory -Path $v8Dir -Force | Out-Null
        $manifestName = "rusty_v8_ptrcomp_sandbox_release_$target.sha256"
        $trustedManifest = Join-Path $sourcePath 'third_party/v8/rusty_v8_150_4_0_release_manifests.sha256'
        $matchingLine = @(Get-Content -LiteralPath $trustedManifest | Where-Object { $_ -match ('^([0-9a-f]{64})  ' + [regex]::Escape($manifestName) + '$') })
        if ($matchingLine.Count -ne 1 -or $matchingLine[0].Split(' ')[0] -ne $expectedV8ManifestSha256) { throw 'Trusted V8 manifest anchor differs from reviewed source' }
        $releaseBase = 'https://github.com/openai/codex/releases/download/rusty-v8-v150.4.0'
        $manifestPath = Join-Path $v8Dir $manifestName
        Invoke-WebRequest -Uri "$releaseBase/$manifestName" -OutFile $manifestPath
        if ((Get-Sha256 $manifestPath) -ne $expectedV8ManifestSha256) { throw 'V8 manifest checksum mismatch' }
        $expectedNames = @("rusty_v8_ptrcomp_sandbox_release_$target.lib.gz", "src_binding_ptrcomp_sandbox_release_$target.rs")
        $manifestLines = @(Get-Content -LiteralPath $manifestPath | Where-Object { $_.Trim() })
        if ($manifestLines.Count -ne 2) { throw 'Expected exactly two V8 checksum records' }
        $seenNames = @()
        foreach ($line in $manifestLines) {
            if ($line -notmatch '^([0-9a-fA-F]{64}) [ *]([^/\\]+)$') { throw 'Malformed V8 checksum record' }
            $expectedHash = $Matches[1].ToLowerInvariant()
            $fileName = $Matches[2]
            if ($fileName -notin $expectedNames -or $fileName -in $seenNames) { throw 'Unexpected or duplicate V8 artifact filename' }
            $seenNames += $fileName
            $downloadPath = Join-Path $v8Dir $fileName
            Invoke-WebRequest -Uri "$releaseBase/$fileName" -OutFile $downloadPath
            if ((Get-Sha256 $downloadPath) -ne $expectedHash) { throw "V8 artifact checksum mismatch: $fileName" }
        }
        Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $outputPath $manifestName)
        $env:RUSTY_V8_ARCHIVE = Join-Path $v8Dir $expectedNames[0]
        $env:RUSTY_V8_SRC_BINDING_PATH = Join-Path $v8Dir $expectedNames[1]
        $env:LIBSQLITE3_FLAGS = 'SQLITE_DISABLE_INTRINSIC'
        $env:STABLE_GIT_COMMIT = $baseCommit
        $env:CARGO_BUILD_JOBS = '2'
        Invoke-LoggedNative cargo @('+1.95.0', 'metadata', '--locked', '--format-version', '1', '--no-deps') 'cargo-metadata.json'
        Invoke-LoggedNative cargo @('+1.95.0', 'test', '--locked', '--target', $target, '--release', '-p', 'codex-git-utils', '--lib', '--', '--test-threads=1') 'git-utils-tests.log'
        $testLog = Get-Content -LiteralPath (Join-Path $logsPath 'git-utils-tests.log') -Raw
        $requiredTests = @(
            'untracked_diff_request_future_is_send',
            'untracked_diffs_bound_overlapping_requests_and_preserve_all_results',
            'untracked_diffs_release_shared_permits_when_canceled'
        )
        foreach ($testName in $requiredTests) {
            if ($testLog -notmatch ('(?m)^test [^\r\n]*::' + [regex]::Escape($testName) + ' \.\.\. ok\s*$')) {
                throw "Required patch test did not report success: $testName"
            }
        }
        $receipt.git_utils_tests = 'PASSED'
        Invoke-LoggedNative cargo @('+1.95.0', 'build', '--locked', '--target', $target, '--release', '--timings', '--bin', 'codex', '-j', '2') 'cargo-build.log'
        $exePath = Join-Path $env:CARGO_TARGET_DIR "$target/release/codex.exe"
        if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) { throw 'Expected codex.exe missing' }
        Invoke-LoggedNative python @($smokePath, '--binary', $exePath, '--source', $sourcePath, '--report', (Join-Path $outputPath 'smoke-candidate.json')) 'smoke-candidate.log'
        $receipt.finite_smoke = 'PASSED'
        Invoke-LoggedNative $exePath @('app-server', 'generate-json-schema', '--experimental', '--out', (Join-Path $outputPath 'schemas-experimental')) 'generate-schemas-experimental.log'
        Copy-Item -LiteralPath $exePath -Destination (Join-Path $outputPath 'codex.exe')
        $receipt.binary_sha256 = Get-Sha256 $exePath
        $receipt.binary_bytes = (Get-Item -LiteralPath $exePath).Length
        $receipt.authenticode = (Get-AuthenticodeSignature -LiteralPath $exePath).Status.ToString()
        $receipt.normalized_lockfile_sha256 = Get-Sha256 (Join-Path $workspacePath 'Cargo.lock')
        $receipt.v8_manifest_sha256 = $expectedV8ManifestSha256
        $receipt.schemas_generated = $true
        $receipt.stable_schemas_compared_with_upstream_fixtures = $true
        $receipt.schemas_compared_with_installed_binary = $false
        $receipt.status = 'BUILT_CANDIDATE_NOT_INSTALLED'
    } finally { Pop-Location }
} catch {
    $receipt.status = 'FAILED'
    $receipt.error = $_.Exception.Message
    throw
} finally {
    $receipt.finished_utc = [DateTime]::UtcNow.ToString('o')
    Save-Json $receipt 'build-receipt.json'
    $checksumRecords = Get-ChildItem -LiteralPath $outputPath -File -Recurse |
        Where-Object { $_.Name -ne 'manifest.sha256' } |
        Sort-Object FullName |
        ForEach-Object { '{0}  {1}' -f (Get-Sha256 $_.FullName), ([IO.Path]::GetRelativePath($outputPath, $_.FullName).Replace('\', '/')) }
    [IO.File]::WriteAllLines((Join-Path $outputPath 'manifest.sha256'), [string[]]$checksumRecords, $utf8)
}
