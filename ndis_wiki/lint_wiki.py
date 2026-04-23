import os
import re

pages_dir = 'ndis_wiki/pages'
existing_pages = set()

# 1. Map all existing pages
for root, dirs, files in os.walk(pages_dir):
    for f in files:
        if f.endswith('.md'):
            existing_pages.add(os.path.splitext(f)[0])

# 2. Extract all links
all_links = set()
link_pattern = re.compile(r'\[\[(.*?)\]\]')

for root, dirs, files in os.walk(pages_dir):
    for f in files:
        if f.endswith('.md'):
            with open(os.path.join(root, f), 'r', encoding='utf-8') as file:
                content = file.read()
                matches = link_pattern.findall(content)
                for m in matches:
                    all_links.add(m)

# 3. Find missing (Red Links)
missing_links = sorted(list(all_links - existing_pages))

if missing_links:
    print(f"Found {len(missing_links)} missing pages (Red Links):")
    for link in missing_links:
        print(f"- {link}")
else:
    print("No missing links found! Wiki integrity is 100%.")
