r"""
run_pipeline.py — Power Academy / precedents

Runs the whole link + validation pipeline as ONE unattended command, so the
script-running stops competing with the 118-deal QC review.

Everything is logged to data\pipeline_log.txt and every stage is idempotent, so
an interrupted run is resumed by re-running. Fetches are disk-cached, so a second
pass costs minutes not hours.

STAGES (in dependency order)
  1 qc-corrections   apply human-verified fixes           offline, seconds
  2 purge            strip XBRL/technical links           offline, seconds
  3 dedup            collapse duplicate press releases    offline, seconds
  4 harvest          8-K history walk: agreements/decks/   SLOW (network)
                     press releases/transcripts
  5 revalidate-decks re-check decks with weak provenance  network
  6 local-transcripts match deals to the S&P call library offline
  7 check            validate every link, flag 404s       network
  8 report           coverage + QC worklists              offline

  python run_pipeline.py                 # everything
  python run_pipeline.py --fast          # offline stages only (1,2,3,6,8)
  python run_pipeline.py --from 5        # resume from a stage
  python run_pipeline.py --dry-run       # nothing is written
"""

import os, sys, subprocess, time, io, argparse, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = None


def log(msg):
    line = '%s  %s' % (datetime.datetime.now().strftime('%H:%M:%S'), msg)
    print(line)
    if LOG:
        LOG.write(line + '\n')
        LOG.flush()


STAGES = [
    # (n, name, script, args, needs_network, description)
    (1, 'qc-corrections',    'apply_qc_corrections.py',  [],                 True,
     'human-verified link fixes (SEC urls, cleared wrong links)'),
    (2, 'purge',             'scrub_links.py',           ['--phase', 'purge'], False,
     'strip XBRL/technical files from document fields'),
    (3, 'dedup',             'scrub_links.py',           ['--phase', 'dedup'], False,
     'collapse duplicate/joint press releases'),
    (4, 'harvest',           'scrub_links.py',           ['--phase', 'harvest'], True,
     '8-K history walk for agreements, decks, PRs, transcripts'),
    (5, 'revalidate-decks',  'revalidate_decks.py',      [],                 True,
     're-check decks whose provenance is weak or absent'),
    (6, 'local-transcripts', 'link_local_transcripts.py', [],                False,
     'match deals to the local S&P transcript library'),
    (7, 'check',             'scrub_links.py',           ['--phase', 'check'], True,
     'validate every link; demote 404s to _needs_find'),
    (8, 'report',            'report_coverage.py',       ['--md'],           False,
     'coverage report'),
]
EXTRA_REPORTS = [('qc_links.py', ['--write']), ('audit_decks.py', ['--md'])]


def run(script, args, dry):
    path = os.path.join(HERE, script)
    if not os.path.isfile(path):
        log('    !! missing script: %s' % script)
        return False, ''
    cmd = [sys.executable, path] + list(args) + (['--dry-run'] if dry else [])
    t0 = time.time()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
    except subprocess.TimeoutExpired:
        log('    !! TIMEOUT after 2h — re-run to resume (cache makes it fast)')
        return False, ''
    out = (p.stdout or '') + (p.stderr or '')
    if LOG:
        LOG.write(out + '\n')
        LOG.flush()
    # surface the summary lines only, so the console stays readable
    for ln in out.splitlines():
        t = ln.strip()
        if (t.startswith(('P0', 'P1', 'P2', 'P3', 'P4', 'agreements', 'decks',
                          'fairness', 'matched', 're-checked', 'removed', 'applied'))
                or 'ERROR' in t or 'Traceback' in t or t.startswith('  ')and '::' in t):
            log('    ' + t[:110])
    log('    done in %ds  (rc=%d)' % (time.time() - t0, p.returncode))
    return p.returncode == 0, out


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument('--fast', action='store_true', help='offline stages only')
    ap.add_argument('--from', dest='start', type=int, default=1)
    ap.add_argument('--to', type=int, default=99)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-reports', action='store_true')
    a = ap.parse_args()

    data = os.path.normpath(os.path.join(HERE, '..', 'data'))
    if not os.path.isdir(data):
        data = HERE
    LOG = io.open(os.path.join(data, 'pipeline_log.txt'), 'a', encoding='utf-8')

    log('=' * 62)
    log('PRECEDENTS PIPELINE  %s%s'
        % (datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
           '  [DRY RUN]' if a.dry_run else ''))
    log('=' * 62)

    t0 = time.time()
    ok = failed = skipped = 0
    for n, name, script, args, net, desc in STAGES:
        if n < a.start or n > a.to:
            continue
        if a.fast and net:
            log('%d. %-18s SKIPPED (--fast, needs network)' % (n, name))
            skipped += 1
            continue
        log('%d. %-18s %s' % (n, name, desc))
        good, _ = run(script, args, a.dry_run)
        ok += 1 if good else 0
        failed += 0 if good else 1

    if not a.no_reports and not a.dry_run:
        log('   writing QC worklists')
        for script, args in EXTRA_REPORTS:
            run(script, args, False)

    log('-' * 62)
    log('pipeline finished in %dm %ds  ·  %d ok, %d failed, %d skipped'
        % ((time.time() - t0) // 60, (time.time() - t0) % 60, ok, failed, skipped))
    log('outputs: coverage_report.md · qc_links.md · deck_audit.md')
    log('full log: %s' % os.path.join(data, 'pipeline_log.txt'))
    if failed:
        log('NOTE: a failed stage is usually a network drop — re-run to resume;')
        log('      the fetch cache means it picks up where it stopped.')
    LOG.close()


if __name__ == '__main__':
    main()