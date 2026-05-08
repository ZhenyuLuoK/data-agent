// Tabs, smooth scroll utilities for paper summary pages
function showTab(groupId, tabId) {
  const group = document.getElementById(groupId);
  if (!group) return;
  group.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  group.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  const btn = group.querySelector(`[data-tab="${tabId}"]`);
  const content = group.querySelector(`#${tabId}`);
  if (btn) btn.classList.add('active');
  if (content) content.classList.add('active');
}

// Initialize: activate first tab in each group
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.tabs').forEach(group => {
    if (!group.id) return;
    const firstBtn = group.querySelector('.tab-btn');
    if (firstBtn) showTab(group.id, firstBtn.dataset.tab);
  });
  // search filter on index page
  const search = document.getElementById('paper-search');
  if (search) {
    search.addEventListener('input', () => {
      const q = search.value.toLowerCase().trim();
      document.querySelectorAll('.paper-card').forEach(c => {
        const text = c.innerText.toLowerCase();
        c.style.display = (!q || text.includes(q)) ? '' : 'none';
      });
      // hide empty categories
      document.querySelectorAll('.cat-block').forEach(cat => {
        const visible = cat.querySelectorAll('.paper-card:not([style*="display: none"])').length;
        cat.style.display = visible === 0 && q ? 'none' : '';
      });
    });
  }
});
