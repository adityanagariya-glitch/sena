(async function() {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
const targetPaths = [
  // ─── Authentication & Roles ───
  '/organization/shift/calendar',
];
    
    const results = [];
    
    for (const targetPath of targetPaths) {
        // Find the block by path text
        const allBlocks = Array.from(document.querySelectorAll('.opblock'));
        const block = allBlocks.find(b => {
            const pathEl = b.querySelector('.opblock-summary-path');
            return pathEl && pathEl.textContent.includes(targetPath);
        });
        
        if (!block) {
            results.push({ path: targetPath, error: "Not found" });
            console.log(`❌ ${targetPath} not found`);
            continue;
        }
        
        // Expand
        const control = block.querySelector('.opblock-summary-control');
        if (control && !block.classList.contains('is-open')) {
            control.click();
            await sleep(500);
        }
        
        // Click Example tab
        const tabs = Array.from(block.querySelectorAll('button.tablinks'));
        const exampleTab = tabs.find(t => t.textContent.includes('Example'));
        if (exampleTab && !exampleTab.classList.contains('active')) {
            exampleTab.click();
            await sleep(300);
        }
        
        // Extract
        const method = block.querySelector('.opblock-summary-method')?.textContent.trim();
        const path = block.querySelector('.opblock-summary-path')?.textContent.trim();
        const desc = block.querySelector('.opblock-summary-description')?.textContent.trim();
        
        // Params
        const params = [];
        block.querySelectorAll('.parameters tbody tr').forEach(row => {
            const nameEl = row.querySelector('.parameter__name');
            if (!nameEl) return;
            params.push({
                name: nameEl.childNodes[0]?.textContent.replace('*','').trim(),
                type: row.querySelector('.parameter__type')?.textContent.trim(),
                required: nameEl.classList.contains('required'),
                description: row.querySelector('.parameters-col_description .renderedMarkdown')?.textContent.trim()
            });
        });
        
        // Example
        let example = block.querySelector('.responses-inner .example.microlight')?.textContent?.trim() || 
                      block.querySelector('.responses-inner pre')?.textContent?.trim() || null;
        
        results.push({ method, path, description: desc, parameters: params, responseExample: example });
        console.log(`✅ ${method} ${path} - Example: ${example ? 'FOUND' : 'MISSING'}`);
    }
    
    // Download
    const blob = new Blob([JSON.stringify(results, null, 2)], {type: 'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'targeted_apis.json';
    a.click();
    
    console.log(`\nDone! Check downloads for targeted_apis.json`);
    return results;
})();