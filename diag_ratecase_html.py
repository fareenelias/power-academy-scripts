"""
diag_ratecase_html.py
Run this on Fareen's machine to dump the raw rate case table HTML from a CapIQ report.
This tells us the exact column structure so we can write a proper parser.

Usage: python E:\PowerAcademy\scripts\diag_ratecase_html.py
"""
import os, glob
from bs4 import BeautifulSoup

REPORTS_DIR = r'E:\PowerAcademy\data\capiq_reports'  # adjust if different

# Find first report file
files = glob.glob(os.path.join(REPORTS_DIR, '*.html')) + \
        glob.glob(os.path.join(REPORTS_DIR, '*.htm')) + \
        glob.glob(os.path.join(REPORTS_DIR, '*.mhtml'))

if not files:
    # Try looking for individual ticker folders
    for root, dirs, fs in os.walk(REPORTS_DIR):
        for f in fs:
            if f.lower().endswith(('.html','.htm','.mhtml')):
                files.append(os.path.join(root, f))
    if not files:
        print(f"No HTML files found in {REPORTS_DIR}")
        print("Checking for alternative locations...")
        for alt in [r'E:\PowerAcademy\data', r'E:\PowerAcademy\scripts']:
            found = glob.glob(os.path.join(alt, '**', '*.html'), recursive=True)
            if found:
                print(f"Found {len(found)} files in {alt}")
                files = found
                break
    
if not files:
    print("ERROR: No CapIQ HTML report files found. Please check REPORTS_DIR path.")
    exit(1)

print(f"Checking {files[0]}")
with open(files[0], 'r', encoding='utf-8', errors='ignore') as f:
    html = f.read()

soup = BeautifulSoup(html, 'html.parser')

# Find all tables and look for one with rate case keywords
keywords = ['rate case', 'authorized', 'requested', 'docket', 'roc', 'roe', 'rate base']
for i, table in enumerate(soup.find_all('table')):
    text = table.get_text(separator=' ', strip=True).lower()
    if any(kw in text for kw in keywords) and len(text) > 200:
        print(f"\n=== TABLE {i} ===")
        rows = table.find_all('tr')
        print(f"Rows: {len(rows)}")
        # Print first 5 rows
        for j, row in enumerate(rows[:5]):
            cells = [td.get_text(strip=True) for td in row.find_all(['th','td'])]
            print(f"  Row {j}: {cells}")
        if len(rows) > 5:
            print(f"  ... ({len(rows)-5} more rows)")