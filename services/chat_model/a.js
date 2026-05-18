(async function() {
    const sleep = ms => new Promise(r => setTimeout(r, ms));
const targetPaths = [
  // ─── Authentication & Roles ───
  '/super-admin/get-profile',
  '/user-type/{id}',
  '/organization/role/get-organizaiton-roles/{id}',
  '/organization/role/{id}',
  '/organization/view-profile',
  '/organization/member/members-list',
  '/sena-admin-role/get-all-sena-admin-roles',
  '/sena-admin-role/role-permissions/{roleId}',
  '/organization/staff/get-all-staff-members',
  '/mobile/organization-member/details',
  '/organization/client/list/all-clients',
  '/organization/client/my-clients',
  '/mobile/client/details',
  '/organization/role/my-roles',

  // ─── Section 2: Shifts ───
  '/organization/shift/ndis-categories',
  '/organization/shift/service-types',
  '/organization/payroll/get-allowances',
  '/organization/shift/list-view',
  '/organization/shift/list-view/type',
  '/organization/shift/details/{id}',
  '/organization/shift/{id}/occurrence',
  '/organization/shift/ongoing',
  '/organization/shift/clients',
  '/organization/shift/staff/support-worker',
  '/organization/shift/staff/in-office',
  '/organization-member/shift/list-view',
  '/organization-member/shift/calendar-view',
  '/organization-member/shift/ongoing-shifts',
  '/organization-member/shift/details/{id}',
  '/organization-member/shift/{id}/occurrence',
  '/mobile/staff-shift/view-shift/{id}',
  '/mobile/staff-shift/this-week-shifts',
  '/mobile/staff-shift/all-shifts',
  '/mobile/organization-member/my-ongoing-shifts',
  '/mobile/organization-member/shift/{id}/occurrence',
  '/mobile/organization-member/shift/details/{id}',
  '/mobile/client-shift/view-shift/{id}',
  '/mobile/client-shift/this-week-shifts',
  '/mobile/client-shift/all-shifts',
  '/mobile/client-shift/calendar-view',
  '/mobile/client/my-ongoing-shifts',
  '/mobile/client/shift/{id}/occurrence',
  '/isw/shift/ongoing-shifts',
  '/isw/shift/list-view',
  '/isw/shift/core-details/{id}',
  '/isw/shift/special-flags/{id}',
  '/isw/shift/allowances/{id}',
  '/mobile/isw-shift/this-week-shifts',
  '/mobile/isw-shift/view-shift/{id}',
  '/organization/work-log',
  '/mobile/visitor/clients/{clientId}',

  // ─── Section 4: Clients ───
  '/organization/client/get/{id}',
  '/organization/client/list',
  '/organization/client/board-view',
  '/organization/client/get-documents/{id}',
  '/organization/client/ndis-documents/{id}',
  '/organization/client/required-document',
  '/organization/client/{clientId}/guardians',
  '/mobile/client/documents',
  '/mobile/client/required-document',
  '/organization/client-agreement/list',
  '/organization/client-agreement/get-data/{agreementId}',
  '/mobile/client/agreement/records',
  '/mobile/client/agreement/records/{agreementId}',
  '/organization/support-coordinator/by-client/{id}',
  '/organization/support-coordinator/client/{id}',
  '/mobile/support-coordinator/clients/{id}',
  '/organization/support-worker/by-client/{clientId}',
  '/mobile/visitor/clients',
  '/mobile/client-access-consent/all-clients',
  '/mobile/organization-member/case-note/get-by-shift/{shiftId}'
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