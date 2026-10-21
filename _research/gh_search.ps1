param([string[]]$Queries, [int]$PerPage = 12)
$ErrorActionPreference = 'Stop'
$H = @{ 'User-Agent' = 'dsh-research'; 'Accept' = 'application/vnd.github+json' }
foreach ($q0 in $Queries) {
    $q = [uri]::EscapeDataString($q0)
    try {
        $r = Invoke-RestMethod -Headers $H -Uri "https://api.github.com/search/repositories?q=$q&sort=stars&order=desc&per_page=$PerPage"
    } catch {
        Write-Output "### QUERY: $q0 -> ERROR $($_.Exception.Message)"
        continue
    }
    Write-Output "### QUERY: $q0   (total=$($r.total_count))"
    foreach ($it in $r.items) {
        $lic = if ($it.license) { $it.license.spdx_id } else { 'NOASSERTION' }
        $push = if ($it.pushed_at) { $it.pushed_at.Substring(0,10) } else { '?' }
        Write-Output ("{0}|{1}|{2}|{3}|{4}|{5}" -f $it.full_name, $it.stargazers_count, $it.language, $lic, $push, $it.description)
    }
    Write-Output ""
}
